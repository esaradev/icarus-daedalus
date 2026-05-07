from __future__ import annotations

from datetime import datetime, timezone

from icarus_memory import IcarusMemory


def test_briefing_offline_template_and_cache(mem: IcarusMemory) -> None:
    briefing = mem.get_briefing("agentA", "fix auth bug")
    again = mem.get_briefing("agentA", "fix auth bug")

    assert briefing.cost_usd == 0
    assert "fix auth bug" in briefing.content
    assert briefing.cache_key == again.cache_key


def test_briefing_cache_changes_when_wiki_changes(mem: IcarusMemory) -> None:
    first = mem.get_briefing("agentA", "fix auth bug")
    entry = mem.write(agent="agentA", type="note", summary="Auth strategy uses cookies")
    mem.wiki.add_entry("decisions/auth-strategy", entry.id)

    second = mem.get_briefing("agentA", "fix auth bug")

    assert first.cache_key != second.cache_key
    assert "decisions/auth-strategy" in second.page_paths


def test_briefing_includes_same_agent_failed_attempts(mem: IcarusMemory) -> None:
    wm, _ = mem.start_session("agentA", "fix auth bug")
    wm.add_attempt("Rotating secrets did not fix redirects", succeeded=False)
    mem.end_session(wm, "Need callback state fix")

    briefing = mem.get_briefing("agentA", "fix auth bug redirects")

    assert "Rotating secrets did not fix redirects" in briefing.content
    assert "session_archive:agentA:" in " ".join(briefing.source_ids)


def test_briefing_recent_superseded_uses_supersession_time(mem: IcarusMemory) -> None:
    old = mem.write(
        agent="agentA",
        type="decision",
        summary="Use legacy auth state",
        timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    mem.write_with_supersession(
        agent="agentA",
        type="decision",
        summary="Use current auth state",
        supersedes_ids=[old.id],
    )

    briefing = mem.get_briefing("agentA", "auth state")

    assert old.id in briefing.source_ids
    assert "Use legacy auth state" in briefing.content
