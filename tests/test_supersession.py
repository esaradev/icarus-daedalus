"""Supersession lifecycle: write_with_supersession + recall filter."""

from __future__ import annotations

from pathlib import Path

import pytest

from icarus_memory import IcarusMemory, ValidationError


@pytest.fixture
def mem(tmp_path: Path) -> IcarusMemory:
    return IcarusMemory(root=tmp_path / "fabric")


def test_write_with_supersession_marks_old_superseded(mem: IcarusMemory) -> None:
    old = mem.write(
        agent="user",
        type="fact",
        summary="user lives in Columbus",
        body="user lives in Columbus",
    )
    new = mem.write_with_supersession(
        agent="user",
        type="fact",
        summary="user lives in Boston",
        body="user lives in Boston",
        supersedes_ids=[old.id],
    )

    refreshed_old = mem.get(old.id)
    refreshed_new = mem.get(new.id)

    assert refreshed_old.lifecycle == "superseded"
    assert refreshed_old.superseded_by == new.id
    assert refreshed_old.body == "user lives in Columbus"  # body preserved for audit
    assert refreshed_new.lifecycle == "active"
    assert refreshed_new.supersedes == [old.id]


def test_default_recall_excludes_superseded(mem: IcarusMemory) -> None:
    old = mem.write(
        agent="user",
        type="fact",
        summary="user lives in Columbus",
        body="user lives in Columbus",
    )
    new = mem.write_with_supersession(
        agent="user",
        type="fact",
        summary="user lives in Boston",
        body="user lives in Boston",
        supersedes_ids=[old.id],
    )

    default_hits = mem.recall("Columbus", k=10, mode="keyword")
    assert [h.entry.id for h in default_hits] == []

    audit_hits = mem.recall(
        "Columbus", k=10, mode="keyword", include_superseded=True
    )
    audit_ids = {h.entry.id for h in audit_hits}
    assert old.id in audit_ids
    # Both lifecycles are visible from the audit recall
    by_id = {h.entry.id: h.entry for h in audit_hits}
    assert by_id[old.id].lifecycle == "superseded"

    # New entry is recallable for its own content (no Columbus token there).
    boston_hits = mem.recall("Boston", k=10, mode="keyword")
    assert [h.entry.id for h in boston_hits] == [new.id]


def test_supersession_with_nonexistent_id_raises_no_partial_write(
    mem: IcarusMemory,
) -> None:
    real = mem.write(
        agent="user",
        type="fact",
        summary="real entry",
        body="real entry",
    )

    before_ids = set(mem.store.list_ids())

    with pytest.raises(ValidationError, match="nonexistent"):
        mem.write_with_supersession(
            agent="user",
            type="fact",
            summary="will not be written",
            body="will not be written",
            supersedes_ids=[real.id, "icarus:000000000000"],
        )

    after_ids = set(mem.store.list_ids())
    # No new entry written, no mutation to the real one.
    assert before_ids == after_ids
    refreshed_real = mem.get(real.id)
    assert refreshed_real.lifecycle == "active"
    assert refreshed_real.superseded_by is None


def test_supersedes_field_validates_existing_targets(mem: IcarusMemory) -> None:
    real = mem.write(
        agent="user",
        type="fact",
        summary="real entry",
        body="real entry",
    )
    # write() also accepts supersedes (without the cascading update); the
    # validator must catch nonexistent refs there too.
    with pytest.raises(ValidationError, match="nonexistent"):
        mem.write(
            agent="user",
            type="fact",
            summary="solo",
            body="solo",
            supersedes=[real.id, "icarus:111111111111"],
        )


def test_search_excludes_superseded_by_default(mem: IcarusMemory) -> None:
    old = mem.write(
        agent="user",
        type="fact",
        summary="legacy server is in Frankfurt",
        body="legacy server is in Frankfurt",
    )
    mem.write_with_supersession(
        agent="user",
        type="fact",
        summary="server moved to Berlin",
        body="server moved to Berlin",
        supersedes_ids=[old.id],
    )

    assert mem.search("Frankfurt") == []
    audit = mem.search("Frankfurt", include_superseded=True)
    assert [e.id for e in audit] == [old.id]


def test_audit_search_returns_superseded_with_no_flag(mem: IcarusMemory) -> None:
    old = mem.write(
        agent="user",
        type="fact",
        summary="user prefers vim",
        body="user prefers vim",
    )
    mem.write_with_supersession(
        agent="user",
        type="fact",
        summary="user prefers helix",
        body="user prefers helix",
        supersedes_ids=[old.id],
    )
    # audit_search is for human review and should always show the full picture
    out = mem.audit_search("vim")
    assert [e.id for e in out] == [old.id]


def test_legacy_entry_reads_with_active_lifecycle(mem: IcarusMemory) -> None:
    entry = mem.write(
        agent="user",
        type="fact",
        summary="legacy migration",
        body="legacy migration",
    )
    path = mem.store._find_path(entry.id)
    assert path is not None
    text = path.read_text(encoding="utf-8")
    text = text.replace("lifecycle: active\n", "")
    path.write_text(text, encoding="utf-8")

    loaded = mem.get(entry.id)

    assert loaded.lifecycle == "active"
    assert loaded.superseded_by is None
    assert loaded.supersedes == []


def test_include_superseded_must_be_bool(mem: IcarusMemory) -> None:
    mem.write(agent="user", type="fact", summary="x", body="x")

    with pytest.raises(ValidationError, match="include_superseded"):
        mem.recall("x", include_superseded="yes")  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="include_superseded"):
        mem.search("x", include_superseded="yes")  # type: ignore[arg-type]


def test_write_with_supersession_preserves_verification_log(mem: IcarusMemory) -> None:
    old = mem.write(
        agent="user",
        type="fact",
        summary="user prefers vim",
        body="user prefers vim",
    )
    mem.verify(old.id, verifier="qa", note="checked")

    mem.write_with_supersession(
        agent="user",
        type="fact",
        summary="user prefers helix",
        body="user prefers helix",
        supersedes_ids=[old.id],
    )

    refreshed = mem.get(old.id)
    assert refreshed.lifecycle == "superseded"
    assert len(refreshed.verification_log) == 1
    assert refreshed.verification_log[0].verifier == "qa"
