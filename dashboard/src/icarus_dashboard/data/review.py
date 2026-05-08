"""Review-queue detectors.

Each detector is a pure read against substrate data — no schema changes,
no new endpoints in icarus-memory. Resolutions and dismissals are recorded
as ordinary entries (type=review_resolved / review_dismissed) so the audit
trail lives in the same store as everything else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from icarus_memory import IcarusMemory

STALE_AFTER = timedelta(days=90)
DISCONNECTED_AFTER = timedelta(days=30)

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

KIND_LABEL = {
    "contradiction": "contradiction",
    "stale": "stale",
    "unsourced": "unsourced",
    "disconnected": "disconnected",
    "sync_failure": "sync.failure",
    "briefing_error": "briefing.error",
}

KIND_GROUPS = (
    ("Contradictions", "contradiction"),
    ("Stale facts", "stale"),
    ("Unsourced memories", "unsourced"),
    ("Disconnected agents", "disconnected"),
    ("Sync failures", "sync_failure"),
    ("Briefing errors", "briefing_error"),
)


@dataclass
class Issue:
    id: str
    kind: str
    severity: str
    summary: str
    target_id: str
    target_kind: str
    detail: dict[str, Any]
    created_at: datetime
    age_days: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def _age_days(ts: datetime) -> int:
    return max(0, (_now() - _to_utc(ts)).days)


def get_resolved_issue_ids(memory: IcarusMemory) -> set[str]:
    out: set[str] = set()
    for entry in memory.store.iter_entries():
        if entry.type not in ("review_resolved", "review_dismissed"):
            continue
        for ev in entry.evidence:
            if ev.ref.startswith("review:"):
                out.add(ev.ref[len("review:"):])
    return out


def find_contradictions(memory: IcarusMemory) -> list[Issue]:
    issues: list[Issue] = []
    for entry in memory.store.iter_entries():
        if entry.verified != "contradicted":
            continue
        last = entry.verification_log[-1] if entry.verification_log else None
        issues.append(
            Issue(
                id=f"contradiction:{entry.id}",
                kind="contradiction",
                severity="high",
                summary=entry.summary,
                target_id=entry.id,
                target_kind="entry",
                detail={
                    "agent": entry.agent,
                    "type": entry.type,
                    "body": entry.body,
                    "contradicted_by": entry.contradicted_by,
                    "reason": last.note if last else "",
                },
                created_at=_to_utc(entry.timestamp),
                age_days=_age_days(entry.timestamp),
            )
        )
    return issues


def find_stale(memory: IcarusMemory) -> list[Issue]:
    cutoff = _now() - STALE_AFTER
    issues: list[Issue] = []
    for entry in memory.store.iter_entries():
        if entry.lifecycle != "active":
            continue
        if entry.type in ("review_resolved", "review_dismissed"):
            continue
        if _to_utc(entry.timestamp) >= cutoff:
            continue
        if entry.verification_log:
            continue
        issues.append(
            Issue(
                id=f"stale:{entry.id}",
                kind="stale",
                severity="medium",
                summary=entry.summary,
                target_id=entry.id,
                target_kind="entry",
                detail={
                    "agent": entry.agent,
                    "type": entry.type,
                    "body": entry.body,
                    "no_verification": True,
                },
                created_at=_to_utc(entry.timestamp),
                age_days=_age_days(entry.timestamp),
            )
        )
    return issues


def find_unsourced(memory: IcarusMemory) -> list[Issue]:
    issues: list[Issue] = []
    for entry in memory.store.iter_entries():
        if entry.lifecycle != "active":
            continue
        if entry.evidence:
            continue
        if entry.source_tool:
            continue
        if entry.type in ("review_resolved", "review_dismissed"):
            continue
        issues.append(
            Issue(
                id=f"unsourced:{entry.id}",
                kind="unsourced",
                severity="low",
                summary=entry.summary,
                target_id=entry.id,
                target_kind="entry",
                detail={
                    "agent": entry.agent,
                    "type": entry.type,
                    "body": entry.body,
                },
                created_at=_to_utc(entry.timestamp),
                age_days=_age_days(entry.timestamp),
            )
        )
    return issues


def find_disconnected_agents(memory: IcarusMemory) -> list[Issue]:
    cutoff = _now() - DISCONNECTED_AFTER
    agents_root = memory.root / ".icarus" / "agents"
    if not agents_root.exists():
        return []
    issues: list[Issue] = []
    for agent_dir in agents_root.iterdir():
        if not agent_dir.is_dir():
            continue
        sessions_dir = agent_dir / "sessions"
        if not sessions_dir.exists():
            continue
        sessions = list(sessions_dir.glob("*.json"))
        if not sessions:
            continue
        latest_mtime = max(s.stat().st_mtime for s in sessions)
        latest = datetime.fromtimestamp(latest_mtime, tz=timezone.utc)
        if latest >= cutoff:
            continue
        issues.append(
            Issue(
                id=f"disconnected:{agent_dir.name}",
                kind="disconnected",
                severity="medium",
                summary=f"{agent_dir.name} last active {_age_days(latest)} days ago",
                target_id=agent_dir.name,
                target_kind="agent",
                detail={
                    "session_count": len(sessions),
                    "last_session_at": latest.isoformat(),
                },
                created_at=latest,
                age_days=_age_days(latest),
            )
        )
    return issues


def find_briefing_errors(memory: IcarusMemory) -> list[Issue]:
    briefings_root = memory.root / ".icarus" / "briefings"
    if not briefings_root.exists():
        return []
    issues: list[Issue] = []
    for path in briefings_root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("source_ids") or data.get("page_paths"):
            continue
        ts_raw = data.get("created_at") or ""
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            ts = _now()
        cache_key = data.get("cache_key", path.stem)
        agent_id = data.get("agent_id", "unknown")
        issues.append(
            Issue(
                id=f"briefing_error:{cache_key}",
                kind="briefing_error",
                severity="low",
                summary=f"Briefing for {agent_id}: nothing matched",
                target_id=cache_key,
                target_kind="briefing",
                detail={
                    "agent_id": agent_id,
                    "task_description": data.get("task_description"),
                    "content": data.get("content"),
                    "path": str(path),
                },
                created_at=ts,
                age_days=_age_days(ts),
            )
        )
    return issues


def all_issues(memory: IcarusMemory) -> list[Issue]:
    found: list[Issue] = []
    found.extend(find_contradictions(memory))
    found.extend(find_stale(memory))
    found.extend(find_unsourced(memory))
    found.extend(find_disconnected_agents(memory))
    found.extend(find_briefing_errors(memory))
    resolved = get_resolved_issue_ids(memory)
    open_issues = [i for i in found if i.id not in resolved]
    open_issues.sort(key=lambda i: (SEVERITY_RANK[i.severity], -i.age_days))
    return open_issues


def find_issue(memory: IcarusMemory, issue_id: str) -> Issue | None:
    for issue in all_issues(memory):
        if issue.id == issue_id:
            return issue
    if issue_id == "sync_failure:placeholder":
        return Issue(
            id=issue_id,
            kind="sync_failure",
            severity="low",
            summary="No substrate signal yet",
            target_id="",
            target_kind="na",
            detail={},
            created_at=_now(),
            age_days=0,
        )
    return None


def write_marker(
    memory: IcarusMemory, issue: Issue, *, action: str
) -> None:
    """Write a review_resolved or review_dismissed entry against an issue."""
    memory.write(
        agent="dashboard",
        type=f"review_{action}",
        summary=f"{action} {issue.kind}: {issue.summary[:140]}",
        evidence=[{"kind": "message", "ref": f"review:{issue.id}"}],
        source_tool="icarus-dashboard",
    )
