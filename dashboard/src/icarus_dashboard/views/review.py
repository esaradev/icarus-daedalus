"""Review Queue view — stub for v1 shell commit.

The "Sync failures" filter is shipped visible. There's no sync log in the
substrate yet; selecting that filter renders an explanation, not a fake
list. Visible-with-explanation is more useful than hidden — the operator
sees the category exists and knows what's missing.
"""

from __future__ import annotations

from typing import Any

from fasthtml.common import Div, H2, P, Span

from ..layout import shell


def _filters() -> Any:
    return Div(
        Div("issue types", cls="nav-section"),
        Div(
            Div("Contradictions", Span("0", cls="count"), cls="nav-filter"),
            Div("Stale facts", Span("0", cls="count"), cls="nav-filter"),
            Div("Unsourced memories", Span("0", cls="count"), cls="nav-filter"),
            Div("Disconnected agents", Span("0", cls="count"), cls="nav-filter"),
            Div(
                "Sync failures ",
                Span("n/a", cls="count"),
                cls="nav-filter",
                title="No substrate signal yet — see detail.",
            ),
            Div("Briefing errors", Span("0", cls="count"), cls="nav-filter"),
            cls="nav-filters",
        ),
    )


def _list_pane() -> Any:
    return Div(
        Div(
            Span("Review Queue", cls="list-title"),
            Span("0 open", cls="list-meta"),
            cls="list-header",
        ),
        Div(
            P(
                "Issue detectors land in the next commit. Detectors run "
                "across the existing data — no new schema, no new endpoint."
            ),
            cls="empty-state",
        ),
    )


def _detail_pane() -> Any:
    return Div(
        Div(
            Span("Sync failures", cls="detail-title"),
            Span("not yet implementable", cls="detail-meta"),
            cls="detail-header",
        ),
        Div(
            H2("Why this category is empty"),
            P(
                "Sync failures are a category of issue the operator should "
                "see at a glance, but the icarus-memory substrate does not "
                "currently emit a sync log. There is no filesystem signal "
                "for the dashboard to derive from."
            ),
            P(
                "The category stays visible in the nav so it's discoverable. "
                "When the substrate ships sync logging, the detector wires "
                "in without UI changes."
            ),
            P(
                Span("If you need sync visibility now: ", cls="muted"),
                "have agents write entries with type=\"sync_failure\" and "
                "evidence pointing at the failed run. The Contradictions "
                "and Unsourced filters will surface them.",
            ),
            cls="detail-body",
        ),
    )


def page() -> Any:
    return shell(
        active="review",
        title="Review",
        filters=_filters(),
        list_pane=_list_pane(),
        detail_pane=_detail_pane(),
    )
