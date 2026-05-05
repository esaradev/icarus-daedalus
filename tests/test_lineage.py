from __future__ import annotations

from icarus_memory import IcarusMemory


def test_lineage_walks_revises_chain(mem: IcarusMemory) -> None:
    a = mem.write(agent="t", type="decision", summary="A")
    b = mem.write(agent="t", type="decision", summary="B", revises=a.id)
    c = mem.write(agent="t", type="decision", summary="C", revises=b.id)
    chain = [e.id for e in mem.lineage(c.id)]
    assert chain == [c.id, b.id, a.id]


def test_lineage_includes_review_of(mem: IcarusMemory) -> None:
    a = mem.write(agent="t", type="decision", summary="A")
    review = mem.write(
        agent="t", type="review", summary="reviewed A", review_of=a.id
    )
    chain = {e.id for e in mem.lineage(review.id)}
    assert chain == {review.id, a.id}


def test_lineage_handles_missing_link_gracefully(mem: IcarusMemory) -> None:
    a = mem.write(agent="t", type="decision", summary="A")
    chain = mem.lineage(a.id)
    assert [e.id for e in chain] == [a.id]
