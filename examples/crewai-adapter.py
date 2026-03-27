"""Icarus Memory Protocol adapter for CrewAI.
Add as a tool to any CrewAI agent. Shared memory across crews."""

import os
from datetime import datetime, timezone
from pathlib import Path
from crewai.tools import tool

FABRIC_DIR = Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric"))


@tool("fabric_write")
def fabric_write(agent: str, content: str, entry_type: str = "task", tags: str = "") -> str:
    """Write a memory entry to the shared fabric. Other agents can read it."""
    FABRIC_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H%MZ")
    ts_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    import secrets
    suffix = secrets.token_hex(2)
    filepath = FABRIC_DIR / f"{agent}-{entry_type}-{ts}-{suffix}.md"
    lines = [
        "---",
        f"agent: {agent}",
        f"platform: crewai",
        f"timestamp: {ts_iso}",
        f"type: {entry_type}",
        "tier: hot",
    ]
    if tags:
        lines.append(f"tags: [{tags}]")
    lines.extend(["---", "", content])
    filepath.write_text("\n".join(lines))
    return f"written to {filepath.name}"


@tool("fabric_read")
def fabric_read(agent: str = "", tier: str = "hot") -> str:
    """Read memory entries from the shared fabric."""
    search_dir = FABRIC_DIR / "cold" if tier == "cold" else FABRIC_DIR
    if not search_dir.exists():
        return "no entries"
    results = []
    for f in sorted(search_dir.glob("*.md")):
        text = f.read_text()
        if agent and f"agent: {agent}" not in text[:500]:
            continue
        if f"tier: {tier}" not in text[:500]:
            continue
        results.append(text)
    return "\n---\n".join(results) if results else "no matching entries"


# Usage in CrewAI:
# agent = Agent(role="researcher", tools=[fabric_write, fabric_read])
