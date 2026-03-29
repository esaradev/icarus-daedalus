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

    entry_id = secrets.token_hex(4)
    lines = [
        "---",
        f"id: {entry_id}",
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


def _load_retriever():
    """Load fabric-retrieve.py from the plugin directory or common locations.

    setup.sh copies fabric-retrieve.py into the plugin dir during install.
    This is the single source of retrieval logic -- no inline duplicate.
    Returns the module or None.
    """
    search_paths = [
        Path(__file__).parent / "fabric-retrieve.py",               # plugin-local copy (installed by setup.sh)
        Path(os.environ.get("FABRIC_RETRIEVE_PATH", "")),           # explicit override
        Path(__file__).parent.parent.parent / "fabric-retrieve.py", # repo checkout
    ]
    for p in search_paths:
        if p.exists():
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("fabric_retrieve", str(p))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.FABRIC_DIR = FABRIC_DIR
                logger.debug("fabric-memory: loaded retriever from %s", p)
                return mod
            except Exception as exc:
                logger.debug("fabric-memory: failed to load %s: %s", p, exc)
    return None


_retriever = None


def _get_retriever():
    """Lazy-load the retriever module once."""
    global _retriever
    if _retriever is None:
        _retriever = _load_retriever()
    return _retriever


def _retrieve_relevant(query, agent=None, limit=5, max_tokens=1500):
    """Retrieve relevant entries using the shared fabric-retrieve.py module.

    Falls back to _read_recent if the retriever isn't available.
    """
    mod = _get_retriever()
    if mod is None:
        logger.debug("fabric-memory: retriever not available, falling back to _read_recent")
        return _read_recent(agent, limit)

    mod.FABRIC_DIR = FABRIC_DIR
    try:
        results = mod.retrieve(query, max_results=limit, max_tokens=max_tokens, agent=agent)
        # results are (score, entry) tuples; extract just the entries
        return [e for _, e in results]
    except Exception as exc:
        logger.debug("fabric-memory: retrieval error: %s", exc)
        return _read_recent(agent, limit)


# Holds the first user message for deferred retrieval
_pending_query = ""


def _on_session_start(session_id="", platform="", **kwargs):
    """Initialize session. Actual context injection happens on first pre_llm_call
    when we have the user's actual message to query against."""
    global _session_exchanges, _pending_query, _last_query_tokens
    _session_exchanges = []
    _pending_query = ""
    _last_query_tokens = set()

    # Load a minimal set of recent entries as baseline context
    agent = AGENT_NAME or "agent"
    entries = _read_recent(limit=5)
    if not entries:
        return None

    context_lines = ["[fabric memory] recent activity:"]
    for e in entries:
        ts = e["timestamp"][:16] if e["timestamp"] else "?"
        context_lines.append(f"  [{ts}] {e['agent']}: {e['summary']}")

    return "\n".join(context_lines)


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


_last_query_tokens = set()


def _pre_llm_call(session_id="", user_message="", is_first_turn=False, **kwargs):
    """Retrieve memories relevant to the user's actual message.

    Fires on first turn always. On subsequent turns, fires only if the
    user's message has substantially different keywords from the last
    query (topic changed). This prevents re-injecting the same context
    but catches topic shifts mid-session.

    Returns context string that hermes appends to the ephemeral system prompt.
    """
    global _last_query_tokens
    if not user_message:
        return None

    # Tokenize the current message
    msg_tokens = set(re.findall(r'[a-z0-9]+', user_message.lower())) - {
        "the", "a", "an", "is", "was", "are", "to", "of", "in", "for",
        "on", "with", "it", "and", "or", "not", "i", "you", "can", "do",
        "this", "that", "what", "how", "please", "help", "me", "my"}

    if not msg_tokens:
        return None

    # Skip if the topic hasn't changed (>60% keyword overlap with last query)
    if _last_query_tokens:
        overlap = len(msg_tokens & _last_query_tokens) / max(len(msg_tokens), 1)
        if overlap > 0.6:
            return None

    _last_query_tokens = msg_tokens

    agent = AGENT_NAME or "agent"
    results = _retrieve_relevant(user_message, agent=agent, limit=5, max_tokens=1500)
    if not results:
        return None

    lines = ["[fabric memory] relevant to your request:"]
    for e in results:
        ts = e.get("timestamp", "")[:16] if e.get("timestamp") else "?"
        summary = e.get("summary") or e.get("_body", e.get("body", ""))[:80]
        lines.append(f"  [{ts}] {e.get('agent', '?')}: {summary}")

    logger.info("fabric-memory: injected %d entries via query-aware retrieval (query: %s)", len(results), user_message[:50])
    return "\n".join(lines)


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
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("post_llm_call", _post_llm_call)
    logger.info("fabric-memory plugin registered")
