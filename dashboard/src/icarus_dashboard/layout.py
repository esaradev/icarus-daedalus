"""Three-pane shell. Mail.app / Linear / GitHub-Issues pattern."""

from __future__ import annotations

from typing import Any

from fasthtml.common import (
    Aside,
    Body,
    Div,
    Head,
    Html,
    Li,
    Link,
    Main,
    Meta,
    Nav,
    Title,
    Ul,
    A,
)

from .theme import NAV_ITEMS

GOOGLE_FONTS = (
    "https://fonts.googleapis.com/css2"
    "?family=Inter:wght@400;500"
    "&family=JetBrains+Mono:wght@400;500"
    "&display=swap"
)


def _nav(active: str, filters: Any) -> Any:
    items = [
        Li(
            A(
                label,
                href=href,
                cls=f"nav-item{' active' if key == active else ''}",
            )
        )
        for key, label, href in NAV_ITEMS
    ]
    children = [
        Div("icarus / dashboard", cls="nav-brand"),
        Ul(*items, cls="nav-views"),
    ]
    if filters is not None:
        children.append(filters)
    return Nav(*children, cls="nav-pane")


def shell(
    *,
    active: str,
    title: str,
    list_pane: Any,
    detail_pane: Any,
    filters: Any = None,
) -> Any:
    return Html(
        Head(
            Meta(charset="utf-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1"),
            Title(f"{title} — icarus"),
            Link(rel="preconnect", href="https://fonts.googleapis.com"),
            Link(
                rel="preconnect",
                href="https://fonts.gstatic.com",
                crossorigin="",
            ),
            Link(rel="stylesheet", href=GOOGLE_FONTS),
            Link(rel="stylesheet", href="/app.css"),
        ),
        Body(
            Div(
                _nav(active, filters),
                Main(list_pane, cls="list-pane"),
                Aside(detail_pane, cls="detail-pane"),
                cls="app",
            ),
        ),
    )
