"""Briefings assembled from wiki pages, archives, and recent supersessions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ._layers import atomic_write_json, call_openai_json, safe_id
from .schema import Entry
from .session_archive import ArchivedSession, SessionArchive
from .store import MarkdownStore
from .wiki import WikiManager, WikiPage

BRIEFING_TTL = timedelta(hours=1)
RECENT_SUPERSEDED_WINDOW = timedelta(days=30)
MAX_LLM_COST_USD = 0.05


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class Briefing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    task_description: str
    content: str
    source_ids: list[str] = Field(default_factory=list)
    page_paths: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)
    cache_key: str


class _MemoryLike(Protocol):
    store: MarkdownStore


class BriefingGenerator:
    """Generate cached task briefings for an agent."""

    def __init__(
        self,
        root: str | Path,
        *,
        wiki: WikiManager,
        archive: SessionArchive,
        memory: _MemoryLike,
    ):
        self.root = Path(root).expanduser().resolve()
        self.cache_root = self.root / ".icarus" / "briefings"
        self.wiki = wiki
        self.archive = archive
        self.memory = memory

    def generate(self, *, agent_id: str, task_description: str) -> Briefing:
        safe_agent = safe_id(agent_id, "agent_id")
        cache_key = self._cache_key(safe_agent, task_description)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached
        pages = list(self.wiki.search_pages(task_description))[:5]
        sessions = self.archive.search(task_description, agent_id=safe_agent, limit=5)
        failed = self.archive.search(
            task_description, agent_id=safe_agent, filter_failed=True, limit=5
        )
        superseded = self._recent_superseded()
        source_ids = [entry.id for entry in superseded]
        source_ids.extend(session.ref for session in sessions)
        page_paths = [page.path for page in pages]
        briefing = self._llm_or_template(
            agent_id=safe_agent,
            task_description=task_description,
            pages=pages,
            sessions=sessions,
            failed=failed,
            superseded=superseded,
            source_ids=source_ids,
            page_paths=page_paths,
            cache_key=cache_key,
        )
        atomic_write_json(self._cache_path(cache_key), briefing.model_dump(mode="json"))
        return briefing

    def _llm_or_template(
        self,
        *,
        agent_id: str,
        task_description: str,
        pages: list[WikiPage],
        sessions: list[ArchivedSession],
        failed: list[ArchivedSession],
        superseded: list[Entry],
        source_ids: list[str],
        page_paths: list[str],
        cache_key: str,
    ) -> Briefing:
        prompt = _briefing_prompt(
            task_description=task_description,
            pages=pages,
            sessions=sessions,
            failed=failed,
            superseded=superseded,
        )
        if _estimate_cost_usd(prompt) <= MAX_LLM_COST_USD:
            result = call_openai_json(prompt, max_tokens=350)
            if result is not None and isinstance(result.get("content"), str):
                return Briefing(
                    agent_id=agent_id,
                    task_description=task_description,
                    content=str(result["content"]),
                    source_ids=source_ids,
                    page_paths=page_paths,
                    cost_usd=_estimate_cost_usd(prompt),
                    cache_key=cache_key,
                )
        return Briefing(
            agent_id=agent_id,
            task_description=task_description,
            content=_template_content(task_description, pages, sessions, failed, superseded),
            source_ids=source_ids,
            page_paths=page_paths,
            cost_usd=0.0,
            cache_key=cache_key,
        )

    def _cache_key(self, agent_id: str, task_description: str) -> str:
        payload = {
            "agent_id": agent_id,
            "task_description": task_description,
            "wiki_version": self.wiki.version(),
            "archive_version": self.archive.agent_version(agent_id),
        }
        raw = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _read_cache(self, cache_key: str) -> Briefing | None:
        path = self._cache_path(cache_key)
        if not path.exists():
            return None
        briefing = Briefing.model_validate_json(path.read_text(encoding="utf-8"))
        if _utcnow() - briefing.created_at.astimezone(timezone.utc) > BRIEFING_TTL:
            return None
        return briefing

    def _cache_path(self, cache_key: str) -> Path:
        return self.cache_root / f"{cache_key}.json"

    def _recent_superseded(self) -> list[Entry]:
        cutoff = _utcnow() - RECENT_SUPERSEDED_WINDOW
        store = self.memory.store
        entries = store.iter_entries()
        return [
            entry
            for entry in entries
            if entry.lifecycle == "superseded"
            and self._supersession_time(entry).astimezone(timezone.utc) >= cutoff
        ][:10]

    def _supersession_time(self, entry: Entry) -> datetime:
        if entry.superseded_by is None:
            return entry.timestamp
        try:
            return self.memory.store.get(entry.superseded_by).timestamp
        except Exception:
            return entry.timestamp


def _briefing_prompt(
    *,
    task_description: str,
    pages: list[WikiPage],
    sessions: list[ArchivedSession],
    failed: list[ArchivedSession],
    superseded: list[Entry],
) -> str:
    return (
        "Write a concise ~200 word briefing for this task. Include source ids and page paths. "
        f"Task: {task_description}\n"
        f"Wiki pages: {[{'path': p.path, 'title': p.title, 'entries': p.entries} for p in pages]}\n"
        f"Same-agent sessions: {[s.model_dump(mode='json') for s in sessions]}\n"
        f"Failed attempts: {[s.ref for s in failed]}\n"
        f"Recent superseded entries: {[e.id + ': ' + e.summary for e in superseded]}\n"
        "Return JSON: {\"content\": \"...\"}."
    )


def _template_content(
    task_description: str,
    pages: list[WikiPage],
    sessions: list[ArchivedSession],
    failed: list[ArchivedSession],
    superseded: list[Entry],
) -> str:
    lines = [f"Task briefing for: {task_description}"]
    if pages:
        lines.append("Relevant wiki pages: " + ", ".join(page.path for page in pages))
    else:
        lines.append("Relevant wiki pages: none found")
    if sessions:
        lines.append(
            "Same-agent archive: "
            + "; ".join(f"{session.ref} - {session.final_summary}" for session in sessions[:3])
        )
    else:
        lines.append("Same-agent archive: no prior sessions found")
    failed_attempts = [
        attempt.text
        for session in failed
        for attempt in session.attempts
        if not attempt.succeeded
    ]
    if failed_attempts:
        lines.append("Known failed attempts: " + "; ".join(failed_attempts[:5]))
    if superseded:
        lines.append(
            "Recent superseded entries: "
            + ", ".join(f"{entry.id} ({entry.summary})" for entry in superseded[:5])
        )
    lines.append("Use promoted wiki entries as shared context; private session archives are same-agent only.")
    return "\n".join(lines)


def _estimate_cost_usd(prompt: str) -> float:
    approximate_tokens = max(1, len(prompt.split()) // 4)
    return approximate_tokens * 0.00000015
