from __future__ import annotations

from pathlib import Path

import pytest

from icarus_memory import IcarusMemory


@pytest.fixture()
def fabric_root(tmp_path: Path) -> Path:
    return tmp_path / "fabric"


@pytest.fixture()
def mem(fabric_root: Path) -> IcarusMemory:
    return IcarusMemory(root=fabric_root)
