"""Adapter sketch: route Hermes session events into icarus-memory.

Hermes exposes hook callbacks for tool calls, decisions, and session
boundaries. This adapter wires those onto ``IcarusMemory.write`` so every
Hermes interaction becomes a fabric entry with proper provenance.

Wire-up depends on your Hermes deployment; this file is a reference shape,
not runnable code.
"""

from __future__ import annotations

from typing import Any

from icarus_memory import IcarusMemory


class HermesAdapter:
    def __init__(self, fabric_root: str = "~/fabric"):
        self.mem = IcarusMemory(root=fabric_root, platform="hermes")

    def on_tool_call(self, *, agent: str, tool: str, result: dict[str, Any]) -> None:
        self.mem.write(
            agent=agent,
            type="tool-call",
            summary=f"called {tool}",
            body=str(result),
            source_tool=tool,
            evidence=[
                {
                    "kind": "tool_output",
                    "ref": result.get("call_id", tool),
                }
            ],
        )

    def on_decision(
        self,
        *,
        agent: str,
        summary: str,
        body: str,
        evidence_files: list[str] | None = None,
    ) -> str:
        entry = self.mem.write(
            agent=agent,
            type="decision",
            summary=summary,
            body=body,
            source_tool="hermes",
            evidence=[
                {"kind": "file", "ref": p} for p in (evidence_files or [])
            ],
        )
        return entry.id

    def on_session_close(
        self, *, agent: str, session_id: str, summary: str
    ) -> None:
        self.mem.write(
            agent=agent,
            type="session",
            summary=summary,
            session_id=session_id,
            source_tool="hermes",
            status="closed",
        )
