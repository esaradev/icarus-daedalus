from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from icarus_memory import IcarusMemory


def _chain(mem: IcarusMemory) -> list[str]:
    ids: list[str] = []
    prev: str | None = None
    start = datetime(2026, 5, 5, tzinfo=timezone.utc)
    for i in range(1, 11):
        entry = mem.write(
            agent="a",
            type="decision",
            summary=f"poison chain {i}",
            timestamp=start + timedelta(minutes=i),
            revises=prev,
        )
        ids.append(entry.id)
        prev = entry.id
        if i == 3:
            mem.verify(entry.id)
    mem.contradict(ids[6], contradicted_by=ids[2], reason="poison")
    return ids


def test_rollback_dry_run_surfaces_tainted_descendants(mem: IcarusMemory) -> None:
    ids = _chain(mem)

    plan = mem.rollback(ids[6], dry_run=True)

    assert plan.intermediate == ids[3:7]
    assert plan.tainted_descendants == ids[7:10]
    assert plan.applied is False


def test_rollback_without_cascade_flags_but_does_not_mutate_descendants(
    mem: IcarusMemory,
) -> None:
    ids = _chain(mem)

    plan = mem.rollback(ids[6], dry_run=False, cascade=False)

    assert plan.applied is True
    assert plan.tainted_descendants == ids[7:10]
    assert [mem.get(entry_id).verified for entry_id in ids[3:7]] == ["rolled_back"] * 4
    assert [mem.get(entry_id).verified for entry_id in ids[7:10]] == ["unverified"] * 3


def test_rollback_with_cascade_marks_descendants(mem: IcarusMemory) -> None:
    ids = _chain(mem)

    plan = mem.rollback(ids[6], dry_run=False, cascade=True)

    assert plan.applied is True
    assert plan.tainted_descendants == ids[7:10]
    assert [mem.get(entry_id).verified for entry_id in ids[3:10]] == ["rolled_back"] * 7
    for entry_id in ids[7:10]:
        notes = [record.note for record in mem.get(entry_id).verification_log]
        assert f"cascaded from rollback of {ids[6]}" in notes


def test_branching_descendants_are_reported(mem: IcarusMemory) -> None:
    start = datetime(2026, 5, 5, tzinfo=timezone.utc)
    root = mem.write(agent="a", type="decision", summary="root", timestamp=start)
    mem.verify(root.id)
    a = mem.write(
        agent="a",
        type="decision",
        summary="A",
        revises=root.id,
        timestamp=start + timedelta(minutes=1),
    )
    b = mem.write(
        agent="a",
        type="decision",
        summary="B",
        revises=a.id,
        timestamp=start + timedelta(minutes=2),
    )
    c = mem.write(
        agent="a",
        type="decision",
        summary="C",
        revises=a.id,
        timestamp=start + timedelta(minutes=3),
    )
    d = mem.write(
        agent="a",
        type="decision",
        summary="D",
        revises=b.id,
        review_of=c.id,
        timestamp=start + timedelta(minutes=4),
    )
    mem.contradict(a.id, contradicted_by=root.id, reason="poison")

    plan = mem.rollback(a.id, dry_run=True)

    assert plan.intermediate == [a.id]
    assert plan.tainted_descendants == [b.id, c.id, d.id]


def _rewrite_revises(mem: IcarusMemory, entry_id: str, revises: str) -> None:
    path = mem.store._find_path(entry_id)
    assert path is not None
    text = path.read_text(encoding="utf-8")
    front, body = text.split("\n---", 1)
    data = yaml.safe_load(front.removeprefix("---\n"))
    data["revises"] = revises
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---" + body)
    mem.store._reverse_revises_cache = None


def test_revises_cycle_reports_warning_in_plan(tmp_path: Path) -> None:
    mem = IcarusMemory(root=tmp_path / "fabric")
    root = mem.write(agent="a", type="decision", summary="root")
    mem.verify(root.id)
    a = mem.write(agent="a", type="decision", summary="A", revises=root.id)
    b = mem.write(agent="a", type="decision", summary="B", revises=a.id)
    _rewrite_revises(mem, a.id, b.id)

    plan = mem.rollback(a.id, dry_run=True)

    assert plan.error is not None
    assert "cycle detected" in plan.error
    assert any("cycle detected" in warning for warning in plan.warnings)
