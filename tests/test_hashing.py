from __future__ import annotations

from pathlib import Path

from icarus_memory.hashing import sha256_bytes, sha256_file, sha256_text


def test_sha256_text_matches_known_value() -> None:
    # echo -n hello | sha256sum
    assert (
        sha256_text("hello")
        == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_sha256_bytes_round_trip() -> None:
    assert sha256_bytes(b"hello") == sha256_text("hello")


def test_sha256_file_matches(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello")
    assert sha256_file(p) == sha256_text("hello")
