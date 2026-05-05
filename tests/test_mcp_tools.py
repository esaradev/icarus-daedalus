"""Invoke the MCP tool registry directly to cover mcp_server.py.

We use FastMCP's internal tool manager — its API is the registered tool
function objects. This exercises every tool-handler closure without spinning
up a stdio server.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")


def _call(server: Any, name: str, **kwargs: Any) -> Any:
    """Invoke a registered FastMCP tool by name and return its raw result."""
    manager = getattr(server, "_tool_manager", None)
    if manager is None or not hasattr(manager, "call_tool"):
        pytest.skip("mcp SDK in this env does not expose tool_manager.call_tool")
    coro = manager.call_tool(name, kwargs)
    return asyncio.run(coro)


def test_mcp_tools_round_trip(tmp_path: Path) -> None:
    from icarus_memory.mcp_server import build_server

    server = build_server(root=tmp_path / "fabric")

    # write
    written = _call(
        server,
        "memory_write",
        agent="t",
        type="decision",
        summary="postgres for users",
    )
    entry_id = _extract_entry(written)["id"]

    # get
    got = _call(server, "memory_get", id=entry_id)
    assert _extract_entry(got)["id"] == entry_id

    # search
    found = _call(server, "memory_search", query="postgres")
    assert any(_extract_entry(e)["id"] == entry_id for e in _as_list(found))

    # recall
    hits = _call(server, "memory_recall", query="postgres", mode="keyword")
    hit_ids = [_extract_entry(h["entry"])["id"] for h in _as_list(hits)]
    assert entry_id in hit_ids

    # verify
    verified = _call(server, "memory_verify", id=entry_id, note="ok")
    assert _extract_entry(verified)["verified"] == "verified"

    # contradict requires another existing entry
    other = _call(server, "memory_write", agent="t", type="decision", summary="other")
    other_id = _extract_entry(other)["id"]
    contradicted = _call(
        server,
        "memory_contradict",
        id=other_id,
        contradicted_by=entry_id,
        reason="superseded",
    )
    assert _extract_entry(contradicted)["verified"] == "contradicted"

    # rollback target needs verified ancestor + revises chain
    revised = _call(
        server,
        "memory_write",
        agent="t",
        type="decision",
        summary="postgres v2",
        revises=entry_id,
    )
    revised_id = _extract_entry(revised)["id"]
    plan = _call(server, "memory_rollback", id=revised_id, dry_run=True)
    assert plan["verified_ancestor"] == entry_id

    # lineage
    chain = _call(server, "memory_lineage", id=revised_id)
    chain_ids = [_extract_entry(e)["id"] for e in _as_list(chain)]
    assert entry_id in chain_ids

    # pending
    _call(
        server,
        "memory_write",
        agent="t",
        type="task",
        summary="open task",
        status="open",
        assigned_to="me",
    )
    pending = _call(server, "memory_pending", agent="me")
    assert any(
        _extract_entry(e)["status"] == "open" for e in _as_list(pending)
    )


def _as_list(result: Any) -> list[Any]:
    """FastMCP may wrap return values as Content lists or raw lists."""
    if hasattr(result, "structured_content") and result.structured_content is not None:
        sc = result.structured_content
        if isinstance(sc, dict) and "result" in sc:
            return list(sc["result"])
        if isinstance(sc, list):
            return sc
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return [result]
    if hasattr(result, "content"):
        import json as _json

        out: list[Any] = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text is not None:
                parsed = _json.loads(text)
                if isinstance(parsed, list):
                    out.extend(parsed)
                else:
                    out.append(parsed)
        return out
    return [result]


def _extract_entry(value: Any) -> dict[str, Any]:
    """Unwrap a single entry-shaped value from FastMCP's various return forms."""
    if isinstance(value, dict):
        return value
    items = _as_list(value)
    assert items, f"expected at least one item, got {value!r}"
    item = items[0]
    if isinstance(item, dict):
        return item
    raise AssertionError(f"could not extract entry dict from {value!r}")
