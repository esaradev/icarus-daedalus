from __future__ import annotations

from pathlib import Path

import pytest

from icarus_memory import IcarusMemory, ValidationError, WikiManager


def test_write_creates_uncategorized_wiki_page_offline(
    mem: IcarusMemory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    entry = mem.write(agent="agent", type="note", summary="Auth bug uses stale token")

    page = mem.get_wiki_page("uncategorized")
    assert page is not None
    assert entry.id in page.entries
    assert "Auth bug uses stale token" in page.body


def test_wiki_path_traversal_rejected(fabric_root: Path) -> None:
    wiki = WikiManager(fabric_root)

    with pytest.raises(ValidationError):
        wiki.ensure_page("../outside")

    with pytest.raises(ValidationError):
        wiki.ensure_page("decisions/../../outside")


def test_wiki_atomic_write_leaves_no_temp_file(mem: IcarusMemory) -> None:
    page = mem.wiki.ensure_page("decisions/auth-strategy")
    mem.wiki.write_page(page)

    assert (mem.root / ".icarus" / "wiki" / "decisions" / "auth-strategy.md").exists()
    assert list((mem.root / ".icarus" / "wiki").rglob("*.tmp.*")) == []


def test_search_wiki_uses_entry_recall(mem: IcarusMemory) -> None:
    entry = mem.write(agent="agent", type="decision", summary="Use signed auth cookies")
    mem.wiki.add_entry("decisions/auth-strategy", entry.id)

    results = mem.search_wiki("signed auth")

    assert "decisions/auth-strategy" in [page.path for page in results]
