from __future__ import annotations

import json

from app.models import Agent, MemoryEntry
from app.ingest import watcher
from app.ingest.fabric_backfill import backfill


def test_sync_once_backfills_fabric_markdown_into_events_and_db(test_env):
    fabric_dir = test_env["fabric_dir"]
    SessionLocal = test_env["SessionLocal"]

    entry = fabric_dir / "decision.md"
    entry.write_text(
        "\n".join([
            "---",
            'timestamp: "2026-04-16T12:00:00Z"',
            'agent: "Icarus"',
            'platform: "hermes"',
            'session_id: "s-1"',
            'project_id: "icarus-daedalus"',
            'type: "decision"',
            'summary: "Use JSONL ingest"',
            "---",
            "Keep Hermes integration file-based for MVP.",
        ]),
        encoding="utf-8",
    )

    result = watcher.sync_once(fabric_dir)

    assert result["appended"] >= 3
    assert result["applied"] >= 3
    assert (fabric_dir / "events.jsonl").exists()

    with SessionLocal() as db:
        assert db.query(Agent).filter(Agent.id == "icarus").one_or_none() is not None
        memory = db.query(MemoryEntry).one()
        assert memory.title == "Use JSONL ingest"
        assert memory.source == "fabric_backfill"


def test_ingest_once_skips_bad_event_and_continues(test_env):
    fabric_dir = test_env["fabric_dir"]
    SessionLocal = test_env["SessionLocal"]
    events = fabric_dir / "events.jsonl"
    events.write_text(
        "\n".join([
            json.dumps({"type": "agent.status", "agent_id": "icarus", "name": "Icarus", "at": "2026-04-16T12:00:00Z"}),
            json.dumps({"type": "agent.status", "name": "Missing agent id", "at": "2026-04-16T12:01:00Z"}),
            json.dumps({"type": "memory.write", "agent_id": "icarus", "kind": "fact", "title": "Still ingests", "body": "after bad event", "at": "2026-04-16T12:02:00Z"}),
        ]) + "\n",
        encoding="utf-8",
    )

    applied = watcher.ingest_once(events)
    assert applied == 2

    with SessionLocal() as db:
        assert db.query(Agent).filter(Agent.id == "icarus").one_or_none() is not None
        memory = db.query(MemoryEntry).filter(MemoryEntry.title == "Still ingests").one_or_none()
        assert memory is not None


def test_backfill_does_not_drop_older_markdown_when_newer_live_events_exist(test_env):
    fabric_dir = test_env["fabric_dir"]
    SessionLocal = test_env["SessionLocal"]
    events = fabric_dir / "events.jsonl"
    events.write_text(
        json.dumps({
            "type": "agent.status",
            "agent_id": "live-agent",
            "name": "Live Agent",
            "at": "2026-04-17T12:00:00Z",
            "source": "events_jsonl",
        }) + "\n",
        encoding="utf-8",
    )

    entry = fabric_dir / "older.md"
    entry.write_text(
        "\n".join([
            "---",
            'timestamp: "2026-04-16T12:00:00Z"',
            'agent: "Icarus"',
            'platform: "hermes"',
            'session_id: "s-older"',
            'project_id: "icarus-daedalus"',
            'type: "fact"',
            'summary: "Older note"',
            "---",
            "This older markdown should still backfill.",
        ]),
        encoding="utf-8",
    )

    written = backfill(fabric_dir, events)
    assert written >= 3

    applied = watcher.ingest_once(events)
    assert applied >= 4

    with SessionLocal() as db:
        memory = db.query(MemoryEntry).filter(MemoryEntry.title == "Older note").one_or_none()
        assert memory is not None
        assert memory.source == "fabric_backfill"
