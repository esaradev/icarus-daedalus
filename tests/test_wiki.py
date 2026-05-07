from __future__ import annotations

from pathlib import Path

import pytest

from icarus_memory import IcarusMemory, ValidationError, WikiManager, _layers


def test_write_creates_uncategorized_wiki_page_offline(
    mem: IcarusMemory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    entry = mem.write(agent="agent", type="note", summary="Auth bug uses stale token")

    page = mem.get_wiki_page("uncategorized")
    assert page is not None
    assert entry.id in page.entries
    assert "Auth bug uses stale token" in page.body


def test_wiki_classification_defaults_off_without_http(
    fabric_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("OpenAI should not be called by default")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(_layers.urllib.request, "urlopen", fail_urlopen)
    mem = IcarusMemory(root=fabric_root)

    entry = mem.write(agent="agent", type="note", summary="No classification by default")

    page = mem.get_wiki_page("uncategorized")
    assert page is not None
    assert entry.id in page.entries


def test_wiki_classification_per_write_override_uses_openai(
    fabric_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"{\\"path\\":'
                b'\\"decisions/auth\\",\\"page_type\\":\\"decision\\"}"}}]}'
            )

    def fake_urlopen(*_args: object, **_kwargs: object) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(_layers.urllib.request, "urlopen", fake_urlopen)
    mem = IcarusMemory(root=fabric_root)

    entry = mem.write(agent="agent", type="note", summary="Classify auth", classify=True)

    page = mem.get_wiki_page("decisions/auth")
    assert calls == 1
    assert page is not None
    assert entry.id in page.entries


def test_wiki_classification_missing_key_warns_once(
    fabric_root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("OpenAI should not be called without a key")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(_layers.urllib.request, "urlopen", fail_urlopen)
    mem = IcarusMemory(root=fabric_root, enable_wiki_classification=True)

    first = mem.write(agent="agent", type="note", summary="First")
    second = mem.write(agent="agent", type="note", summary="Second", classify=True)

    page = mem.get_wiki_page("uncategorized")
    assert page is not None
    assert first.id in page.entries
    assert second.id in page.entries
    assert caplog.text.count("OPENAI_API_KEY is not set") == 1


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
