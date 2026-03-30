#!/usr/bin/env python3
"""eval-replacement.py -- Compare a candidate model against a base model.

Extracts eval prompts from high-value fabric entries, runs both models,
scores task completion, format compliance, and style match.

Usage:
    python3 scripts/eval-replacement.py \
        --candidate-model user/icarus-v1 \
        --base-model Qwen/Qwen2-7B-Instruct \
        --together-api-key tok_... \
        --sample-count 10
"""

import argparse
import json
import math
import os
import re
import sys
import urllib.request
from pathlib import Path

FABRIC_DIR = Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric"))

STOP_WORDS = {"the", "a", "an", "is", "was", "are", "to", "of", "in", "for",
              "on", "with", "it", "and", "or", "not", "i", "you", "this", "that"}

# type-specific format patterns
FORMAT_PATTERNS = {
    "review": re.compile(r"(?i)(MUST FIX|SHOULD FIX|approved|rejected|feedback|issue)"),
    "decision": re.compile(r"(?i)(because|result|outcome|conclusion|chose|decided)"),
    "code-session": re.compile(r"(?i)(function|class|def |import |return |const |let |var )"),
    "resolution": re.compile(r"(?i)(resolved|fixed|root cause|refund|ticket)"),
    "research": re.compile(r"(?i)(found|compared|analysis|benchmark|option)"),
}


def parse_entry(filepath):
    text = filepath.read_text("utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta = {}
    for line in parts[1].strip().split("\n"):
        if ": " in line and not line.strip().startswith("-"):
            k, v = line.strip().split(": ", 1)
            meta[k.strip()] = v.strip()
    meta["body"] = parts[2].strip()
    return meta


def get_eval_entries(sample_count):
    """Get high-value entries for eval prompts."""
    entries = []
    for d in [FABRIC_DIR, FABRIC_DIR / "cold"]:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            e = parse_entry(f)
            if not e or not e.get("body") or len(e["body"]) < 50:
                continue
            if e.get("training_value") == "high" or e.get("status") == "completed":
                entries.append(e)
            if len(entries) >= sample_count * 2:
                break
    return entries[:sample_count]


def call_model(model, prompt, api_key):
    """Call a model via Together's OpenAI-compatible API."""
    data = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful AI agent."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 512,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        "https://api.together.xyz/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR: {e}"


def tokenize(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in STOP_WORDS]


def score_task_completion(response, expected):
    """Does the response have enough substance? 0-1."""
    if not expected:
        return 1.0 if len(response) > 50 else 0.0
    return min(1.0, len(response) / max(len(expected) * 0.5, 1))


def score_format_compliance(response, entry_type):
    """Does the response match type-specific format patterns? 0 or 1."""
    pattern = FORMAT_PATTERNS.get(entry_type)
    if not pattern:
        return 1.0
    return 1.0 if pattern.search(response) else 0.0


def score_style_match(response, expected):
    """Cosine similarity of word frequency distributions. 0-1."""
    if not expected or not response:
        return 0.0
    resp_tokens = tokenize(response)
    exp_tokens = tokenize(expected)
    if not resp_tokens or not exp_tokens:
        return 0.0

    all_words = set(resp_tokens) | set(exp_tokens)
    resp_freq = {w: resp_tokens.count(w) for w in all_words}
    exp_freq = {w: exp_tokens.count(w) for w in all_words}

    dot = sum(resp_freq.get(w, 0) * exp_freq.get(w, 0) for w in all_words)
    mag_r = math.sqrt(sum(v ** 2 for v in resp_freq.values()))
    mag_e = math.sqrt(sum(v ** 2 for v in exp_freq.values()))

    if mag_r == 0 or mag_e == 0:
        return 0.0
    return dot / (mag_r * mag_e)


def main():
    parser = argparse.ArgumentParser(description="Compare candidate vs base model")
    parser.add_argument("--candidate-model", required=True)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--together-api-key", required=True)
    parser.add_argument("--fabric-dir", default=None)
    parser.add_argument("--sample-count", type=int, default=10)
    args = parser.parse_args()

    global FABRIC_DIR
    if args.fabric_dir:
        FABRIC_DIR = Path(args.fabric_dir)

    entries = get_eval_entries(args.sample_count)
    if not entries:
        json.dump({"error": "no eval entries found"}, sys.stdout)
        sys.exit(1)

    results = []
    for e in entries:
        entry_type = e.get("type", "task")
        summary = e.get("summary", "")
        body = e.get("body", "")
        prompt = f"[{entry_type}] {summary}" if summary else f"Complete this {entry_type}"

        base_resp = call_model(args.base_model, prompt, args.together_api_key)
        cand_resp = call_model(args.candidate_model, prompt, args.together_api_key)

        base_scores = {
            "task_completion": score_task_completion(base_resp, body),
            "format_compliance": score_format_compliance(base_resp, entry_type),
            "style_match": score_style_match(base_resp, body),
        }
        cand_scores = {
            "task_completion": score_task_completion(cand_resp, body),
            "format_compliance": score_format_compliance(cand_resp, entry_type),
            "style_match": score_style_match(cand_resp, body),
        }

        results.append({
            "prompt": prompt[:80],
            "type": entry_type,
            "base_scores": base_scores,
            "candidate_scores": cand_scores,
        })

    # aggregate
    def avg_scores(key):
        vals = {}
        for r in results:
            for metric, score in r[key].items():
                vals.setdefault(metric, []).append(score)
        return {m: round(sum(s) / len(s), 3) for m, s in vals.items()}

    base_avg = avg_scores("base_scores")
    cand_avg = avg_scores("candidate_scores")

    output = {
        "sample_count": len(results),
        "base_model": args.base_model,
        "candidate_model": args.candidate_model,
        "base_scores": base_avg,
        "candidate_scores": cand_avg,
        "per_prompt": results,
    }

    json.dump(output, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
