"""Persistent wiki layer for Icarus.

This keeps synthesized knowledge in markdown pages separate from raw fabric
entries. The wiki is designed to be viewed directly in Obsidian and updated
incrementally by agents.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import state

WIKI_DIRNAME = "wiki"
PAGE_DIRS = {
    "entity": "entities",
    "person": "entities",
    "project": "entities",
    "topic": "topics",
    "decision": "topics",
    "source": "sources",
    "index": "indexes",
    "other": "notes",
}


def wiki_dir() -> Path:
    configured = os.environ.get("ICARUS_WIKI_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return state.FABRIC_DIR / WIKI_DIRNAME


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_title(title: str) -> str:
    title = " ".join(str(title).strip().split())
    title = re.sub(r'[\\/:\*\?"<>\|#\^]+', " ", title)
    title = re.sub(r"\s+", " ", title).strip(" .")
    return title[:120]


def _filename_for(title: str) -> str:
    safe = _safe_title(title)
    return f"{safe or 'Untitled'}.md"


def _split_csv(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = str(value).split(",")
    out = []
    seen = set()
    for item in items:
        cleaned = " ".join(str(item).strip().split())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _page_folder(page_type: str) -> str:
    normalized = str(page_type or "other").strip().lower()
    return PAGE_DIRS.get(normalized, PAGE_DIRS["other"])


def _page_path(title: str, page_type: str = "other") -> Path:
    return wiki_dir() / _page_folder(page_type) / _filename_for(title)


def _frontmatter(data: dict) -> str:
    lines = ["---"]
    for key in (
        "title",
        "type",
        "summary",
        "created_at",
        "updated_at",
        "agent",
    ):
        value = data.get(key, "")
        if value:
            lines.append(f"{key}: {json.dumps(str(value))}")
    for key in ("aliases", "tags", "wikilinks", "source_refs"):
        values = data.get(key, [])
        if values:
            encoded = ", ".join(json.dumps(str(v)) for v in values)
            lines.append(f"{key}: [{encoded}]")
    lines.append("---")
    return "\n".join(lines)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    frontmatter = text[4:end]
    body = text[end + 5:].lstrip("\n")
    parsed = {}
    for line in frontmatter.splitlines():
        if ": " not in line:
            continue
        key, raw = line.split(": ", 1)
        key = key.strip()
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed[key] = json.loads(raw)
            except Exception:
                parsed[key] = []
            continue
        try:
            parsed[key] = json.loads(raw)
        except Exception:
            parsed[key] = raw.strip("\"'")
    return parsed, body


def init_wiki() -> dict:
    root = wiki_dir()
    created = []
    for dirname in sorted(set(PAGE_DIRS.values())):
        path = root / dirname
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path))

    schema_path = root / "_schema.json"
    if not schema_path.exists():
        schema = {
            "version": 1,
            "description": "Persistent markdown wiki maintained by agents. Raw fabric entries stay immutable.",
            "page_types": sorted(set(PAGE_DIRS.keys())),
            "rules": [
                "Do not edit raw source material in fabric entries.",
                "Update existing pages before creating duplicates.",
                "Prefer wikilinks between related pages.",
                "Record contradictions and unknowns explicitly.",
                "Keep summaries short and factual.",
            ],
            "folders": PAGE_DIRS,
        }
        schema_path.write_text(json.dumps(schema, indent=2) + "\n", "utf-8")
        created.append(str(schema_path))

    home_path = root / "Home.md"
    if not home_path.exists():
        home_path.write_text(
            "\n".join(
                [
                    "# Icarus Wiki",
                    "",
                    "Persistent synthesized knowledge for Icarus.",
                    "",
                    "## Folders",
                    "- `entities/`: people, teams, products, projects",
                    "- `topics/`: themes, decisions, research summaries",
                    "- `sources/`: source manifests and provenance pages",
                    "- `indexes/`: curated overviews and maps",
                    "- `notes/`: temporary or uncategorized pages",
                    "",
                    "## Rules",
                    "- Raw fabric entries remain unchanged.",
                    "- Update pages incrementally as new evidence arrives.",
                    "- Use wikilinks aggressively where relationships matter.",
                    "- Keep contradictions visible instead of flattening them away.",
                ]
            )
            + "\n",
            "utf-8",
        )
        created.append(str(home_path))

    return {
        "status": "initialized" if created else "already_initialized",
        "wiki_dir": str(root),
        "created": created,
    }


def _find_existing_page(title: str) -> Optional[Path]:
    filename = _filename_for(title)
    root = wiki_dir()
    for dirname in sorted(set(PAGE_DIRS.values())):
        path = root / dirname / filename
        if path.exists():
            return path
    return None


def get_page(title: str) -> dict:
    path = _find_existing_page(title)
    if path is None:
        return {"found": False, "title": _safe_title(title)}
    text = path.read_text("utf-8")
    meta, body = _parse_frontmatter(text)
    return {
        "found": True,
        "title": meta.get("title") or path.stem,
        "path": str(path),
        "page_type": meta.get("type", ""),
        "summary": meta.get("summary", ""),
        "wikilinks": meta.get("wikilinks", []),
        "source_refs": meta.get("source_refs", []),
        "content": body,
    }


def upsert_page(
    title: str,
    content: str,
    page_type: str = "other",
    summary: str = "",
    wikilinks=None,
    source_refs=None,
    aliases=None,
    tags=None,
) -> dict:
    title = _safe_title(title)
    if not title:
        return {"error": "title is required"}
    content = str(content or "").strip()
    if not content:
        return {"error": "content is required"}

    existing = _find_existing_page(title)
    path = existing or _page_path(title, page_type)
    path.parent.mkdir(parents=True, exist_ok=True)

    created_at = _utc_now()
    if existing:
        old_meta, _ = _parse_frontmatter(existing.read_text("utf-8"))
        created_at = old_meta.get("created_at", created_at)
        page_type = old_meta.get("type", page_type) or page_type

    metadata = {
        "title": title,
        "type": str(page_type or "other").strip().lower(),
        "summary": " ".join(str(summary or "").strip().split()),
        "created_at": created_at,
        "updated_at": _utc_now(),
        "agent": state.AGENT_NAME or "agent",
        "aliases": _split_csv(aliases),
        "tags": _split_csv(tags),
        "wikilinks": _split_csv(wikilinks),
        "source_refs": _split_csv(source_refs),
    }

    text = _frontmatter(metadata) + "\n\n" + content.rstrip() + "\n"
    state._atomic_write_text(path, text)
    return {
        "status": "updated" if existing else "created",
        "path": str(path),
        "title": title,
        "page_type": metadata["type"],
    }


def search_pages(query: str, limit: int = 10) -> dict:
    q = str(query or "").strip().lower()
    if not q:
        return {"query": "", "count": 0, "results": []}

    results = []
    root = wiki_dir()
    if not root.exists():
        return {"query": query, "count": 0, "results": []}

    for path in sorted(root.rglob("*.md")):
        if path.name.startswith("."):
            continue
        text = path.read_text("utf-8")
        if q not in text.lower():
            continue
        meta, body = _parse_frontmatter(text)
        matches = [line.strip() for line in body.splitlines() if q in line.lower()][:3]
        results.append(
            {
                "title": meta.get("title") or path.stem,
                "path": str(path),
                "page_type": meta.get("type", ""),
                "summary": meta.get("summary", ""),
                "matches": matches,
            }
        )
        if len(results) >= max(int(limit or 10), 1):
            break

    return {"query": query, "count": len(results), "results": results}


def wiki_overview() -> dict:
    root = wiki_dir()
    counts = {}
    recent = []
    total = 0

    if not root.exists():
        return {"exists": False, "wiki_dir": str(root), "total_pages": 0, "counts": {}, "recent": []}

    for dirname in sorted(set(PAGE_DIRS.values())):
        folder = root / dirname
        pages = [p for p in folder.glob("*.md") if p.is_file()]
        counts[dirname] = len(pages)
        total += len(pages)
        for page in pages:
            recent.append((page.stat().st_mtime, page))

    recent.sort(reverse=True)
    recent_pages = []
    for _, path in recent[:10]:
        meta, _ = _parse_frontmatter(path.read_text("utf-8"))
        recent_pages.append(
            {
                "title": meta.get("title") or path.stem,
                "path": str(path),
                "page_type": meta.get("type", ""),
                "updated_at": meta.get("updated_at", ""),
            }
        )

    return {
        "exists": True,
        "wiki_dir": str(root),
        "total_pages": total,
        "counts": counts,
        "recent": recent_pages,
    }
