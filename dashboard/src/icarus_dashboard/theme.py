"""Single source of truth for palette + typography.

Anything that needs a color or a font name reads it from here. The CSS
file mirrors these values as custom properties; if you change one place,
change both.
"""

from __future__ import annotations

PALETTE = {
    "bg": "#0a0a0a",
    "surface": "#1a1a1a",
    "border": "#2a2a2a",
    "text": "#e8e8e8",
    "muted": "#888888",
    "accent": "#f5a524",
}

FONT_SANS = (
    '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
)
FONT_MONO = (
    '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Monaco, Consolas, monospace'
)

FONT_SIZE_DETAIL = "13px"
FONT_SIZE_BODY = "14px"
FONT_SIZE_TITLE = "18px"

NAV_ITEMS = (
    ("wiki", "Wiki", "/wiki"),
    ("activity", "Activity", "/activity"),
    ("review", "Review", "/review"),
)
