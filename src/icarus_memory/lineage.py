"""Walk ancestor chains via revises and review_of links."""

from __future__ import annotations

from typing import NamedTuple

from .exceptions import EntryNotFound
from .schema import Entry
from .store import MarkdownStore

__all__ = ["DescendantResult", "_find_descendants", "lineage"]


class DescendantResult(NamedTuple):
    descendants: list[str]
    warnings: list[str]


def lineage(store: MarkdownStore, entry_id: str) -> list[Entry]:
    """Return the merged ancestry of an entry (revises + review_of).

    Order: each entry appears once, in BFS order from ``entry_id``.
    """
    seen: set[str] = set()
    out: list[Entry] = []
    frontier: list[str] = [entry_id]
    while frontier:
        next_frontier: list[str] = []
        for current_id in frontier:
            if current_id in seen:
                continue
            seen.add(current_id)
            try:
                current = store.get(current_id)
            except EntryNotFound:
                continue
            out.append(current)
            for link in (current.revises, current.review_of):
                if link and link not in seen:
                    next_frontier.append(link)
        frontier = next_frontier
    return out


def _reverse_revises_index(store: MarkdownStore) -> dict[str, list[str]]:
    if store._reverse_revises_cache is not None:
        return store._reverse_revises_cache

    entries = sorted(store.iter_entries(), key=lambda entry: (entry.timestamp, entry.id))
    index: dict[str, list[str]] = {}
    for entry in entries:
        if entry.revises is None:
            continue
        index.setdefault(entry.revises, []).append(entry.id)
    store._reverse_revises_cache = index
    return index


def _find_descendants(store: MarkdownStore, entry_id: str | list[str] | set[str]) -> DescendantResult:
    """Return entries that transitively revise the given entry id or ids."""
    seeds_list = [entry_id] if isinstance(entry_id, str) else list(entry_id)
    seeds = set(seeds_list)
    index = _reverse_revises_index(store)
    descendants: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set(seeds)
    frontier = list(seeds_list)

    while frontier:
        current = frontier.pop(0)
        for child in index.get(current, []):
            if child in seeds:
                continue
            if child in seen:
                warnings.append(f"revises cycle or duplicate descendant at {child}")
                continue
            seen.add(child)
            descendants.append(child)
            frontier.append(child)

    return DescendantResult(descendants=descendants, warnings=warnings)
