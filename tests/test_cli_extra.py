from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from icarus_memory import IcarusMemory
from icarus_memory.cli import main


def test_cli_verify(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    mem = IcarusMemory(root=root)
    entry = mem.write(agent="t", type="decision", summary="x")

    result = CliRunner().invoke(
        main, ["verify", entry.id, "--root", str(root), "--note", "ok"]
    )
    assert result.exit_code == 0
    assert "verified" in result.output

    reloaded = IcarusMemory(root=root).get(entry.id)
    assert reloaded.verified == "verified"


def test_cli_rollback_dry_run(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    mem = IcarusMemory(root=root)
    a = mem.write(agent="t", type="decision", summary="A")
    mem.verify(a.id)
    b = mem.write(agent="t", type="decision", summary="B", revises=a.id)

    result = CliRunner().invoke(main, ["rollback", b.id, "--root", str(root)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["verified_ancestor"] == a.id
    assert payload["applied"] is False


def test_cli_rollback_apply(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    mem = IcarusMemory(root=root)
    a = mem.write(agent="t", type="decision", summary="A")
    mem.verify(a.id)
    b = mem.write(agent="t", type="decision", summary="B", revises=a.id)

    result = CliRunner().invoke(
        main, ["rollback", b.id, "--root", str(root), "--apply"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["applied"] is True


def test_cli_recall_no_results(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    IcarusMemory(root=root)  # ensure dir exists
    result = CliRunner().invoke(
        main, ["recall", "nothing-matches", "--root", str(root), "--mode", "keyword"]
    )
    assert result.exit_code == 0
    assert "no results" in result.output
