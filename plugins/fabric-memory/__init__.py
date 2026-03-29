"""
Fabric Memory Plugin for Hermes Agent
======================================

Automatic shared memory via the Icarus Memory Protocol.

- on_session_start: loads relevant fabric entries into agent context
- on_session_end: writes session summary to ~/fabric/
- post_llm_call: detects decisions/completions and writes them to ~/fabric/

Agents never call fabric_write. This plugin does it for them.
"""

import os
import re
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

FABRIC_DIR = Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric"))
AGENT_NAME = os.environ.get("HERMES_AGENT_NAME", "")

# Resolve agent name from HERMES_HOME if not set
if not AGENT_NAME:
    hermes_home = os.environ.get("HERMES_HOME", "")
    if hermes_home and ".hermes-" in hermes_home:
        AGENT_NAME = hermes_home.split(".hermes-")[-1].rstrip("/")

# keywords that indicate a decision or completion worth remembering
DECISION_PATTERNS = [
    r"(?i)\b(decided|resolved|completed|fixed|built|created|deployed|shipped|reviewed|approved|rejected)\b",
    r"(?i)\b(will do|agreed to|committed to|plan is|conclusion|takeaway|finding|result)\b",
    r"(?i)\b(important|critical|note|remember|key point|action item)\b",
]


def _write_entry(agent, platform, entry_type, content, summary=""):
    """Write a fabric entry. Returns the file path."""
    FABRIC_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H%MZ")
    ts_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    suffix = secrets.token_hex(2)
    filename = f"{agent}-{entry_type}-{ts}-{suffix}.md"
    filepath = FABRIC_DIR / filename

    lines = [
        "---",
        f"agent: {agent}",
        f"platform: {platform}",
        f"timestamp: {ts_iso}",
        f"type: {entry_type}",
        "tier: hot",
    ]
    if summary:
        lines.append(f"summary: {summary}")
    lines.extend(["---", "", content])
    filepath.write_text("\n".join(lines), encoding="utf-8")
    logger.info("fabric-memory: wrote %s", filename)
    return filepath


def _read_recent(agent="", limit=5):
    """Read recent hot fabric entries, optionally filtered by agent."""
    if not FABRIC_DIR.exists():
        return []
    entries = []
    for f in sorted(FABRIC_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        text = f.read_text(encoding="utf-8")[:600]
        if "tier: hot" not in text:
            continue
        if agent and f"agent: {agent}" not in text:
            continue
        summary = ""
        m = re.search(r"^summary: (.+)$", text, re.MULTILINE)
        if m:
            summary = m.group(1)
        else:
            body = text.split("---", 2)
            if len(body) > 2:
                summary = body[2].strip()[:100]
        entry_agent = ""
        m = re.search(r"^agent: (.+)$", text, re.MULTILINE)
        if m:
            entry_agent = m.group(1)
        ts = ""
        m = re.search(r"^timestamp: (.+)$", text, re.MULTILINE)
        if m:
            ts = m.group(1)
        entries.append({"agent": entry_agent, "timestamp": ts, "summary": summary})
        if len(entries) >= limit:
            break
    return entries


def _has_decision(text):
    """Check if text contains patterns worth remembering."""
    for pattern in DECISION_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


# session accumulator: collects user messages + assistant responses during a session
_session_exchanges = []


def _on_session_start(session_id="", platform="", **kwargs):
    """Load relevant fabric context at session start.

    Returns a string that hermes injects into the ephemeral system prompt.
    """
    global _session_exchanges
    _session_exchanges = []

    agent = AGENT_NAME or "agent"
    entries = _read_recent(limit=8)

    if not entries:
        return None

    context_lines = [f"[fabric memory] recent activity across all agents:"]
    for e in entries:
        ts = e["timestamp"][:16] if e["timestamp"] else "?"
        context_lines.append(f"  [{ts}] {e['agent']}: {e['summary']}")

    context = "\n".join(context_lines)
    logger.info("fabric-memory: injected %d entries into session context", len(entries))
    return context


def _on_session_end(session_id="", platform="", completed=False, **kwargs):
    """Write a session summary to fabric after the session ends."""
    agent = AGENT_NAME or "agent"
    plat = platform or "cli"

    if not _session_exchanges:
        return

    # Build summary from accumulated exchanges
    summary_parts = []
    for ex in _session_exchanges[-5:]:  # last 5 exchanges
        if ex.get("assistant", "").strip():
            summary_parts.append(ex["assistant"][:200])

    if not summary_parts:
        return

    content = "\n\n".join(summary_parts)
    summary = content[:80].replace("\n", " ")

    _write_entry(agent, plat, "session", content, summary=summary)


def _post_llm_call(
    session_id="", user_message="", assistant_response="", platform="", **kwargs
):
    """After each LLM response, check for decisions and accumulate exchanges."""
    agent = AGENT_NAME or "agent"
    plat = platform or "cli"

    # accumulate for session summary
    _session_exchanges.append({
        "user": (user_message or "")[:200],
        "assistant": (assistant_response or "")[:500],
    })

    # check if the response contains a decision worth capturing immediately
    if assistant_response and _has_decision(assistant_response):
        # only write if the response is substantial (not just a greeting)
        if len(assistant_response) > 100:
            summary = assistant_response[:80].replace("\n", " ")
            _write_entry(agent, plat, "decision", assistant_response[:500], summary=summary)


def register(ctx):
    """Register hooks with the hermes plugin system."""
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("post_llm_call", _post_llm_call)
    logger.info("fabric-memory plugin registered")
