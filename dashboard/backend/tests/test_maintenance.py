from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Agent, MemoryEntry
from app.maintenance.scorer import corpus_health


def test_corpus_health_counts_full_corpus_not_just_latest_500(test_env):
    SessionLocal = test_env["SessionLocal"]
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        db.add(Agent(id="icarus", name="Icarus"))
        db.add_all(
            [
                MemoryEntry(
                    author_agent_id="icarus",
                    kind="fact",
                    title=f"Entry {i}",
                    body="body",
                    created_at=now - timedelta(minutes=i),
                    updated_at=now - timedelta(minutes=i),
                )
                for i in range(505)
            ]
        )
        db.commit()

        health = corpus_health(db)

    assert health["total"] == 505
    assert sum(bucket["count"] for bucket in health["distribution"]) == 505
