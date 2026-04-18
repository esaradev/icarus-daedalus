"""Scan ~/fabric/*.md and emit an events.jsonl the watcher can ingest.

Only entries newer than the max timestamp already in events.jsonl are appended,
so rerunning is safe and incremental.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
SCALAR_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$')

PREAMBLE_RE = re.compile(
    r"^(of course[!,.]?|sure[!,.]?|certainly[!,.]?|absolutely[!,.]?|"
    r"here('?s| is)|i'?d be happy to|i'?ll|let me|here are)\b[^.!?\n]*[.!?\n]",
    re.I,
)
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")

TYPE_TO_KIND = {
    "decision": "decision", "note": "observation", "task": "handoff",
    "session": "observation", "review": "review", "failure": "failure",
    "fix": "fix", "completion": "completion", "fact": "fact",
    "preference": "preference", "observation": "observation",
}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = FM_RE.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        sm = SCALAR_RE.match(line)
        if not sm:
            continue
        k, v = sm.group(1), sm.group(2).strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip('"') for x in v[1:-1].split(",") if x.strip()]
        meta[k] = v
    return meta, m.group(2)


def _latest_memory_write_ts_by_source(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    latest: dict[str, str] = {}
    with path.open() as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("type") != "memory.write":
                continue
            source_path = e.get("source_path")
            ts = e.get("at")
            if not source_path or not ts:
                continue
            prev = latest.get(str(source_path))
            if prev is None or str(ts) > prev:
                latest[str(source_path)] = str(ts)
    return latest


def _derive_title(summary, body: str) -> str:
    text = str(summary or "").strip() or (body or "")
    # drop LLM preambles like "Of course! ...", "Sure, here's ..."
    while True:
        m = PREAMBLE_RE.match(text.lstrip())
        if not m:
            break
        text = text[m.end():]
    text = text.lstrip()
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    first_sentence = SENTENCE_END_RE.split(first_line, 1)[0].strip()
    return (first_sentence or first_line or "(untitled)")[:140]


def _md_to_events(path: Path) -> list[dict]:
    text = path.read_text("utf-8", errors="replace")
    meta, body = _parse_frontmatter(text)
    if not meta:
        return []
    ts = meta.get("timestamp")
    if not ts:
        return []
    agent_id = str(meta.get("agent") or "agent").strip().lower().replace(" ", "-")
    agent_name = str(meta.get("agent") or "agent")
    platform = str(meta.get("platform") or "hermes")
    session_id = meta.get("session_id") or None
    project_id = meta.get("project_id") or None
    entry_type = str(meta.get("type") or "note").lower()
    kind = TYPE_TO_KIND.get(entry_type, "observation")
    summary = _derive_title(meta.get("summary"), body)

    evts: list[dict] = [
        {"type": "agent.status", "agent_id": agent_id, "name": agent_name,
         "platform": platform, "at": ts, "source": "fabric_backfill"},
    ]
    if project_id:
        evts.append({"type": "project", "project_id": project_id, "name": project_id, "source": "fabric_backfill"})
    if session_id:
        evts.append({"type": "session.start", "session_id": session_id,
                     "agent_id": agent_id, "project_id": project_id, "at": ts, "source": "fabric_backfill"})

    if entry_type in ("task", "review", "handoff", "failure", "fix", "completion"):
        evts.append({
            "type": "agent.event", "agent_id": agent_id, "session_id": session_id,
            "kind": kind, "payload": {"title": summary, "source_path": str(path)},
            "at": ts, "source": "fabric_backfill",
        })
    evts.append({
        "type": "memory.write", "agent_id": agent_id, "session_id": session_id,
        "project_id": project_id, "kind": kind, "title": summary,
        "body": body.strip(),
        "source_path": str(path),
        "at": ts, "source": "fabric_backfill",
    })
    return evts


def backfill(fabric_dir: Path, out_path: Path) -> int:
    latest_by_source = _latest_memory_write_ts_by_source(out_path)
    files = sorted(fabric_dir.glob("*.md"))
    written = 0
    with out_path.open("a", encoding="utf-8") as out:
        for md in files:
            try:
                events = _md_to_events(md)
            except Exception as e:
                print(f"[backfill] skip {md.name}: {e}")
                continue
            entry_ts = next((e.get("at") for e in events if e.get("type") == "memory.write"), None)
            last_seen = latest_by_source.get(str(md))
            if last_seen and entry_ts and entry_ts <= last_seen:
                continue
            for e in events:
                out.write(json.dumps(e, ensure_ascii=False) + "\n")
                written += 1
            if entry_ts:
                latest_by_source[str(md)] = str(entry_ts)
    return written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fabric", default=str(Path.home() / "fabric"))
    ap.add_argument("--out", default=str(Path.home() / "fabric" / "events.jsonl"))
    args = ap.parse_args()
    n = backfill(Path(args.fabric), Path(args.out))
    print(f"[backfill] appended {n} events to {args.out}")


if __name__ == "__main__":
    main()
