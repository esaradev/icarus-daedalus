from __future__ import annotations

from pathlib import Path

import pytest

from icarus_memory import IcarusMemory, RollbackError


def _file_count(root: Path) -> int:
    return sum(1 for _ in root.rglob("icarus-*.md"))


def test_rollback_dry_run_finds_verified_ancestor(mem: IcarusMemory, fabric_root: Path) -> None:
    a = mem.write(agent="t", type="decision", summary="A")
    mem.verify(a.id, note="confirmed")
    b = mem.write(agent="t", type="decision", summary="B", revises=a.id)
    c = mem.write(agent="t", type="decision", summary="C", revises=b.id)

    before = _file_count(fabric_root)
    plan = mem.rollback(c.id, dry_run=True)
    after = _file_count(fabric_root)

    assert plan.verified_ancestor == a.id
    assert set(plan.intermediate) == {b.id, c.id}
    assert plan.error is None
    assert plan.applied is False
    assert before == after  # dry-run never touches disk


def test_rollback_apply_marks_intermediates_and_writes_rollback_entry(
    mem: IcarusMemory, fabric_root: Path
) -> None:
    a = mem.write(agent="t", type="decision", summary="A")
    mem.verify(a.id)
    b = mem.write(agent="t", type="decision", summary="B", revises=a.id)
    c = mem.write(agent="t", type="decision", summary="C", revises=b.id)

    before = _file_count(fabric_root)
    plan = mem.rollback(c.id, dry_run=False)
    after = _file_count(fabric_root)

    assert plan.applied is True
    assert plan.rollback_entry_id is not None
    assert after == before + 1  # one new rollback entry; never decreases

    assert mem.get(b.id).verified == "rolled_back"
    assert mem.get(c.id).verified == "rolled_back"
    assert mem.get(a.id).verified == "verified"

    rb_entry = mem.get(plan.rollback_entry_id)
    assert rb_entry.type == "rollback"
    assert rb_entry.revises == a.id


def test_rollback_no_verified_ancestor(mem: IcarusMemory) -> None:
    a = mem.write(agent="t", type="decision", summary="A")
    b = mem.write(agent="t", type="decision", summary="B", revises=a.id)
    plan = mem.rollback(b.id, dry_run=True)
    assert plan.verified_ancestor is None
    assert plan.error is not None
    assert "no verified ancestor" in plan.error


def test_rollback_target_already_verified(mem: IcarusMemory) -> None:
    a = mem.write(agent="t", type="decision", summary="A")
    mem.verify(a.id)
    plan = mem.rollback(a.id, dry_run=True)
    assert plan.error is not None
    assert "already verified" in plan.error


def test_rollback_apply_without_ancestor_raises(mem: IcarusMemory) -> None:
    a = mem.write(agent="t", type="decision", summary="A")
    b = mem.write(agent="t", type="decision", summary="B", revises=a.id)
    with pytest.raises(RollbackError):
        mem.rollback(b.id, dry_run=False)
