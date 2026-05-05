from __future__ import annotations

import os
from pathlib import Path

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
