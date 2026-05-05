"""Write-time validation rules for icarus-memory entries."""

from __future__ import annotations

from .exceptions import ValidationError
from .schema import Entry
from .store import MarkdownStore


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
