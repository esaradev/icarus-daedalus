from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

from ..db import SessionLocal
from ..models import IngestCursor
from .fabric_backfill import backfill
from .handlers import dispatch

logger = logging.getLogger("icarus.ingest")


def _cursor(db, source: str) -> IngestCursor:
    row = db.get(IngestCursor, source)
    if row is None:
        row = IngestCursor(source=source, byte_offset=0)
        db.add(row)
        db.flush()
    return row


def ingest_once(path: Path) -> int:
    count = 0
    db = SessionLocal()
    try:
        cur = _cursor(db, str(path))
        if not path.exists():
            return 0
        size = path.stat().st_size
        if cur.byte_offset > size:
            cur.byte_offset = 0
        with path.open("rb") as f:
            f.seek(cur.byte_offset)
            while True:
                line = f.readline()
                if not line:
                    break
                if not line.strip():
                    cur.byte_offset = f.tell()
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("[ingest] skipped invalid json at byte %s in %s", cur.byte_offset, path)
                    cur.byte_offset = f.tell()
                    continue
                try:
                    with db.begin_nested():
                        handled = dispatch(db, evt)
                        db.flush()
                except Exception as exc:
                    logger.warning("[ingest] skipped event at byte %s in %s: %s", cur.byte_offset, path, exc)
                else:
                    if handled:
                        count += 1
                cur.byte_offset = f.tell()
        db.commit()
        return count
    finally:
        db.close()


def sync_once(fabric_dir: Path, events_path: Path | None = None) -> dict[str, int]:
    events = events_path or (fabric_dir / "events.jsonl")
    events.parent.mkdir(parents=True, exist_ok=True)
    appended = backfill(fabric_dir, events)
    applied = ingest_once(events)
    return {"appended": appended, "applied": applied}


def watch(path: Path, interval: float = 2.0) -> None:
    while True:
        n = ingest_once(path)
        if n:
            print(f"[ingest] applied {n} events from {path}", flush=True)
        time.sleep(interval)


async def run_forever(fabric_dir: Path, interval: float = 2.0) -> None:
    events_path = fabric_dir / "events.jsonl"
    logger.info("[ingest] worker enabled (fabric=%s events=%s)", fabric_dir, events_path)
    while True:
        result = await asyncio.to_thread(sync_once, fabric_dir, events_path)
        if result["appended"] or result["applied"]:
            logger.info(
                "[ingest] synced events appended=%s applied=%s",
                result["appended"],
                result["applied"],
            )
        await asyncio.sleep(interval)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()
    path = Path(args.file).expanduser()
    if args.once:
        print(f"[ingest] {ingest_once(path)} events applied")
    else:
        watch(path, interval=args.interval)


if __name__ == "__main__":
    main()
