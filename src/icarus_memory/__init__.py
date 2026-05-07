"""icarus-memory: framework-agnostic agent memory with provenance and rollback."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from .briefing import Briefing, BriefingGenerator
from .exceptions import (
    EntryNotFound,
    IcarusMemoryError,
    IllegalStateTransition,
    RollbackError,
    StoreError,
    ValidationError,
)
from .lineage import lineage as _lineage
from .retrieval import RecallMode, StatusFilter
from .retrieval import audit_search as _audit_search
from .retrieval import recall as _recall
from .retrieval import search as _search
from .rollback import apply_rollback, plan_rollback
from .schema import (
    Entry,
    EvidencePointer,
    Lifecycle,
    RecallHit,
    RollbackPlan,
    TrainingValue,
    VerificationRecord,
    VerifiedStatus,
)
from .session_archive import ArchivedSession, SessionArchive
from .store import MarkdownStore
from .validation import (
    _check_transition,
    validate_bool,
    validate_entry_id,
    validate_evidence_input,
    validate_for_write,
    validate_k,
    validate_mode,
    validate_non_empty_string,
    validate_optional_string,
    validate_query,
    validate_status_filter,
    validate_verified_status,
    validate_write_inputs,
)
from .wiki import PageType, WikiManager, WikiPage
from .working_memory import WorkingMemory

__version__ = "0.3.0"

DEFAULT_ROOT_ENV = "ICARUS_FABRIC_ROOT"
DEFAULT_ROOT = "~/fabric"
logger = logging.getLogger(__name__)


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
        enable_wiki_classification: bool = False,
    ):
        self.root = _resolve_root(root)
        self.store = MarkdownStore(self.root)
        self.embedding_model = embedding_model
        self.platform = platform
        self.enable_wiki_classification = enable_wiki_classification
        self._wiki_classification_missing_key_warned = False
        self.wiki = WikiManager(self.root, memory=self)
        self.archive = SessionArchive(self.root)
        self.briefings = BriefingGenerator(
            self.root, wiki=self.wiki, archive=self.archive, memory=self
        )

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
        supersedes: list[str] | None = None,
        classify: bool | None = None,
    ) -> Entry:
        validate_write_inputs(
            agent=agent,
            type=type,
            summary=summary,
            body=body,
            platform=platform,
            project_id=project_id,
            session_id=session_id,
            status=status,
            assigned_to=assigned_to,
            review_of=review_of,
            revises=revises,
            source_tool=source_tool,
            artifact_paths=artifact_paths,
        )
        if timestamp is not None and not isinstance(timestamp, datetime):
            raise ValidationError("timestamp must be a datetime")
        if training_value not in {"high", "normal", "low"}:
            raise ValidationError("training_value must be one of: high, low, normal")
        validate_evidence_input(evidence)
        if supersedes is not None:
            if not isinstance(supersedes, list):
                raise ValidationError("supersedes must be a list of entry ids")
            for sid in supersedes:
                validate_entry_id(sid, "supersedes[]")
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
            supersedes=supersedes or [],
        )
        validate_for_write(entry, self.store, is_initial_write=True)
        written = self.store.write(entry)
        self._classify_wiki_after_write(written, classify=classify)
        return written

    def write_with_supersession(
        self,
        *,
        agent: str,
        type: str,
        summary: str,
        body: str = "",
        supersedes_ids: list[str],
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
        """Write a new entry that supersedes one or more existing entries.

        Validates that every supersedes_id exists *before* any disk writes
        happen — if validation fails, no entries are created or modified.
        Once validation passes, the new entry is written first; then each
        old entry is mutated to set lifecycle="superseded" and
        superseded_by=<new_entry.id>. Bodies and verification history of
        the old entries are preserved for audit.
        """
        if not isinstance(supersedes_ids, list) or not supersedes_ids:
            raise ValidationError("supersedes_ids must be a non-empty list of entry ids")
        for sid in supersedes_ids:
            validate_entry_id(sid, "supersedes_ids[]")
        # Fail-fast existence check across all targets before any write.
        missing = [sid for sid in supersedes_ids if not self.store.exists(sid)]
        if missing:
            raise ValidationError(
                f"supersedes_ids reference nonexistent entries: {missing}"
            )

        new_entry = self.write(
            agent=agent,
            type=type,
            summary=summary,
            body=body,
            platform=platform,
            timestamp=timestamp,
            project_id=project_id,
            session_id=session_id,
            status=status,
            assigned_to=assigned_to,
            review_of=review_of,
            revises=revises,
            training_value=training_value,
            evidence=evidence,
            source_tool=source_tool,
            artifact_paths=artifact_paths,
            supersedes=supersedes_ids,
        )

        for old_id in supersedes_ids:
            old = self.store.get(old_id)
            old.lifecycle = "superseded"
            old.superseded_by = new_entry.id
            validate_for_write(old, self.store, is_initial_write=False)
            self.store.write(old)

        return new_entry

    def get(self, entry_id: str) -> Entry:
        return self.store.get(validate_entry_id(entry_id))

    # -- Recall / search ------------------------------------------------

    def recall(
        self,
        query: str,
        *,
        k: int = 10,
        mode: RecallMode = "auto",
        status_filter: StatusFilter = "safe",
        min_verified: VerifiedStatus = "unverified",
        exclude_rolled_back: bool = True,
        agent: str | None = None,
        project_id: str | None = None,
        type: str | None = None,
        include_superseded: bool = False,
    ) -> list[RecallHit]:
        query = validate_query(query)
        k = validate_k(k)
        mode = cast(RecallMode, validate_mode(mode))
        validate_status_filter(status_filter)
        min_verified = validate_verified_status(min_verified)
        exclude_rolled_back = validate_bool(exclude_rolled_back, "exclude_rolled_back")
        include_superseded = validate_bool(include_superseded, "include_superseded")
        agent = validate_optional_string(agent, "agent")
        project_id = validate_optional_string(project_id, "project_id")
        type = validate_optional_string(type, "type")
        return _recall(
            self.store,
            query,
            k=k,
            mode=mode,
            status_filter=status_filter,
            min_verified=min_verified,
            exclude_rolled_back=exclude_rolled_back,
            include_superseded=include_superseded,
            agent=agent,
            project_id=project_id,
            type=type,
            embedding_model=self.embedding_model,
        )

    def search(
        self,
        query: str,
        *,
        status_filter: StatusFilter = "safe",
        agent: str | None = None,
        project_id: str | None = None,
        type: str | None = None,
        include_superseded: bool = False,
    ) -> list[Entry]:
        query = validate_query(query)
        status_filter = cast(StatusFilter, validate_status_filter(status_filter))
        include_superseded = validate_bool(include_superseded, "include_superseded")
        agent = validate_optional_string(agent, "agent")
        project_id = validate_optional_string(project_id, "project_id")
        type = validate_optional_string(type, "type")
        return _search(
            self.store,
            query,
            status_filter=status_filter,
            include_superseded=include_superseded,
            agent=agent,
            project_id=project_id,
            type=type,
        )

    def audit_search(
        self,
        query: str,
        *,
        agent: str | None = None,
        project_id: str | None = None,
        type: str | None = None,
    ) -> list[Entry]:
        query = validate_query(query)
        agent = validate_optional_string(agent, "agent")
        project_id = validate_optional_string(project_id, "project_id")
        type = validate_optional_string(type, "type")
        return _audit_search(
            self.store,
            query,
            agent=agent,
            project_id=project_id,
            type=type,
        )

    # -- Verification ---------------------------------------------------

    def verify(self, entry_id: str, *, verifier: str = "manual", note: str = "") -> Entry:
        entry_id = validate_entry_id(entry_id)
        verifier = validate_non_empty_string(verifier, "verifier")
        if not isinstance(note, str):
            raise ValidationError("note must be a string")
        entry = self.store.get(entry_id)
        _check_transition(entry, "verified")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entry.verified = "verified"
        entry.verification_log.append(
            VerificationRecord(
                verifier=verifier, timestamp=now, status="verified", note=note
            )
        )
        return self.store.write(entry)

    def contradict(self, entry_id: str, *, contradicted_by: str, reason: str) -> Entry:
        entry_id = validate_entry_id(entry_id)
        contradicted_by = validate_entry_id(contradicted_by, "contradicted_by")
        if entry_id == contradicted_by:
            raise ValidationError("self-contradiction not allowed")
        reason = validate_non_empty_string(reason, "reason")
        entry = self.store.get(entry_id)
        _check_transition(entry, "contradicted")
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

    def rollback(self, entry_id: str, *, dry_run: bool = True, cascade: bool = False) -> RollbackPlan:
        entry_id = validate_entry_id(entry_id)
        dry_run = validate_bool(dry_run, "dry_run")
        validate_bool(cascade, "cascade")
        plan = plan_rollback(self.store, entry_id)
        if dry_run:
            return plan
        if plan.error:
            raise RollbackError(plan.error)
        return apply_rollback(self.store, plan, cascade=cascade)

    def lineage(self, entry_id: str) -> list[Entry]:
        return _lineage(self.store, validate_entry_id(entry_id))

    def pending(self, agent: str) -> list[Entry]:
        agent = validate_non_empty_string(agent, "agent")
        out: list[Entry] = []
        for entry in self.store.iter_entries():
            if entry.status != "open":
                continue
            if entry.assigned_to != agent:
                continue
            out.append(entry)
        return out

    # -- Three-layer memory --------------------------------------------

    def start_session(
        self, agent_id: str, task_description: str
    ) -> tuple[WorkingMemory, Briefing]:
        """Start an active working-memory session and return its task briefing."""
        agent_id = validate_non_empty_string(agent_id, "agent_id")
        task_description = validate_non_empty_string(task_description, "task_description")
        session_id = secrets.token_hex(8)
        working = WorkingMemory.start(
            self.root,
            agent_id=agent_id,
            session_id=session_id,
            task_description=task_description,
        )
        return working, self.get_briefing(agent_id, task_description)

    def end_session(
        self,
        working_memory: WorkingMemory,
        summary: str,
        promote_to_wiki: list[str] | None = None,
    ) -> ArchivedSession:
        """Archive a working session and optionally promote a summary to wiki pages."""
        summary = validate_non_empty_string(summary, "summary")
        pages = [self._validate_page_path_for_public(path) for path in (promote_to_wiki or [])]
        archived = self.archive.archive(
            working_memory, final_summary=summary, promoted_to_wiki=pages
        )
        for page_path in pages:
            entry = self._write_promoted_session_summary(archived, summary)
            self.wiki.add_entry(page_path, entry.id, page_type="decision")
        return archived

    def get_briefing(self, agent_id: str, task_description: str) -> Briefing:
        """Return a cached or freshly generated task briefing for an agent."""
        agent_id = validate_non_empty_string(agent_id, "agent_id")
        task_description = validate_non_empty_string(task_description, "task_description")
        return self.briefings.generate(agent_id=agent_id, task_description=task_description)

    def get_wiki_page(self, path: str) -> WikiPage | None:
        """Return a wiki page by path, or ``None`` if it does not exist."""
        return self.wiki.get_page(path)

    def search_wiki(self, query: str) -> list[WikiPage]:
        """Search wiki pages by Entry recall matches."""
        query = validate_query(query)
        return self.wiki.search_pages(query)

    def _classify_wiki_after_write(self, entry: Entry, *, classify: bool | None = None) -> None:
        use_llm = self.enable_wiki_classification if classify is None else classify
        try:
            if not use_llm:
                self.wiki.add_entry("uncategorized", entry.id, page_type="uncategorized")
                return
            if not os.environ.get("OPENAI_API_KEY"):
                if not self._wiki_classification_missing_key_warned:
                    logger.warning(
                        "OPENAI_API_KEY is not set; wiki classification is using uncategorized"
                    )
                    self._wiki_classification_missing_key_warned = True
                self.wiki.add_entry("uncategorized", entry.id, page_type="uncategorized")
                return
            self.wiki.classify_and_add(entry)
        except Exception:
            # Wiki classification is advisory; the Entry write is the source of truth.
            return

    def _write_promoted_session_summary(self, archived: ArchivedSession, summary: str) -> Entry:
        entry = Entry(
            id=self.store.generate_id(),
            agent=archived.agent_id,
            platform=self.platform,
            timestamp=datetime.now(timezone.utc).replace(microsecond=0),
            type="session_summary",
            summary=summary[:200],
            body=_session_summary_body(archived),
            session_id=archived.session_id,
            training_value="high",
            evidence=[
                EvidencePointer(
                    kind="tool_output",
                    ref=archived.ref,
                    excerpt=archived.final_summary[:500],
                )
            ],
            source_tool="session_archive",
        )
        validate_for_write(entry, self.store, is_initial_write=True)
        return self.store.write(entry)

    @staticmethod
    def _validate_page_path_for_public(path: str) -> str:
        from ._layers import safe_page_path

        return safe_page_path(path)


def _session_summary_body(archived: ArchivedSession) -> str:
    attempts = "\n".join(
        f"- {'success' if attempt.succeeded else 'failed'}: {attempt.text}"
        for attempt in archived.attempts
    )
    return (
        f"Archived session: {archived.ref}\n\n"
        f"Task: {archived.task_description}\n\n"
        f"Summary: {archived.final_summary}\n\n"
        f"Key attempts:\n{attempts or '- none'}\n"
    )


__all__ = [
    "ArchivedSession",
    "Briefing",
    "Entry",
    "EntryNotFound",
    "EvidencePointer",
    "IcarusMemory",
    "IcarusMemoryError",
    "IllegalStateTransition",
    "Lifecycle",
    "PageType",
    "RecallHit",
    "RecallMode",
    "RollbackError",
    "RollbackPlan",
    "SessionArchive",
    "StatusFilter",
    "StoreError",
    "TrainingValue",
    "ValidationError",
    "VerificationRecord",
    "VerifiedStatus",
    "WikiManager",
    "WikiPage",
    "WorkingMemory",
    "__version__",
]
