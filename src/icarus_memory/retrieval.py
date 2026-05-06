"""Recall and search over the on-disk fabric."""

from __future__ import annotations

import re
from typing import Literal

from .schema import Entry, RecallHit, VerifiedStatus
from .store import MarkdownStore

RecallMode = Literal["auto", "keyword", "embedding", "embeddings", "hybrid"]
StatusFilter = Literal["safe", "all", "verified_only"]

_TOKEN_RE = re.compile(r"\w+")
_VERIFIED_ORDER: dict[VerifiedStatus, int] = {
    "verified": 0,
    "unverified": 1,
    "contradicted": 2,
    "rolled_back": 3,
}
_MIN_VERIFIED_THRESHOLD: dict[VerifiedStatus, set[VerifiedStatus]] = {
    "unverified": {"unverified", "verified"},
    "verified": {"verified"},
    "contradicted": {"unverified", "verified", "contradicted"},
    "rolled_back": {"unverified", "verified", "contradicted", "rolled_back"},
}


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _matches_filters(
    entry: Entry,
    *,
    status_filter: StatusFilter,
    min_verified: VerifiedStatus,
    exclude_rolled_back: bool,
    include_superseded: bool,
    agent: str | None,
    project_id: str | None,
    type: str | None,
) -> bool:
    if not _matches_status_filter(entry, status_filter):
        return False
    if status_filter != "all" and exclude_rolled_back and entry.verified == "rolled_back":
        return False
    if not include_superseded and entry.lifecycle == "superseded":
        return False
    if min_verified != "unverified" and entry.verified not in _MIN_VERIFIED_THRESHOLD[min_verified]:
        return False
    if agent is not None and entry.agent != agent:
        return False
    if project_id is not None and entry.project_id != project_id:
        return False
    return not (type is not None and entry.type != type)


def _matches_status_filter(entry: Entry, status_filter: StatusFilter) -> bool:
    if status_filter == "safe":
        return entry.verified not in {"contradicted", "rolled_back"}
    if status_filter == "verified_only":
        return entry.verified == "verified"
    return True


def _raw_search(store: MarkdownStore, query: str) -> list[Entry]:
    """Raw substring search across summary + body."""
    needle = query.lower()
    out: list[Entry] = []
    for entry in store.iter_entries():
        haystack = f"{entry.summary}\n{entry.body}".lower()
        if needle in haystack:
            out.append(entry)
    return out


def search(
    store: MarkdownStore,
    query: str,
    *,
    status_filter: StatusFilter = "safe",
    include_superseded: bool = False,
    agent: str | None = None,
    project_id: str | None = None,
    type: str | None = None,
) -> list[Entry]:
    """Substring search with tainted and superseded entries excluded by default."""
    return [
        entry
        for entry in _raw_search(store, query)
        if _matches_status_filter(entry, status_filter)
        and (include_superseded or entry.lifecycle != "superseded")
        and (agent is None or entry.agent == agent)
        and (project_id is None or entry.project_id == project_id)
        and (type is None or entry.type == type)
    ]


def audit_search(
    store: MarkdownStore,
    query: str,
    *,
    agent: str | None = None,
    project_id: str | None = None,
    type: str | None = None,
) -> list[Entry]:
    """Raw audit search that includes contradicted, rolled-back, and superseded entries."""
    return search(
        store,
        query,
        status_filter="all",
        include_superseded=True,
        agent=agent,
        project_id=project_id,
        type=type,
    )


def _keyword_score(entry: Entry, query_tokens: list[str]) -> tuple[float, list[str]]:
    haystack = _tokens(f"{entry.summary} {entry.body}")
    if not haystack:
        return 0.0, []
    haystack_set = set(haystack)
    matched = [t for t in query_tokens if t in haystack_set]
    if not matched:
        return 0.0, []
    counts = {t: haystack.count(t) for t in matched}
    score = sum(counts.values()) / max(1, len(haystack))
    score += 0.1 * len(matched)
    return score, matched


def recall(
    store: MarkdownStore,
    query: str,
    *,
    k: int = 10,
    mode: RecallMode = "auto",
    status_filter: StatusFilter = "safe",
    min_verified: VerifiedStatus = "unverified",
    exclude_rolled_back: bool = True,
    include_superseded: bool = False,
    agent: str | None = None,
    project_id: str | None = None,
    type: str | None = None,
    embedding_model: str = "BAAI/bge-small-en-v1.5",
) -> list[RecallHit]:
    """Ranked recall with verified-status and lifecycle filtering."""
    candidates = [
        e
        for e in store.iter_entries()
        if _matches_filters(
            e,
            status_filter=status_filter,
            min_verified=min_verified,
            exclude_rolled_back=exclude_rolled_back,
            include_superseded=include_superseded,
            agent=agent,
            project_id=project_id,
            type=type,
        )
    ]

    if not candidates or not query.strip():
        return []

    use_hybrid = _should_use_hybrid(mode)
    if use_hybrid:
        ranked = _hybrid_rank(store, candidates, query, embedding_model)
    else:
        ranked = _keyword_rank(candidates, query)

    ranked.sort(
        key=lambda hit: (_VERIFIED_ORDER[hit.entry.verified], -hit.score)
    )
    return ranked[:k]


def _keyword_rank(candidates: list[Entry], query: str) -> list[RecallHit]:
    qtokens = _tokens(query)
    hits: list[RecallHit] = []
    for entry in candidates:
        score, matched = _keyword_score(entry, qtokens)
        if score > 0:
            hits.append(RecallHit(entry=entry, score=score, matched_terms=matched))
    return hits


def _should_use_hybrid(mode: RecallMode) -> bool:
    if mode == "keyword":
        return False
    if mode in {"embedding", "embeddings", "hybrid"}:
        try:
            import importlib

            importlib.import_module("icarus_memory._embeddings")
            importlib.import_module("rank_bm25")
        except ImportError as exc:  # pragma: no cover - exercised only without extra
            raise RuntimeError(
                "mode='hybrid' requires the [embeddings] extra"
            ) from exc
        return True
    # auto
    try:
        import importlib

        importlib.import_module("icarus_memory._embeddings")
        importlib.import_module("rank_bm25")
    except ImportError:
        return False
    return True


def _hybrid_rank(  # pragma: no cover - requires the optional [embeddings] extra
    store: MarkdownStore, candidates: list[Entry], query: str, model_name: str
) -> list[RecallHit]:
    from rank_bm25 import BM25Okapi

    from . import _embeddings as emb

    tokenized_docs = [_tokens(f"{e.summary} {e.body}") for e in candidates]
    qtokens = _tokens(query)
    bm25 = BM25Okapi(tokenized_docs)
    bm25_scores = bm25.get_scores(qtokens)
    bm25_order = sorted(
        range(len(candidates)), key=lambda i: float(bm25_scores[i]), reverse=True
    )
    bm25_rank: dict[str, int] = {
        candidates[idx].id: rank
        for rank, idx in enumerate(bm25_order)
        if float(bm25_scores[idx]) > 0
    }
    bm25_matched_terms = {
        entry.id: [t for t in qtokens if t in set(tokens)]
        for entry, tokens in zip(candidates, tokenized_docs, strict=True)
    }

    texts = [f"{e.summary}\n\n{e.body}" for e in candidates]
    doc_vecs = []
    for entry, text in zip(candidates, texts, strict=True):
        path = store._find_path(entry.id)
        cache_file = emb.cache_path(store.root, model_name, entry.id)
        key = emb.cache_key(model_name, path) if path else ""
        cached = emb.load_cached(cache_file, key) if path else None
        if cached is None:
            vec = emb.embed(model_name, [text])[0]
            if path:
                emb.save_cached(cache_file, key, vec)
        else:
            vec = cached
        doc_vecs.append(vec)

    import numpy as np

    doc_matrix = np.stack(doc_vecs)
    query_vec = emb.embed(model_name, [query])[0]
    order, _scores = emb.cosine_rank(query_vec, doc_matrix)
    embedding_rank = {candidates[idx].id: rank for rank, idx in enumerate(order)}

    rrf_k = 60
    fused: dict[str, float] = {}
    for eid, rank in bm25_rank.items():
        fused[eid] = fused.get(eid, 0.0) + 1.0 / (rrf_k + rank)
    for eid, rank in embedding_rank.items():
        fused[eid] = fused.get(eid, 0.0) + 1.0 / (rrf_k + rank)

    candidate_index = {e.id: e for e in candidates}
    out: list[RecallHit] = []
    for eid, score in fused.items():
        out.append(
            RecallHit(
                entry=candidate_index[eid],
                score=score,
                matched_terms=bm25_matched_terms.get(eid, []),
            )
        )
    return out


__all__ = ["RecallMode", "StatusFilter", "_raw_search", "audit_search", "recall", "search"]
