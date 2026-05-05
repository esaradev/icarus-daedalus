"""Rollback engine: walk the revises chain back to the last verified ancestor."""

from __future__ import annotations

from datetime import datetime, timezone

from .exceptions import EntryNotFound, RollbackError
from .lineage import _find_descendants
from .schema import Entry, RollbackPlan, VerificationRecord
from .store import MarkdownStore
from .validation import _check_transition


def _with_descendants(store: MarkdownStore, plan: RollbackPlan) -> RollbackPlan:
    result = _find_descendants(store, plan.intermediate)
    return plan.model_copy(
        update={
            "tainted_descendants": result.descendants,
            "warnings": [*plan.warnings, *result.warnings],
        }
    )


def plan_rollback(store: MarkdownStore, entry_id: str) -> RollbackPlan:
    """Compute a rollback plan without touching disk."""
    try:
        target = store.get(entry_id)
    except EntryNotFound as exc:
        raise RollbackError(str(exc)) from exc

    if target.verified == "verified":
        return _with_descendants(
            store,
            RollbackPlan(
                target=entry_id,
                error="target is already verified; nothing to roll back",
            ),
        )

    intermediate: list[str] = []
    seen: set[str] = {entry_id}
    current = target
    verified_ancestor: Entry | None = None

    intermediate.append(current.id)
    while current.revises:
        if current.revises in seen:
            return _with_descendants(
                store,
                RollbackPlan(
                    target=entry_id,
                    intermediate=list(reversed(intermediate)),
                    error=f"cycle detected in revises chain at {current.revises}",
                    warnings=[f"cycle detected in revises chain at {current.revises}"],
                ),
            )
        seen.add(current.revises)
        try:
            current = store.get(current.revises)
        except EntryNotFound:
            return _with_descendants(
                store,
                RollbackPlan(
                    target=entry_id,
                    intermediate=list(reversed(intermediate)),
                    error=f"revises chain broken: {current.revises} not found",
                ),
            )
        if current.verified == "verified":
            verified_ancestor = current
            break
        intermediate.append(current.id)

    if verified_ancestor is None:
        return _with_descendants(
            store,
            RollbackPlan(
                target=entry_id,
                intermediate=list(reversed(intermediate)),
                error="no verified ancestor in revises chain",
            ),
        )

    return _with_descendants(
        store,
        RollbackPlan(
            target=entry_id,
            verified_ancestor=verified_ancestor.id,
            intermediate=list(reversed(intermediate)),
        ),
    )


def apply_rollback(store: MarkdownStore, plan: RollbackPlan, *, cascade: bool = False) -> RollbackPlan:
    """Apply a previously-computed rollback plan. Non-destructive.

    Marks every intermediate entry ``verified='rolled_back'`` and writes a
    new entry of type ``rollback`` pointing at the verified ancestor via
    ``revises``.
    """
    if plan.error:
        raise RollbackError(plan.error)
    if plan.verified_ancestor is None:
        raise RollbackError("plan has no verified_ancestor; cannot apply")

    now = datetime.now(timezone.utc).replace(microsecond=0)

    for intermediate_id in plan.intermediate:
        entry = store.get(intermediate_id)
        _check_transition(entry, "rolled_back")
        entry.verified = "rolled_back"
        entry.verification_log.append(
            VerificationRecord(
                verifier="rollback",
                timestamp=now,
                status="rolled_back",
                note=f"rolled back to {plan.verified_ancestor}",
            )
        )
        store.write(entry)

    if cascade:
        for descendant_id in plan.tainted_descendants:
            entry = store.get(descendant_id)
            _check_transition(entry, "rolled_back")
            entry.verified = "rolled_back"
            entry.verification_log.append(
                VerificationRecord(
                    verifier="rollback",
                    timestamp=now,
                    status="rolled_back",
                    note=f"cascaded from rollback of {plan.target}",
                )
            )
            store.write(entry)

    rollback_entry_id = store.generate_id()
    rollback_entry = Entry(
        id=rollback_entry_id,
        agent="rollback",
        platform="icarus-memory",
        timestamp=now,
        type="rollback",
        summary=f"rollback {plan.target} to {plan.verified_ancestor}",
        body=(
            f"Rolled back {plan.target} to verified ancestor "
            f"{plan.verified_ancestor}.\n\n"
            f"Intermediate entries marked rolled_back: "
            f"{', '.join(plan.intermediate)}\n"
            f"Tainted descendants: {', '.join(plan.tainted_descendants)}\n"
        ),
        revises=plan.verified_ancestor,
    )
    store.write(rollback_entry)

    return plan.model_copy(
        update={"applied": True, "rollback_entry_id": rollback_entry_id}
    )
