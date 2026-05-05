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


class RollbackError(IcarusMemoryError):
    """Raised when a rollback cannot be planned or applied."""
