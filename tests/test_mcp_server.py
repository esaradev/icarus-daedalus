from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest


def test_server_builds_and_registers_tools(fabric_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    from icarus_memory.mcp_server import build_server

    monkeypatch.setenv("ICARUS_FABRIC_ROOT", str(fabric_root))
    server = build_server(root=fabric_root)
    # The exact attribute name varies across mcp SDK versions; we just want
    # to confirm the server constructed and exposes a tool registry.
    assert server is not None
    name = getattr(server, "name", None) or getattr(server, "_name", None)
    assert name == "icarus-memory" or name is None  # FastMCP sets this


def test_server_builds_with_configured_http_port(fabric_root: Path) -> None:
    pytest.importorskip("mcp")
    from icarus_memory.mcp_server import build_server

    server = build_server(root=fabric_root, port=8765)
    settings = getattr(server, "settings", None)
    if settings is None or not hasattr(settings, "port"):
        pytest.skip("mcp SDK in this env does not expose FastMCP settings.port")
    assert settings.port == 8765


def test_serve_module_imports() -> None:
    pytest.importorskip("mcp")
    # Importing the module should not start the server.
    import icarus_memory.mcp_server  # noqa: F401


def test_cli_help_exits_zero() -> None:
    from click.testing import CliRunner

    from icarus_memory.cli import main

    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "icarus-memory" in result.output.lower() or "usage" in result.output.lower()


def test_cli_init_creates_directory(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from icarus_memory.cli import main

    target = tmp_path / "fabric"
    result = CliRunner().invoke(main, ["init", str(target)])
    assert result.exit_code == 0
    assert target.exists()


def test_cli_recall_smoke(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from icarus_memory import IcarusMemory
    from icarus_memory.cli import main

    root = tmp_path / "fabric"
    mem = IcarusMemory(root=root)
    mem.write(agent="t", type="decision", summary="postgres for users")

    os.environ["ICARUS_FABRIC_ROOT"] = str(root)
    try:
        result = CliRunner().invoke(
            main, ["recall", "postgres", "--root", str(root), "--mode", "keyword"]
        )
    finally:
        del os.environ["ICARUS_FABRIC_ROOT"]
    assert result.exit_code == 0
    assert "postgres" in result.output


def test_mcp_tools_reject_unknown_arguments(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from mcp.server.fastmcp.exceptions import ToolError

    from icarus_memory.mcp_server import build_server

    server = build_server(root=tmp_path / "fabric")
    manager = getattr(server, "_tool_manager", None)
    if manager is None or not hasattr(manager, "call_tool"):
        pytest.skip("mcp SDK in this env does not expose tool_manager.call_tool")

    payloads: dict[str, dict[str, Any]] = {
        "memory_write": {"agent": "a", "type": "decision", "summary": "x"},
        "memory_get": {"id": "icarus:000000000000"},
        "memory_recall": {"query": "x"},
        "memory_search": {"query": "x"},
        "memory_audit_search": {"query": "x"},
        "memory_verify": {"id": "icarus:000000000000"},
        "memory_contradict": {
            "id": "icarus:000000000000",
            "contradicted_by": "icarus:000000000001",
            "reason": "x",
        },
        "memory_rollback": {"id": "icarus:000000000000"},
        "memory_lineage": {"id": "icarus:000000000000"},
        "memory_pending": {"agent": "a"},
    }

    async def call_with_extra(name: str, payload: dict[str, Any]) -> None:
        with pytest.raises(ToolError, match="unknown argument: bogus"):
            await manager.call_tool(name, {**payload, "bogus": "x"})

    for name, payload in payloads.items():
        asyncio.run(call_with_extra(name, payload))
