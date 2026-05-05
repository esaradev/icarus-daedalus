"""icarus-memory: framework-agnostic agent memory with provenance and rollback."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .exceptions import (
    EntryNotFound,
    IcarusMemoryError,
    RollbackError,
    StoreError,
    ValidationError,
)
from .lineage import lineage as _lineage
from .retrieval import RecallMode
from .retrieval import keyword_search as _keyword_search
from .retrieval import recall as _recall
from .rollback import apply_rollback, plan_rollback
from .schema import (
    Entry,
    EvidencePointer,
    RecallHit,
    RollbackPlan,
    TrainingValue,
    VerificationRecord,
    VerifiedStatus,
)
from .store import MarkdownStore
from .validation import validate_for_write

__version__ = "0.1.0"

DEFAULT_ROOT_ENV = "ICARUS_FABRIC_ROOT"
DEFAULT_ROOT = "~/fabric"


def _resolve_root(root: str | Path | None) -> Path:
    if root is not None:
        return Path(root).expanduser()
    env = os.environ.get(DEFAULT_ROOT_ENV)
    if env:
        return Path(env).expanduser()
    return Path(DEFAULT_ROOT).expanduser()


class IcarusMemory:
    """High-level facade over the on-disk fabric.

    Owns a ``MarkdownStore`` and exposes the public API for writing,
    reading, recalling, verifying, contradicting, and rolling back entries.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        embedding_model: str = "BAAI/bge-small-en-v1.5",
        platform: str = "icarus-memory",
    ):
        self.root = _resolve_root(root)
        self.store = MarkdownStore(self.root)
        self.embedding_model = embedding_model
        self.platform = platform

    # -- Write / read ---------------------------------------------------

    def write(
        self,
        *,
        agent: str,
        type: str,
        summary: str,
        body: str = "",
        platform: str | None = None,
        timestamp: datetime | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        assigned_to: str | None = None,
        review_of: str | None = None,
        revises: str | None = None,
        training_value: TrainingValue = "normal",
        evidence: list[dict[str, Any]] | list[EvidencePointer] | None = None,
        source_tool: str | None = None,
        artifact_paths: list[str] | None = None,
    ) -> Entry:
        evidence_models = [
            ev if isinstance(ev, EvidencePointer) else EvidencePointer(**ev)
            for ev in (evidence or [])
        ]
        entry = Entry(
            id=self.store.generate_id(),
            agent=agent,
            platform=platform or self.platform,
            timestamp=timestamp or datetime.now(timezone.utc).replace(microsecond=0),
            type=type,
            summary=summary,
            body=body,
            project_id=project_id,
            session_id=session_id,
            status=status,  # type: ignore[arg-type]
            assigned_to=assigned_to,
            review_of=review_of,
            revises=revises,
            training_value=training_value,
            evidence=evidence_models,
            source_tool=source_tool,
            artifact_paths=artifact_paths or [],
        )
        validate_for_write(entry, self.store, is_initial_write=True)
        return self.store.write(entry)

    def get(self, entry_id: str) -> Entry:
        return self.store.get(entry_id)

    # -- Recall / search ------------------------------------------------

    def recall(
        self,
        query: str,
        *,
        k: int = 10,
        mode: RecallMode = "auto",
        min_verified: VerifiedStatus = "unverified",
        exclude_rolled_back: bool = True,
        agent: str | None = None,
        project_id: str | None = None,
        type: str | None = None,
    ) -> list[RecallHit]:
        return _recall(
            self.store,
            query,
            k=k,
            mode=mode,
            min_verified=min_verified,
            exclude_rolled_back=exclude_rolled_back,
            agent=agent,
            project_id=project_id,
            type=type,
            embedding_model=self.embedding_model,
        )

    def search(self, query: str) -> list[Entry]:
        return _keyword_search(self.store, query)

    # -- Verification ---------------------------------------------------

    def verify(self, entry_id: str, *, verifier: str = "manual", note: str = "") -> Entry:
        entry = self.store.get(entry_id)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entry.verified = "verified"
        entry.verification_log.append(
            VerificationRecord(
                verifier=verifier, timestamp=now, status="verified", note=note
            )
        )
        return self.store.write(entry)

    def contradict(self, entry_id: str, *, contradicted_by: str, reason: str) -> Entry:
        entry = self.store.get(entry_id)
        if not self.store.exists(contradicted_by):
            raise ValidationError(
                f"contradicted_by points to nonexistent entry {contradicted_by}"
            )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entry.verified = "contradicted"
        entry.contradicted_by = contradicted_by
        entry.verification_log.append(
            VerificationRecord(
                verifier="contradict",
                timestamp=now,
                status="contradicted",
                note=reason,
            )
        )
        validate_for_write(entry, self.store, is_initial_write=False)
        return self.store.write(entry)

    # -- Rollback / lineage --------------------------------------------

    def rollback(self, entry_id: str, *, dry_run: bool = True) -> RollbackPlan:
        plan = plan_rollback(self.store, entry_id)
        if dry_run:
            return plan
        if plan.error:
            raise RollbackError(plan.error)
        return apply_rollback(self.store, plan)

    def lineage(self, entry_id: str) -> list[Entry]:
        return _lineage(self.store, entry_id)

    def pending(self, agent: str | None = None) -> list[Entry]:
        out = []
        for entry in self.store.iter_entries():
            if entry.status != "open":
                continue
            if agent is not None and entry.assigned_to != agent:
                continue
            out.append(entry)
        return out


__all__ = [
    "Entry",
    "EntryNotFound",
    "EvidencePointer",
    "IcarusMemory",
    "IcarusMemoryError",
    "RecallHit",
    "RecallMode",
    "RollbackError",
    "RollbackPlan",
    "StoreError",
    "TrainingValue",
    "ValidationError",
    "VerificationRecord",
    "VerifiedStatus",
    "__version__",
]
