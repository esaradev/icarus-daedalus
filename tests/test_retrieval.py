from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from icarus_memory import IcarusMemory, ValidationError


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
    with pytest.raises(ValidationError):
        mem.recall("", mode="keyword")


def test_recall_hybrid_without_extra_raises_clear_error(mem: IcarusMemory) -> None:
    _seed(mem)
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="\\[embeddings\\]"):
            mem.recall("postgres", mode="hybrid")
    else:
        pytest.skip("embeddings extra installed; skipping the negative path")


def test_recall_hybrid_paraphrase_returns_expected_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hybrid recall should use embedding signal when BM25 terms differ."""

    class FakeScores(list[float]):
        def __neg__(self) -> list[float]:
            return [-score for score in self]

    class FakeMatrix:
        def __init__(self, rows: list[list[float]]):
            self.rows = rows

        def __matmul__(self, vector: list[float]) -> FakeScores:
            return FakeScores(
                [sum(a * b for a, b in zip(row, vector, strict=True)) for row in self.rows]
            )

    class FakeNumpy(types.ModuleType):
        def asarray(self, value: Any) -> Any:
            return value

        def stack(self, rows: list[list[float]]) -> FakeMatrix:
            return FakeMatrix(rows)

        def argsort(self, values: list[float]) -> list[int]:
            return sorted(range(len(values)), key=lambda index: values[index])

        def save(self, path: Path, vector: list[float]) -> None:
            path.write_text(json.dumps(vector), encoding="utf-8")

        def load(self, path: Path) -> list[float]:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, list):
                raise AssertionError("fake numpy cache must contain a list")
            return [float(item) for item in loaded]

    class FakeSentenceTransformer:
        def __init__(self, model_name: str):
            self.model_name = model_name

        def encode(
            self, texts: list[str], normalize_embeddings: bool = True
        ) -> list[list[float]]:
            del normalize_embeddings
            vectors: list[list[float]] = []
            for text in texts:
                low = text.lower()
                if "born" in low or "birthday" in low:
                    vectors.append([1.0, 0.0])
                else:
                    vectors.append([0.0, 1.0])
            return vectors

    class FakeBM25Okapi:
        def __init__(self, docs: list[list[str]]):
            self.docs = docs

        def get_scores(self, query_tokens: list[str]) -> list[float]:
            query = {token for token in query_tokens if token != "alice"}
            return [float(len(query.intersection(doc))) for doc in self.docs]

    fake_sentence_transformers = types.ModuleType("sentence_transformers")
    fake_sentence_transformers.SentenceTransformer = FakeSentenceTransformer  # type: ignore[attr-defined]
    fake_rank_bm25 = types.ModuleType("rank_bm25")
    fake_rank_bm25.BM25Okapi = FakeBM25Okapi  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "numpy", FakeNumpy("numpy"))
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_sentence_transformers)
    monkeypatch.setitem(sys.modules, "rank_bm25", fake_rank_bm25)
    sys.modules.pop("icarus_memory._embeddings", None)

    mem = IcarusMemory(root=tmp_path)
    expected = mem.write(
        agent="tester",
        type="fact",
        summary="Alice's birthday is 1990-01-01",
        body="Alice's birthday is 1990-01-01.",
    )
    mem.write(
        agent="tester",
        type="fact",
        summary="Alice likes espresso",
        body="Alice likes espresso.",
    )

    hits = mem.recall("when was Alice born", k=1, mode="hybrid")

    assert [hit.entry.id for hit in hits] == [expected.id]
    assert (tmp_path / ".cache" / "embeddings").exists()
