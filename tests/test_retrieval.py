from __future__ import annotations

import pytest

from icarus_memory import IcarusMemory


def _seed(mem: IcarusMemory) -> dict[str, str]:
    a = mem.write(agent="t", type="decision", summary="postgres for users")
    b = mem.write(agent="t", type="decision", summary="redis for caching")
    c = mem.write(agent="t", type="decision", summary="mysql for users")
    return {"pg": a.id, "redis": b.id, "mysql": c.id}


def test_recall_keyword_returns_matches(mem: IcarusMemory) -> None:
    ids = _seed(mem)
    hits = mem.recall("users", mode="keyword")
    matched = {h.entry.id for h in hits}
    assert ids["pg"] in matched
    assert ids["mysql"] in matched
    assert ids["redis"] not in matched


def test_recall_orders_verified_above_unverified(mem: IcarusMemory) -> None:
    ids = _seed(mem)
    mem.verify(ids["mysql"], note="we changed our mind")
    hits = mem.recall("users", mode="keyword")
    assert hits[0].entry.id == ids["mysql"]


def test_recall_excludes_rolled_back_by_default(mem: IcarusMemory) -> None:
    ids = _seed(mem)
    mem.verify(ids["pg"])
    new_pg = mem.write(
        agent="t", type="decision", summary="postgres on users", revises=ids["pg"]
    )
    mem.contradict(new_pg.id, contradicted_by=ids["pg"], reason="bad idea")
    plan = mem.rollback(new_pg.id, dry_run=False)
    assert plan.applied is True

    hits = mem.recall("postgres", mode="keyword")
    matched = {h.entry.id for h in hits}
    assert new_pg.id not in matched
    assert ids["pg"] in matched


def test_recall_min_verified_filter(mem: IcarusMemory) -> None:
    ids = _seed(mem)
    mem.verify(ids["pg"])
    hits = mem.recall("users", mode="keyword", min_verified="verified")
    assert {h.entry.id for h in hits} == {ids["pg"]}


def test_recall_filters_by_agent(mem: IcarusMemory) -> None:
    a = mem.write(agent="alice", type="decision", summary="postgres for users")
    mem.write(agent="bob", type="decision", summary="postgres for billing")
    hits = mem.recall("postgres", mode="keyword", agent="alice")
    assert [h.entry.id for h in hits] == [a.id]


def test_keyword_search(mem: IcarusMemory) -> None:
    ids = _seed(mem)
    res = mem.search("redis")
    assert {e.id for e in res} == {ids["redis"]}


def test_recall_empty_query_returns_nothing(mem: IcarusMemory) -> None:
    _seed(mem)
    assert mem.recall("", mode="keyword") == []


def test_recall_hybrid_without_extra_raises_clear_error(mem: IcarusMemory) -> None:
    _seed(mem)
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="\\[embeddings\\]"):
            mem.recall("postgres", mode="hybrid")
    else:
        pytest.skip("embeddings extra installed; skipping the negative path")
