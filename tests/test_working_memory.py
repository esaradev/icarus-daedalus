from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from icarus_memory import ValidationError
from icarus_memory.working_memory import WorkingMemory


def test_working_memory_persists_context_and_clears_on_end(fabric_root: Path) -> None:
    wm = WorkingMemory.start(
        fabric_root,
        agent_id="agentA",
        session_id="sessionA",
        task_description="fix auth bug",
    )

    wm.add_observation("Token refresh fails after redirect")
    wm.add_attempt("Tried refreshing before redirect", succeeded=False)
    wm.add_hypothesis("Cookie domain mismatch", confidence=0.8)

    path = fabric_root / ".icarus" / "sessions" / "sessionA.json"
    assert path.exists()
    assert "Token refresh fails" in wm.get_context(max_tokens=2000)
    assert list(path.parent.glob("*.tmp.*")) == []

    loaded = WorkingMemory.load(fabric_root, session_id="sessionA")
    assert loaded is not None
    assert loaded.observations[0].text == "Token refresh fails after redirect"

    wm.end()
    assert not path.exists()


def test_working_memory_expired_records_are_omitted(fabric_root: Path) -> None:
    wm = WorkingMemory.start(
        fabric_root,
        agent_id="agentA",
        session_id="sessionA",
        task_description="fix auth bug",
    )
    old = wm.add_observation("old observation")
    old.updated_at = datetime.now(timezone.utc) - timedelta(hours=25)
    wm.add_observation("fresh observation")

    context = wm.get_context()

    assert "fresh observation" in context
    assert "old observation" not in context


def test_working_memory_rejects_unsafe_session_id(fabric_root: Path) -> None:
    with pytest.raises(ValidationError):
        WorkingMemory.start(
            fabric_root,
            agent_id="agentA",
            session_id="../session",
            task_description="fix auth bug",
        )
