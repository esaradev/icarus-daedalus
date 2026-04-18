from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import select, desc, and_
from sqlalchemy.orm import Session as DBSession

from ..db import get_db
import time
from ..models import Agent, MemoryEntry, Event, Project, ProvenanceEdge, Recall
from ..schemas import (
    FleetOut, FleetCounts, FleetMetrics, AgentOut, EventOut, MemoryEntryOut,
    ProjectActivity, SourceDebugOut, SourceCountOut,
)
from sqlalchemy import func
from ..wiki import reader as wiki_reader, bridge as wiki_bridge

_STALE_CACHE: dict = {"at": 0.0, "value": None}


def _stale_count_cached(db) -> int:
    now = time.time()
    if _STALE_CACHE["value"] is not None and now - _STALE_CACHE["at"] < 60:
        return int(_STALE_CACHE["value"])
    try:
        health = corpus_health(db)
        count = health.get("stale_count", 0)
    except Exception:
        count = 0
    _STALE_CACHE["at"] = now
    _STALE_CACHE["value"] = count
    return count


from ..services import metrics as M
from ..maintenance.scorer import corpus_health

router = APIRouter(tags=["fleet"])


def _refresh_agent_status(a: Agent) -> None:
    if a.last_seen_at is None:
        a.status = "offline"
        return
    seen = a.last_seen_at if a.last_seen_at.tzinfo else a.last_seen_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - seen).total_seconds()
    if a.status == "blocked":
        return
    if age > 3600:
        a.status = "offline"
    elif age > 600:
        a.status = "stale"
    else:
        a.status = "healthy" if a.current_task else "idle"


@router.get("/fleet", response_model=FleetOut)
def fleet(db: DBSession = Depends(get_db)) -> FleetOut:
    agents = db.execute(select(Agent).order_by(Agent.name)).scalars().all()
    for a in agents:
        _refresh_agent_status(a)

    counts = Counter(a.status for a in agents)
    rate, sample = M.recall_success_rate(db)

    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    proj_rows = db.execute(
        select(MemoryEntry.project_id, func.count(MemoryEntry.id))
        .where(and_(
            MemoryEntry.created_at >= since_24h,
            MemoryEntry.project_id.is_not(None),
            MemoryEntry.project_id.notin_(["unknown", "backend", ""]),
        ))
        .group_by(MemoryEntry.project_id)
        .order_by(desc(func.count(MemoryEntry.id)))
        .limit(8)
    ).all()
    project_names = {p.id: p.name for p in db.execute(select(Project)).scalars().all()}
    projects = [
        ProjectActivity(
            project_id=pid,
            name=project_names.get(pid, pid),
            entries_24h=int(count),
        )
        for pid, count in proj_rows
    ]

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    promotions_today = db.scalar(
        select(func.count(ProvenanceEdge.id)).where(and_(
            ProvenanceEdge.relation == "promoted_from",
            ProvenanceEdge.created_at >= today_start,
        ))
    ) or 0
    highlights = db.execute(
        select(MemoryEntry)
        .where(and_(MemoryEntry.created_at >= today_start, MemoryEntry.kind == "decision"))
        .order_by(desc(MemoryEntry.reuse_count), desc(MemoryEntry.created_at))
        .limit(5)
    ).scalars().all()

    return FleetOut(
        agents=[AgentOut.model_validate(a) for a in agents],
        counts=FleetCounts(
            healthy=counts.get("healthy", 0),
            idle=counts.get("idle", 0),
            stale=counts.get("stale", 0),
            offline=counts.get("offline", 0),
            blocked=counts.get("blocked", 0),
        ),
        metrics=FleetMetrics(
            recall_success_rate=rate,
            recall_sample_size=sample,
            reuse_rate=M.reuse_rate(db),
            verification_rate=M.verification_rate(db),
            entries_today=M.entries_today(db),
            promotions_today=int(promotions_today),
            stale_knowledge_count=_stale_count_cached(db),
            contradiction_count=0,
            unresolved_handoffs=0,
        ),
        highlights=[MemoryEntryOut.model_validate(h, from_attributes=True) for h in highlights],
        projects=projects,
    )


@router.get("/fleet/activity")
def activity(limit: int = 50, db: DBSession = Depends(get_db)) -> list[EventOut]:
    rows = db.execute(
        select(Event, Agent.name)
        .outerjoin(Agent, Event.agent_id == Agent.id)
        .order_by(desc(Event.occurred_at))
        .limit(limit)
    ).all()
    out: list[EventOut] = []
    for evt, name in rows:
        out.append(EventOut(
            id=evt.id,
            agent_id=evt.agent_id,
            agent_name=name,
            session_id=evt.session_id,
            source=evt.source,
            kind=evt.kind,
            payload=evt.payload or {},
            occurred_at=evt.occurred_at,
        ))
    return out


@router.get("/debug/sources", response_model=SourceDebugOut)
def debug_sources(db: DBSession = Depends(get_db)) -> SourceDebugOut:
    def _rows(stmt) -> list[SourceCountOut]:
        return [
            SourceCountOut(source=str(src or "unknown"), count=int(count))
            for src, count in db.execute(stmt).all()
        ]

    agent_rows = db.execute(
        select(MemoryEntry.source, func.count(func.distinct(MemoryEntry.author_agent_id)))
        .where(MemoryEntry.author_agent_id.is_not(None))
        .group_by(MemoryEntry.source)
        .order_by(desc(func.count(func.distinct(MemoryEntry.author_agent_id))))
    ).all()

    return SourceDebugOut(
        agents=[SourceCountOut(source=str(src or "unknown"), count=int(count)) for src, count in agent_rows],
        events=_rows(
            select(Event.source, func.count(Event.id))
            .group_by(Event.source)
            .order_by(desc(func.count(Event.id)))
        ),
        memory_entries=_rows(
            select(MemoryEntry.source, func.count(MemoryEntry.id))
            .group_by(MemoryEntry.source)
            .order_by(desc(func.count(MemoryEntry.id)))
        ),
        recalls=_rows(
            select(Recall.source, func.count(Recall.id))
            .group_by(Recall.source)
            .order_by(desc(func.count(Recall.id)))
        ),
    )
