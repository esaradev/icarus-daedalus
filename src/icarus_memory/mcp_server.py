"""MCP server exposing IcarusMemory as tools over stdio or streamable HTTP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from .schema import Entry, RecallHit, RollbackPlan


def _entry_dict(entry: Entry) -> dict[str, Any]:
    return entry.model_dump(mode="json")


def _hit_dict(hit: RecallHit) -> dict[str, Any]:
    return hit.model_dump(mode="json")


def _plan_dict(plan: RollbackPlan) -> dict[str, Any]:
    return plan.model_dump(mode="json")


def build_server(root: str | Path | None = None, *, port: int = 8000) -> Any:
    """Build a FastMCP server with all icarus-memory tools registered.

    The mcp SDK is imported lazily so that ``import icarus_memory`` stays
    cheap for callers who only use the library.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError(
            "icarus-memory MCP server requires `mcp>=1.0`. "
            "Install with: pip install icarus-memory"
        ) from exc

    from . import IcarusMemory

    memory = IcarusMemory(root=root)
    mcp = FastMCP("icarus-memory", port=port)

    @mcp.tool()
    def memory_write(
        agent: str,
        type: str,
        summary: str,
        body: str = "",
        project_id: str | None = None,
        session_id: str | None = None,
        revises: str | None = None,
        review_of: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
        source_tool: str | None = None,
        artifact_paths: list[str] | None = None,
        training_value: Literal["high", "normal", "low"] = "normal",
        status: Literal["open", "in-progress", "closed"] | None = None,
        assigned_to: str | None = None,
    ) -> dict[str, Any]:
        """Write a new memory entry. Returns the persisted entry."""
        entry = memory.write(
            agent=agent,
            type=type,
            summary=summary,
            body=body,
            project_id=project_id,
            session_id=session_id,
            revises=revises,
            review_of=review_of,
            evidence=evidence,
            source_tool=source_tool,
            artifact_paths=artifact_paths,
            training_value=training_value,
            status=status,
            assigned_to=assigned_to,
        )
        return _entry_dict(entry)

    @mcp.tool()
    def memory_get(id: str) -> dict[str, Any]:
        """Fetch an entry by id."""
        return _entry_dict(memory.get(id))

    @mcp.tool()
    def memory_recall(
        query: str,
        k: int = 10,
        mode: Literal["auto", "keyword", "embedding", "hybrid"] = "auto",
        status_filter: Literal["safe", "all", "verified_only"] = "safe",
        min_verified: Literal[
            "unverified", "verified", "contradicted", "rolled_back"
        ] = "unverified",
        exclude_rolled_back: bool = True,
        agent: str | None = None,
        project_id: str | None = None,
        type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Ranked recall with verified-status filtering and ordering."""
        hits = memory.recall(
            query,
            k=k,
            mode=mode,
            status_filter=status_filter,
            min_verified=min_verified,
            exclude_rolled_back=exclude_rolled_back,
            agent=agent,
            project_id=project_id,
            type=type,
        )
        return [_hit_dict(h) for h in hits]

    @mcp.tool()
    def memory_search(
        query: str,
        status_filter: Literal["safe", "all", "verified_only"] = "safe",
    ) -> list[dict[str, Any]]:
        """Substring search; excludes contradicted and rolled-back entries by default."""
        return [_entry_dict(e) for e in memory.search(query, status_filter=status_filter)]

    @mcp.tool()
    def memory_audit_search(query: str) -> list[dict[str, Any]]:
        """Audit-only substring search that includes tainted entries."""
        return [_entry_dict(e) for e in memory.audit_search(query)]

    @mcp.tool()
    def memory_verify(id: str, verifier: str = "manual", note: str = "") -> dict[str, Any]:
        """Mark an entry verified and append a verification record."""
        return _entry_dict(memory.verify(id, verifier=verifier, note=note))

    @mcp.tool()
    def memory_contradict(
        id: str, contradicted_by: str, reason: str
    ) -> dict[str, Any]:
        """Mark an entry contradicted by another (does not delete)."""
        return _entry_dict(
            memory.contradict(id, contradicted_by=contradicted_by, reason=reason)
        )

    @mcp.tool()
    def memory_rollback(id: str, dry_run: bool = True, cascade: bool = False) -> dict[str, Any]:
        """Plan or apply a rollback to the last verified ancestor."""
        return _plan_dict(memory.rollback(id, dry_run=dry_run, cascade=cascade))

    @mcp.tool()
    def memory_lineage(id: str) -> list[dict[str, Any]]:
        """Return the merged ancestry chain (revises + review_of)."""
        return [_entry_dict(e) for e in memory.lineage(id)]

    @mcp.tool()
    def memory_pending(agent: str) -> list[dict[str, Any]]:
        """List entries with status='open' filtered by assignee."""
        return [_entry_dict(e) for e in memory.pending(agent)]

    return mcp


def serve_stdio(root: str | Path | None = None) -> None:
    server = build_server(root)
    server.run("stdio")


def serve_http(root: str | Path | None = None, port: int = 8765) -> None:
    server = build_server(root, port=port)
    server.run("streamable-http")


def list_tool_names() -> list[str]:
    """Return the registered tool names without starting the server."""
    server = build_server(root=None)
    # FastMCP exposes a list_tools() that varies by version; fall back to attr.
    tools = getattr(server, "_tool_manager", None)
    if tools is not None and hasattr(tools, "list_tools"):
        return [t.name for t in tools.list_tools()]
    return []


# Convenience for CLI smoke tests
def dump_tool_names_json() -> str:
    return json.dumps(list_tool_names())
