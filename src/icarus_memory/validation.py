"""Write-time validation rules for icarus-memory entries."""

from __future__ import annotations

import re

from .exceptions import IllegalStateTransition, ValidationError
from .schema import Entry, EvidencePointer, VerifiedStatus
from .store import MarkdownStore

ENTRY_ID_PATTERN = re.compile(r"^icarus:[0-9a-f]{8,}$")
RECALL_MODES = {"auto", "keyword", "embedding", "embeddings", "hybrid"}
STATUS_FILTERS = {"safe", "all", "verified_only"}
VERIFIED_STATUSES: set[VerifiedStatus] = {
    "unverified",
    "verified",
    "contradicted",
    "rolled_back",
}
MAX_QUERY_LENGTH = 10000
MAX_RECALL_K = 1000
_LEGAL_TRANSITIONS: dict[VerifiedStatus, set[VerifiedStatus]] = {
    "unverified": {"verified", "contradicted", "rolled_back"},
    "verified": {"verified", "contradicted", "rolled_back"},
    "contradicted": {"rolled_back"},
    "rolled_back": set(),
}


def _type_name(value: object) -> str:
    return type(value).__name__


def validate_entry_id(value: object, arg_name: str = "id") -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{arg_name} must be a string entry id, got {_type_name(value)}")
    if not value:
        raise ValidationError(f"{arg_name} must be a non-empty entry id")
    if ENTRY_ID_PATTERN.fullmatch(value) is None:
        raise ValidationError(f"{arg_name} must match format icarus:[0-9a-f]{{8,}}")
    return value


def validate_query(value: object, arg_name: str = "query") -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{arg_name} must be a string, got {_type_name(value)}")
    if not value:
        raise ValidationError(f"{arg_name} must be non-empty")
    if len(value) > MAX_QUERY_LENGTH:
        raise ValidationError(f"{arg_name} must be at most {MAX_QUERY_LENGTH} characters")
    return value


def validate_non_empty_string(value: object, arg_name: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{arg_name} must be a string, got {_type_name(value)}")
    if not value:
        raise ValidationError(f"{arg_name} must be non-empty")
    return value


def validate_optional_string(value: object, arg_name: str) -> str | None:
    if value is None:
        return None
    return validate_non_empty_string(value, arg_name)


def validate_bool(value: object, arg_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{arg_name} must be a bool, got {_type_name(value)}")
    return value


def validate_k(value: object, arg_name: str = "k") -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{arg_name} must be an int, got {_type_name(value)}")
    if value < 1:
        raise ValidationError(f"{arg_name} must be positive")
    if value > MAX_RECALL_K:
        raise ValidationError(f"{arg_name} must be at most {MAX_RECALL_K}")
    return value


def validate_mode(value: object, arg_name: str = "mode") -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{arg_name} must be a string, got {_type_name(value)}")
    if value not in RECALL_MODES:
        allowed = ", ".join(sorted(RECALL_MODES))
        raise ValidationError(f"{arg_name} must be one of: {allowed}")
    return value


def validate_status_filter(value: object, arg_name: str = "status_filter") -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{arg_name} must be a string, got {_type_name(value)}")
    if value not in STATUS_FILTERS:
        allowed = ", ".join(sorted(STATUS_FILTERS))
        raise ValidationError(f"{arg_name} must be one of: {allowed}")
    return value


def validate_verified_status(value: object, arg_name: str = "min_verified") -> VerifiedStatus:
    if not isinstance(value, str):
        raise ValidationError(f"{arg_name} must be a string, got {_type_name(value)}")
    if value not in VERIFIED_STATUSES:
        allowed = ", ".join(sorted(VERIFIED_STATUSES))
        raise ValidationError(f"{arg_name} must be one of: {allowed}")
    return value


def validate_string_list(value: object, arg_name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValidationError(f"{arg_name} must be a list of strings")
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise ValidationError(f"{arg_name}[{i}] must be a string")
    return value


def validate_evidence_input(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValidationError("evidence must be a list")
    for i, item in enumerate(value):
        if not isinstance(item, (dict, EvidencePointer)):
            raise ValidationError(f"evidence[{i}] must be an evidence mapping")
    return value


def validate_write_inputs(
    *,
    agent: object,
    type: object,
    summary: object,
    body: object,
    platform: object,
    project_id: object,
    session_id: object,
    status: object,
    assigned_to: object,
    review_of: object,
    revises: object,
    source_tool: object,
    artifact_paths: object,
) -> None:
    validate_non_empty_string(agent, "agent")
    validate_non_empty_string(type, "type")
    validate_non_empty_string(summary, "summary")
    if not isinstance(body, str):
        raise ValidationError(f"body must be a string, got {_type_name(body)}")
    validate_optional_string(platform, "platform")
    validate_optional_string(project_id, "project_id")
    validate_optional_string(session_id, "session_id")
    validate_optional_string(status, "status")
    validate_optional_string(assigned_to, "assigned_to")
    if review_of is not None:
        validate_entry_id(review_of, "review_of")
    if revises is not None:
        validate_entry_id(revises, "revises")
    validate_optional_string(source_tool, "source_tool")
    validate_string_list(artifact_paths, "artifact_paths")


def _check_transition(current: Entry, target: VerifiedStatus) -> None:
    from_state = current.verified
    if from_state == target:
        if target == "verified":
            return
        raise IllegalStateTransition(
            entry_id=current.id,
            from_state=from_state,
            to_state=target,
            reason=f"idempotent transition to {target} is not allowed",
        )
    if target not in _LEGAL_TRANSITIONS[from_state]:
        raise IllegalStateTransition(
            entry_id=current.id,
            from_state=from_state,
            to_state=target,
            reason="transition is not allowed",
        )


def validate_for_write(entry: Entry, store: MarkdownStore, *, is_initial_write: bool) -> None:
    """Enforce invariants before persisting an entry.

    is_initial_write distinguishes ``store.write(new_entry)`` (where
    ``verified='verified'`` is forbidden) from internal mutations driven by
    ``verify()``/``contradict()``/``rollback()`` (where status changes are
    expected).
    """
    if is_initial_write and entry.verified == "verified":
        raise ValidationError(
            "verified='verified' cannot be set on initial write; "
            "use IcarusMemory.verify() instead"
        )

    if entry.verified == "contradicted":
        if not entry.contradicted_by:
            raise ValidationError(
                "verified='contradicted' requires contradicted_by to be set"
            )
        if not store.exists(entry.contradicted_by):
            raise ValidationError(
                f"contradicted_by points to nonexistent entry {entry.contradicted_by}"
            )

    if entry.status == "open" and not entry.assigned_to:
        raise ValidationError("status='open' requires assigned_to")

    if entry.type == "review" and not entry.review_of:
        raise ValidationError("type='review' requires review_of")

    if entry.revises and not store.exists(entry.revises):
        raise ValidationError(f"revises points to nonexistent entry {entry.revises}")

    if entry.review_of and not store.exists(entry.review_of):
        raise ValidationError(f"review_of points to nonexistent entry {entry.review_of}")

    for i, ev in enumerate(entry.evidence):
        if ev.kind == "fabric_ref" and not store.exists(ev.ref):
            raise ValidationError(
                f"evidence[{i}].ref points to nonexistent entry {ev.ref}"
            )
