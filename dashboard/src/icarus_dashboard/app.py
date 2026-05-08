"""FastHTML application — wires routes to view modules."""

from __future__ import annotations

from pathlib import Path

from urllib.parse import quote

from fasthtml.common import EventStream, RedirectResponse, fast_app

from .data.memory import get_memory
from .views import activity, review, wiki

STATIC_DIR = Path(__file__).parent / "static"

app, rt = fast_app(
    pico=False,
    hdrs=(),
    live=False,
    static_path=str(STATIC_DIR),
)


@rt("/")
def home():
    return RedirectResponse("/wiki", status_code=303)


@rt("/wiki")
def wiki_route():
    return wiki.page()


# More-specific append routes must be registered before the generic page route
# so /wiki/page/<path>/append doesn't get swallowed by {path:path}.
@rt("/wiki/page/{path:path}/append", methods=["GET"])
def wiki_append_form(path: str):
    return wiki.append_form(active_path=path)


@rt("/wiki/page/{path:path}/append", methods=["POST"])
def wiki_append_submit(
    path: str, agent: str, type: str, summary: str, body: str = ""
):
    memory = get_memory()
    entry = memory.write(agent=agent, type=type, summary=summary, body=body)
    memory.wiki.add_entry(path, entry.id)
    return RedirectResponse(
        f"/wiki/page/{quote(path, safe='/')}", status_code=303
    )


@rt("/wiki/page/{path:path}")
def wiki_page_route(path: str):
    return wiki.page(active_path=path)


@rt("/activity")
async def activity_route():
    return await activity.page()


@rt("/activity/event/{event_id}")
async def activity_event_route(event_id: str):
    return await activity.page(active_event_id=event_id)


@rt("/activity/stream")
async def activity_stream_route():
    return EventStream(activity.stream())


@rt("/review")
def review_route():
    return review.page()


# More-specific issue routes registered before the generic detail route so the
# /resolve, /dismiss, /supersede suffixes don't get swallowed by {issue_id}.
@rt("/review/issue/{issue_id}/resolve", methods=["POST"])
def review_resolve(issue_id: str):
    from .data.review import find_issue, write_marker

    memory = get_memory()
    issue = find_issue(memory, issue_id)
    if issue is not None:
        write_marker(memory, issue, action="resolved")
    return RedirectResponse("/review", status_code=303)


@rt("/review/issue/{issue_id}/dismiss", methods=["POST"])
def review_dismiss(issue_id: str):
    from .data.review import find_issue, write_marker

    memory = get_memory()
    issue = find_issue(memory, issue_id)
    if issue is not None:
        write_marker(memory, issue, action="dismissed")
    return RedirectResponse("/review", status_code=303)


@rt("/review/issue/{issue_id}/supersede", methods=["GET"])
def review_supersede_form(issue_id: str):
    return review.supersede_form(issue_id)


@rt("/review/issue/{issue_id}/supersede", methods=["POST"])
def review_supersede_submit(
    issue_id: str, agent: str, summary: str, body: str = ""
):
    from .data.review import find_issue

    memory = get_memory()
    issue = find_issue(memory, issue_id)
    if issue is None or issue.target_kind != "entry":
        return RedirectResponse("/review", status_code=303)
    memory.write_with_supersession(
        agent=agent,
        type="decision",
        summary=summary,
        body=body,
        supersedes_ids=[issue.target_id],
    )
    return RedirectResponse("/review", status_code=303)


@rt("/review/issue/{issue_id}")
def review_issue_route(issue_id: str):
    return review.page(active_issue_id=issue_id)
