"""MarkdownStore: atomic on-disk read/write/list of fabric entries."""

from __future__ import annotations

import contextlib
import logging
import os
import re
import secrets
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .exceptions import EntryNotFound, StoreError
from .schema import Entry

logger = logging.getLogger(__name__)

ID_SUFFIX_BYTES = 6  # 12 hex chars -> 48 bits of entropy
ID_COLLISION_RETRY = 8

_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n)?(.*)$", re.DOTALL)


def _id_from_filename(name: str) -> str | None:
    if name.startswith("icarus-") and name.endswith(".md"):
        return "icarus:" + name[len("icarus-") : -len(".md")]
    return None


def _filename_from_id(entry_id: str) -> str:
    return f"icarus-{entry_id.split(':', 1)[1]}.md"


def _yaml_safe(obj: Any) -> Any:
    """Recursively convert a model_dump() result into YAML-friendly primitives.

    Pydantic emits datetimes as iso strings when mode='json', but lists of
    nested models become dicts of strings — we want the same for nested
    timestamps. Easiest path: dump with mode='json' and then post-process for
    aesthetics.
    """
    if isinstance(obj, dict):
        return {k: _yaml_safe(v) for k, v in obj.items() if v is not None and v != [] and v != {}}
    if isinstance(obj, list):
        return [_yaml_safe(v) for v in obj]
    return obj


def _format_timestamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MarkdownStore:
    """Read, write, and list fabric entries on disk.

    Entries live at ``<root>/<YYYY>/<MM>/icarus-<id_suffix>.md``. Writes are
    atomic via tmp-file + ``os.replace``. The store maintains no in-memory
    index; lookups glob the disk on demand.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._reverse_revises_cache: dict[str, list[str]] | None = None

    # -- ID generation --------------------------------------------------

    def generate_id(self) -> str:
        for _ in range(ID_COLLISION_RETRY):
            candidate = "icarus:" + secrets.token_hex(ID_SUFFIX_BYTES)
            if not self.exists(candidate):
                return candidate
        raise StoreError(
            f"failed to generate unique entry id after {ID_COLLISION_RETRY} retries"
        )

    # -- Path resolution ------------------------------------------------

    def _path_for(self, entry: Entry) -> Path:
        ts = entry.timestamp.astimezone(timezone.utc)
        return (
            self.root
            / f"{ts.year:04d}"
            / f"{ts.month:02d}"
            / _filename_from_id(entry.id)
        )

    def _find_path(self, entry_id: str) -> Path | None:
        filename = _filename_from_id(entry_id)
        for match in self.root.rglob(filename):
            if match.is_file():
                return match
        return None

    # -- CRUD -----------------------------------------------------------

    def exists(self, entry_id: str) -> bool:
        return self._find_path(entry_id) is not None

    def get(self, entry_id: str) -> Entry:
        path = self._find_path(entry_id)
        if path is None:
            raise EntryNotFound(f"no entry with id {entry_id}")
        return self._read(path)

    def write(self, entry: Entry) -> Entry:
        path = self._path_for(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = self._serialize(entry)
        self._atomic_write(path, text)
        self._reverse_revises_cache = None
        return entry

    def iter_entries(self) -> Iterator[Entry]:
        for path in sorted(self.root.rglob("icarus-*.md")):
            try:
                yield self._read(path)
            except StoreError as exc:
                logger.warning("skipping unreadable entry at %s: %s", path, exc)

    def list_ids(self) -> list[str]:
        ids: list[str] = []
        for path in self.root.rglob("icarus-*.md"):
            entry_id = _id_from_filename(path.name)
            if entry_id is not None:
                ids.append(entry_id)
        return ids

    # -- Serialization --------------------------------------------------

    def _serialize(self, entry: Entry) -> str:
        data = entry.model_dump(mode="json", exclude_none=True)
        # body lives outside the frontmatter
        body = data.pop("body", "")
        # drop empty collections for cleaner YAML
        for key in list(data.keys()):
            if data[key] == [] or data[key] == {}:
                del data[key]
        # re-emit timestamp without trailing milliseconds, with Z suffix
        if "timestamp" in data:
            data["timestamp"] = _format_timestamp(entry.timestamp)
        for record in data.get("verification_log", []):
            if "timestamp" in record:
                # parse + reformat
                ts = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
                record["timestamp"] = _format_timestamp(ts)

        front = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n{body}"

    def _read(self, path: Path) -> Entry:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StoreError(f"could not read {path}: {exc}") from exc

        match = _FRONTMATTER_RE.match(text)
        if match is None:
            raise StoreError(f"missing YAML frontmatter in {path}")

        try:
            data = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise StoreError(f"invalid YAML in {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise StoreError(f"frontmatter must be a mapping in {path}")

        # Lazy migration: fill in fields older entries didn't have.
        data.setdefault("verified", "unverified")
        data.setdefault("evidence", [])
        data.setdefault("artifact_paths", [])
        data.setdefault("verification_log", [])
        data.setdefault("training_value", "normal")
        data.setdefault("lifecycle", "active")
        data.setdefault("supersedes", [])

        # Drop unknown keys so older fabrics with stray fields still load.
        # (pydantic Entry has extra='forbid'.)
        known = set(Entry.model_fields.keys())
        data = {k: v for k, v in data.items() if k in known}

        body = match.group(2)
        data["body"] = body

        try:
            return Entry.model_validate(data)
        except Exception as exc:
            raise StoreError(f"invalid entry in {path}: {exc}") from exc

    # -- Atomic write helper -------------------------------------------

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
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
