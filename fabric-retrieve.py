#!/usr/bin/env python3
"""fabric-retrieve.py -- Smart retrieval for fabric entries.

Given a query, returns the top N most relevant entries ranked by:
keyword match, project match, agent match, recency, tier, type match, ref chain.

Usage:
    python3 fabric-retrieve.py "billing issue" --max-results 5 --max-tokens 2000
    python3 fabric-retrieve.py "auth module" --agent icarus --project myapp
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

FABRIC_DIR = Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric"))

STOP_WORDS = {"the", "a", "an", "is", "was", "are", "were", "be", "been", "being",
              "have", "has", "had", "do", "does", "did", "will", "would", "could",
              "should", "may", "might", "shall", "can", "to", "of", "in", "for",
              "on", "with", "at", "by", "from", "as", "into", "through", "during",
              "it", "its", "this", "that", "and", "or", "but", "not", "no", "if",
              "then", "than", "so", "up", "out", "about", "what", "which", "who",
              "how", "when", "where", "why", "i", "me", "my", "we", "our", "you"}

CODE_WORDS = {"function", "bug", "error", "build", "deploy", "test", "code", "fix",
              "commit", "merge", "api", "endpoint", "module", "class", "method",
              "refactor", "debug", "compile", "runtime", "exception", "stack"}

CUSTOMER_WORDS = {"customer", "billing", "support", "ticket", "refund", "account",
                  "subscription", "payment", "invoice", "complaint", "resolution",
                  "escalation", "onboarding", "churn", "retention"}

HANDOFF_WORDS = {"handoff", "review", "reviewer", "pickup", "pending", "relay",
                 "assigned", "assignee", "revise", "revision", "feedback"}


def parse_entry(filepath):
    text = filepath.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta = {}
    try:
        import yaml
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        current_key = None
        for line in parts[1].strip().split("\n"):
            stripped = line.strip()
            if stripped.startswith("- ") and current_key:
                if not isinstance(meta.get(current_key), list):
                    meta[current_key] = []
                meta[current_key].append(stripped[2:].strip().strip("\"'"))
            elif ": " in stripped and not stripped.startswith("-"):
                k, v = stripped.split(": ", 1)
                k = k.strip()
                current_key = k
                if v.startswith("[") and v.endswith("]"):
                    meta[k] = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
                elif v.strip():
                    meta[k] = v.strip()
                else:
                    meta[k] = []
            elif stripped.endswith(":") and not stripped.startswith("-"):
                current_key = stripped[:-1].strip()
                meta[current_key] = []
    meta["_body"] = parts[2].strip()
    meta["_file"] = filepath.name
    meta["_full"] = text
    return meta


def tokenize(text):
    words = set(re.findall(r'[a-z0-9]+', text.lower()))
    return words - STOP_WORDS


def _ngrams(tokens, n):
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def age_hours(timestamp_str):
    if not timestamp_str:
        return 9999
    try:
        ts = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        return max(0, delta.total_seconds() / 3600)
    except (ValueError, AttributeError):
        return 9999


def _as_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [value]


def score_entry(entry, query_tokens, agent=None, project=None, relevant_refs=None):
    summary = str(entry.get("summary", ""))
    summary_lower = summary.lower()
    body = (entry.get("_body", "") + " " + summary).lower()
    entry_tokens = tokenize(body)
    summary_tokens = tokenize(summary_lower)
    entry_type = entry.get("type", "")
    query_text = " ".join(re.findall(r"[a-z0-9]+", " ".join(sorted(query_tokens))))
    body_text = " ".join(re.findall(r"[a-z0-9]+", body))
    query_seq = re.findall(r"[a-z0-9]+", query_text)
    body_seq = re.findall(r"[a-z0-9]+", body)

    score = 0.0

    # 1. Keyword match (body + summary)
    keyword_hits = len(query_tokens & entry_tokens)
    score += keyword_hits * 5  # keywords are the primary signal

    # 1a. Summary match is higher-signal than body text alone.
    summary_hits = len(query_tokens & summary_tokens)
    score += summary_hits * 3

    # 1b. Exact phrase and n-gram matches beat loose token overlap.
    raw_query = " ".join(re.findall(r"[a-z0-9]+", entry.get("_query", "")))
    if raw_query and raw_query in body_text:
        score += 18
    if query_seq:
        body_bigrams = _ngrams(body_seq, 2)
        query_bigrams = _ngrams(query_seq, 2)
        score += len(query_bigrams & body_bigrams) * 4
        body_trigrams = _ngrams(body_seq, 3)
        query_trigrams = _ngrams(query_seq, 3)
        score += len(query_trigrams & body_trigrams) * 7

    # 1b. Tag match (tags are high-signal metadata)
    entry_tags = _as_list(entry.get("tags", []))
    tag_tokens = set()
    for t in entry_tags:
        tag_tokens.update(re.findall(r'[a-z0-9]+', str(t).lower()))
    tag_hits = len(query_tokens & tag_tokens)
    score += tag_hits * 4

    # 2. Same project (check project_id field first, then fallback to keyword match)
    entry_project = entry.get("project_id", entry.get("project", ""))
    if project:
        project_lower = project.lower()
        if project_lower == str(entry_project).lower():
            score += 10  # exact project_id match
        elif project_lower in body:
            score += 8   # project name in body text
        elif any(project_lower in str(t).lower() for t in entry_tags):
            score += 8   # project name in tags

    # 3. Same agent
    if agent and entry.get("agent") == agent:
        score += 5

    # 4. Recency (secondary signal, should not override keyword match)
    hours = age_hours(entry.get("timestamp"))
    if hours < 1:
        score += 4
    elif hours < 24:
        score += 3
    elif hours < 168:  # 1 week
        score += 2
    elif hours < 720:  # 1 month
        score += 1

    # 5. Tier boost (light touch)
    tier = entry.get("tier", "")
    if tier == "hot":
        score += 2
    elif tier == "warm":
        score += 1

    # 6. Type match
    if query_tokens & CODE_WORDS:
        if entry_type in ("code-session", "review", "decision"):
            score += 5
    if query_tokens & CUSTOMER_WORDS:
        if entry_type in ("resolution", "task", "decision"):
            score += 5
    if query_tokens & HANDOFF_WORDS:
        if entry_type in ("task", "review", "resolution", "code-session"):
            score += 6
        elif entry_type == "session":
            score -= 3

    # Prefer source work artifacts over generic summaries.
    if entry_type in ("task", "review", "resolution", "code-session", "research"):
        score += 2
    elif entry_type == "decision":
        score += 1
    elif entry_type == "session":
        score -= 2

    # Structured workflow fields are high-signal for handoffs and follow-ups.
    if entry.get("status") == "open":
        score += 4
    if entry.get("review_of"):
        score += 4
    if entry.get("revises"):
        score += 4
    if entry.get("assigned_to"):
        score += 2

    # 7. Ref chain
    if relevant_refs:
        entry_refs = _as_list(entry.get("refs", []))
        entry_id = entry.get("id", "")
        entry_agent = entry.get("agent", "")
        entry_cycle = str(entry.get("cycle", ""))
        for ref in relevant_refs:
            if ref in entry_refs:
                score += 3
        # Check if this entry is referenced by a relevant entry
        for ref_str in relevant_refs:
            if ":" in ref_str:
                ref_agent, ref_id = ref_str.split(":", 1)
                if ref_agent == entry_agent and (ref_id == entry_id or ref_id == entry_cycle):
                    score += 3
        linked_refs = [entry.get("review_of"), entry.get("revises")]
        for ref in linked_refs:
            if ref and ref in relevant_refs:
                score += 5

    return score


def deduplicate(entries):
    seen = {}
    result = []
    for e in entries:
        key = (e.get("agent", ""), e.get("type", ""), e.get("_body", "")[:50])
        existing = seen.get(key)
        if existing:
            # Keep the newer one
            if str(e.get("timestamp", "")) > str(existing.get("timestamp", "")):
                result.remove(existing)
                result.append(e)
                seen[key] = e
        else:
            seen[key] = e
            result.append(e)
    return result


def retrieve(query, max_results=5, max_tokens=2000, agent=None, project=None):
    if not FABRIC_DIR.exists():
        return []

    # Scan all entries
    entries = []
    for d in [FABRIC_DIR, FABRIC_DIR / "cold"]:
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            e = parse_entry(f)
            if e:
                entries.append(e)

    if not entries:
        return []

    query_tokens = tokenize(query)
    query_words = re.findall(r"[a-z0-9]+", query.lower())
    normalized_query = " ".join(query_words)
    for e in entries:
        e["_query"] = normalized_query

    # First pass: score without ref chain
    scored = [(score_entry(e, query_tokens, agent, project), e) for e in entries]

    # Collect refs from top-scoring entries for ref chain boost
    scored.sort(key=lambda x: x[0], reverse=True)
    top_refs = set()
    for score, e in scored[:10]:
        if score > 0:
            refs = e.get("refs", [])
            if isinstance(refs, str):
                refs = [refs]
            top_refs.update(refs)
            eid = e.get("id", "")
            eagent = e.get("agent", "")
            if eid:
                top_refs.add(f"{eagent}:{eid}")

    # Second pass: rescore with ref chain
    if top_refs:
        scored = [(score_entry(e, query_tokens, agent, project, top_refs), e) for e in entries]
        scored.sort(key=lambda x: x[0], reverse=True)

    # Filter zero scores
    scored = [(s, e) for s, e in scored if s > 0]

    # Deduplicate
    deduped_entries = deduplicate([e for _, e in scored])
    # Reattach scores
    score_map = {id(e): s for s, e in scored}
    # Rebuild scored list preserving dedup order
    final = []
    for e in deduped_entries:
        # Find the score for this entry
        for s, orig in scored:
            if orig is e:
                final.append((s, e))
                break
    final.sort(key=lambda x: x[0], reverse=True)

    # Apply max_results
    final = final[:max_results]

    # Apply token budget (always enforced, including first entry)
    budget = max_tokens
    result = []
    for score, e in final:
        content = e.get("_full", "")
        tokens = len(content) // 4
        if tokens > budget:
            continue  # skip oversized entries, try next
        budget -= tokens
        result.append((score, e))

    return result


def format_results(results):
    lines = []
    for score, e in results:
        lines.append(f"# relevance: {score:.0f} | {e.get('agent','')} | {e.get('platform','')} | {e.get('type','')}")
        lines.append(e.get("_full", "").strip())
        lines.append("---")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Smart fabric retrieval")
    parser.add_argument("query", help="Search query or current task description")
    parser.add_argument("--max-results", type=int, default=5, help="Maximum entries to return")
    parser.add_argument("--max-tokens", type=int, default=2000, help="Token budget (chars/4)")
    parser.add_argument("--agent", default=None, help="Boost entries from this agent")
    parser.add_argument("--project", default=None, help="Boost entries from this project")
    parser.add_argument("--fabric-dir", default=None, help="Override fabric directory")
    args = parser.parse_args()

    global FABRIC_DIR
    if args.fabric_dir:
        FABRIC_DIR = Path(args.fabric_dir)

    results = retrieve(args.query, args.max_results, args.max_tokens, args.agent, args.project)

    if not results:
        print("no relevant entries found")
        sys.exit(0)

    print(format_results(results))


if __name__ == "__main__":
    main()
