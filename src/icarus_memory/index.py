"""Durable sqlite-backed index for fabric entries.

The index is an implementation detail of MarkdownStore: it accelerates entry-id
lookups and supports filtered iteration without repeated filesystem globbing.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .locking import FileLock

_FRONTMATTER_RE = r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n)?"


def _id_from_filename(name: str) -> str | None:
    if name.startswith("icarus-") and name.endswith(".md"):
        return "icarus:" + name[len("icarus-") : -len(".md")]
    return None


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


class SqliteIndex:
    def __init__(self, root: Path):
        self.root = root
        self.icarus_root = self.root / ".icarus"
        self.db_path = self.icarus_root / "index.sqlite3"
        self.lock_path = self.icarus_root / "index.lock"
        self._schema_ready = False

    def lock(self) -> FileLock:
        return FileLock(self.lock_path)

    def find_path(self, entry_id: str, *, filename_fallback_root: Path) -> Path | None:
        self._ensure_built()
        row = self._one(
            "SELECT path, mtime_ns, size FROM entries WHERE id = ?",
            (entry_id,),
        )
        if row is None:
            filename = f"icarus-{entry_id.split(':', 1)[1]}.md"
            for match in filename_fallback_root.rglob(filename):
                if match.is_file():
                    self._index_path_only(entry_id, match)
                    return match
            return None

        rel_path, mtime_ns, size = row
        full = (self.root / str(rel_path)).resolve()
        if not full.exists():
            self._exec("DELETE FROM entries WHERE id = ?", (entry_id,))
            return None
        stat = full.stat()
        if int(mtime_ns) != int(stat.st_mtime_ns) or int(size) != int(stat.st_size):
            self._refresh_from_disk(entry_id, full)
        return full

    def iter_paths(
        self,
        *,
        agent: str | None = None,
        project_id: str | None = None,
        type: str | None = None,
        verified_in: set[str] | None = None,
        lifecycle_in: set[str] | None = None,
        exclude_lifecycle: set[str] | None = None,
    ) -> Iterable[Path]:
        self._ensure_built()
        clauses: list[str] = []
        params: list[Any] = []
        if agent is not None:
            clauses.append("agent = ?")
            params.append(agent)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if type is not None:
            clauses.append("type = ?")
            params.append(type)
        if verified_in is not None:
            clauses.append(f"verified IN ({','.join('?' for _ in verified_in)})")
            params.extend(sorted(verified_in))
        if lifecycle_in is not None:
            clauses.append(f"lifecycle IN ({','.join('?' for _ in lifecycle_in)})")
            params.extend(sorted(lifecycle_in))
        if exclude_lifecycle is not None:
            clauses.append(f"lifecycle NOT IN ({','.join('?' for _ in exclude_lifecycle)})")
            params.extend(sorted(exclude_lifecycle))

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT path FROM entries"
            f"{where} "
            "ORDER BY (timestamp IS NULL), timestamp, path"
        )
        for (rel_path,) in self._all(sql, tuple(params)):
            yield self.root / str(rel_path)

    def list_ids(self) -> list[str]:
        self._ensure_built()
        return [row[0] for row in self._all("SELECT id FROM entries ORDER BY id", ())]

    def upsert_entry(self, entry_id: str, path: Path, meta: dict[str, Any]) -> None:
        self._ensure_schema()
        stat = path.stat()
        payload = {
            "id": entry_id,
            "path": _rel(self.root, path),
            "mtime_ns": int(stat.st_mtime_ns),
            "size": int(stat.st_size),
            **meta,
        }
        self._exec(
            """
            INSERT INTO entries (
              id, path, mtime_ns, size, timestamp, agent, project_id, type, verified, lifecycle, status, assigned_to
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              path=excluded.path,
              mtime_ns=excluded.mtime_ns,
              size=excluded.size,
              timestamp=excluded.timestamp,
              agent=excluded.agent,
              project_id=excluded.project_id,
              type=excluded.type,
              verified=excluded.verified,
              lifecycle=excluded.lifecycle,
              status=excluded.status,
              assigned_to=excluded.assigned_to
            """,
            (
                payload["id"],
                payload["path"],
                payload["mtime_ns"],
                payload["size"],
                payload.get("timestamp"),
                payload.get("agent"),
                payload.get("project_id"),
                payload.get("type"),
                payload.get("verified"),
                payload.get("lifecycle"),
                payload.get("status"),
                payload.get("assigned_to"),
            ),
        )

    def _ensure_built(self) -> None:
        self.icarus_root.mkdir(parents=True, exist_ok=True)
        with self.lock():
            self._init_schema()
            self._schema_ready = True
            built = self._one("SELECT value FROM meta WHERE key='built'", ())
            if built is not None:
                return
            for path in self.root.rglob("icarus-*.md"):
                entry_id = _id_from_filename(path.name)
                if entry_id is None or not path.is_file():
                    continue
                self._refresh_from_disk(entry_id, path, allow_yaml_failure=True)
            self._exec("INSERT OR REPLACE INTO meta(key,value) VALUES('built','1')", ())

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                  id TEXT PRIMARY KEY,
                  path TEXT NOT NULL,
                  mtime_ns INTEGER NOT NULL,
                  size INTEGER NOT NULL,
                  timestamp TEXT,
                  agent TEXT,
                  project_id TEXT,
                  type TEXT,
                  verified TEXT,
                  lifecycle TEXT,
                  status TEXT,
                  assigned_to TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_timestamp ON entries(timestamp)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_agent ON entries(agent)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_project ON entries(project_id)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_type ON entries(type)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_verified ON entries(verified)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_lifecycle ON entries(lifecycle)"
            )
            conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema','1')")
            conn.commit()

    def _ensure_schema(self) -> None:
        if self._schema_ready and self.db_path.exists():
            return
        self.icarus_root.mkdir(parents=True, exist_ok=True)
        with self.lock():
            self._init_schema()
        self._schema_ready = True

    def _index_path_only(self, entry_id: str, path: Path) -> None:
        stat = path.stat()
        self._exec(
            """
            INSERT INTO entries(id, path, mtime_ns, size)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET path=excluded.path, mtime_ns=excluded.mtime_ns, size=excluded.size
            """,
            (entry_id, _rel(self.root, path), int(stat.st_mtime_ns), int(stat.st_size)),
        )

    def _refresh_from_disk(self, entry_id: str, path: Path, *, allow_yaml_failure: bool = False) -> None:
        meta: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            meta = _extract_meta(path)
        if not meta and not allow_yaml_failure:
            meta = _extract_meta(path)
        self.upsert_entry(entry_id, path, meta)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _exec(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._connect() as conn:
            conn.execute(sql, params)
            conn.commit()

    def _one(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            return tuple(row)

    def _all(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return [tuple(row) for row in cur.fetchall()]


def _extract_meta(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    import re

    m = re.match(_FRONTMATTER_RE, text, re.DOTALL)
    if m is None:
        return {}
    front = yaml.safe_load(m.group(1)) or {}
    if not isinstance(front, dict):
        return {}
    timestamp = front.get("timestamp")
    return {
        "timestamp": str(timestamp) if timestamp else None,
        "agent": front.get("agent"),
        "project_id": front.get("project_id"),
        "type": front.get("type"),
        "verified": front.get("verified"),
        "lifecycle": front.get("lifecycle"),
        "status": front.get("status"),
        "assigned_to": front.get("assigned_to"),
    }
