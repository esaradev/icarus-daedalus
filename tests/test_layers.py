from __future__ import annotations

import json
from pathlib import Path

import pytest

from icarus_memory import ValidationError, _layers


def test_safe_id_and_page_path_validation() -> None:
    assert _layers.safe_id("agent-1", "agent_id") == "agent-1"
    assert _layers.safe_page_path("/decisions/auth.md") == "decisions/auth"

    with pytest.raises(ValidationError):
        _layers.safe_id("", "agent_id")

    with pytest.raises(ValidationError):
        _layers.safe_page_path("bad segment/ok")


def test_frontmatter_round_trip_and_invalid_cases() -> None:
    text = _layers.yaml_frontmatter({"path": "x"}, "body")
    front, body = _layers.split_yaml_frontmatter(text)

    assert front == {"path": "x"}
    assert body == "body"

    with pytest.raises(ValidationError):
        _layers.split_yaml_frontmatter("no frontmatter")

    with pytest.raises(ValidationError):
        _layers.split_yaml_frontmatter("---\n- nope\n---\nbody")


def test_atomic_write_json(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "file.json"

    _layers.atomic_write_json(path, {"a": 1})

    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
    assert list(path.parent.glob("*.tmp.*")) == []


def test_call_openai_json_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert _layers.call_openai_json("prompt") is None


def test_call_openai_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "{\"path\": \"decisions/auth\"}"}}]}
            ).encode("utf-8")

    def fake_urlopen(_request: object, *, timeout: int) -> FakeResponse:
        assert timeout == 10
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(_layers.urllib.request, "urlopen", fake_urlopen)

    assert _layers.call_openai_json("prompt") == {"path": "decisions/auth"}


def test_call_openai_json_malformed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "not-json"}}]}).encode(
                "utf-8"
            )

    def fake_urlopen(_request: object, *, timeout: int) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(_layers.urllib.request, "urlopen", fake_urlopen)

    assert _layers.call_openai_json("prompt") is None
