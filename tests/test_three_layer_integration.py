from __future__ import annotations

from icarus_memory import IcarusMemory


def test_three_layer_agent_flow_and_privacy(mem: IcarusMemory) -> None:
    wm, first_briefing = mem.start_session("agentA", "fix auth bug")
    assert first_briefing.agent_id == "agentA"
    wm.add_observation("Login redirect loses session cookie")
    wm.add_attempt("Regenerated OAuth client secret", succeeded=False)
    wm.add_attempt("Pinned cookie domain to app host", succeeded=True)
    wm.add_hypothesis("Callback and app domains disagree", confidence=0.9)

    archived = mem.end_session(
        wm,
        "Auth fix is to pin callback cookie domain",
        promote_to_wiki=["decisions/auth-strategy"],
    )

    page = mem.get_wiki_page("decisions/auth-strategy")
    assert page is not None
    assert page.entries
    promoted_entry = mem.get(page.entries[-1])
    assert promoted_entry.source_tool == "session_archive"
    assert promoted_entry.evidence[0].ref == archived.ref

    later = mem.get_briefing("agentA", "fix auth bug cookie")
    assert "decisions/auth-strategy" in later.page_paths
    assert "Regenerated OAuth client secret" in later.content

    other_agent = mem.get_briefing("agentB", "fix auth bug cookie")
    assert "decisions/auth-strategy" in other_agent.page_paths
    assert "Regenerated OAuth client secret" not in other_agent.content
