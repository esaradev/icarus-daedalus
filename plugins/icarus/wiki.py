"""Icarus Wiki — persistent markdown knowledge layer.

Three-folder contract under FABRIC_DIR:
  raw/     immutable source material (user-dropped files)
  wiki/    LLM-owned pages (entities, topics, sources, indexes, notes)
  wiki/_schema.json   ingest rules + conventions

v1 scope:
  init_wiki — scaffold
  ingest    — raw source -> source page + entity/topic pages + index + log
  query     — grep wiki first, raw second
  lint      — report broken wikilinks, orphan pages, pages without sources

Entity extraction in v1 is deterministic: markdown headings + capitalized noun
phrases + URLs. No LLM call. See SKILL.md for upgrade notes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

WIKI_SUBDIRS = ("entities", "topics", "sources", "indexes", "notes")

DEFAULT_SCHEMA = {
    "version": 1,
    "page_types": list(WIKI_SUBDIRS),
    "frontmatter_required": ["type", "title", "created"],
    "linking": {
        "style": "wikilink",
        "example": "[[entities/andrej-karpathy]]",
    },
    "ingest": {
        "source_root": "raw",
        "max_pages_per_ingest": 5,
        "entity_heuristics": ["markdown_headings", "capitalized_phrases", "urls"],
        "stopwords_min_count": 2,
    },
    "provenance": {
        "every_page_must_reference_source": True,
        "source_page_is_authoritative": True,
    },
}

HOME_TEMPLATE = """# Home

Welcome to your Icarus wiki. This is a persistent, compounding knowledge base
the agent maintains as new sources arrive.

## Where to start

- [[index]] — auto-maintained table of contents
- [[log]] — chronological ingest history

## How it works

1. Drop sources into `raw/inbox/`
2. Call `wiki_ingest` with the source path
3. Browse the resulting entity, topic, and source pages

Raw sources are never modified. This wiki is owned by the agent.
"""

INDEX_HEADER = """# Index

Auto-maintained table of contents. Do not edit by hand between ingests.

"""

LOG_HEADER = """# Log

Chronological ingest history. Append-only.

"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slugify(text: str, max_len: int = 64) -> str:
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:max_len] or "untitled"


def _wiki_root(fabric_dir: Path) -> Path:
    return fabric_dir / "wiki"


def _raw_root(fabric_dir: Path) -> Path:
    return fabric_dir / "raw"


def init_wiki(fabric_dir: Path) -> dict:
    """Create wiki scaffold. Idempotent."""
    fabric_dir = Path(fabric_dir)
    wiki = _wiki_root(fabric_dir)
    raw = _raw_root(fabric_dir)
    created: list[str] = []

    for d in (raw, raw / "inbox", wiki, *(wiki / s for s in WIKI_SUBDIRS)):
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))

    home = wiki / "Home.md"
    if not home.exists():
        home.write_text(HOME_TEMPLATE, "utf-8")
        created.append(str(home))

    index = wiki / "index.md"
    if not index.exists():
        index.write_text(INDEX_HEADER, "utf-8")
        created.append(str(index))

    log = wiki / "log.md"
    if not log.exists():
        log.write_text(LOG_HEADER, "utf-8")
        created.append(str(log))

    schema = wiki / "_schema.json"
    if not schema.exists():
        schema.write_text(json.dumps(DEFAULT_SCHEMA, indent=2), "utf-8")
        created.append(str(schema))

    return {
        "status": "initialized" if created else "already_initialized",
        "wiki_dir": str(wiki),
        "raw_dir": str(raw),
        "created": created,
    }


# ── Deterministic entity/topic extraction ────────────────────────────────

_HEADING_RE = re.compile(r"^\s{0,3}(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
_URL_RE = re.compile(r"https?://[^\s<>\"')]+")
_CAP_PHRASE_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9]+)(?:\s+[A-Z][a-zA-Z0-9]+){0,3}\b")

_STOPPHRASES = {
    "I", "The", "A", "An", "This", "That", "These", "Those",
    "It", "He", "She", "They", "We", "You",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
}


def _extract_candidates(text: str, max_pages: int = 5) -> list[dict]:
    """Return up to max_pages candidate entity/topic dicts.

    Each dict: {kind: "entity"|"topic", title, slug, evidence}
    Heuristic: headings become topic pages; repeated capitalized phrases
    become entity pages. We interleave topics and entities so both kinds
    show up even when one is abundant.
    """
    topics: list[dict] = []
    entities: list[dict] = []
    seen_slugs: set[str] = set()

    for match in _HEADING_RE.finditer(text):
        title = match.group(2).strip().rstrip(":")
        slug = _slugify(title)
        if slug in seen_slugs or len(title) < 3:
            continue
        seen_slugs.add(slug)
        topics.append({
            "kind": "topic",
            "title": title,
            "slug": slug,
            "evidence": f"heading: {title}",
        })

    phrase_counts = Counter()
    for m in _CAP_PHRASE_RE.finditer(text):
        phrase = m.group(0)
        if phrase in _STOPPHRASES or len(phrase) < 4:
            continue
        phrase_counts[phrase] += 1

    for phrase, count in phrase_counts.most_common(20):
        if count < 2:
            break
        slug = _slugify(phrase)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        entities.append({
            "kind": "entity",
            "title": phrase,
            "slug": slug,
            "evidence": f"mentioned {count}× in source",
        })

    out: list[dict] = []
    i = j = 0
    while len(out) < max_pages and (i < len(topics) or j < len(entities)):
        if i < len(topics):
            out.append(topics[i]); i += 1
            if len(out) >= max_pages: break
        if j < len(entities):
            out.append(entities[j]); j += 1
    return out


# ── Page I/O ─────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, text[m.end():]


def _write_frontmatter(fm: dict, body: str) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(repr(x) for x in v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines) + body


def _generated_markers(key: str) -> tuple[str, str]:
    safe = _slugify(key, max_len=80)
    return (
        f"<!-- ICARUS_GENERATED:{safe}:START -->",
        f"<!-- ICARUS_GENERATED:{safe}:END -->",
    )


def _upsert_generated_block(body: str, key: str, content: str) -> str:
    start, end = _generated_markers(key)
    block = f"{start}\n{content.strip()}\n{end}"
    pattern = re.compile(
        rf"{re.escape(start)}.*?{re.escape(end)}",
        re.DOTALL,
    )
    if pattern.search(body):
        return pattern.sub(block, body)
    body = body.rstrip()
    return f"{body}\n\n{block}\n"


def _upsert_page(
    path: Path,
    page_type: str,
    title: str,
    summary: str,
    source_link: str,
    body_append: Optional[str] = None,
    generated_block_key: Optional[str] = None,
) -> bool:
    """Create or update a wiki page. Returns True if created, False if updated."""
    now = _now()
    if path.exists():
        fm, body = _parse_frontmatter(path.read_text("utf-8"))
        sources = fm.get("sources", "[]")
        if source_link not in sources:
            existing = sources.strip("[]").strip()
            fm["sources"] = (
                f"[{existing}, {source_link!r}]" if existing else f"[{source_link!r}]"
            )
        fm["updated"] = now
        if body_append:
            if generated_block_key:
                body = _upsert_generated_block(body, generated_block_key, body_append)
            elif body_append.strip() not in body:
                body = body.rstrip() + "\n\n" + body_append.strip() + "\n"
        path.write_text(_write_frontmatter(fm, body), "utf-8")
        return False

    fm = {
        "type": page_type,
        "title": title,
        "summary": summary,
        "sources": f"[{source_link!r}]",
        "created": now,
        "updated": now,
    }
    body = f"\n# {title}\n\n{summary}\n"
    if body_append:
        if generated_block_key:
            body += "\n" + _upsert_generated_block("", generated_block_key, body_append).strip() + "\n"
        else:
            body += "\n" + body_append.strip() + "\n"
    body += f"\n## Sources\n\n- {source_link}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_write_frontmatter(fm, body), "utf-8")
    return True


# ── Ingest ───────────────────────────────────────────────────────────────

def ingest(source_path: str | Path, fabric_dir: Path) -> dict:
    fabric_dir = Path(fabric_dir)
    src = Path(source_path).expanduser().resolve()
    raw = _raw_root(fabric_dir).resolve()

    if not src.exists():
        return {"error": f"source not found: {src}"}
    try:
        src.relative_to(raw)
    except ValueError:
        return {
            "error": f"source must live under {raw} (got {src}). "
                     f"Drop files into raw/inbox/ first."
        }

    wiki = _wiki_root(fabric_dir)
    if not wiki.exists():
        return {"error": "wiki not initialized — run wiki_init first"}

    text = src.read_text("utf-8", errors="replace")
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    rel_source = src.relative_to(raw).with_suffix("").as_posix()
    source_slug = _slugify(rel_source.replace("/", "-"))
    source_page = wiki / "sources" / f"{source_slug}.md"
    source_link = f"[[sources/{source_slug}]]"
    title_guess = _derive_title(text, fallback=src.stem)
    summary = _derive_summary(text)

    candidates = _extract_candidates(text, max_pages=4)
    see_also = "\n".join(
        f"- [[{('entities' if c['kind'] == 'entity' else 'topics')}/{c['slug']}]]"
        for c in candidates
    )

    src_body = (
        f"**Original path:** `{src}`\n\n"
        f"**Hash:** `{content_hash}`\n\n"
        f"## See also\n\n{see_also or '_No related pages extracted._'}\n\n"
        f"## Excerpt\n\n"
        f"{_head(text, 600)}\n"
    )
    source_created = _upsert_page(
        source_page,
        "source",
        title_guess,
        summary,
        source_link=source_link,
        body_append=src_body,
        generated_block_key=f"source:{rel_source}",
    )
    created: list[str] = []
    updated: list[str] = []
    page_links: list[str] = []

    for c in candidates:
        subdir = "entities" if c["kind"] == "entity" else "topics"
        page = wiki / subdir / f"{c['slug']}.md"
        link = f"[[{subdir}/{c['slug']}]]"
        page_summary = c["evidence"]
        was_created = _upsert_page(
            page,
            c["kind"],
            c["title"],
            page_summary,
            source_link=source_link,
            body_append=f"_Seen in {source_link}._",
            generated_block_key=f"source-ref:{source_slug}",
        )
        (created if was_created else updated).append(str(page))
        page_links.append(link)

    if source_created:
        created.append(str(source_page))
    else:
        updated.append(str(source_page))

    _refresh_index(wiki)
    _append_log(wiki, src, source_link, page_links)

    return {
        "status": "ingested",
        "source": str(src),
        "source_page": str(source_page),
        "pages_created": created,
        "pages_updated": updated,
        "links": page_links,
    }


def _derive_title(text: str, fallback: str) -> str:
    m = re.search(r"^\s{0,3}#\s+(.+?)\s*$", text, re.MULTILINE)
    return m.group(1).strip() if m else fallback.replace("-", " ").replace("_", " ").title()


def _derive_summary(text: str, limit: int = 240) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for p in paragraphs:
        if p.startswith("#") or p.startswith("---"):
            continue
        summary = re.sub(r"\s+", " ", p)
        return summary[:limit] + ("…" if len(summary) > limit else "")
    return (text[:limit] + "…") if len(text) > limit else text


def _head(text: str, limit: int) -> str:
    body = text.strip()
    return body[:limit] + ("…" if len(body) > limit else "")


# ── Index + log maintenance ──────────────────────────────────────────────

def _refresh_index(wiki: Path) -> None:
    sections: list[str] = [INDEX_HEADER.rstrip() + "\n"]
    for sub in WIKI_SUBDIRS:
        d = wiki / sub
        if not d.exists():
            continue
        entries = sorted(d.glob("*.md"))
        if not entries:
            continue
        sections.append(f"## {sub.capitalize()}\n")
        for f in entries:
            fm, _ = _parse_frontmatter(f.read_text("utf-8"))
            title = fm.get("title", f.stem)
            summary = fm.get("summary", "")
            link = f"[[{sub}/{f.stem}]]"
            sections.append(f"- {link} — {title}" + (f" — {summary}" if summary else ""))
        sections.append("")
    (wiki / "index.md").write_text("\n".join(sections).rstrip() + "\n", "utf-8")


def _append_log(wiki: Path, src: Path, source_link: str, page_links: list[str]) -> None:
    log = wiki / "log.md"
    line = f"- {_now()} ingested `{src.name}` → {source_link}"
    if page_links:
        line += " + " + ", ".join(page_links)
    current = log.read_text("utf-8") if log.exists() else LOG_HEADER
    log.write_text(current.rstrip() + "\n" + line + "\n", "utf-8")


# ── Query (v1: grep) ─────────────────────────────────────────────────────

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def query(question: str, fabric_dir: Path, max_hits: int = 10) -> dict:
    q = question.strip().lower()
    if not q:
        return {"error": "empty question"}
    fabric_dir = Path(fabric_dir)
    hits: list[dict] = []

    for root, tag in ((_wiki_root(fabric_dir), "wiki"), (_raw_root(fabric_dir), "raw")):
        if not root.exists():
            continue
        for f in root.rglob("*.md"):
            text = f.read_text("utf-8", errors="replace")
            if q in text.lower():
                hits.append({
                    "source": tag,
                    "path": str(f),
                    "snippet": _snippet(text, q),
                })
                if len(hits) >= max_hits:
                    break
        if len(hits) >= max_hits:
            break

    return {"question": question, "count": len(hits), "hits": hits}


def _snippet(text: str, needle: str, radius: int = 80) -> str:
    idx = text.lower().find(needle)
    if idx < 0:
        return text[:radius]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    return ("…" if start > 0 else "") + text[start:end].replace("\n", " ") + ("…" if end < len(text) else "")


# ── Lint ─────────────────────────────────────────────────────────────────

def lint(fabric_dir: Path) -> dict:
    wiki = _wiki_root(Path(fabric_dir))
    if not wiki.exists():
        return {"error": "wiki not initialized"}

    pages: dict[str, Path] = {}
    inbound: Counter = Counter()
    sources_refs: dict[str, list[str]] = {}
    broken: list[dict] = []

    for f in wiki.rglob("*.md"):
        if f.name in ("index.md", "log.md", "Home.md"):
            continue
        rel = f.relative_to(wiki).with_suffix("").as_posix()
        pages[rel] = f

    for rel, f in pages.items():
        text = f.read_text("utf-8")
        fm, body = _parse_frontmatter(text)
        sources_refs[rel] = _WIKILINK_RE.findall(fm.get("sources", ""))
        for target in _WIKILINK_RE.findall(body):
            if target not in pages and target not in ("index", "log", "Home"):
                broken.append({"page": rel, "missing": target})
            else:
                inbound[target] += 1

    orphans = [rel for rel in pages if inbound[rel] == 0 and not rel.startswith("sources/")]
    missing_sources = [
        rel for rel, refs in sources_refs.items()
        if not refs and not rel.startswith("sources/")
    ]

    return {
        "status": "ok" if not (broken or orphans or missing_sources) else "issues",
        "broken_links": broken,
        "orphan_pages": orphans,
        "pages_without_sources": missing_sources,
        "page_count": len(pages),
    }
