"""Filesystem-tailing activity stream for the dashboard.

Watches the fabric root for substrate file changes and produces typed Events.
The bus is a single-process in-memory ring buffer plus an asyncio fan-out
to subscribers (the SSE endpoint). Designed for one uvicorn worker; multi-
worker deployments would need a real broker.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from watchfiles import Change, awatch

EVENT_BUFFER = 500
INITIAL_SEED = 100

EVENT_KINDS = (
    "write",
    "edit",
    "session_start",
    "session_end",
    "archive",
    "briefing",
    "wiki_edit",
)


@dataclass
class Event:
    id: str
    ts: datetime
    kind: str
    agent: str | None
    target: str
    path: str
    payload: dict[str, Any]


def _gen_id() -> str:
    return f"evt_{int(time.time() * 1000)}_{secrets.token_hex(3)}"


def _path_mtime(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.now(timezone.utc)


def _entry_id_from_filename(name: str) -> str | None:
    if name.startswith("icarus-") and name.endswith(".md"):
        return f"icarus:{name[len('icarus-') : -len('.md')]}"
    return None


def _parse_entry_frontmatter(path: Path) -> tuple[str | None, dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, {}
    if not text.startswith("---"):
        return None, {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, {}
    try:
        data = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None, {}
    if not isinstance(data, dict):
        return None, {}
    return data.get("agent"), {
        "id": data.get("id"),
        "type": data.get("type"),
        "summary": data.get("summary"),
        "verified": data.get("verified"),
        "lifecycle": data.get("lifecycle"),
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def classify(path: Path, root: Path) -> tuple[str, str | None, str, dict[str, Any]] | None:
    """Return (kind, agent, target, payload) for a substrate path or None."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    name = path.name

    if (
        len(parts) == 3
        and name.startswith("icarus-")
        and name.endswith(".md")
    ):
        agent, payload = _parse_entry_frontmatter(path)
        target = _entry_id_from_filename(name) or name
        return "write", agent, target, payload

    if (
        len(parts) >= 3
        and parts[0] == ".icarus"
        and parts[1] == "sessions"
        and name.endswith(".json")
    ):
        data = _load_json(path)
        return (
            "session_start",
            data.get("agent_id"),
            data.get("session_id", name[:-5]),
            {
                "task_description": data.get("task_description"),
                "observations": len(data.get("observations") or []),
                "attempts": len(data.get("attempts") or []),
            },
        )

    if (
        len(parts) >= 5
        and parts[0] == ".icarus"
        and parts[1] == "agents"
        and parts[3] == "sessions"
        and name.endswith(".json")
    ):
        data = _load_json(path)
        return (
            "archive",
            parts[2],
            data.get("session_id", name[:-5]),
            {
                "task_description": data.get("task_description"),
                "final_summary": data.get("final_summary"),
                "promoted_to_wiki": data.get("promoted_to_wiki") or [],
            },
        )

    if (
        len(parts) >= 3
        and parts[0] == ".icarus"
        and parts[1] == "briefings"
        and name.endswith(".json")
    ):
        data = _load_json(path)
        return (
            "briefing",
            data.get("agent_id"),
            data.get("cache_key", name[:-5]),
            {
                "task_description": data.get("task_description"),
                "source_ids": data.get("source_ids") or [],
                "page_paths": data.get("page_paths") or [],
            },
        )

    if (
        len(parts) >= 3
        and parts[0] == ".icarus"
        and parts[1] == "wiki"
        and name.endswith(".md")
    ):
        page_path = "/".join(parts[2:])[:-3]
        return "wiki_edit", None, page_path, {}

    return None


def _event_for_change(change: Change, path: Path, root: Path) -> Event | None:
    classified = classify(path, root)
    if classified is None:
        return None
    kind, agent, target, payload = classified
    if change == Change.deleted and kind == "session_start":
        kind = "session_end"
    elif change == Change.modified and kind == "write":
        kind = "edit"
    ts = (
        _path_mtime(path)
        if change != Change.deleted
        else datetime.now(timezone.utc)
    )
    return Event(
        id=_gen_id(),
        ts=ts,
        kind=kind,
        agent=agent,
        target=target,
        path=str(path),
        payload=payload,
    )


class ActivityBus:
    """In-memory event bus and filesystem watcher. Singleton per process."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._buffer: deque[Event] = deque(maxlen=EVENT_BUFFER)
        self._task: asyncio.Task[Any] | None = None
        self._lock = asyncio.Lock()
        self._root: Path | None = None

    async def ensure_started(self, root: Path) -> None:
        async with self._lock:
            if self._task is not None and not self._task.done():
                return
            self._root = root
            self._buffer.clear()
            for ev in self._initial_seed(root):
                self._buffer.append(ev)
            if root.exists():
                self._task = asyncio.create_task(self._watch(root))

    def _initial_seed(self, root: Path) -> list[Event]:
        if not root.exists():
            return []
        events: list[Event] = []
        seed_paths = list(root.rglob("icarus-*.md"))
        sessions = root / ".icarus" / "sessions"
        if sessions.exists():
            seed_paths.extend(sessions.glob("*.json"))
        agents = root / ".icarus" / "agents"
        if agents.exists():
            seed_paths.extend(agents.rglob("*.json"))
        briefings = root / ".icarus" / "briefings"
        if briefings.exists():
            seed_paths.extend(briefings.glob("*.json"))
        wiki = root / ".icarus" / "wiki"
        if wiki.exists():
            seed_paths.extend(wiki.rglob("*.md"))

        for path in seed_paths:
            classified = classify(path, root)
            if classified is None:
                continue
            kind, agent, target, payload = classified
            events.append(
                Event(
                    id=_gen_id(),
                    ts=_path_mtime(path),
                    kind=kind,
                    agent=agent,
                    target=target,
                    path=str(path),
                    payload=payload,
                )
            )
        events.sort(key=lambda e: e.ts)
        return events[-INITIAL_SEED:]

    async def _watch(self, root: Path) -> None:
        async for changes in awatch(root, recursive=True):
            for change, raw in changes:
                event = _event_for_change(change, Path(raw), root)
                if event is not None:
                    self._publish(event)

    def _publish(self, event: Event) -> None:
        self._buffer.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def recent(self) -> list[Event]:
        return list(self._buffer)

    def get(self, event_id: str) -> Event | None:
        for ev in reversed(self._buffer):
            if ev.id == event_id:
                return ev
        return None

    @asynccontextmanager
    async def subscriber(self) -> AsyncIterator[asyncio.Queue[Event]]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=200)
        self._subscribers.append(q)
        try:
            yield q
        finally:
            if q in self._subscribers:
                self._subscribers.remove(q)


bus = ActivityBus()
