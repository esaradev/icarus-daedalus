"""FastHTML application — wires routes to view modules."""

from __future__ import annotations

from pathlib import Path

from urllib.parse import quote

from fasthtml.common import RedirectResponse, fast_app

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
def activity_route():
    return activity.page()


@rt("/review")
def review_route():
    return review.page()
