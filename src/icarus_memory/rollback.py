"""Rollback engine: walk the revises chain back to the last verified ancestor."""

from __future__ import annotations

from datetime import datetime, timezone

from .exceptions import EntryNotFound, RollbackError
from .schema import Entry, RollbackPlan, VerificationRecord
from .store import MarkdownStore


def plan_rollback(store: MarkdownStore, entry_id: str) -> RollbackPlan:
    """Compute a rollback plan without touching disk."""
    try:
        target = store.get(entry_id)
    except EntryNotFound as exc:
        raise RollbackError(str(exc)) from exc

    if target.verified == "verified":
        return RollbackPlan(
            target=entry_id,
            error="target is already verified; nothing to roll back",
        )

    intermediate: list[str] = []
    seen: set[str] = {entry_id}
    current = target
    verified_ancestor: Entry | None = None

    intermediate.append(current.id)
    while current.revises:
        if current.revises in seen:
            raise RollbackError(
                f"cycle detected in revises chain at {current.revises}"
            )
        seen.add(current.revises)
        try:
            current = store.get(current.revises)
        except EntryNotFound:
            return RollbackPlan(
                target=entry_id,
                intermediate=intermediate,
                error=f"revises chain broken: {current.revises} not found",
            )
        if current.verified == "verified":
            verified_ancestor = current
            break
        intermediate.append(current.id)

    if verified_ancestor is None:
        return RollbackPlan(
            target=entry_id,
            intermediate=intermediate,
            error="no verified ancestor in revises chain",
        )

    return RollbackPlan(
        target=entry_id,
        verified_ancestor=verified_ancestor.id,
        intermediate=intermediate,
    )


def apply_rollback(store: MarkdownStore, plan: RollbackPlan) -> RollbackPlan:
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
        ),
        revises=plan.verified_ancestor,
    )
    store.write(rollback_entry)

    return plan.model_copy(
        update={"applied": True, "rollback_entry_id": rollback_entry_id}
    )
