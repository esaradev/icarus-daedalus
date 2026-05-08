"""Wiki view — stub for v1 shell commit.

The detail-pane CTA is intentionally labeled "Append or Supersede" rather
than "Edit". The substrate's WikiManager re-renders page bodies from the
list of linked entries, so freeform body edits aren't a real operation.
The button names what actually happens.
"""

from __future__ import annotations

from typing import Any

from fasthtml.common import Button, Div, H2, P, Span

from ..layout import shell


def _filters() -> Any:
    return Div(
        Div("page types", cls="nav-section"),
        Div(
            Div("Decisions", Span("0", cls="count"), cls="nav-filter"),
            Div("Facts", Span("0", cls="count"), cls="nav-filter"),
            Div("Failed Attempts", Span("0", cls="count"), cls="nav-filter"),
            Div("Superseded", Span("0", cls="count"), cls="nav-filter"),
            Div("Briefings", Span("0", cls="count"), cls="nav-filter"),
            Div("Sources", Span("0", cls="count"), cls="nav-filter"),
            Div("Uncategorized", Span("0", cls="count"), cls="nav-filter"),
            cls="nav-filters",
        ),
    )


def _list_pane() -> Any:
    return Div(
        Div(
            Span("Wiki", cls="list-title"),
            Span("0 pages", cls="list-meta"),
            cls="list-header",
        ),
        Div(
            P(
                "Wiki page list lands in the next commit. The list will read ",
                Span(".icarus/wiki/", cls="mono"),
                " via WikiManager.iter_pages() and group by page_type.",
            ),
            cls="empty-state",
        ),
    )


def _detail_pane() -> Any:
    return Div(
        Div(
            Span("Select a page", cls="detail-title"),
            Div(
                Button("Append or Supersede", cls="action primary"),
                cls="action-row",
            ),
            cls="detail-header",
        ),
        Div(
            H2("Why the button isn't called Edit"),
            P(
                "WikiManager.write_page() regenerates the page body from its "
                "linked entries every write. Freeform body edits would be "
                "silently overwritten. The dashboard exposes only the "
                "operations the substrate actually supports: appending a "
                "new entry, or superseding an existing one. The substrate's "
                "append-only / immutable semantics are surfaced in the UI, "
                "not hidden behind a button label."
            ),
            cls="detail-body",
        ),
    )


def page() -> Any:
    return shell(
        active="wiki",
        title="Wiki",
        filters=_filters(),
        list_pane=_list_pane(),
        detail_pane=_detail_pane(),
    )
