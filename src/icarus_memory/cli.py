"""icarus-memory CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import IcarusMemory, __version__


@click.group()
@click.version_option(__version__, prog_name="icarus-memory")
def main() -> None:
    """Framework-agnostic agent memory with provenance and rollback."""


@main.command()
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True), required=False)
def init(path: str | None) -> None:
    """Create a fabric directory at PATH (default: ~/fabric)."""
    target = Path(path).expanduser() if path else Path("~/fabric").expanduser()
    target.mkdir(parents=True, exist_ok=True)
    click.echo(f"initialized fabric at {target}")


@main.command()
@click.argument("query")
@click.option("--root", type=click.Path(), help="fabric root directory")
@click.option("-k", "--k", type=int, default=10, help="max results")
@click.option("--mode", type=click.Choice(["auto", "keyword", "hybrid"]), default="auto")
def recall(query: str, root: str | None, k: int, mode: str) -> None:
    """Recall entries matching QUERY."""
    mem = IcarusMemory(root=root)
    hits = mem.recall(query, k=k, mode=mode)  # type: ignore[arg-type]
    if not hits:
        click.echo("no results")
        return
    for hit in hits:
        click.echo(
            f"{hit.entry.id}  [{hit.entry.verified}]  {hit.entry.summary}  "
            f"(score={hit.score:.4f})"
        )


@main.command()
@click.argument("entry_id")
@click.option("--root", type=click.Path(), help="fabric root directory")
@click.option("--note", default="", help="verification note")
@click.option("--verifier", default="manual", help="who/what verified")
def verify(entry_id: str, root: str | None, note: str, verifier: str) -> None:
    """Mark ENTRY_ID as verified."""
    mem = IcarusMemory(root=root)
    entry = mem.verify(entry_id, verifier=verifier, note=note)
    click.echo(f"verified {entry.id}")


@main.command()
@click.argument("entry_id")
@click.option("--root", type=click.Path(), help="fabric root directory")
@click.option("--apply", "apply_", is_flag=True, help="apply (default is dry-run)")
def rollback(entry_id: str, root: str | None, apply_: bool) -> None:
    """Plan (or apply with --apply) a rollback for ENTRY_ID."""
    mem = IcarusMemory(root=root)
    plan = mem.rollback(entry_id, dry_run=not apply_)
    click.echo(json.dumps(plan.model_dump(mode="json"), indent=2))


@main.command()
@click.option("--root", type=click.Path(), help="fabric root directory")
@click.option("--http", "http_port", type=int, default=None, help="serve HTTP on PORT")
def serve(root: str | None, http_port: int | None) -> None:
    """Start the MCP server (stdio by default, --http for streamable HTTP)."""
    from .mcp_server import serve_http, serve_stdio

    if http_port is not None:
        serve_http(root, port=http_port)
    else:
        serve_stdio(root)


if __name__ == "__main__":
    main()
    sys.exit(0)
