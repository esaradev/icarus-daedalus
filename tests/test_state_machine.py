from __future__ import annotations

from datetime import datetime, timezone

import pytest

from icarus_memory import IcarusMemory, IllegalStateTransition
from icarus_memory.schema import Entry
from icarus_memory.validation import _check_transition


def _entry(status: str) -> Entry:
    return Entry(
        id="icarus:aaaaaaaaaaaa",
        agent="a",
        platform="pytest",
        timestamp=datetime(2026, 5, 5, tzinfo=timezone.utc),
        type="decision",
        summary="x",
        verified=status,  # type: ignore[arg-type]
    )


def test_unverified_to_verified_succeeds(mem: IcarusMemory) -> None:
    entry = mem.write(agent="a", type="decision", summary="x")
    assert mem.verify(entry.id).verified == "verified"


def test_unverified_to_contradicted_succeeds(mem: IcarusMemory) -> None:
    entry = mem.write(agent="a", type="decision", summary="x")
    rebuttal = mem.write(agent="a", type="decision", summary="rebuttal")
    assert (
        mem.contradict(entry.id, contradicted_by=rebuttal.id, reason="wrong").verified
        == "contradicted"
    )


def test_verified_to_contradicted_succeeds(mem: IcarusMemory) -> None:
    entry = mem.write(agent="a", type="decision", summary="x")
    mem.verify(entry.id)
    rebuttal = mem.write(agent="a", type="decision", summary="rebuttal")
    assert (
        mem.contradict(entry.id, contradicted_by=rebuttal.id, reason="wrong").verified
        == "contradicted"
    )


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        ("unverified", "rolled_back"),
        ("verified", "rolled_back"),
        ("contradicted", "rolled_back"),
    ],
)
def test_rollback_transitions_are_legal(from_state: str, to_state: str) -> None:
    _check_transition(_entry(from_state), to_state)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        ("contradicted", "verified"),
        ("rolled_back", "verified"),
        ("rolled_back", "contradicted"),
        ("rolled_back", "rolled_back"),
        ("contradicted", "contradicted"),
    ],
)
def test_illegal_transitions_raise_with_attributes(from_state: str, to_state: str) -> None:
    entry = _entry(from_state)
    with pytest.raises(IllegalStateTransition) as excinfo:
        _check_transition(entry, to_state)  # type: ignore[arg-type]

    exc = excinfo.value
    assert exc.entry_id == entry.id
    assert exc.from_state == from_state
    assert exc.to_state == to_state
    assert exc.reason


def test_idempotent_verify_appends_to_log(mem: IcarusMemory) -> None:
    entry = mem.write(agent="a", type="decision", summary="x")
    first = mem.verify(entry.id, verifier="one")
    second = mem.verify(entry.id, verifier="two")

    assert second.verified == "verified"
    assert len(second.verification_log) == len(first.verification_log) + 1
    assert [record.verifier for record in second.verification_log] == ["one", "two"]


def test_idempotent_contradict_rejects(mem: IcarusMemory) -> None:
    entry = mem.write(agent="a", type="decision", summary="x")
    rebuttal = mem.write(agent="a", type="decision", summary="rebuttal")
    mem.contradict(entry.id, contradicted_by=rebuttal.id, reason="wrong")

    with pytest.raises(IllegalStateTransition, match="idempotent"):
        mem.contradict(entry.id, contradicted_by=rebuttal.id, reason="still wrong")


def test_verify_after_rollback_rejects(mem: IcarusMemory) -> None:
    good = mem.write(agent="a", type="decision", summary="good")
    mem.verify(good.id)
    bad = mem.write(agent="a", type="decision", summary="bad", revises=good.id)
    mem.contradict(bad.id, contradicted_by=good.id, reason="bad")
    mem.rollback(bad.id, dry_run=False)

    rolled_back = mem.get(bad.id)
    assert rolled_back.verified == "rolled_back"
    with pytest.raises(IllegalStateTransition) as excinfo:
        mem.verify(bad.id)

    assert excinfo.value.entry_id == bad.id
    assert excinfo.value.from_state == "rolled_back"
    assert excinfo.value.to_state == "verified"
