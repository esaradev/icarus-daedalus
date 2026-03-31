#!/usr/bin/env python3
"""export-training.py -- Extract fine-tuning data from fabric entries.

Reads ~/fabric/ and generates training pairs in three formats:
  openai.jsonl     -- OpenAI fine-tuning format
  hf-dataset.jsonl -- Hugging Face dataset format
  raw-pairs.json   -- Raw input/output pairs

Usage: python3 export-training.py --output ./training-data/
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

FABRIC_DIR = Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric"))


def parse_entry(filepath):
    """Parse a fabric markdown entry into a dict."""
    text = filepath.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta = {}
    try:
        import yaml as _yaml
        meta = _yaml.safe_load(parts[1]) or {}
    except Exception:
        lines = parts[1].strip().split("\n")
        current_key = None
        for line in lines:
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
    meta["body"] = parts[2].strip()
    meta["file"] = filepath.name
    return meta


def scan_all():
    """Scan all fabric entries including cold."""
    entries = []
    for d in [FABRIC_DIR, FABRIC_DIR / "cold"]:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            e = parse_entry(f)
            if e:
                entries.append(e)
    return entries


def _resolve_ref(ref, entries):
    """Resolve a ref string (agent:id) to a specific entry.

    Checks in priority order:
    1. id field match (exact)
    2. agent:cycle match
    3. agent:timestamp substring
    4. agent:filename substring
    First match wins. Returns None if unresolvable.
    """
    if ":" not in ref:
        return None
    ref_agent, ref_id = ref.split(":", 1)
    if not ref_agent or not ref_id:
        return None
    # 1. Exact id field match
    for o in entries:
        if o.get("agent") == ref_agent and str(o.get("id", "")) == str(ref_id):
            return o
    # 2. Cycle field match
    for o in entries:
        if o.get("agent") == ref_agent and str(o.get("cycle", "")) == str(ref_id):
            return o
    # 3. Timestamp substring match
    for o in entries:
        if o.get("agent") == ref_agent and str(ref_id) in str(o.get("timestamp", "")):
            return o
    # 4. Filename substring match
    for o in entries:
        if o.get("agent") == ref_agent and str(ref_id) in o.get("file", ""):
            return o
    return None


def estimate_tokens(text):
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def make_pair(user_content, assistant_content, metadata=None):
    """Create a training pair dict."""
    return {
        "input": user_content,
        "output": assistant_content,
        "metadata": metadata or {},
    }


def extract_pairs(entries):
    """Extract all training pairs from fabric entries."""
    pairs = []
    review_pairs = 0
    xplat_pairs = 0

    # index entries by agent+cycle for cross-referencing
    by_ref = {}
    for e in entries:
        refs = e.get("refs", [])
        if isinstance(refs, str):
            refs = [r.strip() for r in refs.split(",") if r.strip()]
        agent = e.get("agent", "")
        by_ref[f"{agent}:{e.get('file', '')}"] = e

    for e in entries:
        agent = e.get("agent", "unknown")
        platform = e.get("platform", "unknown")
        entry_type = e.get("type", "")
        body = e.get("body", "")
        summary = e.get("summary", "")

        tv = e.get("training_value", "")

        if not body or len(body) < 20:
            continue

        # ── OUTCOME PAIR: focused summary → outcome ──
        if e.get("outcome"):
            pairs.append(make_pair(
                f"[outcome] {summary}",
                e["outcome"],
                {"type": "outcome", "agent": agent, "platform": platform, "training_value": tv},
            ))

        # ── BASIC PAIR: type as task, body as response ──
        if entry_type in ("code-session", "task", "resolution", "research"):
            user_msg = f"[{entry_type}] {summary}" if summary else f"Complete this {entry_type}"
            pairs.append(make_pair(user_msg, body, {"type": "basic", "agent": agent, "platform": platform, "training_value": tv}))

        elif entry_type == "dialogue":
            # For dialogue, the thought IS the output
            user_msg = f"[dialogue] Respond as {agent} in a multi-agent conversation."
            pairs.append(make_pair(user_msg, body, {"type": "dialogue", "agent": agent, "platform": platform, "training_value": tv}))

        elif entry_type == "decision":
            user_msg = f"[decision] What did you decide?"
            pairs.append(make_pair(user_msg, body, {"type": "decision", "agent": agent, "platform": platform, "training_value": tv}))

        elif entry_type == "session":
            user_msg = f"[session] Summarize what was accomplished."
            pairs.append(make_pair(user_msg, body, {"type": "session", "agent": agent, "platform": platform, "training_value": tv}))

        elif entry_type == "review":
            user_msg = f"[review] Review the following code or work."
            pairs.append(make_pair(user_msg, body, {"type": "review", "agent": agent, "platform": platform, "training_value": tv}))

        else:
            user_msg = f"[{entry_type or 'task'}] {summary or 'Complete this task'}"
            pairs.append(make_pair(user_msg, body, {"type": "basic", "agent": agent, "platform": platform}))

        # ── Parse refs ──
        refs = e.get("refs", [])
        if isinstance(refs, str):
            refs = [r.strip() for r in refs.split(",") if r.strip()]

        # ── REVIEW PAIRS: only pair explicitly linked entries ──
        if entry_type == "review" and refs:
            for ref in refs:
                orig = _resolve_ref(ref, entries)
                if not orig:
                    continue
                # Find revision: must explicitly ref back to the review or original
                review_file = e.get("file", "")
                orig_file = orig.get("file", "")
                ref_agent = ref.split(":")[0] if ":" in ref else ""
                improved = None
                for candidate in entries:
                    if candidate.get("agent") != ref_agent:
                        continue
                    if candidate.get("timestamp", "") <= e.get("timestamp", ""):
                        continue
                    if candidate.get("file") == orig_file:
                        continue
                    # candidate must ref back to the review or original
                    cand_refs = candidate.get("refs", [])
                    if isinstance(cand_refs, str):
                        cand_refs = [r.strip() for r in cand_refs.split(",") if r.strip()]
                    refs_back = False
                    for cr in cand_refs:
                        resolved = _resolve_ref(cr, [e, orig])
                        if resolved:
                            refs_back = True
                            break
                    if refs_back:
                        improved = candidate
                        break
                if not improved:
                    continue
                user_msg = f"[self-correct] Original work:\n{orig.get('body', '')[:300]}\n\nReview feedback:\n{body[:300]}\n\nProvide the improved version."
                pairs.append(make_pair(user_msg, improved.get("body", ""), {"type": "review-correction", "reviewer": agent, "author": ref_agent}))
                review_pairs += 1

        # ── REVIEW PAIRS via review_of/revises (v3 plugin path) ──
        if entry_type == "review" and e.get("review_of"):
            ref = e["review_of"]
            orig = _resolve_ref(ref, entries)
            if orig:
                ref_agent = ref.split(":")[0] if ":" in ref else ""
                improved = None
                for candidate in entries:
                    if candidate.get("revises") == ref:
                        improved = candidate
                        break
                if improved:
                    rc_key = (e.get("file", ""), orig.get("file", ""))
                    # avoid duplicate if refs-based path already found this pair
                    rc_msg = f"[self-correct] Original work:\n{orig.get('body', '')[:300]}\n\nReview feedback:\n{body[:300]}\n\nProvide the improved version."
                    if not any(p["input"] == rc_msg for p in pairs if p.get("metadata", {}).get("type") == "review-correction"):
                        pairs.append(make_pair(rc_msg, improved.get("body", ""),
                            {"type": "review-correction", "reviewer": agent, "author": ref_agent, "training_value": tv}))
                        review_pairs += 1

        # ── CROSS-PLATFORM via review_of ──
        if e.get("review_of") and platform:
            source = _resolve_ref(e["review_of"], entries)
            if source:
                src_plat = source.get("platform", "")
                if src_plat and src_plat != platform:
                    user_msg = f"[cross-platform context] Memory from {src_plat}:\n{source.get('body', '')[:300]}\n\nYou are on {platform}. Use this context in your response."
                    pairs.append(make_pair(user_msg, body,
                        {"type": "cross-platform", "source_platform": src_plat, "target_platform": platform, "agent": agent, "training_value": tv}))
                    xplat_pairs += 1

        # ── CROSS-PLATFORM PAIRS: resolve ref to specific entry ──
        if refs and platform:
            for ref in refs:
                source = _resolve_ref(ref, entries)
                if not source:
                    continue
                src_plat = source.get("platform", "")
                if not src_plat or src_plat == platform:
                    continue  # same platform, not cross-platform
                user_msg = f"[cross-platform context] Memory from {src_plat}:\n{source.get('body', '')[:300]}\n\nYou are on {platform}. Use this context in your response."
                pairs.append(make_pair(user_msg, body, {"type": "cross-platform", "source_platform": src_plat, "target_platform": platform, "agent": agent}))
                xplat_pairs += 1

    return pairs, review_pairs, xplat_pairs


def to_openai(pair):
    """Convert to OpenAI fine-tuning format."""
    return {"messages": [
        {"role": "user", "content": pair["input"]},
        {"role": "assistant", "content": pair["output"]},
    ]}


def to_together(pair):
    """Convert to Together AI fine-tuning format (messages with system prompt)."""
    return {"messages": [
        {"role": "system", "content": "You are a helpful AI agent with shared memory across platforms."},
        {"role": "user", "content": pair["input"]},
        {"role": "assistant", "content": pair["output"]},
    ]}


def to_hf(pair):
    """Convert to Hugging Face dataset format."""
    return {
        "instruction": pair["input"],
        "output": pair["output"],
        "metadata": pair.get("metadata", {}),
    }


def main():
    parser = argparse.ArgumentParser(description="Export fabric entries as fine-tuning data")
    parser.add_argument("--output", default="./training-data", help="Output directory")
    parser.add_argument("--fabric-dir", default=None, help="Fabric directory (default: ~/fabric/)")
    parser.add_argument("--mode", choices=["high-precision", "normal", "high-volume"],
                        default="normal", help="Export quality mode")
    args = parser.parse_args()

    global FABRIC_DIR
    if args.fabric_dir:
        FABRIC_DIR = Path(args.fabric_dir)

    if not FABRIC_DIR.exists():
        print(f"error: {FABRIC_DIR} does not exist")
        sys.exit(1)

    all_entries = scan_all()
    if not all_entries:
        print("no fabric entries found")
        sys.exit(0)

    # filter by mode
    excluded = 0
    if args.mode == "high-precision":
        entries = [e for e in all_entries
                   if e.get("training_value") == "high"
                   or e.get("status") == "completed"
                   or (e.get("type") == "review" and e.get("review_of"))]
        excluded = len(all_entries) - len(entries)
    elif args.mode == "normal":
        entries = [e for e in all_entries if e.get("training_value") != "low"]
        excluded = len(all_entries) - len(entries)
    else:
        entries = all_entries

    pairs, review_count, xplat_count = extract_pairs(entries)

    if not pairs:
        print("no training pairs extracted")
        sys.exit(0)

    # weight high-value pairs
    weighted = []
    for p in pairs:
        meta = p.get("metadata", {})
        ptype = meta.get("type", "")
        tv = meta.get("training_value", "")
        if ptype == "review-correction":
            weighted.extend([p] * 3)
        elif tv == "high":
            weighted.extend([p] * 2)
        else:
            weighted.append(p)
    pairs = weighted

    # Write outputs
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    # OpenAI format
    with open(out / "openai.jsonl", "w") as f:
        for p in pairs:
            f.write(json.dumps(to_openai(p)) + "\n")

    # Together AI format (Llama instruct template)
    with open(out / "together.jsonl", "w") as f:
        for p in pairs:
            f.write(json.dumps(to_together(p)) + "\n")

    # HuggingFace format
    with open(out / "hf-dataset.jsonl", "w") as f:
        for p in pairs:
            f.write(json.dumps(to_hf(p)) + "\n")

    # Raw pairs
    with open(out / "raw-pairs.json", "w") as f:
        json.dump(pairs, f, indent=2)

    # Stats
    total_tokens = sum(estimate_tokens(p["input"] + p["output"]) for p in pairs)
    type_counts = {}
    for p in pairs:
        t = p.get("metadata", {}).get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"exported to {out}/")
    print(f"  total pairs:       {len(pairs)}")
    print(f"  review pairs:      {review_count}")
    print(f"  cross-platform:    {xplat_count}")
    print(f"  estimated tokens:  {total_tokens:,}")
    print(f"  by type:")
    for t, c in sorted(type_counts.items()):
        print(f"    {t}: {c}")
    print(f"  files:")
    print(f"    {out}/openai.jsonl")
    print(f"    {out}/together.jsonl")
    print(f"    {out}/hf-dataset.jsonl")
    print(f"    {out}/raw-pairs.json")


if __name__ == "__main__":
    main()
