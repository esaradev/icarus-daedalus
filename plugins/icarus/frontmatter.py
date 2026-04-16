"""Strict fabric frontmatter parsing helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable


class FrontmatterError(ValueError):
    """Raised when a markdown entry has invalid or malformed frontmatter."""


_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(frontmatter_text, body)`` or raise ``FrontmatterError``."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise FrontmatterError("missing or malformed YAML frontmatter delimiters")
    return match.group(1), match.group(2)


def parse_frontmatter_text(frontmatter_text: str) -> dict:
    """Parse YAML frontmatter into a mapping."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment issue
        raise FrontmatterError("PyYAML is required to parse fabric entries") from exc

    try:
        meta = yaml.safe_load(frontmatter_text)
    except Exception as exc:
        raise FrontmatterError(f"invalid YAML frontmatter: {exc}") from exc

    if meta is None:
        return {}
    if not isinstance(meta, dict):
        raise FrontmatterError(f"frontmatter must be a mapping, got {type(meta).__name__}")
    return meta


def parse_markdown_entry(
    filepath: Path,
    *,
    logger=None,
    body_transform: Callable[[str], str] | None = None,
    include_full: bool = False,
) -> dict | None:
    """Parse a markdown fabric entry or return ``None`` on invalid metadata."""
    try:
        text = filepath.read_text(encoding="utf-8")
        frontmatter_text, body = split_frontmatter(text)
        meta = parse_frontmatter_text(frontmatter_text)
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        if logger:
            logger.warning("icarus: skipping invalid entry %s: %s", filepath, exc)
        return None

    entry = dict(meta)
    entry["body"] = body_transform(body) if body_transform else body.strip()
    entry["file"] = filepath.name
    if include_full:
        entry["_full"] = text
    return entry
