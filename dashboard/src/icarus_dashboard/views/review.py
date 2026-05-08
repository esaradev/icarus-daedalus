"""Review Queue view — six detectors over substrate data.

Sync failures stays a top-level filter even with zero rows: there is no
substrate signal for it yet, and surfacing the empty category is more
useful than hiding it. Selecting the filter shows an explanatory detail
pane rather than a fabricated list.
"""

from __future__ import annotations

import json
from typing import Any

from fasthtml.common import (
    A,
    Button,
    Div,
    Form,
    Input,
    Label,
    P,
    Pre,
    Script,
    Span,
    Textarea,
)

from ..data.memory import fabric_exists, fabric_root, get_memory
from ..data.review import (
    KIND_GROUPS,
    KIND_LABEL,
    Issue,
    all_issues,
    find_issue,
)
from ..layout import shell

SEVERITY_GLYPH = {"high": "✗", "medium": "⚠", "low": "·"}


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


def _filters(issues: list[Issue]) -> Any:
    counts: dict[str, int] = {kind: 0 for _, kind in KIND_GROUPS}
    for issue in issues:
        counts[issue.kind] = counts.get(issue.kind, 0) + 1
    rows: list[Any] = []
    for label, kind in KIND_GROUPS:
        if kind == "sync_failure":
            rows.append(
                A(
                    label,
                    Span("n/a", cls="count"),
                    href="/review/issue/sync_failure:placeholder",
                    cls="nav-filter",
                    title="No substrate signal yet — see detail.",
                )
            )
            continue
        rows.append(
            Div(
                label,
                Span(str(counts.get(kind, 0)), cls="count"),
                cls="nav-filter",
                data_filter_kind=kind,
                role="button",
            )
        )
    return Div(
        Div("issue types", cls="nav-section"),
        Div(*rows, cls="nav-filters"),
    )


def _issue_row(issue: Issue, *, active: bool = False) -> Any:
    glyph = SEVERITY_GLYPH.get(issue.severity, "·")
    return A(
        Div(
            Span(glyph, cls=f"glyph severity-{issue.severity}"),
            " ",
            Span(KIND_LABEL.get(issue.kind, issue.kind), cls="badge"),
            " ",
            Span(issue.summary[:70], cls="muted"),
            cls="title",
        ),
        Div(
            Span(issue.target_id or "—", cls="mono muted"),
            " · ",
            Span(f"{issue.age_days}d", cls="mono muted"),
            cls="meta",
        ),
        href=f"/review/issue/{issue.id}",
        cls=f"list-item issue-row{' active' if active else ''}",
        data_kind=issue.kind,
    )


def _action_form(issue_id: str, action: str, label: str) -> Any:
    return Form(
        Button(label, type="submit", cls="action"),
        method="post",
        action=f"/review/issue/{issue_id}/{action}",
        cls="inline-form",
    )


def _detail_for_sync_failure() -> Any:
    return Div(
        Div(
            Span("Sync failures", cls="detail-title"),
            Div(
                Span("not yet implementable", cls="mono muted"),
                cls="detail-meta",
            ),
            cls="detail-header",
        ),
        Div(
            P(
                "Sync failures are a category the operator should see at a "
                "glance, but the icarus-memory substrate does not currently "
                "emit a sync log. There is no filesystem signal for the "
                "dashboard to derive from."
            ),
            P(
                "The category stays visible so it's discoverable. When the "
                "substrate ships sync logging, the detector wires in here "
                "without UI changes."
            ),
            P(
                Span("If you need sync visibility now: ", cls="muted"),
                'have agents write entries with type="sync_failure" and '
                "evidence pointing at the failed run. The Contradictions "
                "and Unsourced filters will surface them.",
            ),
            cls="detail-body",
        ),
    )


def _detail_pane(issue: Issue | None) -> Any:
    if issue is None:
        return Div(
            Div(
                Span("Select an issue", cls="detail-title"),
                cls="detail-header",
            ),
            Div(
                P("Pick an issue on the left.", cls="muted"),
                cls="empty-state",
            ),
        )
    if issue.kind == "sync_failure":
        return _detail_for_sync_failure()

    glyph = SEVERITY_GLYPH.get(issue.severity, "·")
    actions: list[Any] = []
    actions.append(_action_form(issue.id, "resolve", "Mark resolved"))
    if issue.target_kind == "entry":
        actions.append(
            A(
                "Supersede",
                href=f"/review/issue/{issue.id}/supersede",
                cls="action",
            )
        )
    actions.append(_action_form(issue.id, "dismiss", "Dismiss"))

    detail_text = json.dumps(issue.detail, indent=2, default=str)
    return Div(
        Div(
            Div(
                Span(
                    f"{glyph} {KIND_LABEL.get(issue.kind, issue.kind)}",
                    cls="detail-title",
                ),
                Div(
                    Span(issue.target_id or "—", cls="mono muted"),
                    " · ",
                    Span(f"{issue.age_days}d", cls="mono muted"),
                    " · ",
                    Span(f"severity {issue.severity}", cls="muted"),
                    cls="detail-meta",
                ),
            ),
            Div(*actions, cls="action-row"),
            cls="detail-header",
        ),
        Div(
            Div("Summary", cls="entry-group-label"),
            P(issue.summary),
            Div("Detail", cls="entry-group-label"),
            Pre(detail_text, cls="payload-block"),
            cls="detail-body",
        ),
    )


def _list_pane(issues: list[Issue], active_issue_id: str | None) -> Any:
    header = Div(
        Span("Review Queue", cls="list-title"),
        Span(f"{len(issues)} open", cls="list-meta"),
        cls="list-header",
    )
    if not issues:
        return Div(
            header,
            Div(
                P(
                    "Nothing to review right now. New contradictions, stale "
                    "facts, unsourced memories, disconnected agents, and "
                    "briefing errors will appear here as they're detected."
                ),
                cls="empty-state",
            ),
        )
    rows = [
        _issue_row(issue, active=issue.id == active_issue_id)
        for issue in issues
    ]
    return Div(
        header,
        Div(*rows, id="review-list", cls="review-list"),
        Script(src="/review.js", defer=""),
    )


def page(active_issue_id: str | None = None) -> Any:
    if not fabric_exists():
        return shell(
            active="review",
            title="Review",
            list_pane=_missing_fabric_pane(),
            detail_pane=Div(),
        )
    memory = get_memory()
    issues = all_issues(memory)
    target = find_issue(memory, active_issue_id) if active_issue_id else None
    return shell(
        active="review",
        title="Review",
        filters=_filters(issues),
        list_pane=_list_pane(issues, active_issue_id),
        detail_pane=_detail_pane(target),
    )


def supersede_form(issue_id: str) -> Any:
    if not fabric_exists():
        return shell(
            active="review",
            title="Review",
            list_pane=_missing_fabric_pane(),
            detail_pane=Div(),
        )
    memory = get_memory()
    issue = find_issue(memory, issue_id)
    if issue is None or issue.target_kind != "entry":
        return shell(
            active="review",
            title="Review",
            list_pane=_list_pane(all_issues(memory), issue_id),
            detail_pane=Div(
                P("Issue is not an entry, or no longer open.", cls="muted"),
                cls="empty-state",
            ),
        )
    old = memory.get(issue.target_id)
    cancel_href = f"/review/issue/{issue_id}"
    form = Form(
        Div(
            Label("Agent", For="agent"),
            Input(name="agent", id="agent", required="", value="dashboard"),
            cls="form-row",
        ),
        Div(
            Label("New summary", For="summary"),
            Input(
                name="summary",
                id="summary",
                required="",
                maxlength="200",
                value=old.summary,
            ),
            cls="form-row",
        ),
        Div(
            Label("New body", For="body"),
            Textarea(old.body, name="body", id="body", rows="8"),
            cls="form-row",
        ),
        Div(
            Button(
                "Write supersession", type="submit", cls="action primary"
            ),
            A("Cancel", href=cancel_href, cls="action"),
            cls="action-row",
        ),
        method="post",
        action=f"/review/issue/{issue_id}/supersede",
        cls="form",
    )
    issues = all_issues(memory)
    return shell(
        active="review",
        title="Review",
        filters=_filters(issues),
        list_pane=_list_pane(issues, issue_id),
        detail_pane=Div(
            Div(
                Div(
                    Span(
                        f"Supersede {old.id}", cls="detail-title"
                    ),
                    Div(
                        Span(
                            f"old summary: {old.summary[:80]}",
                            cls="muted",
                        ),
                        cls="detail-meta",
                    ),
                ),
                cls="detail-header",
            ),
            Div(form, cls="detail-body"),
        ),
    )
