"""Icarus Memory Protocol adapter for LangChain/LangGraph.
Use as a custom memory class or tool in any chain."""

import os
from datetime import datetime, timezone
from pathlib import Path
from langchain_core.tools import tool

FABRIC_DIR = Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric"))


def _write(agent, platform, entry_type, content, refs=None, tags=None):
    FABRIC_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H%MZ")
    ts_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    import secrets
    suffix = secrets.token_hex(2)
    filepath = FABRIC_DIR / f"{agent}-{entry_type}-{ts}-{suffix}.md"
    lines = ["---", f"agent: {agent}", f"platform: {platform}",
             f"timestamp: {ts_iso}", f"type: {entry_type}", "tier: hot"]
    if refs:
        lines.append(f"refs: [{', '.join(refs)}]")
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    lines.extend(["---", "", content])
    filepath.write_text("\n".join(lines))
    return str(filepath)


@tool
def fabric_remember(content: str, agent: str = "langchain", tags: str = "") -> str:
    """Save a memory to the shared fabric for other agents to read."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    path = _write(agent, "langchain", "task", content, tags=tag_list)
    return f"saved to {os.path.basename(path)}"


@tool
def fabric_recall(agent: str = "", tier: str = "hot") -> str:
    """Read memories from the shared fabric."""
    search_dir = FABRIC_DIR / "cold" if tier == "cold" else FABRIC_DIR
    if not search_dir.exists():
        return "no memories"
    results = []
    for f in sorted(search_dir.glob("*.md")):
        text = f.read_text()
        if agent and f"agent: {agent}" not in text[:500]:
            continue
        if f"tier: {tier}" not in text[:500]:
            continue
        results.append(text)
    return "\n---\n".join(results) if results else "no matching memories"


# Usage: agent = create_react_agent(llm, tools=[fabric_remember, fabric_recall])
