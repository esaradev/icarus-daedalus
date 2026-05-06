"""Pydantic v2 models for the icarus-memory data model."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

EvidenceKind = Literal["file", "url", "fabric_ref", "tool_output", "message"]
VerifiedStatus = Literal["unverified", "verified", "contradicted", "rolled_back"]
# Lifecycle is orthogonal to verified: verified is about provenance/trust,
# lifecycle is about freshness. A fact can be unverified-and-active or
# verified-and-superseded. They live in separate fields so callers can
# combine them without overloading either.
Lifecycle = Literal["active", "superseded"]
TrainingValue = Literal["high", "normal", "low"]
EntryStatus = Literal["open", "in-progress", "closed"]

ID_PATTERN = re.compile(r"^icarus:[0-9a-f]{12}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

EntryId = Annotated[str, StringConstraints(pattern=r"^icarus:[0-9a-f]{12}$")]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class EvidencePointer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    ref: str = Field(min_length=1)
    excerpt: str | None = Field(default=None, max_length=500)
    hash: str | None = None

    @field_validator("hash")
    @classmethod
    def _check_hash(cls, v: str | None) -> str | None:
        if v is not None and not SHA256_PATTERN.match(v):
            raise ValueError("hash must be lowercase hex sha256 (64 chars)")
        return v


class VerificationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verifier: str = Field(min_length=1)
    timestamp: datetime
    status: Literal["verified", "contradicted", "rolled_back"]
    note: str = ""


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: EntryId
    agent: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    timestamp: datetime
    type: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=200)
    body: str = ""

    project_id: str | None = None
    session_id: str | None = None
    status: EntryStatus | None = None
    assigned_to: str | None = None
    review_of: EntryId | None = None
    revises: EntryId | None = None
    training_value: TrainingValue = "normal"

    evidence: list[EvidencePointer] = Field(default_factory=list)
    source_tool: str | None = None
    verified: VerifiedStatus = "unverified"
    contradicted_by: EntryId | None = None
    artifact_paths: list[str] = Field(default_factory=list)
    verification_log: list[VerificationRecord] = Field(default_factory=list)

    lifecycle: Lifecycle = "active"
    superseded_by: EntryId | None = None
    supersedes: list[EntryId] = Field(default_factory=list)

    @field_validator("timestamp")
    @classmethod
    def _ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).replace(microsecond=0)


class RollbackPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: EntryId
    verified_ancestor: EntryId | None = None
    intermediate: list[EntryId] = Field(default_factory=list)
    tainted_descendants: list[EntryId] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    applied: bool = False
    rollback_entry_id: EntryId | None = None


class RecallHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: Entry
    score: float
    matched_terms: list[str] = Field(default_factory=list)


__all__ = [
    "ID_PATTERN",
    "SHA256_PATTERN",
    "Entry",
    "EntryStatus",
    "EvidenceKind",
    "EvidencePointer",
    "Lifecycle",
    "RecallHit",
    "RollbackPlan",
    "TrainingValue",
    "VerificationRecord",
    "VerifiedStatus",
]
