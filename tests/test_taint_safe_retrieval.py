from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from icarus_memory import IcarusMemory


def _seed_statuses(mem: IcarusMemory) -> dict[str, list[str]]:
    ids: dict[str, list[str]] = {
        "verified": [],
        "unverified": [],
        "contradicted": [],
        "rolled_back": [],
    }

    for i in range(3):
        entry = mem.write(agent="a", type="decision", summary=f"needle verified {i}")
        ids["verified"].append(mem.verify(entry.id).id)

    for i in range(3):
        entry = mem.write(agent="a", type="decision", summary=f"needle unverified {i}")
        ids["unverified"].append(entry.id)

    for i in range(2):
        entry = mem.write(agent="a", type="decision", summary=f"needle contradicted {i}")
        mem.contradict(entry.id, contradicted_by=ids["verified"][0], reason="wrong")
        ids["contradicted"].append(entry.id)

    rb1 = mem.write(
        agent="a",
        type="decision",
        summary="needle rolled back 1",
        revises=ids["verified"][1],
    )
    rb2 = mem.write(
        agent="a",
        type="decision",
        summary="needle rolled back 2",
        revises=rb1.id,
    )
    mem.contradict(rb2.id, contradicted_by=ids["verified"][1], reason="wrong")
    mem.rollback(rb2.id, dry_run=False)
    ids["rolled_back"].extend([rb1.id, rb2.id])
    return ids


def test_search_defaults_to_safe_statuses(mem: IcarusMemory) -> None:
    ids = _seed_statuses(mem)

    found = {entry.id for entry in mem.search("needle")}

    assert found == set(ids["verified"] + ids["unverified"])


def test_search_status_filter_all_returns_everything(mem: IcarusMemory) -> None:
    ids = _seed_statuses(mem)

    found = {entry.id for entry in mem.search("needle", status_filter="all")}

    assert found == set().union(*ids.values())


def test_search_status_filter_verified_only(mem: IcarusMemory) -> None:
    ids = _seed_statuses(mem)

    found = {entry.id for entry in mem.search("needle", status_filter="verified_only")}

    assert found == set(ids["verified"])


def test_audit_search_returns_everything(mem: IcarusMemory) -> None:
    ids = _seed_statuses(mem)

    found = {entry.id for entry in mem.audit_search("needle")}

    assert found == set().union(*ids.values())


def test_recall_status_filter_all_can_include_tainted(mem: IcarusMemory) -> None:
    ids = _seed_statuses(mem)

    found = {
        hit.entry.id
        for hit in mem.recall("needle", mode="keyword", k=20, status_filter="all")
    }

    assert found == set().union(*ids.values())


def _call(server: Any, name: str, **kwargs: Any) -> Any:
    manager = getattr(server, "_tool_manager", None)
    if manager is None or not hasattr(manager, "call_tool"):
        pytest.skip("mcp SDK in this env does not expose tool_manager.call_tool")
    return asyncio.run(manager.call_tool(name, kwargs))


def _as_list(result: Any) -> list[Any]:
    if hasattr(result, "structured_content") and result.structured_content is not None:
        structured = result.structured_content
        if isinstance(structured, dict) and "result" in structured:
            return list(structured["result"])
        if isinstance(structured, list):
            return structured
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return [result]
    if hasattr(result, "content"):
        import json as _json

        out: list[Any] = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text is None:
                continue
            parsed = _json.loads(text)
            if isinstance(parsed, list):
                out.extend(parsed)
            else:
                out.append(parsed)
        return out
    return [result]


def test_mcp_memory_search_defaults_to_safe(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from icarus_memory.mcp_server import build_server

    root = tmp_path / "fabric"
    mem = IcarusMemory(root=root)
    ids = _seed_statuses(mem)
    server = build_server(root=root)

    found = {entry["id"] for entry in _as_list(_call(server, "memory_search", query="needle"))}

    assert found == set(ids["verified"] + ids["unverified"])


def test_mcp_memory_audit_search_returns_everything(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from icarus_memory.mcp_server import build_server

    root = tmp_path / "fabric"
    mem = IcarusMemory(root=root)
    ids = _seed_statuses(mem)
    server = build_server(root=root)

    found = {
        entry["id"]
        for entry in _as_list(_call(server, "memory_audit_search", query="needle"))
    }

    assert found == set().union(*ids.values())
