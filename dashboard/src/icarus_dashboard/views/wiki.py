"""Wiki view — pages grouped by page_type, structured entry detail."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from fasthtml.common import (
    A,
    Button,
    Details,
    Div,
    Form,
    Input,
    Label,
    Li,
    P,
    Span,
    Summary,
    Sup,
    Textarea,
    Ul,
)
from icarus_memory import Entry, IcarusMemory, WikiPage
from icarus_memory.exceptions import EntryNotFound

from ..data.memory import fabric_exists, fabric_root, get_memory
from ..layout import shell

PAGE_TYPE_LABELS = {
    "decision": "Decisions",
    "topic": "Topics",
    "project": "Projects",
    "agent": "Agents",
    "uncategorized": "Uncategorized",
}
PAGE_TYPE_ORDER = ("decision", "topic", "project", "agent", "uncategorized")


def _utc_short(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _verified_glyph(entry: Entry) -> str:
    if entry.verified == "verified":
        return "✓"
    if entry.verified == "contradicted":
        return "✗"
    if entry.verified == "rolled_back":
        return "↺"
    return "·"


def _missing_fabric_pane() -> Any:
    return Div(
        P(
            "No fabric found at ",
            Span(str(fabric_root()), cls="mono"),
            ". Set ",
            Span("ICARUS_FABRIC_ROOT", cls="mono"),
            " to a directory containing a ",
            Span(".icarus/", cls="mono"),
            " tree, or run icarus-memory once to seed the default location.",
        ),
        cls="empty-state",
    )


def _filters(memory: IcarusMemory) -> Any:
    counts: dict[str, int] = defaultdict(int)
    for page in memory.wiki.iter_pages():
        counts[page.page_type] += 1
    rows = [
        Div(
            PAGE_TYPE_LABELS[pt],
            Span(str(counts.get(pt, 0)), cls="count"),
            cls="nav-filter",
        )
        for pt in PAGE_TYPE_ORDER
    ]
    return Div(
        Div("page types", cls="nav-section"),
        Div(*rows, cls="nav-filters"),
    )


def _list_pane(memory: IcarusMemory, active_path: str | None) -> Any:
    pages = sorted(
        memory.wiki.iter_pages(), key=lambda p: p.updated_at, reverse=True
    )
    header = Div(
        Span("Wiki", cls="list-title"),
        Span(f"{len(pages)} pages", cls="list-meta"),
        cls="list-header",
    )
    if not pages:
        return Div(
            header,
            Div(P("No wiki pages yet."), cls="empty-state"),
        )
    grouped: dict[str, list[WikiPage]] = defaultdict(list)
    for page in pages:
        grouped[page.page_type].append(page)
    sections = []
    for pt in PAGE_TYPE_ORDER:
        bucket = grouped.get(pt) or []
        if not bucket:
            continue
        items = []
        for page in bucket:
            href = f"/wiki/page/{quote(page.path, safe='/')}"
            items.append(
                A(
                    Div(page.title, cls="title"),
                    Div(
                        Span(_utc_short(page.updated_at), cls="mono"),
                        Span(page.page_type, cls="badge"),
                        cls="meta",
                    ),
                    href=href,
                    cls=f"list-item{' active' if page.path == active_path else ''}",
                )
            )
        sections.append(
            Details(
                Summary(
                    f"{PAGE_TYPE_LABELS[pt]} ({len(bucket)})",
                    cls="list-section-summary",
                ),
                *items,
                open="",
                cls="list-section",
            )
        )
    return Div(header, *sections)


def _entry_row(entry: Entry, idx: int) -> Any:
    evidence = ", ".join(ev.ref for ev in entry.evidence) or "none"
    title = f"by {entry.agent} at {entry.timestamp.isoformat()}"
    return Div(
        Div(
            Span(_verified_glyph(entry), cls="glyph"),
            " ",
            Span(entry.id, cls="mono muted"),
            " ",
            Span(entry.summary),
            cls="entry-row-head",
        ),
        Div(
            Span(f"by {entry.agent}", cls="muted"),
            " · ",
            Span(_utc_short(entry.timestamp), cls="mono muted"),
            " · ",
            Span(f"evidence: {evidence}", cls="muted"),
            " ",
            A(Sup(str(idx)), href=f"#fn-{idx}", cls="footnote-ref", title=title),
            cls="entry-row-meta",
        ),
        cls="entry-row",
    )


def _detail_pane(
    memory: IcarusMemory, page: WikiPage | None, active_path: str | None
) -> Any:
    if page is None:
        if active_path:
            return Div(
                Div(
                    Span("Page not found", cls="detail-title"),
                    cls="detail-header",
                ),
                Div(
                    P(f"No wiki page at {active_path}.", cls="muted"),
                    cls="empty-state",
                ),
            )
        return Div(
            Div(Span("Select a page", cls="detail-title"), cls="detail-header"),
            Div(P("Pick a page on the left.", cls="muted"), cls="empty-state"),
        )

    entries: list[Entry] = []
    for eid in page.entries:
        try:
            entries.append(memory.get(eid))
        except EntryNotFound:
            continue

    active_entries = [e for e in entries if e.lifecycle != "superseded"]
    superseded_entries = [e for e in entries if e.lifecycle == "superseded"]

    body_parts: list[Any] = []
    if active_entries:
        body_parts.append(
            Div(f"Active ({len(active_entries)})", cls="entry-group-label")
        )
        for i, entry in enumerate(active_entries, start=1):
            body_parts.append(_entry_row(entry, i))
    if superseded_entries:
        offset = len(active_entries)
        body_parts.append(
            Details(
                Summary(
                    f"Show {len(superseded_entries)} superseded",
                    cls="superseded-summary",
                ),
                *[
                    _entry_row(entry, offset + i)
                    for i, entry in enumerate(superseded_entries, start=1)
                ],
                cls="superseded-toggle",
            )
        )
    if not entries:
        body_parts.append(P("No entries linked to this page yet.", cls="muted"))

    if entries:
        fns = []
        for i, entry in enumerate(entries, start=1):
            fns.append(
                Li(
                    f"entry {entry.id} by {entry.agent} at {_utc_short(entry.timestamp)}",
                    id=f"fn-{i}",
                )
            )
        body_parts.append(
            Div(
                Div("Provenance", cls="footnotes-label"),
                Ul(*fns, cls="footnotes"),
                cls="footnotes-block",
            )
        )

    append_href = f"/wiki/page/{quote(page.path, safe='/')}/append"
    return Div(
        Div(
            Div(
                Span(page.title, cls="detail-title"),
                Div(
                    Span(page.path, cls="mono muted"),
                    " · ",
                    Span(f"updated {_utc_short(page.updated_at)}", cls="mono muted"),
                    " · ",
                    Span(f"{len(entries)} entries", cls="muted"),
                    cls="detail-meta",
                ),
            ),
            Div(
                A("Append or Supersede", href=append_href, cls="action primary"),
                cls="action-row",
            ),
            cls="detail-header",
        ),
        Div(*body_parts, cls="detail-body"),
    )


def page(active_path: str | None = None) -> Any:
    if not fabric_exists():
        return shell(
            active="wiki",
            title="Wiki",
            list_pane=_missing_fabric_pane(),
            detail_pane=Div(),
        )
    memory = get_memory()
    target = memory.wiki.get_page(active_path) if active_path else None
    return shell(
        active="wiki",
        title="Wiki",
        filters=_filters(memory),
        list_pane=_list_pane(memory, active_path),
        detail_pane=_detail_pane(memory, target, active_path),
    )


def append_form(active_path: str) -> Any:
    if not fabric_exists():
        return shell(
            active="wiki",
            title="Wiki",
            list_pane=_missing_fabric_pane(),
            detail_pane=Div(),
        )
    memory = get_memory()
    target = memory.wiki.get_page(active_path)
    cancel_href = f"/wiki/page/{quote(active_path, safe='/')}"
    if target is None:
        return shell(
            active="wiki",
            title="Wiki",
            list_pane=_list_pane(memory, active_path),
            detail_pane=Div(
                P(f"No page at {active_path}.", cls="muted"),
                cls="empty-state",
            ),
        )
    form = Form(
        Div(
            Label("Agent", For="agent"),
            Input(name="agent", id="agent", required="", value="dashboard"),
            cls="form-row",
        ),
        Div(
            Label("Type", For="type"),
            Input(name="type", id="type", required="", value="note"),
            cls="form-row",
        ),
        Div(
            Label("Summary", For="summary"),
            Input(
                name="summary", id="summary", required="", maxlength="200"
            ),
            cls="form-row",
        ),
        Div(
            Label("Body", For="body"),
            Textarea(name="body", id="body", rows="8"),
            cls="form-row",
        ),
        Div(
            Button("Append entry", type="submit", cls="action primary"),
            A("Cancel", href=cancel_href, cls="action"),
            cls="action-row",
        ),
        method="post",
        action=f"/wiki/page/{quote(active_path, safe='/')}/append",
        cls="form",
    )
    return shell(
        active="wiki",
        title="Wiki",
        filters=_filters(memory),
        list_pane=_list_pane(memory, active_path),
        detail_pane=Div(
            Div(
                Div(
                    Span(f"Append to {target.title}", cls="detail-title"),
                    Div(
                        Span(target.path, cls="mono muted"),
                        cls="detail-meta",
                    ),
                ),
                cls="detail-header",
            ),
            Div(form, cls="detail-body"),
        ),
    )
