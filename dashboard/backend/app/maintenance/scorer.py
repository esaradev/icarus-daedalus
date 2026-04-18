"""Quality scoring for memory entries using DB models."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session as DBSession

from ..models import MemoryEntry, Recall


def _age_days(dt: datetime | None) -> float:
    if dt is None:
        return 999.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)


def score_entry(entry: MemoryEntry, recall_count: int = 0) -> dict[str, float]:
    recency = math.exp(-_age_days(entry.created_at) / 60)
    reuse = min(math.log1p(entry.reuse_count or 0) / math.log1p(10), 1.0)
    recall_signal = min(recall_count / 5, 1.0)
    trust = 1.0 if entry.verified_at else 0.3
    richness = 0.2

    total = 0.30 * recency + 0.25 * recall_signal + 0.20 * reuse + 0.15 * trust + 0.10 * richness
    return {
        "quality": round(total, 3),
        "recency": round(recency, 3),
        "recall_signal": round(recall_signal, 3),
        "reuse": round(reuse, 3),
        "trust": round(trust, 3),
        "age_days": round(_age_days(entry.created_at), 1),
    }


def recall_counts_for_entries(db: DBSession, entry_ids: list[int]) -> dict[int, int]:
    if not entry_ids:
        return {}
    rows = db.execute(select(Recall)).scalars().all()
    counts: dict[int, int] = {}
    for r in rows:
        for eid in (r.returned_entry_ids or []):
            try:
                eid = int(eid)
            except (TypeError, ValueError):
                continue
            if eid in entry_ids:
                counts[eid] = counts.get(eid, 0) + 1
    return counts


def corpus_health(db: DBSession) -> dict:
    entries = db.execute(select(MemoryEntry).order_by(MemoryEntry.created_at.desc()).limit(500)).scalars().all()
    if not entries:
        return {"total": 0, "quality_avg": 0.0, "stale_count": 0, "healthy_count": 0, "distribution": []}

    eids = [e.id for e in entries]
    rcounts = recall_counts_for_entries(db, eids)

    scores = [score_entry(e, rcounts.get(e.id, 0)) for e in entries]
    qualities = [s["quality"] for s in scores]

    buckets = [0] * 5
    for q in qualities:
        idx = min(int(q * 5), 4)
        buckets[idx] += 1

    stale = sum(1 for q in qualities if q < 0.2)
    healthy = sum(1 for q in qualities if q >= 0.5)

    return {
        "total": len(entries),
        "quality_avg": round(sum(qualities) / len(qualities), 3),
        "stale_count": stale,
        "healthy_count": healthy,
        "distribution": [
            {"range": "0.0-0.2", "count": buckets[0]},
            {"range": "0.2-0.4", "count": buckets[1]},
            {"range": "0.4-0.6", "count": buckets[2]},
            {"range": "0.6-0.8", "count": buckets[3]},
            {"range": "0.8-1.0", "count": buckets[4]},
        ],
    }
