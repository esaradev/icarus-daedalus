"""Lazy singleton wrapper around IcarusMemory.

Resolves the fabric root from ICARUS_FABRIC_ROOT (matching the substrate's
own resolution rule), defaulting to ~/fabric. The dashboard reads the
substrate; it never writes new endpoints into icarus-memory itself.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from icarus_memory import IcarusMemory

DEFAULT_ROOT = "~/fabric"
ROOT_ENV = "ICARUS_FABRIC_ROOT"


def fabric_root() -> Path:
    return Path(os.environ.get(ROOT_ENV) or DEFAULT_ROOT).expanduser()


def fabric_exists() -> bool:
    return fabric_root().exists()


@lru_cache(maxsize=1)
def get_memory() -> IcarusMemory:
    return IcarusMemory(root=fabric_root())
