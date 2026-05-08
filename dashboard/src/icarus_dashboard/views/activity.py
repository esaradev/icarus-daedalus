"""Activity view — stub for v1 shell commit.

The reads-not-logged banner is shipped with the stub on purpose. Direct
read events aren't observable from the icarus filesystem today; the
banner is a feature, not a placeholder. When the substrate ships a read
log, the banner can be updated or removed.
"""

from __future__ import annotations

from typing import Any

from fasthtml.common import Div, H2, P, Span

from ..layout import shell


def _filters() -> Any:
    return Div(
        Div("event types", cls="nav-section"),
        Div(
            Div("Writes", Span("0", cls="count"), cls="nav-filter"),
            Div("Edits", Span("0", cls="count"), cls="nav-filter"),
            Div("Sessions", Span("0", cls="count"), cls="nav-filter"),
            Div("Archives", Span("0", cls="count"), cls="nav-filter"),
            Div("Briefings", Span("0", cls="count"), cls="nav-filter"),
            Div(
                "Reads ",
                Span("inferred", cls="count"),
                cls="nav-filter",
                title="Reads aren't logged by the substrate; inferred from briefings.",
            ),
            cls="nav-filters",
        ),
        Div("agents", cls="nav-section"),
        Div(
            Div("All agents", Span("·", cls="count"), cls="nav-filter active"),
            cls="nav-filters",
        ),
    )


def _reads_banner() -> Any:
    return Div(
        Span("Reads aren't directly observable. ", cls="muted"),
        "The substrate does not log read events at the filesystem layer. The ",
        Span("Reads", cls="mono"),
        " filter shows briefing-derived reads (each briefing implies reads of "
        "its source_ids and page_paths). Direct read tracking would be a ",
        Span("substrate change", cls="mono"),
        ", not a dashboard change.",
        cls="banner",
    )


def _list_pane() -> Any:
    return Div(
        _reads_banner(),
        Div(
            Span("Activity", cls="list-title"),
            Span("live", cls="list-meta"),
            cls="list-header",
        ),
        Div(
            P(
                "Live event stream lands in the next commit. The watcher "
                "will tail entry markdown writes, session start/end, "
                "archives, and briefings via watchfiles + SSE."
            ),
            cls="empty-state",
        ),
    )


def _detail_pane() -> Any:
    return Div(
        Div(
            Span("Select an event", cls="detail-title"),
            cls="detail-header",
        ),
        Div(
            H2("Event sources"),
            P(
                "Entry writes: <root>/<YYYY>/<MM>/icarus-*.md. "
                "Sessions: .icarus/sessions/*.json. "
                "Archives: .icarus/agents/<agent>/sessions/*.json. "
                "Briefings: .icarus/briefings/*.json. "
                "Wiki edits: .icarus/wiki/**.md."
            ),
            cls="detail-body",
        ),
    )


def page() -> Any:
    return shell(
        active="activity",
        title="Activity",
        filters=_filters(),
        list_pane=_list_pane(),
        detail_pane=_detail_pane(),
    )
