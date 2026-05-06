from __future__ import annotations

from pathlib import Path

import pytest

from icarus_memory import ValidationError
from icarus_memory.session_archive import SessionArchive
from icarus_memory.working_memory import WorkingMemory


def test_session_archive_is_per_agent_and_searchable(fabric_root: Path) -> None:
    wm = WorkingMemory.start(
        fabric_root,
        agent_id="agentA",
        session_id="sessionA",
        task_description="fix auth bug",
    )
    wm.add_observation("OAuth callback has wrong state")
    wm.add_attempt("Regenerated client secret", succeeded=False)
    archive = SessionArchive(fabric_root)

    archived = archive.archive(wm, final_summary="Use stable callback state")

    assert archived.ref == "session_archive:agentA:sessionA"
    assert archive.search("callback state", agent_id="agentA")[0].session_id == "sessionA"
    assert archive.search("callback state", agent_id="agentB") == []


def test_session_archive_rejects_traversal_ids(fabric_root: Path) -> None:
    archive = SessionArchive(fabric_root)

    with pytest.raises(ValidationError):
        archive.search("anything", agent_id="../agent")


def test_session_archive_atomic_write_has_no_temp_file(fabric_root: Path) -> None:
    wm = WorkingMemory.start(
        fabric_root,
        agent_id="agentA",
        session_id="sessionA",
        task_description="fix auth bug",
    )
    archive = SessionArchive(fabric_root)
    archive.archive(wm, final_summary="summary")

    session_dir = fabric_root / ".icarus" / "agents" / "agentA" / "sessions"
    assert (session_dir / "sessionA.json").exists()
    assert list(session_dir.glob("*.tmp.*")) == []
