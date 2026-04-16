"""Runtime cache for fabric metadata and retrieval bodies."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from .frontmatter import parse_markdown_entry
except ImportError:
    _frontmatter_path = Path(__file__).with_name("frontmatter.py")
    _spec = importlib.util.spec_from_file_location("icarus_frontmatter", _frontmatter_path)
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    parse_markdown_entry = _module.parse_markdown_entry

INDEX_VERSION = 1
INDEX_FILENAME = ".icarus-index.json"

ENTRY_FIELDS = (
    "id",
    "agent",
    "platform",
    "timestamp",
    "type",
    "tier",
    "summary",
    "project_id",
    "session_id",
    "status",
    "outcome",
    "review_of",
    "revises",
    "customer_id",
    "assigned_to",
    "training_value",
    "verified",
    "evidence",
    "source_tool",
    "artifact_paths",
    "refs",
    "tags",
    "cycle",
)


def _strip_generated_obsidian_sections(body: str) -> str:
    import re

    body = re.sub(
        r"\n*<!-- ICARUS_OBSIDIAN_LINKS_START -->.*?<!-- ICARUS_OBSIDIAN_LINKS_END -->\n*",
        "\n",
        body,
        flags=re.DOTALL,
    )
    return body.strip()


def index_path(fabric_dir: Path) -> Path:
    return fabric_dir / INDEX_FILENAME


def _scan_files(fabric_dir: Path) -> list[Path]:
    files = []
    for directory in (fabric_dir, fabric_dir / "cold"):
        if not directory.exists():
            continue
        files.extend(sorted(directory.glob("*.md")))
    return files


def _relative_key(filepath: Path, fabric_dir: Path) -> str:
    return filepath.relative_to(fabric_dir).as_posix()


def _record_from_file(filepath: Path, fabric_dir: Path, logger=None) -> dict | None:
    entry = parse_markdown_entry(filepath, logger=logger, body_transform=_strip_generated_obsidian_sections)
    if entry is None:
        return None

    stat = filepath.stat()
    record = {
        "path": _relative_key(filepath, fabric_dir),
        "file": filepath.name,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "body": entry.pop("body", ""),
    }
    for field in ENTRY_FIELDS:
        if field in entry:
            record[field] = _json_safe(entry[field])
    return record


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return value.isoformat()
        except Exception:
            pass
    return value


def _normalize_index_payload(payload) -> dict | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != INDEX_VERSION:
        return None
    records = payload.get("records", {})
    if not isinstance(records, dict):
        return None
    return payload


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_runtime_index(fabric_dir: Path, logger=None) -> dict:
    """Load or refresh the runtime index."""
    fabric_dir = Path(fabric_dir)
    if not fabric_dir.exists():
        return {"version": INDEX_VERSION, "generated_at": None, "records": {}, "invalid": 0}

    current_files = _scan_files(fabric_dir)
    current_map = {_relative_key(path, fabric_dir): path for path in current_files}
    idx_path = index_path(fabric_dir)

    payload = None
    if idx_path.exists():
        try:
            payload = _normalize_index_payload(json.loads(idx_path.read_text(encoding="utf-8")))
        except Exception:
            payload = None
    if payload is None:
        payload = {"version": INDEX_VERSION, "generated_at": None, "records": {}, "invalid": 0}

    records = dict(payload.get("records", {}))
    invalid = 0
    changed = False

    for rel_path in list(records.keys()):
        if rel_path not in current_map:
            del records[rel_path]
            changed = True

    for rel_path, filepath in current_map.items():
        stat = filepath.stat()
        existing = records.get(rel_path)
        if existing and existing.get("mtime_ns") == stat.st_mtime_ns and existing.get("size") == stat.st_size:
            continue
        record = _record_from_file(filepath, fabric_dir, logger=logger)
        changed = True
        if record is None:
            records.pop(rel_path, None)
            invalid += 1
            continue
        records[rel_path] = record

    new_payload = {
        "version": INDEX_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "records": records,
        "invalid": invalid,
    }
    if changed or payload.get("generated_at") is None:
        _atomic_write_json(idx_path, new_payload)
    return new_payload


def refresh_runtime_index(fabric_dir: Path, changed_paths: list[Path] | None = None, logger=None) -> dict:
    """Refresh the runtime index after writes or metadata updates."""
    fabric_dir = Path(fabric_dir)
    idx_path = index_path(fabric_dir)
    payload = None
    if idx_path.exists():
        try:
            payload = _normalize_index_payload(json.loads(idx_path.read_text(encoding="utf-8")))
        except Exception:
            payload = None
    if payload is None:
        return load_runtime_index(fabric_dir, logger=logger)

    records = dict(payload.get("records", {}))
    invalid = 0
    changed = False
    paths = changed_paths or _scan_files(fabric_dir)

    for raw_path in paths:
        filepath = Path(raw_path)
        rel_path = _relative_key(filepath, fabric_dir)
        if not filepath.exists():
            if rel_path in records:
                del records[rel_path]
                changed = True
            continue
        record = _record_from_file(filepath, fabric_dir, logger=logger)
        changed = True
        if record is None:
            records.pop(rel_path, None)
            invalid += 1
            continue
        records[rel_path] = record

    new_payload = {
        "version": INDEX_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "records": records,
        "invalid": invalid,
    }
    if changed:
        _atomic_write_json(idx_path, new_payload)
    return new_payload


def load_runtime_entries(fabric_dir: Path, logger=None) -> list[dict]:
    payload = load_runtime_index(fabric_dir, logger=logger)
    records = list(payload.get("records", {}).values())
    records.sort(key=lambda e: (str(e.get("timestamp", "")), str(e.get("path", ""))), reverse=True)
    return records


def read_entry_text(fabric_dir: Path, record: dict) -> str:
    rel_path = record.get("path", "")
    if not rel_path:
        return ""
    filepath = Path(fabric_dir) / rel_path
    try:
        return filepath.read_text(encoding="utf-8")
    except Exception:
        return ""
