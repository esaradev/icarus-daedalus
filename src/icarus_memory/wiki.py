"""Shared wiki pages layered over Entry records.

Wiki pages are intentionally global within one fabric root. They are used for
promoted knowledge that should be visible across agents; private same-agent
history belongs in the session archive instead.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._layers import (
    atomic_write_text,
    call_openai_json,
    safe_page_path,
    split_yaml_frontmatter,
    yaml_frontmatter,
)
from .exceptions import StoreError, ValidationError
from .retrieval import RecallMode
from .schema import Entry, RecallHit

PageType = Literal["topic", "decision", "project", "agent", "uncategorized"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class WikiPage(BaseModel):
    """A Markdown wiki page whose provenance is a list of Entry ids."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    title: str = Field(min_length=1)
    page_type: PageType = "topic"
    entries: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    body: str = ""

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: str) -> str:
        return safe_page_path(value)


class _MemoryLike(Protocol):
    def recall(
        self, query: str, *, k: int = 10, mode: RecallMode = "auto"
    ) -> list[RecallHit]: ...

    def get(self, entry_id: str) -> Entry: ...


class WikiManager:
    """Create, read, search, and classify wiki pages under ``.icarus/wiki``."""

    def __init__(self, root: str | Path, memory: _MemoryLike | None = None):
        self.root = Path(root).expanduser().resolve()
        self.wiki_root = self.root / ".icarus" / "wiki"
        self.memory = memory
        self.wiki_root.mkdir(parents=True, exist_ok=True)

    def get_page(self, path: str) -> WikiPage | None:
        safe = safe_page_path(path)
        file_path = self._file_for(safe)
        if not file_path.exists():
            return None
        try:
            front, body = split_yaml_frontmatter(file_path.read_text(encoding="utf-8"))
            return WikiPage(**front, body=body)
        except Exception as exc:
            raise StoreError(f"invalid wiki page at {file_path}: {exc}") from exc

    def ensure_page(
        self, path: str, *, title: str | None = None, page_type: PageType = "topic"
    ) -> WikiPage:
        safe = safe_page_path(path)
        existing = self.get_page(safe)
        if existing is not None:
            return existing
        now = _utcnow()
        page = WikiPage(
            path=safe,
            title=title or _title_from_path(safe),
            page_type=page_type,
            created_at=now,
            updated_at=now,
        )
        self.write_page(page)
        return page

    def write_page(self, page: WikiPage) -> WikiPage:
        safe = safe_page_path(page.path)
        page.path = safe
        page.updated_at = _utcnow()
        page.body = self._render_body(page.entries)
        front = page.model_dump(mode="json", exclude={"body"})
        atomic_write_text(self._file_for(safe), yaml_frontmatter(front, page.body))
        return page

    def add_entry(self, path: str, entry_id: str, *, page_type: PageType = "topic") -> WikiPage:
        page = self.ensure_page(path, page_type=page_type)
        if entry_id not in page.entries:
            page.entries.append(entry_id)
        return self.write_page(page)

    def classify_and_add(self, entry: Entry) -> WikiPage:
        page_path, page_type = self._classify_entry(entry)
        return self.add_entry(page_path, entry.id, page_type=page_type)

    def search_pages(self, query: str) -> list[WikiPage]:
        if self.memory is None:
            return [
                page
                for page in self.iter_pages()
                if query.lower() in f"{page.path} {page.title} {page.body}".lower()
            ]
        hits = self.memory.recall(query, k=20, mode="auto")
        hit_ids = {hit.entry.id for hit in hits}
        return [page for page in self.iter_pages() if hit_ids.intersection(page.entries)]

    def iter_pages(self) -> Iterable[WikiPage]:
        for path in sorted(self.wiki_root.rglob("*.md")):
            rel = path.relative_to(self.wiki_root).with_suffix("")
            page = self.get_page(rel.as_posix())
            if page is not None:
                yield page

    def version(self) -> str:
        parts: list[str] = []
        for path in sorted(self.wiki_root.rglob("*.md")):
            stat = path.stat()
            parts.append(f"{path.relative_to(self.wiki_root).as_posix()}:{stat.st_mtime_ns}:{stat.st_size}")
        return "|".join(parts)

    def _file_for(self, safe_path: str) -> Path:
        full = (self.wiki_root / f"{safe_path}.md").resolve()
        if self.wiki_root not in full.parents:
            raise ValidationError("wiki path escapes wiki root")
        return full

    def _classify_entry(self, entry: Entry) -> tuple[str, PageType]:
        existing = [
            {"path": page.path, "title": page.title, "page_type": page.page_type}
            for page in self.iter_pages()
        ]
        prompt = (
            "Choose a wiki page for this memory entry. Existing pages: "
            f"{existing}. Entry summary: {entry.summary!r}. Entry body: {entry.body[:1000]!r}. "
            "Return JSON with keys path and page_type. Use an existing path when appropriate."
        )
        result = call_openai_json(prompt, max_tokens=120)
        if result is None:
            return "uncategorized", "uncategorized"
        try:
            path = safe_page_path(str(result.get("path", "uncategorized")))
            raw_type = str(result.get("page_type", "topic"))
            page_type: PageType = raw_type if raw_type in _PAGE_TYPES else "topic"  # type: ignore[assignment]
            return path, page_type
        except ValidationError:
            return "uncategorized", "uncategorized"

    def _render_body(self, entry_ids: list[str]) -> str:
        lines = ["# Linked Entries", ""]
        if not entry_ids:
            lines.append("_No linked entries yet._")
            return "\n".join(lines) + "\n"
        for idx, entry_id in enumerate(entry_ids, start=1):
            entry = self._entry_or_none(entry_id)
            if entry is None:
                lines.append(f"- {entry_id} [missing]")
                continue
            status = entry.status or entry.lifecycle
            evidence_refs = ", ".join(ev.ref for ev in entry.evidence) or "none"
            lines.append(f"- [{entry.id}] {entry.summary}")
            lines.append(f"  - status: {status}; lifecycle: {entry.lifecycle}")
            lines.append(f"  - evidence: {evidence_refs}")
            lines.append(f"  - provenance: [^{idx}]")
            lines.append(f"[^{idx}]: entry {entry.id} by {entry.agent} at {entry.timestamp.isoformat()}")
        return "\n".join(lines) + "\n"

    def _entry_or_none(self, entry_id: str) -> Entry | None:
        if self.memory is None:
            return None
        try:
            return self.memory.get(entry_id)
        except Exception:
            return None


_PAGE_TYPES = {"topic", "decision", "project", "agent", "uncategorized"}


def _title_from_path(path: str) -> str:
    return path.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").title()
