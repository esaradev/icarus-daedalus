from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from ..db import get_db
from ..maintenance.scorer import corpus_health
from ..wiki import bridge, reader

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("/status")
def maintenance_status(db: DBSession = Depends(get_db)):
    health = corpus_health(db)
    try:
        report = bridge.load().maintenance_report(reader.fabric_dir()) if hasattr(bridge.load(), "maintenance_report") else {}
    except Exception:
        report = {}
    try:
        lint = bridge.lint(reader.fabric_dir())
    except Exception:
        lint = {}
    return {
        "corpus": health,
        "fabric": {
            "total": report.get("total", 0),
            "cold_count": report.get("cold_count", 0),
            "duplicate_count": len(report.get("duplicate_candidates", [])),
            "stale_count": len(report.get("stale_candidates", [])),
            "by_type": report.get("by_type", {}),
        },
        "wiki": {
            "page_count": lint.get("page_count", 0),
            "broken_links": len(lint.get("broken_links", [])),
            "orphan_pages": len(lint.get("orphan_pages", [])),
        },
    }
