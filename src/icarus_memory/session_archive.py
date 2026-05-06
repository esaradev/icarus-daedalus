"""Immutable per-agent archive of completed working-memory sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ._layers import atomic_write_json, safe_id
from .working_memory import WorkingMemory


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class ArchivedAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    succeeded: bool


class ArchivedSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    session_id: str
    task_description: str
    final_summary: str
    observations: list[str] = Field(default_factory=list)
    attempts: list[ArchivedAttempt] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    promoted_to_wiki: list[str] = Field(default_factory=list)
    archived_at: datetime = Field(default_factory=_utcnow)

    @property
    def ref(self) -> str:
        return f"session_archive:{self.agent_id}:{self.session_id}"


class SessionArchive:
    """Read and write same-agent session archives."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.archive_root = self.root / ".icarus" / "agents"

    def archive(
        self,
        working_memory: WorkingMemory,
        *,
        final_summary: str,
        promoted_to_wiki: list[str] | None = None,
    ) -> ArchivedSession:
        session = ArchivedSession(
            agent_id=safe_id(working_memory.agent_id, "agent_id"),
            session_id=safe_id(working_memory.session_id, "session_id"),
            task_description=working_memory.task_description,
            final_summary=final_summary,
            observations=[item.text for item in working_memory.observations],
            attempts=[
                ArchivedAttempt(text=item.text, succeeded=item.succeeded)
                for item in working_memory.attempts
            ],
            hypotheses=[item.text for item in working_memory.hypotheses],
            promoted_to_wiki=promoted_to_wiki or [],
        )
        atomic_write_json(self._file_for(session.agent_id, session.session_id), session.model_dump(mode="json"))
        working_memory.end()
        return session

    def get(self, agent_id: str, session_id: str) -> ArchivedSession | None:
        path = self._file_for(safe_id(agent_id, "agent_id"), safe_id(session_id, "session_id"))
        if not path.exists():
            return None
        return ArchivedSession.model_validate_json(path.read_text(encoding="utf-8"))

    def search(
        self,
        query: str,
        *,
        agent_id: str,
        filter_failed: bool = False,
        limit: int = 5,
    ) -> list[ArchivedSession]:
        safe_agent = safe_id(agent_id, "agent_id")
        tokens = {token.lower() for token in query.split() if token.strip()}
        scored: list[tuple[int, ArchivedSession]] = []
        for session in self.iter_agent_sessions(safe_agent):
            if filter_failed and not any(not attempt.succeeded for attempt in session.attempts):
                continue
            haystack = _session_text(session).lower()
            score = sum(haystack.count(token) for token in tokens) if tokens else 1
            if score > 0:
                scored.append((score, session))
        scored.sort(key=lambda item: (-item[0], item[1].archived_at), reverse=False)
        return [session for _, session in scored[:limit]]

    def iter_agent_sessions(self, agent_id: str) -> list[ArchivedSession]:
        safe_agent = safe_id(agent_id, "agent_id")
        agent_root = self.archive_root / safe_agent / "sessions"
        sessions: list[ArchivedSession] = []
        for path in sorted(agent_root.glob("*.json")):
            sessions.append(ArchivedSession.model_validate_json(path.read_text(encoding="utf-8")))
        return sessions

    def agent_version(self, agent_id: str) -> str:
        safe_agent = safe_id(agent_id, "agent_id")
        agent_root = self.archive_root / safe_agent / "sessions"
        parts: list[str] = []
        for path in sorted(agent_root.glob("*.json")):
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
        return "|".join(parts)

    def _file_for(self, agent_id: str, session_id: str) -> Path:
        safe_agent = safe_id(agent_id, "agent_id")
        safe_session = safe_id(session_id, "session_id")
        return self.archive_root / safe_agent / "sessions" / f"{safe_session}.json"


def _session_text(session: ArchivedSession) -> str:
    attempts = " ".join(attempt.text for attempt in session.attempts)
    return " ".join(
        [
            session.task_description,
            session.final_summary,
            " ".join(session.observations),
            attempts,
            " ".join(session.hypotheses),
        ]
    )
