"""Cross-process advisory file locks (stdlib-only)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import IO


class FileLock:
    def __init__(
        self,
        path: str | Path,
        *,
        timeout_s: float = 10.0,
        poll_s: float = 0.05,
    ):
        self.path = Path(path)
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self._fh: IO[str] | None = None
        self._owner_pid: int | None = None
        self._depth = 0

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.release()

    def acquire(self) -> None:
        pid = os.getpid()
        if self._owner_pid == pid and self._fh is not None:
            self._depth += 1
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+", encoding="utf-8")  # noqa: SIM115
        start = time.monotonic()
        try:
            while True:
                try:
                    _lock_exclusive_nonblocking(fh)
                    self._fh = fh
                    self._owner_pid = pid
                    self._depth = 1
                    return
                except BlockingIOError:
                    if time.monotonic() - start >= self.timeout_s:
                        raise TimeoutError(f"timed out acquiring lock {self.path}") from None
                    time.sleep(self.poll_s)
        except Exception:
            fh.close()
            raise

    def release(self) -> None:
        fh = self._fh
        if fh is None:
            return
        if self._owner_pid == os.getpid() and self._depth > 1:
            self._depth -= 1
            return
        self._fh = None
        self._owner_pid = None
        self._depth = 0
        try:
            _unlock(fh)
        finally:
            fh.close()


def _lock_exclusive_nonblocking(fh: IO[str]) -> None:
    if os.name == "nt":  # pragma: no cover
        import msvcrt

        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc
        return

    import fcntl

    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fh: IO[str]) -> None:
    if os.name == "nt":  # pragma: no cover
        import msvcrt

        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        return

    import fcntl

    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
