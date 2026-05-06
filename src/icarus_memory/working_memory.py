"""Short-lived working memory for an active agent session."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ._layers import atomic_write_json, safe_id

WORKING_TTL = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class WorkingObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkingAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    succeeded: bool
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkingHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkingMemory(BaseModel):
    """Mutable prompt context for one active session."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    agent_id: str
    session_id: str
    task_description: str = Field(min_length=1)
    observations: list[WorkingObservation] = Field(default_factory=list)
    attempts: list[WorkingAttempt] = Field(default_factory=list)
    hypotheses: list[WorkingHypothesis] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    root: Path | None = Field(default=None, exclude=True)
    persist: bool = Field(default=True, exclude=True)

    @classmethod
    def start(
        cls,
        root: str | Path,
        *,
        agent_id: str,
        session_id: str,
        task_description: str,
        persist: bool = True,
    ) -> WorkingMemory:
        wm = cls(
            root=Path(root).expanduser().resolve(),
            agent_id=safe_id(agent_id, "agent_id"),
            session_id=safe_id(session_id, "session_id"),
            task_description=task_description,
            persist=persist,
        )
        wm._persist()
        return wm

    @classmethod
    def load(
        cls,
        root: str | Path,
        *,
        session_id: str,
        persist: bool = True,
    ) -> WorkingMemory | None:
        root_path = Path(root).expanduser().resolve()
        safe_session = safe_id(session_id, "session_id")
        path = root_path / ".icarus" / "sessions" / f"{safe_session}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        wm = cls.model_validate(data)
        wm.root = root_path
        wm.persist = persist
        if wm.is_expired():
            return None
        return wm

    def add_observation(self, text: str) -> WorkingObservation:
        item = WorkingObservation(text=text)
        self.observations.append(item)
        self.touch()
        return item

    def add_attempt(self, text: str, *, succeeded: bool) -> WorkingAttempt:
        item = WorkingAttempt(text=text, succeeded=succeeded)
        self.attempts.append(item)
        self.touch()
        return item

    def add_hypothesis(self, text: str, *, confidence: float = 0.5) -> WorkingHypothesis:
        item = WorkingHypothesis(text=text, confidence=confidence)
        self.hypotheses.append(item)
        self.touch()
        return item

    def touch(self) -> None:
        self.updated_at = _utcnow()
        self._persist()

    def is_expired(self, *, now: datetime | None = None) -> bool:
        ref = now or _utcnow()
        return ref - self.updated_at.astimezone(timezone.utc) > WORKING_TTL

    def get_context(self, max_tokens: int = 2000) -> str:
        self._drop_expired()
        lines = [
            f"Task: {self.task_description}",
            "",
            "Observations:",
            *[f"- {item.text}" for item in self.observations],
            "",
            "Attempts:",
            *[
                f"- {'success' if item.succeeded else 'failed'}: {item.text}"
                for item in self.attempts
            ],
            "",
            "Hypotheses:",
            *[
                f"- {item.text} (confidence {item.confidence:.2f})"
                for item in self.hypotheses
            ],
        ]
        return _truncate_tokens("\n".join(lines).strip() + "\n", max_tokens)

    def end(self) -> None:
        path = self._path()
        if path is not None:
            path.unlink(missing_ok=True)

    def _drop_expired(self) -> None:
        cutoff = _utcnow() - WORKING_TTL
        self.observations = [item for item in self.observations if item.updated_at >= cutoff]
        self.attempts = [item for item in self.attempts if item.updated_at >= cutoff]
        self.hypotheses = [item for item in self.hypotheses if item.updated_at >= cutoff]

    def _persist(self) -> None:
        path = self._path()
        if path is not None:
            atomic_write_json(path, self.model_dump(mode="json"))

    def _path(self) -> Path | None:
        if self.root is None or not self.persist:
            return None
        return self.root / ".icarus" / "sessions" / f"{self.session_id}.json"


def _truncate_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    words = text.split()
    budget = max_tokens * 4
    if len(words) <= budget:
        return text
    return " ".join(words[:budget])
