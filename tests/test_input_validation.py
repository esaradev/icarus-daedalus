from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from icarus_memory import EntryNotFound, IcarusMemory, ValidationError

BAD_IDS: list[Any] = [None, "", 123, [], "x", "icarus:", "icarus:nothex", "icarus:abc"]


@pytest.mark.parametrize("entry_id", BAD_IDS)
def test_get_validates_entry_id(mem: IcarusMemory, entry_id: Any) -> None:
    with pytest.raises(ValidationError):
        mem.get(entry_id)


def test_get_valid_format_missing_still_raises_entry_not_found(mem: IcarusMemory) -> None:
    with pytest.raises(EntryNotFound):
        mem.get("icarus:00000000")


@pytest.mark.parametrize("query", [None, "", 123, [], "x" * 10001])
def test_recall_validates_query(mem: IcarusMemory, query: Any) -> None:
    with pytest.raises(ValidationError):
        mem.recall(query)


@pytest.mark.parametrize("k", [None, "", 0, -1, 1001, True])
def test_recall_validates_k(mem: IcarusMemory, k: Any) -> None:
    with pytest.raises(ValidationError):
        mem.recall("x", k=k)


@pytest.mark.parametrize("mode", [None, "", "semantic", 123])
def test_recall_validates_mode(mem: IcarusMemory, mode: Any) -> None:
    with pytest.raises(ValidationError):
        mem.recall("x", mode=mode)


@pytest.mark.parametrize("status_filter", [None, "", "tainted", 123])
def test_recall_validates_status_filter(mem: IcarusMemory, status_filter: Any) -> None:
    with pytest.raises(ValidationError):
        mem.recall("x", status_filter=status_filter)


@pytest.mark.parametrize("min_verified", [None, "", "approved", 123])
def test_recall_validates_min_verified(mem: IcarusMemory, min_verified: Any) -> None:
    with pytest.raises(ValidationError):
        mem.recall("x", min_verified=min_verified)


@pytest.mark.parametrize("query", [None, "", 123, [], "x" * 10001])
def test_search_validates_query(mem: IcarusMemory, query: Any) -> None:
    with pytest.raises(ValidationError):
        mem.search(query)


@pytest.mark.parametrize("status_filter", [None, "", "tainted", 123])
def test_search_validates_status_filter(mem: IcarusMemory, status_filter: Any) -> None:
    with pytest.raises(ValidationError):
        mem.search("x", status_filter=status_filter)


@pytest.mark.parametrize("entry_id", BAD_IDS)
def test_verify_validates_entry_id(mem: IcarusMemory, entry_id: Any) -> None:
    with pytest.raises(ValidationError):
        mem.verify(entry_id)


@pytest.mark.parametrize("verifier", [None, "", 123, []])
def test_verify_validates_verifier(mem: IcarusMemory, verifier: Any) -> None:
    entry = mem.write(agent="a", type="decision", summary="x")
    with pytest.raises(ValidationError):
        mem.verify(entry.id, verifier=verifier)


@pytest.mark.parametrize("reason", [None, "", 123, []])
def test_contradict_validates_reason(mem: IcarusMemory, reason: Any) -> None:
    entry = mem.write(agent="a", type="decision", summary="x")
    other = mem.write(agent="a", type="decision", summary="other")
    with pytest.raises(ValidationError):
        mem.contradict(entry.id, contradicted_by=other.id, reason=reason)


def test_contradict_rejects_self_contradiction(mem: IcarusMemory) -> None:
    entry = mem.write(agent="a", type="decision", summary="x")
    with pytest.raises(ValidationError, match="self-contradiction"):
        mem.contradict(entry.id, contradicted_by=entry.id, reason="bad")


@pytest.mark.parametrize("entry_id", BAD_IDS)
def test_rollback_validates_entry_id(mem: IcarusMemory, entry_id: Any) -> None:
    with pytest.raises(ValidationError):
        mem.rollback(entry_id)


@pytest.mark.parametrize("dry_run", [None, "", 1, 0, []])
def test_rollback_validates_dry_run(mem: IcarusMemory, dry_run: Any) -> None:
    entry = mem.write(agent="a", type="decision", summary="x")
    with pytest.raises(ValidationError):
        mem.rollback(entry.id, dry_run=dry_run)


@pytest.mark.parametrize("cascade", [None, "", 1, 0, []])
def test_rollback_validates_cascade(mem: IcarusMemory, cascade: Any) -> None:
    entry = mem.write(agent="a", type="decision", summary="x")
    with pytest.raises(ValidationError):
        mem.rollback(entry.id, cascade=cascade)


@pytest.mark.parametrize("entry_id", BAD_IDS)
def test_lineage_validates_entry_id(mem: IcarusMemory, entry_id: Any) -> None:
    with pytest.raises(ValidationError):
        mem.lineage(entry_id)


@pytest.mark.parametrize("agent", [None, "", 123, []])
def test_pending_validates_agent(mem: IcarusMemory, agent: Any) -> None:
    with pytest.raises(ValidationError):
        mem.pending(agent)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"agent": ""}, "agent"),
        ({"agent": 123}, "agent"),
        ({"type": ""}, "type"),
        ({"summary": ""}, "summary"),
        ({"body": 123}, "body"),
        ({"timestamp": "now"}, "timestamp"),
        ({"review_of": "bad"}, "review_of"),
        ({"revises": "bad"}, "revises"),
        ({"artifact_paths": [123]}, "artifact_paths"),
        ({"training_value": "urgent"}, "training_value"),
    ],
)
def test_write_validates_top_level_inputs(
    mem: IcarusMemory, kwargs: dict[str, Any], message: str
) -> None:
    params: dict[str, Any] = {
        "agent": "a",
        "type": "decision",
        "summary": "x",
        "body": "",
        "timestamp": datetime(2026, 5, 5, tzinfo=timezone.utc),
    }
    params.update(kwargs)
    with pytest.raises(ValidationError, match=message):
        mem.write(**params)


def test_public_methods_accept_valid_inputs(mem: IcarusMemory) -> None:
    entry = mem.write(agent="a", type="decision", summary="postgres auth")
    other = mem.write(agent="a", type="decision", summary="deny auth")
    task = mem.write(agent="a", type="task", summary="todo", status="open", assigned_to="me")

    assert mem.get(entry.id).id == entry.id
    assert mem.recall("postgres", mode="keyword", k=1) != []
    assert mem.search("postgres") != []
    assert mem.verify(entry.id).verified == "verified"
    assert mem.contradict(other.id, contradicted_by=entry.id, reason="wrong").verified == "contradicted"
    assert mem.rollback(other.id, dry_run=True).target == other.id
    assert mem.lineage(entry.id)[0].id == entry.id
    assert [e.id for e in mem.pending("me")] == [task.id]
