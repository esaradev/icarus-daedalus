"""Lifecycle hooks — automatic memory injection, decision capture, creative tracking."""

import logging
import re

from . import state

logger = logging.getLogger(__name__)

# ── Decision detection (from fabric-memory) ──────────────
_DECISION_RE = re.compile(
    r"(?i)\b(decided|resolved|completed|fixed|built|created|deployed|shipped|reviewed|approved|rejected)\b"
)

# ── Creative pattern detection ───────────────────────────
_COMPLETION_RE = re.compile(
    r"(?i)\b(completed|finished|done|shipped|deployed|resolved|closed|merged|fixed)\b"
)
_REVIEW_RE = re.compile(
    r"(?i)\b(reviewed|review:|feedback:|MUST FIX|SHOULD FIX|approved|rejected|looks good|lgtm|nit:)\b"
)
_EVAL_RE = re.compile(
    r"(?i)\b(worked well|didn't work|failed|succeeded|learned|noticed|realized|discovered|finding|insight|improvement)\b"
)
_QUESTION_RE = re.compile(
    r"(?i)\b(what if|wonder|curious about|want to try|experiment with|explore|investigate|test whether)\b"
)
_STOPWORDS = frozenset(
    "this that with from have been were will about would could should their there "
    "these them then when what which some other more also just like very into only "
    "than over such make made most each does done being".split()
)

# ── Topic overlap tracking (from fabric-memory) ─────────
_last_query_tokens: set = set()


def _tokenize(text):
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return words - {"the", "a", "an", "is", "was", "are", "to", "of", "in", "for",
                    "on", "with", "it", "and", "or", "not", "i", "you", "can", "do",
                    "this", "that", "what", "how", "please", "help", "me", "my"}


def _extract_theme(text):
    words = re.findall(r"\b[a-z]{4,}\b", text.lower())
    filtered = [w for w in words[:30] if w not in _STOPWORDS][:3]
    return " ".join(filtered) if filtered else ""


def _extract_sentence(text, pattern):
    for s in re.split(r"[.!?\n]+", text):
        s = s.strip()
        if len(s) > 15 and pattern.search(s):
            return s[:120]
    return ""


# ── Hooks ────────────────────────────────────────────────

def on_session_start(session_id="", platform="", **kwargs):
    """Load context: SOUL + recent entries + cross-agent feedback + creative state."""
    global _last_query_tokens
    _last_query_tokens = set()
    state.session_id = session_id
    state.exchanges = []

    # bump creative cycle
    creative = state.load_creative()
    creative["cycle"] += 1
    state.save_creative(creative)

    parts = []

    # personality
    soul = state.load_soul()
    if soul:
        parts.append(soul.strip())

    # pending work (handoff-aware)
    open_tasks, reviews, open_tickets = state.read_pending()
    if open_tasks:
        parts.append(f"[fabric] {len(open_tasks)} open item(s) waiting for pickup:")
        for t in open_tasks[:5]:
            ts = t.get("timestamp", "")[:16] or "?"
            assignee = t.get("assigned_to", "") or "?"
            parts.append(
                f"  [{ts}] {t.get('agent', '?')} -> {assignee}: "
                f"{t.get('summary', '?')} ({t.get('type', '?')})"
            )

    if reviews:
        parts.append(f"[fabric] {len(reviews)} review(s) of your work:")
        for r in reviews[:5]:
            ts = r.get("timestamp", "")[:16] or "?"
            parts.append(f"  [{ts}] {r.get('agent', '?')}: {r.get('summary', '?')}")

    if open_tickets:
        parts.append(f"[fabric] {len(open_tickets)} open ticket(s):")
        for t in open_tickets[:5]:
            cid = t.get("customer_id", "?")
            assignee = t.get("assigned_to", "") or "?"
            parts.append(
                f"  [{cid}] {t.get('summary', '?')} "
                f"(from {t.get('agent', '?')} -> {assignee})"
            )

    # cross-agent feedback (non-pending items)
    if not open_tasks and not reviews:
        feedback = state.read_cross_agent(3)
        if feedback:
            parts.append("[fabric] from other agents:")
            for f in feedback:
                parts.append(f"  {f}")

    # recent entries
    entries = state.read_recent(limit=5)
    if entries:
        parts.append("[fabric] recent activity:")
        for e in entries:
            ts = e["timestamp"][:16] if e["timestamp"] else "?"
            parts.append(f"  [{ts}] {e['agent']}: {e['summary']}")

    # creative state
    if creative["questions"]:
        parts.append(f"[fabric] open questions: {'; '.join(creative['questions'][-3:])}")
    if creative["learnings"]:
        parts.append(f"[fabric] learnings: {'; '.join(creative['learnings'][-3:])}")

    context = "\n".join(parts)
    return {"context": context} if context else None


def pre_llm_call(session_id="", user_message="", is_first_turn=False, **kwargs):
    """Inject relevant memories when topic changes."""
    global _last_query_tokens
    if not user_message:
        return None

    tokens = _tokenize(user_message)
    if not tokens:
        return None

    # skip if topic hasn't changed (>60% overlap)
    if _last_query_tokens:
        overlap = len(tokens & _last_query_tokens) / max(len(tokens), 1)
        if overlap > 0.6:
            return None

    _last_query_tokens = tokens

    agent = state.AGENT_NAME or "agent"
    results = state.recall(user_message, max_results=5, agent=agent)
    if not results:
        return None

    lines = ["[fabric] relevant to your request:"]
    for e in results:
        ts = str(e.get("timestamp", ""))[:16] or "?"
        summary = e.get("summary") or e.get("_body", e.get("body", ""))[:80]
        lines.append(f"  [{ts}] {e.get('agent', '?')}: {summary}")

    return {"context": "\n".join(lines)}


def post_llm_call(session_id="", user_message="", assistant_response="", platform="", **kwargs):
    """Capture decisions + detect creative patterns."""
    if not assistant_response:
        return

    state.exchanges.append({
        "user": (user_message or "")[:200],
        "assistant": assistant_response[:500],
    })

    agent = state.AGENT_NAME or "agent"
    plat = platform or "cli"

    # capture decisions
    if _DECISION_RE.search(assistant_response) and len(assistant_response) > 100:
        summary = assistant_response[:80].replace("\n", " ")
        # detect if this completes work (status: completed) or is still open
        entry_status = "completed" if _COMPLETION_RE.search(assistant_response) else ""
        state.write_entry("decision", assistant_response[:500], summary,
                         platform=plat, status=entry_status)

    # creative tracking
    creative = state.load_creative()
    changed = False

    if _DECISION_RE.search(assistant_response):
        theme = _extract_theme(assistant_response)
        if theme and theme not in creative["themes"]:
            creative["themes"].append(theme)
            creative["themes"] = creative["themes"][-20:]
            changed = True

    if _EVAL_RE.search(assistant_response):
        learning = _extract_sentence(assistant_response, _EVAL_RE)
        if learning and learning not in creative["learnings"]:
            creative["learnings"].append(learning)
            creative["learnings"] = creative["learnings"][-15:]
            changed = True

    if _QUESTION_RE.search(assistant_response):
        question = _extract_sentence(assistant_response, _QUESTION_RE)
        if question and question not in creative["questions"]:
            creative["questions"].append(question)
            creative["questions"] = creative["questions"][-15:]
            changed = True

    if changed:
        state.save_creative(creative)


def on_session_end(session_id="", platform="", completed=False, **kwargs):
    """Write session summary to fabric + update MEMORY.md."""
    if not state.exchanges:
        return

    agent = state.AGENT_NAME or "agent"
    plat = platform or "cli"

    parts = [ex["assistant"] for ex in state.exchanges[-5:] if ex.get("assistant", "").strip()]
    if not parts:
        return

    content = "\n\n".join(parts)
    summary = content[:80].replace("\n", " ")
    state.write_entry("session", content, summary, platform=plat)

    # update MEMORY.md
    creative = state.load_creative()
    state.write_memory_file(creative)
