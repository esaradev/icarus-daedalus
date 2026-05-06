"""Shared helpers for the v0.3 memory layers."""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .exceptions import ValidationError

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{secrets.token_hex(4)}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def safe_id(raw: str, field: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ValidationError(f"{field} must be a non-empty safe id")
    if raw in {".", ".."} or "/" in raw or "\\" in raw or not SAFE_ID_RE.match(raw):
        raise ValidationError(f"{field} contains unsafe characters")
    return raw


def safe_page_path(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError("wiki path must be a non-empty string")
    path = raw.strip().strip("/")
    if path.endswith(".md"):
        path = path[:-3]
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValidationError("wiki path contains unsafe traversal")
    for part in parts:
        if "\\" in part or not _SAFE_SEGMENT_RE.match(part):
            raise ValidationError("wiki path contains unsafe characters")
    return "/".join(parts)


def yaml_frontmatter(data: Mapping[str, Any], body: str) -> str:
    front = yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n{body}"


def split_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise ValidationError("missing YAML frontmatter")
    try:
        _, front, body = text.split("---", 2)
    except ValueError as exc:
        raise ValidationError("missing YAML frontmatter") from exc
    loaded = yaml.safe_load(front) or {}
    if not isinstance(loaded, dict):
        raise ValidationError("frontmatter must be a mapping")
    return loaded, body.lstrip("\n")


def call_openai_json(prompt: str, *, max_tokens: int = 400) -> dict[str, Any] | None:
    """Call gpt-4o-mini with stdlib HTTP and parse a JSON object response.

    Missing keys, transport failures, non-JSON replies, and malformed payloads
    all return ``None`` so callers can use deterministic fallbacks.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": "Return only one compact JSON object. Do not include Markdown.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
