"""Typed exceptions for icarus-memory."""

from __future__ import annotations


class IcarusMemoryError(Exception):
    """Base class for all icarus-memory errors."""


class StoreError(IcarusMemoryError):
    """Raised on read/write failures from the on-disk store."""


class EntryNotFound(StoreError):
    """Raised when an entry id does not resolve to a file in the store."""


class ValidationError(IcarusMemoryError):
    """Raised when an entry violates a write-time invariant."""


class IllegalStateTransition(ValidationError):
    """Raised when a verification state transition is not allowed."""

    def __init__(
        self,
        *,
        entry_id: str,
        from_state: str,
        to_state: str,
        reason: str,
    ):
        self.entry_id = entry_id
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        super().__init__(
            f"illegal state transition for {entry_id}: "
            f"{from_state} -> {to_state}: {reason}"
        )


class RollbackError(IcarusMemoryError):
    """Raised when a rollback cannot be planned or applied."""
