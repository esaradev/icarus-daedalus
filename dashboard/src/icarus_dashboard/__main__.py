"""Entry point: ``python -m icarus_dashboard``."""

from __future__ import annotations

import os

import uvicorn

from .app import app


def main() -> None:
    host = os.environ.get("ICARUS_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("ICARUS_DASHBOARD_PORT", "5170"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
