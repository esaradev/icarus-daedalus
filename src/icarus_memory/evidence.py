"""Evidence verification helpers."""

from __future__ import annotations

from pathlib import Path

from .hashing import sha256_file, sha256_text
from .schema import Entry, EvidencePointer


def verify_entry_evidence(entry: Entry, *, root: Path) -> None:
    """Raise ValueError if any evidence with a hash does not match."""
    for ev in entry.evidence:
        _verify_pointer(ev, root=root)


def _verify_pointer(ev: EvidencePointer, *, root: Path) -> None:
    if not ev.hash:
        return
    if ev.kind == "file":
        p = Path(ev.ref).expanduser()
        if not p.is_absolute():
            p = (root / p).resolve()
        if not p.exists() or not p.is_file():
            raise ValueError(f"evidence file missing: {ev.ref}")
        actual = sha256_file(p)
        if actual != ev.hash:
            raise ValueError(f"evidence hash mismatch for {ev.ref}")
        return
    if ev.kind in {"message", "tool_output"}:
        actual = sha256_text(ev.ref)
        if actual != ev.hash:
            raise ValueError(f"evidence hash mismatch for {ev.kind}:{ev.ref[:40]}")
        return
    return
