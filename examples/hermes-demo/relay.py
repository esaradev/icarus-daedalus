#!/usr/bin/env python3
"""Message relay between Icarus and Daedalus.

Usage:
    python3 relay.py send <from> <to> <message>
    python3 relay.py read <agent>          # read unread messages, mark as read
    python3 relay.py peek <agent>          # read unread messages, don't mark
    python3 relay.py history [n]           # last n messages (default 20)
    python3 relay.py unread <agent>        # count of unread messages
"""

import sqlite3
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "messages.db"


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_agent TEXT NOT NULL,
            to_agent TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            read_at TEXT
        )
    """)
    db.commit()
    return db


def send(from_agent, to_agent, content):
    db = get_db()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        "INSERT INTO messages (from_agent, to_agent, content, timestamp) VALUES (?, ?, ?, ?)",
        (from_agent, to_agent, content, ts),
    )
    db.commit()
    print(json.dumps({"status": "sent", "from": from_agent, "to": to_agent, "timestamp": ts}))


def read(agent, mark_read=True):
    db = get_db()
    rows = db.execute(
        "SELECT id, from_agent, content, timestamp FROM messages WHERE to_agent = ? AND read_at IS NULL ORDER BY id",
        (agent,),
    ).fetchall()
    messages = [{"id": r["id"], "from": r["from_agent"], "content": r["content"], "timestamp": r["timestamp"]} for r in rows]
    if mark_read and rows:
        ids = [r["id"] for r in rows]
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.execute(f"UPDATE messages SET read_at = ? WHERE id IN ({','.join('?' * len(ids))})", [ts] + ids)
        db.commit()
    print(json.dumps({"agent": agent, "unread_count": len(messages), "messages": messages}, indent=2))


def history(n=20):
    db = get_db()
    rows = db.execute(
        "SELECT from_agent, to_agent, content, timestamp, read_at FROM messages ORDER BY id DESC LIMIT ?",
        (n,),
    ).fetchall()
    messages = [
        {"from": r["from_agent"], "to": r["to_agent"], "content": r["content"], "timestamp": r["timestamp"], "read": r["read_at"] is not None}
        for r in reversed(rows)
    ]
    print(json.dumps({"total": len(messages), "messages": messages}, indent=2))


def unread_count(agent):
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM messages WHERE to_agent = ? AND read_at IS NULL",
        (agent,),
    ).fetchone()[0]
    print(json.dumps({"agent": agent, "unread": count}))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "send" and len(sys.argv) >= 5:
        send(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
    elif cmd == "read" and len(sys.argv) >= 3:
        read(sys.argv[2], mark_read=True)
    elif cmd == "peek" and len(sys.argv) >= 3:
        read(sys.argv[2], mark_read=False)
    elif cmd == "history":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        history(n)
    elif cmd == "unread" and len(sys.argv) >= 3:
        unread_count(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
