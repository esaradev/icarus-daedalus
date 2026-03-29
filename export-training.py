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
    for line in parts[1].strip().split("\n"):
        if ": " in line:
            k, v = line.split(": ", 1)
            k = k.strip()
            if v.startswith("[") and v.endswith("]"):
                v = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
            meta[k] = v
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

        if not body or len(body) < 20:
            continue

        # ── BASIC PAIR: type as task, body as response ──
        if entry_type in ("code-session", "task", "resolution", "research"):
            user_msg = f"[{entry_type}] {summary}" if summary else f"Complete this {entry_type}"
            pairs.append(make_pair(user_msg, body, {"type": "basic", "agent": agent, "platform": platform}))

        elif entry_type == "dialogue":
            # For dialogue, the thought IS the output
            user_msg = f"[dialogue] Respond as {agent} in a multi-agent conversation."
            pairs.append(make_pair(user_msg, body, {"type": "dialogue", "agent": agent, "platform": platform}))

        elif entry_type == "decision":
            user_msg = f"[decision] What did you decide?"
            pairs.append(make_pair(user_msg, body, {"type": "decision", "agent": agent, "platform": platform}))

        elif entry_type == "session":
            user_msg = f"[session] Summarize what was accomplished."
            pairs.append(make_pair(user_msg, body, {"type": "session", "agent": agent, "platform": platform}))

        elif entry_type == "review":
            user_msg = f"[review] Review the following code or work."
            pairs.append(make_pair(user_msg, body, {"type": "review", "agent": agent, "platform": platform}))

        else:
            user_msg = f"[{entry_type or 'task'}] {summary or 'Complete this task'}"
            pairs.append(make_pair(user_msg, body, {"type": "basic", "agent": agent, "platform": platform}))

        # ── REVIEW PAIRS: if this is a review, find the original ──
        refs = e.get("refs", [])
        if isinstance(refs, str):
            refs = [r.strip() for r in refs.split(",") if r.strip()]

        if entry_type == "review" and refs:
            # Find the entry being reviewed
            for ref in refs:
                ref_agent = ref.split(":")[0] if ":" in ref else ""
                # Look for entries from that agent
                originals = [o for o in entries if o.get("agent") == ref_agent and o.get("type") in ("code-session", "task", "dialogue")]
                if originals:
                    orig = originals[0]
                    # Training pair: original + review → improved version
                    user_msg = f"[self-correct] Original work:\n{orig.get('body', '')[:300]}\n\nReview feedback:\n{body[:300]}\n\nProvide the improved version."
                    # The improved version would be a subsequent entry from the original agent
                    improved = [o for o in entries if o.get("agent") == ref_agent and o.get("timestamp", "") > e.get("timestamp", "")]
                    if improved:
                        pairs.append(make_pair(user_msg, improved[0].get("body", ""), {"type": "review-correction", "reviewer": agent, "author": ref_agent}))
                        review_pairs += 1

        # ── CROSS-PLATFORM PAIRS ──
        if refs and platform:
            for ref in refs:
                ref_agent = ref.split(":")[0] if ":" in ref else ""
                # Find entries from the referenced agent on a DIFFERENT platform
                xplat = [o for o in entries if o.get("agent") == ref_agent and o.get("platform") != platform and o.get("platform")]
                if xplat:
                    source = xplat[0]
                    src_plat = source.get("platform", "?")
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
    args = parser.parse_args()

    global FABRIC_DIR
    if args.fabric_dir:
        FABRIC_DIR = Path(args.fabric_dir)

    if not FABRIC_DIR.exists():
        print(f"error: {FABRIC_DIR} does not exist")
        sys.exit(1)

    entries = scan_all()
    if not entries:
        print("no fabric entries found")
        sys.exit(0)

    pairs, review_count, xplat_count = extract_pairs(entries)

    if not pairs:
        print("no training pairs extracted")
        sys.exit(0)

    # Write outputs
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    # OpenAI format
    with open(out / "openai.jsonl", "w") as f:
        for p in pairs:
            f.write(json.dumps(to_openai(p)) + "\n")

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
    print(f"    {out}/hf-dataset.jsonl")
    print(f"    {out}/raw-pairs.json")


if __name__ == "__main__":
    main()
