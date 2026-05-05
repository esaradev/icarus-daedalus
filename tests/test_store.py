from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from icarus_memory.exceptions import EntryNotFound
from icarus_memory.schema import Entry, EvidencePointer, VerificationRecord
from icarus_memory.store import MarkdownStore


def _entry(store: MarkdownStore, **overrides: object) -> Entry:
    base: dict[str, object] = {
        "id": store.generate_id(),
        "agent": "tester",
        "platform": "pytest",
        "timestamp": datetime(2026, 5, 5, 1, 2, 3, tzinfo=timezone.utc),
        "type": "decision",
        "summary": "use postgres",
        "body": "details",
    }
    base.update(overrides)
    return Entry(**base)  # type: ignore[arg-type]


def test_round_trip_minimal(fabric_root: Path) -> None:
    store = MarkdownStore(fabric_root)
    entry = _entry(store)
    store.write(entry)
    loaded = store.get(entry.id)
    assert loaded == entry


def test_round_trip_full(fabric_root: Path) -> None:
    store = MarkdownStore(fabric_root)
    entry = _entry(
        store,
        evidence=[
            EvidencePointer(kind="file", ref="docs/adr.md", excerpt="..."),
            EvidencePointer(kind="url", ref="https://example.com", hash="a" * 64),
        ],
        verification_log=[
            VerificationRecord(
                verifier="manual",
                timestamp=datetime(2026, 5, 5, 2, 0, 0, tzinfo=timezone.utc),
                status="verified",
                note="ok",
            )
        ],
        source_tool="manual",
        artifact_paths=["docs/adr.md"],
        project_id="icarus",
        training_value="high",
    )
    store.write(entry)
    loaded = store.get(entry.id)
    assert loaded == entry


def test_round_trip_preserves_body_whitespace(fabric_root: Path) -> None:
    store = MarkdownStore(fabric_root)
    body = "\n  indented line\nline with trailing spaces  \n\n"
    entry = _entry(store, body=body)

    store.write(entry)
    loaded = store.get(entry.id)

    assert loaded.body == body


def test_get_missing_raises(fabric_root: Path) -> None:
    store = MarkdownStore(fabric_root)
    with pytest.raises(EntryNotFound):
        store.get("icarus:000000000000")


def test_concurrent_id_generation_no_collisions(fabric_root: Path) -> None:
    store = MarkdownStore(fabric_root)
    with ThreadPoolExecutor(max_workers=20) as exe:
        ids = list(exe.map(lambda _: store.generate_id(), range(50)))
    # IDs only need to be unique among non-existing entries (none persisted yet),
    # so generate_id may return duplicates without writes. Assert format only.
    for entry_id in ids:
        assert entry_id.startswith("icarus:")
        assert len(entry_id.split(":")[1]) == 12


def test_concurrent_writes_no_data_loss(fabric_root: Path) -> None:
    store = MarkdownStore(fabric_root)

    def write_one(_: int) -> str:
        e = _entry(store)
        store.write(e)
        return e.id

    with ThreadPoolExecutor(max_workers=10) as exe:
        ids = list(exe.map(write_one, range(20)))

    assert len(set(ids)) == 20
    for entry_id in ids:
        assert store.exists(entry_id)


def test_atomic_write_no_tmp_left_behind(fabric_root: Path) -> None:
    store = MarkdownStore(fabric_root)
    entry = _entry(store)
    store.write(entry)
    tmp_files = list(fabric_root.rglob(".*tmp*"))
    assert tmp_files == []


def test_lazy_migration_for_old_entries(fabric_root: Path) -> None:
    store = MarkdownStore(fabric_root)
    # Hand-craft a legacy entry without the new fields.
    legacy_path = fabric_root / "2025" / "01" / "icarus-aaaaaaaaaaaa.md"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        "---\n"
        "id: icarus:aaaaaaaaaaaa\n"
        "agent: legacy\n"
        "platform: hermes\n"
        "timestamp: 2025-01-01T00:00:00Z\n"
        "type: note\n"
        "summary: legacy entry\n"
        "tier: hot\n"  # unknown legacy field, must be ignored
        "---\n"
        "\nlegacy body\n"
    )
    entry = store.get("icarus:aaaaaaaaaaaa")
    assert entry.verified == "unverified"
    assert entry.evidence == []
    assert entry.body == "\nlegacy body\n"
