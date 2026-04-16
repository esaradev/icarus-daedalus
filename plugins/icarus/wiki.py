"""Icarus Wiki — persistent markdown knowledge layer.

Three-folder contract under FABRIC_DIR:
  raw/     immutable source material (user-dropped files)
  wiki/    LLM-owned pages (entities, topics, sources, indexes, notes)
  wiki/_schema.json   ingest rules + conventions

Tools:
  init_wiki — scaffold
  ingest    — raw source -> source page + entity/topic pages + index + log
  query     — grep wiki first, raw second
  lint      — report broken wikilinks, orphan pages, pages without sources

Entity/topic extraction:
  v1.0 shipped a deterministic heuristic (headings + repeated capitalized
  phrases). v1.1 adds an LLM path via Together AI (reuses TOGETHER_API_KEY)
  that returns a JSON list of {kind, title, slug, summary}. The LLM path
  falls back silently to the heuristic when the key is missing, the call
  errors, or the response is malformed. Set WIKI_LLM_EXTRACTION=0 to force
  the heuristic. Every ingest records which path ran via extraction_mode
  in the response and in the source page frontmatter.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LLM_TIMEOUT_S = 30

# Provider registry, picked in order. First one with an available key wins.
# All providers use the OpenAI chat/completions wire format.
_PROVIDERS = [
    ("openrouter", "OPENROUTER_API_KEY",
     "https://openrouter.ai/api/v1/chat/completions",
     "anthropic/claude-haiku-4-5"),
    ("anthropic_openai", "ANTHROPIC_API_KEY",
     "https://api.anthropic.com/v1/chat/completions",
     "claude-haiku-4-5"),
    ("openai", "OPENAI_API_KEY",
     "https://api.openai.com/v1/chat/completions",
     "gpt-4o-mini"),
    ("together", "TOGETHER_API_KEY",
     "https://api.together.xyz/v1/chat/completions",
     "meta-llama/Llama-3.1-8B-Instruct-Turbo"),
]

# Back-compat aliases for code still importing these.
LLM_MODEL_DEFAULT = _PROVIDERS[0][3]
LLM_ENDPOINT = _PROVIDERS[0][2]

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


def _extract_candidates_heuristic(text: str, max_pages: int = 5) -> list[dict]:
    """Deterministic v1 extractor. Each dict: {kind, title, slug, evidence}.

    Headings -> topic pages. Repeated capitalized phrases -> entity pages.
    Topics and entities are interleaved so both kinds surface when one is
    abundant. Pure Python, no network.
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


# ── LLM extractor (v1.1) ─────────────────────────────────────────────────

_LLM_SYSTEM = (
    "You extract structured entity and topic candidates from a markdown source "
    "for a personal knowledge wiki. Return strict JSON only, no prose."
)

_LLM_USER_TEMPLATE = """Read the source and return up to {max_pages} candidates that would each make a useful wiki page.

Rules:
- kind is "entity" for people, products, organisations, projects.
- kind is "topic" for concepts, themes, techniques, patterns.
- title is the human-readable page title.
- slug is kebab-case, lowercase, no punctuation, no spaces, <= 64 chars.
- summary is one line, <= 160 chars, grounded strictly in the source.
- Omit generic filler ("Introduction", "Overview") and pronouns.
- Prefer entities that appear only once over repeated noise.

Output JSON object exactly like:
{{"candidates": [{{"kind": "entity", "title": "Andrej Karpathy", "slug": "andrej-karpathy", "summary": "..."}}]}}

Source:
<<<
{source}
>>>"""


def _load_env_file_keys() -> dict[str, str]:
    """Read $HERMES_HOME/.env so we can pick up keys that were set there
    rather than exported in the shell that launched the dashboard."""
    out: dict[str, str] = {}
    hh = os.environ.get("HERMES_HOME", "")
    if not hh:
        return out
    env_path = Path(hh) / ".env"
    if not env_path.exists():
        return out
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _pick_llm_provider() -> Optional[tuple[str, str, str, str]]:
    """Return (key, endpoint, model, name) for the first configured provider,
    or None if nothing is set. Respects WIKI_LLM_MODEL as an override."""
    env_file = _load_env_file_keys()
    model_override = os.environ.get("WIKI_LLM_MODEL", "").strip()
    for name, env_var, endpoint, default_model in _PROVIDERS:
        key = os.environ.get(env_var, "").strip() or env_file.get(env_var, "").strip()
        if key:
            return key, endpoint, model_override or default_model, name
    return None


def _together_key_for_wiki() -> str:
    """Back-compat shim for tests. Returns the first configured provider key."""
    picked = _pick_llm_provider()
    return picked[0] if picked else ""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)


def _loose_parse_json_object(text: str) -> dict:
    """Parse a JSON object from an LLM response that may include prose or
    markdown fences. Falls back to the first {...} span in the text."""
    text = (text or "").strip()
    try:
        out = json.loads(text)
        if isinstance(out, dict):
            return out
    except Exception:
        pass
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # last resort: first balanced {...}
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except Exception:
                        break
    raise ValueError("LLM response did not contain a parseable JSON object")


def _summarize_llm_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        if detail:
            detail = re.sub(r"\s+", " ", detail)[:160]
            return f"http-{exc.code}: {detail}"
        return f"http-{exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"network: {exc.reason}"
    return re.sub(r"\s+", " ", str(exc)).strip()[:160] or exc.__class__.__name__


def _extract_candidates_llm(text: str, max_pages: int = 5) -> list[dict]:
    """Call the configured LLM provider to get entity/topic candidates as JSON.

    Raises on any failure (no-key, network, malformed JSON, empty result).
    Caller is responsible for fallback.
    """
    picked = _pick_llm_provider()
    if not picked:
        raise RuntimeError("no LLM provider key configured")
    key, endpoint, model, _ = picked

    # bound the source we send; most sources are small, but cap to keep latency sane
    trimmed = text if len(text) <= 8000 else text[:8000]
    prompt = _LLM_USER_TEMPLATE.format(max_pages=max_pages, source=trimmed)

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 512,
        "temperature": 0.2,
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S)
    body = json.loads(resp.read())
    content = body["choices"][0]["message"]["content"]
    parsed = _loose_parse_json_object(content)
    raw_items = parsed.get("candidates") if isinstance(parsed, dict) else None
    if not isinstance(raw_items, list):
        raise ValueError("LLM response missing 'candidates' list")

    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        title = (item.get("title") or "").strip()
        if kind not in ("entity", "topic") or len(title) < 3:
            continue
        slug = _slugify(item.get("slug") or title)
        if slug in seen:
            continue
        seen.add(slug)
        summary = (item.get("summary") or "").strip()[:240]
        out.append({
            "kind": kind,
            "title": title,
            "slug": slug,
            "evidence": summary or "LLM-extracted",
        })
        if len(out) >= max_pages:
            break
    if not out:
        raise ValueError("LLM returned no valid candidates")
    return out


def _extract_candidates(text: str, max_pages: int = 5) -> tuple[list[dict], str, str]:
    """Dispatch to LLM or heuristic and report which path ran.

    Returns (candidates, mode) where mode is one of:
      "llm"                — LLM call succeeded
      "heuristic"          — WIKI_LLM_EXTRACTION=0 (explicit opt-out)
      "heuristic-no-key"   — no API key configured
      "heuristic-fallback" — LLM call attempted but failed
    """
    if os.environ.get("WIKI_LLM_EXTRACTION", "1") == "0":
        return _extract_candidates_heuristic(text, max_pages), "heuristic", "WIKI_LLM_EXTRACTION=0"
    picked = _pick_llm_provider()
    if not picked:
        return (
            _extract_candidates_heuristic(text, max_pages),
            "heuristic-no-key",
            "No LLM provider key found (OPENROUTER_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY / TOGETHER_API_KEY)",
        )
    try:
        return _extract_candidates_llm(text, max_pages), "llm", f"{picked[3]} extraction succeeded"
    except Exception as exc:
        reason = _summarize_llm_error(exc)
        logger.info("icarus.wiki: LLM extraction fell back (%s)", reason)
        return _extract_candidates_heuristic(text, max_pages), "heuristic-fallback", reason


def llm_status(live: bool = True) -> dict:
    enabled = os.environ.get("WIKI_LLM_EXTRACTION", "1") != "0"
    picked = _pick_llm_provider()
    status = {
        "enabled": enabled,
        "provider": picked[3] if picked else None,
        "model": picked[2] if picked else None,
        "endpoint": picked[1] if picked else None,
        "key_present": picked is not None,
        "live_check": bool(live),
    }
    if not enabled:
        return {**status, "status": "disabled", "reason": "WIKI_LLM_EXTRACTION=0"}
    if not picked:
        return {
            **status,
            "status": "missing_key",
            "reason": "No LLM provider key set (OPENROUTER_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY / TOGETHER_API_KEY)",
        }
    if not live:
        return {**status, "status": "configured", "reason": "Live check skipped"}

    key, endpoint, model, _ = picked
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply with the single word ok."},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 8,
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
            body = json.loads(resp.read())
        return {
            **status,
            "status": "ok",
            "http_status": getattr(resp, "status", 200),
            "response_id": body.get("id", ""),
            "reason": "Together endpoint accepted request",
        }
    except Exception as exc:
        return {
            **status,
            "status": "error",
            "reason": _summarize_llm_error(exc),
        }


# ── Ask (v1.2) ───────────────────────────────────────────────────────────
# Ground an LLM answer in the wiki. v1 retrieval is keyword overlap, which
# is fine for a personal wiki on the order of 10-500 pages. Swap for
# embeddings when corpus size justifies the cost.

_ASK_SYSTEM = (
    "You answer questions strictly from the provided wiki pages. Cite the "
    "pages you used with their [[path]] wikilinks inline in your answer. "
    "If the pages don't contain the answer, say so plainly — do not make "
    "up facts. Be concise."
)


def _tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower())}


def _rank_pages(question: str, pages: list[dict], limit: int = 6) -> list[dict]:
    q_tokens = _tokenize(question)
    if not q_tokens:
        return []
    scored: list[tuple[int, dict]] = []
    for p in pages:
        haystack = " ".join(filter(None, [
            p.get("title", ""), p.get("summary", ""), p.get("body", ""),
        ]))
        overlap = len(q_tokens & _tokenize(haystack))
        if overlap:
            scored.append((overlap, p))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [p for _, p in scored[:limit]]


def _load_wiki_pages(fabric_dir: Path) -> list[dict]:
    wiki = _wiki_root(fabric_dir)
    if not wiki.exists():
        return []
    out: list[dict] = []
    for sub in WIKI_SUBDIRS:
        d = wiki / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            text = f.read_text("utf-8", errors="replace")
            fm, body = _parse_frontmatter(text)
            out.append({
                "path": f"{sub}/{f.stem}",
                "title": fm.get("title", f.stem),
                "summary": fm.get("summary", ""),
                "body": body,
            })
    return out


def ask(question: str, fabric_dir: Path, max_pages: int = 6) -> dict:
    """Answer a question using the wiki as the sole source.

    Returns {question, answer, citations, pages_considered, mode, reason}.
    mode is "llm" on success or "error" with a reason describing the cause.
    """
    q = (question or "").strip()
    if not q:
        return {"error": "empty question"}

    pages = _load_wiki_pages(Path(fabric_dir))
    if not pages:
        return {
            "question": q,
            "answer": "",
            "citations": [],
            "pages_considered": [],
            "mode": "empty",
            "reason": "No wiki pages found. Ingest a source first.",
        }

    top = _rank_pages(q, pages, max_pages)
    if not top:
        return {
            "question": q,
            "answer": "",
            "citations": [],
            "pages_considered": [],
            "mode": "no_match",
            "reason": "No pages mention any keywords from your question.",
        }

    picked = _pick_llm_provider()
    if not picked:
        return {
            "question": q,
            "answer": "",
            "citations": [],
            "pages_considered": [p["path"] for p in top],
            "mode": "no_key",
            "reason": "No LLM provider key found — retrieved pages listed below.",
        }
    key, endpoint, model, _ = picked

    context = "\n\n".join(
        f"=== [[{p['path']}]] ===\n"
        f"Title: {p['title']}\n"
        f"Summary: {p['summary']}\n\n"
        f"{p['body'][:2000]}"
        for p in top
    )

    prompt = (
        f"Wiki pages (use only these):\n\n{context}\n\n"
        f"Question: {q}\n\n"
        f"Answer using only the pages above. Cite each page you use with its "
        f"[[path]] wikilink inline."
    )

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _ASK_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 700,
        "temperature": 0.2,
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S)
        body = json.loads(resp.read())
        answer = body["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return {
            "question": q,
            "answer": "",
            "citations": [],
            "pages_considered": [p["path"] for p in top],
            "mode": "error",
            "reason": _summarize_llm_error(exc),
        }

    cited = [p for p in re.findall(r"\[\[([^\]]+)\]\]", answer)
             if p in {x["path"] for x in top}]
    # dedupe preserving order
    seen: set[str] = set()
    citations = [c for c in cited if not (c in seen or seen.add(c))]

    return {
        "question": q,
        "answer": answer,
        "citations": citations,
        "pages_considered": [p["path"] for p in top],
        "mode": "llm",
        "reason": f"Answered from {len(citations)} cited page(s).",
    }


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
    extra_frontmatter: Optional[dict] = None,
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
        if extra_frontmatter:
            for k, v in extra_frontmatter.items():
                fm[k] = v
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
    if extra_frontmatter:
        for k, v in extra_frontmatter.items():
            fm[k] = v
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

    candidates, extraction_mode, extraction_reason = _extract_candidates(text, max_pages=4)
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
        extra_frontmatter={
            "extraction_mode": extraction_mode,
            "extraction_reason": extraction_reason,
        },
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
        "extraction_mode": extraction_mode,
        "extraction_reason": extraction_reason,
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
