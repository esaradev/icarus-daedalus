"""Lifecycle hooks — memory capture, decision detection, creative tracking."""

import logging
import re

from . import state

logger = logging.getLogger(__name__)

# ── Narrow regex for entry writing (decisions worth persisting) ──
_DECISION_RE = re.compile(
    r"(?i)\b(decided|resolved|completed|fixed|deployed|shipped|reviewed|approved|rejected)\b"
)
_OUTCOME_RE = re.compile(
    r"(?i)(result:|outcome:|conclusion:|because|root cause|instead of|\d+%|\d+x)"
)
_COMPLETION_RE = re.compile(
    r"(?i)\b(completed|finished|done|shipped|deployed|resolved|closed|merged|fixed)\b"
)
_REVIEW_RE = re.compile(
    r"(?i)\b(reviewed|review:|feedback:|MUST FIX|SHOULD FIX|approved|rejected|looks good|lgtm|nit:)\b"
)

# ── Broad regex for creative tracking (theme extraction, not entry writing) ──
_THEME_RE = re.compile(
    r"(?i)\b(decided|resolved|completed|fixed|deployed|shipped|reviewed|approved|rejected|built|created)\b"
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

# ── Topic overlap tracking ──
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
    """Load context: SOUL + pending handoffs + recent entries + creative state."""
    global _last_query_tokens
    _last_query_tokens = set()
    state.session_id = session_id
    state.exchanges = []
    state._recall_log = []

    creative = state.load_creative()
    creative["cycle"] += 1
    state.save_creative(creative)

    parts = []

    soul = state.load_soul()
    if soul:
        parts.append(soul.strip())

    # pending work (handoff-aware)
    open_tasks, reviews, open_tickets = state.read_pending()
    if open_tasks:
        parts.append(f"[fabric] {len(open_tasks)} item(s) assigned to you:")
        for t in open_tasks[:5]:
            src = t.get("agent", "?")
            entry_id = t.get("id", "?")
            etype = t.get("type", "task")
            parts.append(f"  - {src}: {t.get('summary', '?')} ({etype}, id {entry_id})")
        parts.append("  If reviewing, set review_of. If revising, set revises. Otherwise just complete the work.")

    if reviews:
        parts.append(f"[fabric] {len(reviews)} review(s) of your work:")
        for r in reviews[:5]:
            reviewer = r.get("agent", "?")
            entry_id = r.get("id", "?")
            ref = r.get("review_of", "")
            parts.append(f"  - {reviewer}: {r.get('summary', '?')} (review id {entry_id}, of {ref})")
        parts.append("  When you fix the issues, set revises to your original entry's agent:id.")

    if open_tickets:
        parts.append(f"[fabric] {len(open_tickets)} ticket(s) assigned to you:")
        for t in open_tickets[:5]:
            cid = t.get("customer_id", "?")
            src = t.get("agent", "?")
            entry_id = t.get("id", "?")
            parts.append(f"  - [{cid}] {t.get('summary', '?')} (from {src}, id {entry_id})")
        parts.append("  Carry customer_id forward when you resolve these.")

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

    if _last_query_tokens:
        overlap = len(tokens & _last_query_tokens) / max(len(tokens), 1)
        if overlap > 0.6:
            return None

    _last_query_tokens = tokens

    agent = state.AGENT_NAME or "agent"
    results = state.recall(user_message, max_results=5, agent=agent)
    if not results:
        return None

    # log what was recalled for telemetry
    state.log_recall(user_message, results, source="pre_llm_call")

    lines = ["[fabric] relevant to your request:"]
    for e in results:
        ts = str(e.get("timestamp", ""))[:16] or "?"
        summary = e.get("summary") or e.get("_body", e.get("body", ""))[:80]
        lines.append(f"  [{ts}] {e.get('agent', '?')}: {summary}")

    return {"context": "\n".join(lines)}


def post_llm_call(session_id="", user_message="", assistant_response="", platform="", **kwargs):
    """Capture high-value decisions + creative tracking."""
    if not assistant_response:
        return

    state.exchanges.append({
        "user": (user_message or "")[:200],
        "assistant": assistant_response[:500],
    })

    agent = state.AGENT_NAME or "agent"
    plat = platform or "cli"

    # capture decisions: requires decision + outcome in response, AND a substantial
    # user request (>50 chars) to ground the claim. stores both task and result
    # so training pairs have real context, not just assistant prose.
    user_text = (user_message or "").strip()
    if (_DECISION_RE.search(assistant_response)
            and _OUTCOME_RE.search(assistant_response)
            and len(assistant_response) > 200
            and len(user_text) > 50):
        body = f"Task: {user_text[:300]}\n\nResult: {assistant_response[:500]}"
        summary = assistant_response[:80].replace("\n", " ")
        entry_status = "completed" if _COMPLETION_RE.search(assistant_response) else ""
        state.write_entry("decision", body, summary,
                         platform=plat, status=entry_status, training_value="high")

    # creative tracking (uses broader _THEME_RE, doesn't write entries)
    creative = state.load_creative()
    changed = False

    if _THEME_RE.search(assistant_response):
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
    """Write session summary only if the session had substantive work."""
    creative = state.load_creative()

    # always update MEMORY.md
    state.write_memory_file(creative)

    if not state.exchanges:
        return

    plat = platform or "cli"

    # only consider substantial exchanges (assistant response > 100 chars)
    substantive = [ex for ex in state.exchanges
                   if len(ex.get("assistant", "").strip()) > 100]
    if len(substantive) < 2:
        return

    # write the single best exchange, not a join of 5
    best = max(substantive, key=lambda ex: len(ex.get("assistant", "")))
    content = best["assistant"]
    summary = content[:80].replace("\n", " ")

    tv = "high" if (_DECISION_RE.search(content) or _COMPLETION_RE.search(content)) else "low"

    state.write_entry("session", content, summary, platform=plat, training_value=tv)
