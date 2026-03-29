#!/usr/bin/env python3
"""curator.py -- Icarus Memory Protocol curator.
Watches ~/fabric/, re-tiers entries by age, compacts warm entries,
moves cold entries to cold/, builds index.json.

Usage: python3 curator.py [--once]
Env: ANTHROPIC_API_KEY (required for compaction), FABRIC_DIR (default ~/fabric)
"""

import os, sys, json, re, time, glob
from datetime import datetime, timezone, timedelta
from pathlib import Path

FABRIC_DIR = Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric"))
COLD_DIR = FABRIC_DIR / "cold"
INDEX_FILE = FABRIC_DIR / "index.json"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

HOT_HOURS = 24
WARM_DAYS = 7
FORCE_COLD_DAYS = 14  # move to cold even if compaction fails


def parse_entry(filepath):
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
        # Fallback: handle both inline [a, b] and multiline YAML arrays
        lines = parts[1].strip().split("\n")
        current_key = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- ") and current_key:
                # multiline array item
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
    meta["_file"] = str(filepath)
    return meta


def compute_tier(timestamp_str):
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "cold"
    now = datetime.now(timezone.utc)
    age = now - ts
    if age < timedelta(hours=HOT_HOURS):
        return "hot"
    if age < timedelta(days=WARM_DAYS):
        return "warm"
    return "cold"


def update_tier_in_file(filepath, new_tier):
    text = filepath.read_text(encoding="utf-8")
    updated = re.sub(r"^tier: .+$", f"tier: {new_tier}", text, count=1, flags=re.MULTILINE)
    if updated != text:
        filepath.write_text(updated, encoding="utf-8")
        return True
    return False


def compact_warm_entries(entries):
    """Group warm entries by agent, summarize with Claude API."""
    if not API_KEY:
        return
    by_agent = {}
    for e in entries:
        agent = e.get("agent", "unknown")
        by_agent.setdefault(agent, []).append(e)

    for agent, agent_entries in by_agent.items():
        if len(agent_entries) < 3:
            continue
        bodies = "\n\n".join(
            f"[{e.get('timestamp','')}] {e.get('type','')}: {e['_body'][:500]}"
            for e in agent_entries
        )
        prompt = (
            f"Compress these {len(agent_entries)} memory entries from agent '{agent}' "
            f"into one summary entry. Keep key facts, decisions, and cross-references. "
            f"Drop redundancy. Output only the summary body, no frontmatter.\n\n{bodies}"
        )
        summary = call_claude(
            "You are a memory curator. Compress multiple entries into one. "
            "Preserve facts, decisions, and references. Be concise.",
            prompt, 600
        )
        if not summary:
            continue

        # Write compacted entry, remove originals
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        refs = []
        tags = set()
        for e in agent_entries:
            refs.extend(e.get("refs", []) if isinstance(e.get("refs"), list) else [])
            t = e.get("tags", [])
            tags.update(t if isinstance(t, list) else [])

        import secrets
        suffix = secrets.token_hex(2)
        compacted = FABRIC_DIR / f"{agent}-compacted-{ts}-{suffix}.md"
        meta_lines = [
            "---",
            f"agent: {agent}",
            f"platform: multi",
            f"timestamp: {ts_iso}",
            f"type: compacted",
            f"tier: warm",
        ]
        if refs:
            meta_lines.append(f"refs: [{', '.join(refs)}]")
        if tags:
            meta_lines.append(f"tags: [{', '.join(tags)}]")
        meta_lines.append(f"summary: compacted {len(agent_entries)} entries")
        meta_lines.extend(["---", "", summary])
        compacted.write_text("\n".join(meta_lines), encoding="utf-8")

        # Atomic: only delete originals after compacted file is confirmed on disk
        if compacted.exists() and compacted.stat().st_size > 0:
            for e in agent_entries:
                Path(e["_file"]).unlink(missing_ok=True)
            print(f"  compacted {len(agent_entries)} warm entries for {agent}")
        else:
            print(f"  compaction write failed for {agent}, keeping originals")


def call_claude(system, prompt, max_tokens=800):
    import urllib.request
    body = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            if "content" in data and data["content"]:
                return data["content"][0]["text"]
    except Exception as e:
        print(f"  claude call failed: {e}", file=sys.stderr)
    return None


def build_index(entries):
    index = {
        "entries": [],
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    for e in entries:
        index["entries"].append({
            "file": os.path.basename(e["_file"]),
            "agent": e.get("agent", ""),
            "platform": e.get("platform", ""),
            "type": e.get("type", ""),
            "tier": e.get("tier", ""),
            "timestamp": e.get("timestamp", ""),
            "refs": e.get("refs", []),
            "tags": e.get("tags", []),
            "summary": e.get("summary", ""),
        })
    INDEX_FILE.write_text(json.dumps(index, indent=2), encoding="utf-8")


def run_once():
    FABRIC_DIR.mkdir(parents=True, exist_ok=True)
    COLD_DIR.mkdir(parents=True, exist_ok=True)

    files = list(FABRIC_DIR.glob("*.md"))
    if not files:
        print("curator: no entries")
        return

    entries = []
    warm_entries = []
    re_tiered = 0
    moved_cold = 0

    for f in files:
        e = parse_entry(f)
        if not e:
            continue
        new_tier = compute_tier(e.get("timestamp", ""))
        old_tier = e.get("tier", "")

        if new_tier != old_tier:
            update_tier_in_file(f, new_tier)
            e["tier"] = new_tier
            re_tiered += 1

        if new_tier == "cold":
            dest = COLD_DIR / f.name
            f.rename(dest)
            e["_file"] = str(dest)
            moved_cold += 1
        elif new_tier == "warm":
            warm_entries.append(e)

        entries.append(e)

    # Include existing cold entries in index
    for f in COLD_DIR.glob("*.md"):
        e = parse_entry(f)
        if e:
            entries.append(e)

    # Fallback: force-promote stale warm entries to cold even without API
    force_cold_cutoff = datetime.now(timezone.utc) - timedelta(days=FORCE_COLD_DAYS)
    for e in list(warm_entries):
        try:
            ts = datetime.fromisoformat(e.get("timestamp", "").replace("Z", "+00:00"))
            if ts < force_cold_cutoff:
                f = Path(e["_file"])
                if f.exists():
                    update_tier_in_file(f, "cold")
                    dest = COLD_DIR / f.name
                    f.rename(dest)
                    e["_file"] = str(dest)
                    e["tier"] = "cold"
                    warm_entries.remove(e)
                    moved_cold += 1
        except (ValueError, AttributeError):
            pass

    if warm_entries:
        compact_warm_entries(warm_entries)
        # Re-scan after compaction
        entries = []
        for f in FABRIC_DIR.glob("*.md"):
            e = parse_entry(f)
            if e:
                entries.append(e)
        for f in COLD_DIR.glob("*.md"):
            e = parse_entry(f)
            if e:
                entries.append(e)

    build_index(entries)
    print(f"curator: {len(entries)} entries, {re_tiered} re-tiered, {moved_cold} moved to cold")


if __name__ == "__main__":
    if "--once" in sys.argv or len(sys.argv) < 2:
        run_once()
    else:
        interval = 300  # 5 minutes
        print(f"curator: watching {FABRIC_DIR} every {interval}s")
        while True:
            run_once()
            time.sleep(interval)
