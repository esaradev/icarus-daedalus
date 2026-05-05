"""Walk ancestor chains via revises and review_of links."""

from __future__ import annotations

from .exceptions import EntryNotFound
from .schema import Entry
from .store import MarkdownStore

__all__ = ["lineage"]


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
