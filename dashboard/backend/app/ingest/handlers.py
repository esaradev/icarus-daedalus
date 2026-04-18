from __future__ import annotations

from datetime import datetime, timezone
from dateutil import parser as dateparser
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select

from ..models import (
    Agent, Session as SessionRow, Event, MemoryEntry, Recall,
    ProvenanceEdge, Project,
)


def _nn(v):
    """Normalize empty strings to None for FK-safe inserts."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _source(evt: dict, default: str = "events_jsonl") -> str:
    return _nn(evt.get("source")) or default


def _parse_ts(v) -> datetime:
    if v is None:
        return datetime.now(timezone.utc)
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return dateparser.parse(str(v))


def _upsert_agent(db: DBSession, agent_id: str, **fields) -> Agent:
    row = db.get(Agent, agent_id)
    if row is None:
        row = Agent(id=agent_id, name=fields.get("name") or agent_id)
        db.add(row)
    for k, v in fields.items():
        if v is not None and hasattr(row, k):
            setattr(row, k, v)
    return row


def _derive_status(last_seen: datetime | None, current_task: str | None, explicit: str | None) -> str:
    if explicit in ("blocked", "offline"):
        return explicit
    if last_seen is None:
        return "offline"
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - last_seen).total_seconds()
    if age > 3600:
        return "offline"
    if age > 600:
        return "stale"
    return "healthy" if current_task else "idle"


def handle_agent_status(db: DBSession, evt: dict) -> None:
    aid = evt["agent_id"]
    last_seen = _parse_ts(evt.get("at"))
    task = evt.get("current_task")
    explicit = evt.get("status")
    status = _derive_status(last_seen, task, explicit)
    _upsert_agent(
        db, aid,
        name=evt.get("name"),
        platform=evt.get("platform"),
        current_task=task,
        last_seen_at=last_seen,
        status=status,
    )


def handle_agent_event(db: DBSession, evt: dict) -> None:
    db.add(Event(
        agent_id=_nn(evt.get("agent_id")),
        session_id=_nn(evt.get("session_id")),
        source=_source(evt),
        kind=evt.get("kind", "observation"),
        payload=evt.get("payload") or {},
        occurred_at=_parse_ts(evt.get("at")),
    ))


def handle_session_start(db: DBSession, evt: dict) -> None:
    sid = _nn(evt.get("session_id"))
    if sid is None:
        return
    row = db.get(SessionRow, sid)
    if row is None:
        row = SessionRow(
            id=sid,
            agent_id=_nn(evt.get("agent_id")),
            project_id=_nn(evt.get("project_id")),
            started_at=_parse_ts(evt.get("at")),
            summary=evt.get("summary"),
        )
        db.add(row)


def handle_session_end(db: DBSession, evt: dict) -> None:
    sid = _nn(evt.get("session_id"))
    if sid is None:
        return
    row = db.get(SessionRow, sid)
    if row is None:
        return
    row.ended_at = _parse_ts(evt.get("at"))
    if evt.get("summary"):
        row.summary = evt["summary"]


def handle_memory_write(db: DBSession, evt: dict) -> None:
    sid = _nn(evt.get("session_id"))
    pid = _nn(evt.get("project_id"))
    if sid and db.get(SessionRow, sid) is None:
        sid = None
    if pid and db.get(Project, pid) is None:
        db.add(Project(id=pid, name=pid))
        db.flush()
    source_path = _nn(evt.get("source_path"))
    existing = None
    if source_path:
        existing = db.execute(
            select(MemoryEntry).where(MemoryEntry.source_path == source_path)
        ).scalar_one_or_none()
    if existing is not None:
        existing.title = evt.get("title") or existing.title
        existing.body = evt.get("body") or existing.body
        existing.updated_at = _parse_ts(evt.get("at"))
        existing.source = _source(evt)
        entry = existing
    else:
        entry = MemoryEntry(
            author_agent_id=_nn(evt.get("agent_id")),
            session_id=sid,
            project_id=pid,
            kind=evt.get("kind", "observation"),
            source=_source(evt),
            title=evt.get("title") or "(untitled)",
            body=evt.get("body") or "",
            source_path=source_path,
            created_at=_parse_ts(evt.get("at")),
            updated_at=_parse_ts(evt.get("at")),
        )
        db.add(entry)
        db.flush()
    db.add(Event(
        agent_id=entry.author_agent_id,
        session_id=entry.session_id,
        source=_source(evt),
        kind="write",
        payload={"entry_id": entry.id, "title": entry.title, "kind": entry.kind},
        occurred_at=entry.created_at,
    ))


def _apply_recall_effects(db: DBSession, recall: Recall, returned: list[int]) -> None:
    if not returned:
        return
    db.query(MemoryEntry).filter(MemoryEntry.id.in_(returned)).update(
        {MemoryEntry.reuse_count: MemoryEntry.reuse_count + 1},
        synchronize_session=False,
    )
    for eid in returned:
        db.add(ProvenanceEdge(
            src_type="recall", src_id=str(recall.id),
            dst_type="memory_entry", dst_id=str(eid),
            relation="recalled_in",
        ))


def handle_memory_recall(db: DBSession, evt: dict) -> None:
    sid = _nn(evt.get("session_id"))
    if sid and db.get(SessionRow, sid) is None:
        sid = None

    returned = evt.get("returned_entry_ids") or []
    paths = evt.get("returned_source_paths") or []
    resolved: list[int] = []
    for raw in returned:
        try:
            resolved.append(int(raw))
        except (TypeError, ValueError):
            continue
    if paths:
        rows = db.execute(
            select(MemoryEntry.id).where(MemoryEntry.source_path.in_([str(p) for p in paths]))
        ).all()
        resolved.extend(int(r[0]) for r in rows)
    resolved = list(dict.fromkeys(resolved))

    recall = Recall(
        agent_id=_nn(evt.get("agent_id")),
        session_id=sid,
        source=_source(evt),
        query=evt.get("query") or "",
        returned_entry_ids=resolved,
        was_useful=evt.get("was_useful"),
        created_at=_parse_ts(evt.get("at")),
    )
    db.add(recall)
    db.flush()
    _apply_recall_effects(db, recall, resolved)
    db.add(Event(
        agent_id=recall.agent_id,
        session_id=recall.session_id,
        source=_source(evt),
        kind="recall",
        payload={"query": recall.query, "count": len(resolved), "was_useful": recall.was_useful},
        occurred_at=recall.created_at,
    ))


def handle_memory_verify(db: DBSession, evt: dict) -> None:
    eid = int(evt["entry_id"])
    entry = db.get(MemoryEntry, eid)
    if entry is None:
        return
    entry.verified_at = _parse_ts(evt.get("at"))


def handle_memory_cite(db: DBSession, evt: dict) -> None:
    db.add(ProvenanceEdge(
        src_type="memory_entry", src_id=str(evt["src_id"]),
        dst_type="memory_entry", dst_id=str(evt["dst_id"]),
        relation="cites",
    ))


def handle_project(db: DBSession, evt: dict) -> None:
    pid = evt["project_id"]
    row = db.get(Project, pid)
    if row is None:
        db.add(Project(id=pid, name=evt.get("name") or pid, description=evt.get("description")))


def handle_wiki_promotion(db: DBSession, evt: dict) -> None:
    mem_id = evt.get("memory_entry_id")
    slug = _nn(evt.get("page_slug"))
    if mem_id is None or slug is None:
        return
    existing = db.execute(
        select(ProvenanceEdge).where(
            ProvenanceEdge.src_type == "memory_entry",
            ProvenanceEdge.src_id == str(mem_id),
            ProvenanceEdge.dst_type == "wiki_page",
            ProvenanceEdge.dst_id == slug,
            ProvenanceEdge.relation == "promoted_from",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    db.add(ProvenanceEdge(
        src_type="memory_entry", src_id=str(mem_id),
        dst_type="wiki_page", dst_id=slug,
        relation="promoted_from",
        created_at=_parse_ts(evt.get("at")),
    ))


DISPATCH = {
    "agent.status": handle_agent_status,
    "agent.event": handle_agent_event,
    "session.start": handle_session_start,
    "session.end": handle_session_end,
    "memory.write": handle_memory_write,
    "memory.recall": handle_memory_recall,
    "memory.verify": handle_memory_verify,
    "memory.cite": handle_memory_cite,
    "project": handle_project,
    "wiki.promotion": handle_wiki_promotion,
}


def dispatch(db: DBSession, evt: dict) -> bool:
    kind = evt.get("type")
    fn = DISPATCH.get(kind)
    if fn is None:
        return False
    fn(db, evt)
    return True
