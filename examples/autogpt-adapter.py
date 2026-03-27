"""Icarus Memory Protocol adapter for AutoGPT.
Drop this in your AutoGPT plugins directory.
Agents write to ~/fabric/ and share memory across platforms."""

import os, json
from datetime import datetime, timezone
from pathlib import Path

FABRIC_DIR = Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric"))


def fabric_write(agent, platform, entry_type, content, refs=None, tags=None, summary=None):
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
        f"platform: {platform}",
        f"timestamp: {ts_iso}",
        f"type: {entry_type}",
        "tier: hot",
    ]
    if refs:
        lines.append(f"refs: [{', '.join(refs)}]")
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    if summary:
        lines.append(f"summary: {summary}")
    lines.extend(["---", "", content])
    filepath.write_text("\n".join(lines))
    return filepath


def fabric_read(agent=None, tier="hot"):
    search_dir = FABRIC_DIR / "cold" if tier == "cold" else FABRIC_DIR
    if not search_dir.exists():
        return []
    results = []
    for f in search_dir.glob("*.md"):
        text = f.read_text()
        if agent and f"agent: {agent}" not in text[:500]:
            continue
        if f"tier: {tier}" not in text[:500]:
            continue
        results.append(text)
    return results


# AutoGPT integration: call after each agent step
# fabric_write("autogpt-agent", "cli", "task", "completed web search for X")
# memories = fabric_read("autogpt-agent", "hot")
