from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError as PydanticValidationError

from icarus_memory.schema import (
    Entry,
    EvidencePointer,
    VerificationRecord,
)


def _base(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "icarus:0123456789ab",
        "agent": "tester",
        "platform": "pytest",
        "timestamp": datetime(2026, 5, 5, 1, 2, 3, tzinfo=timezone.utc),
        "type": "decision",
        "summary": "use postgres",
        "body": "we picked postgres because...",
    }
    base.update(overrides)
    return base


def test_entry_round_trip_minimal() -> None:
    entry = Entry(**_base())  # type: ignore[arg-type]
    dumped = entry.model_dump(mode="json")
    rebuilt = Entry.model_validate(dumped)
    assert rebuilt == entry


def test_entry_round_trip_full() -> None:
    entry = Entry(
        **_base(
            evidence=[
                EvidencePointer(
                    kind="file", ref="docs/adr.md", excerpt="we will use postgres"
                ).model_dump(),
                EvidencePointer(kind="fabric_ref", ref="icarus:abcdef012345").model_dump(),
            ],
            verification_log=[
                VerificationRecord(
                    verifier="manual",
                    timestamp=datetime(2026, 5, 5, 2, 0, 0, tzinfo=timezone.utc),
                    status="verified",
                    note="confirmed by team",
                ).model_dump()
            ],
            source_tool="manual",
            artifact_paths=["docs/adr.md"],
            project_id="icarus",
            session_id="sess-1",
            training_value="high",
        )  # type: ignore[arg-type]
    )
    rebuilt = Entry.model_validate(entry.model_dump(mode="json"))
    assert rebuilt == entry


def test_id_format_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        Entry(**_base(id="not-an-id"))  # type: ignore[arg-type]
    with pytest.raises(PydanticValidationError):
        Entry(**_base(id="icarus:UPPER12345A"))  # type: ignore[arg-type]
    with pytest.raises(PydanticValidationError):
        Entry(**_base(id="icarus:short"))  # type: ignore[arg-type]


def test_summary_length_capped() -> None:
    with pytest.raises(PydanticValidationError):
        Entry(**_base(summary="x" * 201))  # type: ignore[arg-type]


def test_evidence_excerpt_length_capped() -> None:
    with pytest.raises(PydanticValidationError):
        EvidencePointer(kind="file", ref="x", excerpt="x" * 501)


def test_evidence_hash_format() -> None:
    EvidencePointer(kind="file", ref="x", hash="a" * 64)
    with pytest.raises(PydanticValidationError):
        EvidencePointer(kind="file", ref="x", hash="not-a-hash")


def test_naive_timestamp_coerced_to_utc() -> None:
    naive = datetime(2026, 5, 5, 1, 2, 3)
    entry = Entry(**_base(timestamp=naive))  # type: ignore[arg-type]
    assert entry.timestamp.tzinfo == timezone.utc
