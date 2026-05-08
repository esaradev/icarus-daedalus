"""Activity view — live filesystem-derived event stream.

The reads-not-logged banner ships with the view as a design feature, not a
gap: the substrate doesn't emit read events at the filesystem layer, so
the banner names that explicitly. Briefings *imply* reads of their source
ids and page paths; that's surfaced by the Briefings filter, not by a
fabricated 'reads' kind.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timezone
from typing import Any

from fasthtml.common import (
    A,
    Button,
    Div,
    P,
    Pre,
    Script,
    Span,
    sse_message,
    to_xml,
)

from ..data.activity import Event, bus
from ..data.memory import fabric_exists, fabric_root
from ..layout import shell

KIND_LABEL = {
    "write": "write",
    "edit": "edit",
    "session_start": "session.start",
    "session_end": "session.end",
    "archive": "archive",
    "briefing": "briefing",
    "wiki_edit": "wiki.edit",
}

KIND_GROUPS = (
    ("Writes", "write,edit"),
    ("Sessions", "session_start,session_end"),
    ("Archives", "archive"),
    ("Briefings", "briefing"),
    ("Wiki edits", "wiki_edit"),
)


def _hms(ts) -> str:
    return ts.astimezone(timezone.utc).strftime("%H:%M:%S")


def _full_ts(ts) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _summary_for(ev: Event) -> str:
    payload = ev.payload or {}
    text = (
        payload.get("summary")
        or payload.get("task_description")
        or payload.get("final_summary")
        or ev.target
    )
    text = str(text)
    return text[:80] + ("…" if len(text) > 80 else "")


def event_row(ev: Event, *, active: bool = False) -> Any:
    return A(
        Div(
            Span(KIND_LABEL.get(ev.kind, ev.kind), cls="badge"),
            " ",
            Span(ev.agent or "—", cls="mono muted"),
            cls="title",
        ),
        Div(
            Span(_hms(ev.ts), cls="mono"),
            " ",
            Span(_summary_for(ev), cls="muted"),
            cls="meta",
        ),
        href=f"/activity/event/{ev.id}",
        cls=f"list-item event-row{' active' if active else ''}",
        data_kind=ev.kind,
        data_agent=ev.agent or "",
    )


def _missing_fabric_pane() -> Any:
    return Div(
        P(
            "No fabric found at ",
            Span(str(fabric_root()), cls="mono"),
            ". Set ",
            Span("ICARUS_FABRIC_ROOT", cls="mono"),
            " before starting the dashboard.",
        ),
        cls="empty-state",
    )


def _reads_banner() -> Any:
    return Div(
        Span("Reads aren't directly observable. ", cls="muted"),
        "The substrate does not log read events at the filesystem layer. The ",
        Span("Briefings", cls="mono"),
        " filter shows briefing events, each of which implies reads of its ",
        Span("source_ids", cls="mono"),
        " and ",
        Span("page_paths", cls="mono"),
        ". Direct read tracking would be a substrate change, not a dashboard change.",
        cls="banner",
    )


def _filters(events: list[Event]) -> Any:
    kind_counts: dict[str, int] = {}
    agents: dict[str, int] = {}
    for ev in events:
        kind_counts[ev.kind] = kind_counts.get(ev.kind, 0) + 1
        if ev.agent:
            agents[ev.agent] = agents.get(ev.agent, 0) + 1

    def group_count(kinds: str) -> int:
        return sum(kind_counts.get(k, 0) for k in kinds.split(","))

    kind_filters = [
        Div(
            label,
            Span(str(group_count(kinds)), cls="count"),
            cls="nav-filter",
            data_filter_kinds=kinds,
            role="button",
        )
        for label, kinds in KIND_GROUPS
    ]
    kind_filters.append(
        Div(
            "Reads ",
            Span("inferred", cls="count"),
            cls="nav-filter",
            title="Reads aren't logged. Inferred from briefings.",
        )
    )

    agent_rows: list[Any]
    if agents:
        agent_rows = [
            Div(
                name,
                Span(str(count), cls="count"),
                cls="nav-filter",
                data_filter_agent=name,
                role="button",
            )
            for name, count in sorted(agents.items(), key=lambda kv: kv[0])
        ]
    else:
        agent_rows = [Div("(no agents yet)", cls="nav-filter muted")]

    return Div(
        Div("event types", cls="nav-section"),
        Div(*kind_filters, cls="nav-filters"),
        Div("agents", cls="nav-section"),
        Div(*agent_rows, cls="nav-filters"),
    )


def _detail_pane(ev: Event | None) -> Any:
    if ev is None:
        return Div(
            Div(Span("Select an event", cls="detail-title"), cls="detail-header"),
            Div(
                P(
                    "Pick an event on the left, or wait for new ones.",
                    cls="muted",
                ),
                cls="empty-state",
            ),
        )
    payload_text = (
        json.dumps(ev.payload, indent=2, default=str) if ev.payload else "—"
    )
    return Div(
        Div(
            Div(
                Span(KIND_LABEL.get(ev.kind, ev.kind), cls="detail-title"),
                Div(
                    Span(_full_ts(ev.ts), cls="mono muted"),
                    " · ",
                    Span(ev.agent or "—", cls="mono muted"),
                    " · ",
                    Span(ev.target, cls="mono muted"),
                    cls="detail-meta",
                ),
            ),
            cls="detail-header",
        ),
        Div(
            Div("Payload", cls="entry-group-label"),
            Pre(payload_text, cls="payload-block"),
            Div("Path", cls="entry-group-label"),
            Pre(ev.path, cls="payload-block"),
            cls="detail-body",
        ),
    )


async def page(active_event_id: str | None = None) -> Any:
    if not fabric_exists():
        return shell(
            active="activity",
            title="Activity",
            list_pane=_missing_fabric_pane(),
            detail_pane=Div(),
        )
    await bus.ensure_started(fabric_root())
    events = sorted(bus.recent(), key=lambda e: e.ts, reverse=True)
    rows = [
        event_row(ev, active=ev.id == active_event_id) for ev in events
    ]
    list_pane = Div(
        _reads_banner(),
        Div(
            Span("Activity", cls="list-title"),
            Div(
                Span(f"{len(events)} events", cls="list-meta"),
                " ",
                Button("Pause", id="pause-btn", cls="action"),
                cls="list-meta-row",
            ),
            cls="list-header",
        ),
        Div(*rows, id="activity-list", cls="activity-list"),
        Script(src="/activity.js", defer=""),
    )
    target = bus.get(active_event_id) if active_event_id else None
    return shell(
        active="activity",
        title="Activity",
        filters=_filters(events),
        list_pane=list_pane,
        detail_pane=_detail_pane(target),
    )


async def stream() -> AsyncIterator[str]:
    await bus.ensure_started(fabric_root())
    async with bus.subscriber() as q:
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=20)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            payload = json.dumps(
                {
                    "id": ev.id,
                    "kind": ev.kind,
                    "agent": ev.agent or "",
                    "html": to_xml(event_row(ev)),
                }
            )
            yield sse_message(payload)
