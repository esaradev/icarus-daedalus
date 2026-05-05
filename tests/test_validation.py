from __future__ import annotations

import pytest

from icarus_memory import IcarusMemory, ValidationError


def test_open_status_requires_assigned_to(mem: IcarusMemory) -> None:
    with pytest.raises(ValidationError):
        mem.write(agent="t", type="task", summary="do x", status="open")
    mem.write(
        agent="t", type="task", summary="do x", status="open", assigned_to="me"
    )


def test_review_type_requires_review_of(mem: IcarusMemory) -> None:
    with pytest.raises(ValidationError):
        mem.write(agent="t", type="review", summary="reviewed something")
    target = mem.write(agent="t", type="decision", summary="orig")
    mem.write(
        agent="t", type="review", summary="reviewed", review_of=target.id
    )


def test_revises_must_resolve(mem: IcarusMemory) -> None:
    with pytest.raises(ValidationError):
        mem.write(
            agent="t", type="decision", summary="x", revises="icarus:000000000000"
        )


def test_review_of_must_resolve(mem: IcarusMemory) -> None:
    with pytest.raises(ValidationError):
        mem.write(
            agent="t",
            type="review",
            summary="x",
            review_of="icarus:000000000000",
        )


def test_evidence_fabric_ref_must_resolve(mem: IcarusMemory) -> None:
    with pytest.raises(ValidationError):
        mem.write(
            agent="t",
            type="decision",
            summary="x",
            evidence=[{"kind": "fabric_ref", "ref": "icarus:000000000000"}],
        )
    target = mem.write(agent="t", type="decision", summary="orig")
    mem.write(
        agent="t",
        type="decision",
        summary="x",
        evidence=[{"kind": "fabric_ref", "ref": target.id}],
    )


def test_evidence_non_fabric_ref_not_validated(mem: IcarusMemory) -> None:
    mem.write(
        agent="t",
        type="decision",
        summary="x",
        evidence=[{"kind": "file", "ref": "any/path/that/does/not/exist.py"}],
    )


def test_contradict_requires_existing_target(mem: IcarusMemory) -> None:
    target = mem.write(agent="t", type="decision", summary="orig")
    with pytest.raises(ValidationError):
        mem.contradict(
            target.id,
            contradicted_by="icarus:000000000000",
            reason="bogus pointer",
        )


def test_evidence_missing_kind_rejected(mem: IcarusMemory) -> None:
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        mem.write(
            agent="t",
            type="decision",
            summary="x",
            evidence=[{"ref": "x"}],  # missing kind
        )
