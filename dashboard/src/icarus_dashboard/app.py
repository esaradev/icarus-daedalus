"""FastHTML application — wires routes to view modules."""

from __future__ import annotations

from pathlib import Path

from fasthtml.common import RedirectResponse, fast_app

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


@rt("/activity")
def activity_route():
    return activity.page()


@rt("/review")
def review_route():
    return review.page()
