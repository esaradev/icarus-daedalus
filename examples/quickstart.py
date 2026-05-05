"""Run with: python examples/quickstart.py"""

from __future__ import annotations

import tempfile

from icarus_memory import IcarusMemory


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mem = IcarusMemory(root=tmp)

        a = mem.write(
            agent="builder",
            type="decision",
            summary="chose postgres for user service",
            body="See ADR for full reasoning.",
            evidence=[
                {
                    "kind": "file",
                    "ref": "docs/adr/0007-database.md",
                    "excerpt": "We will use PostgreSQL because...",
                }
            ],
            source_tool="manual",
            training_value="high",
        )
        print("wrote", a.id)

        mem.verify(a.id, note="confirmed by team review")
        print("verified", a.id)

        b = mem.write(
            agent="builder",
            type="decision",
            summary="chose mysql instead",
            body="Bad idea, will be reverted.",
            revises=a.id,
        )
        mem.contradict(b.id, contradicted_by=a.id, reason="superseded by ADR-0007")
        print("contradicted", b.id)

        plan = mem.rollback(b.id, dry_run=True)
        print("rollback plan ancestor:", plan.verified_ancestor)
        print("intermediate:", plan.intermediate)

        applied = mem.rollback(b.id, dry_run=False)
        print("applied; rollback entry:", applied.rollback_entry_id)

        for hit in mem.recall("postgres", mode="keyword"):
            print(f"recall: {hit.entry.id} [{hit.entry.verified}] {hit.entry.summary}")


if __name__ == "__main__":
    main()
