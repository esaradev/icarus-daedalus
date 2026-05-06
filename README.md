# icarus-memory

Framework-agnostic agent memory with **provenance** and **rollback**.

> What did my agent learn, where did it learn it, and can I trust or undo it?

Memory entries are Markdown files with YAML frontmatter. Every entry can carry pointers to the evidence that supports it (files, URLs, tool outputs, prior memories) plus a verification status. When a memory is contradicted or poisoned, you can roll the chain back to the last verified-clean ancestor without deleting history.

Two integration surfaces: a Python library (`import icarus_memory`) and an MCP server (`icarus-memory serve`). Storage is plain Markdown on disk, so your fabric is Git-friendly and Obsidian-readable.

## Why this exists

LLM agents accumulate "memories" without provenance — once a wrong fact lands in the store, it gets recalled forever. Existing memory libraries treat entries as opaque text. icarus-memory makes the evidence and verification status first-class fields, so a downstream verifier can re-ground claims at retrieval time, and you can roll back contaminated chains without losing audit history.

## Install

```bash
pip install git+https://github.com/esaradev/icarus-memory
# Optional hybrid retrieval (downloads ~1GB of PyTorch the first time):
pip install 'icarus-memory[embeddings] @ git+https://github.com/esaradev/icarus-memory'
```

Requires Python 3.10+.

## Quickstart

```python
from icarus_memory import IcarusMemory

mem = IcarusMemory(root="~/fabric")

entry = mem.write(
    agent="builder",
    type="decision",
    summary="chose postgres for the user service",
    body="Long-form reasoning, alternatives considered, etc.",
    evidence=[
        {"kind": "file", "ref": "docs/adr/0007-database.md",
         "excerpt": "We will use PostgreSQL because..."},
    ],
    source_tool="manual",
    training_value="high",
)

mem.verify(entry.id, note="confirmed by team review")

# Later, after a bad update slips in:
bad = mem.write(
    agent="builder", type="decision",
    summary="chose mysql instead", revises=entry.id,
)
mem.contradict(bad.id, contradicted_by=entry.id, reason="superseded by ADR")

plan = mem.rollback(bad.id, dry_run=True)
print(plan.verified_ancestor)  # -> entry.id
mem.rollback(bad.id, dry_run=False)  # mark intermediates rolled_back, write rollback record

for hit in mem.recall("database choice", k=5, mode="keyword"):
    print(hit.entry.id, hit.entry.summary)
```

## Three-layer agent loop

v0.3 adds working memory, per-agent session archives, wiki pages, and task briefings
without changing the Entry substrate:

```python
from icarus_memory import IcarusMemory

mem = IcarusMemory(root="~/fabric")

working, briefing = mem.start_session("builder", "fix auth bug")
print(briefing.content)

working.add_observation("Login redirect loses the session cookie")
working.add_attempt("Regenerated OAuth client secret", succeeded=False)
working.add_hypothesis("Callback and app domains disagree", confidence=0.9)

archive = mem.end_session(
    working,
    "Auth fix is to pin the callback cookie domain",
    promote_to_wiki=["decisions/auth-strategy"],
)

page = mem.get_wiki_page("decisions/auth-strategy")
assert page is not None
print(archive.ref, page.entries)
```

Session archives are private to the same agent during briefing generation. Promoted
wiki entries are shared across agents because they become normal provenance-backed
Entry records linked from `.icarus/wiki`.

## MCP integration

```bash
icarus-memory serve  # stdio (default)
icarus-memory serve --http 8765  # streamable HTTP
```

Point any MCP-compatible client (Claude Code, Cursor, the OpenAI Agents SDK, etc.) at the server. Tools exposed: `memory_write`, `memory_get`, `memory_recall`, `memory_search`, `memory_verify`, `memory_contradict`, `memory_rollback`, `memory_lineage`, `memory_pending`.

For Claude Code, add to `~/.claude/mcp_servers.json`:

```json
{
  "mcpServers": {
    "icarus": {
      "command": "icarus-memory",
      "args": ["serve"],
      "env": { "ICARUS_FABRIC_ROOT": "/Users/you/fabric" }
    }
  }
}
```

## Hermes integration

See [`examples/hermes_adapter.py`](examples/hermes_adapter.py) for a thin adapter that maps Hermes session hooks onto `IcarusMemory.write`.

## Data model

Every entry carries (full schema in [`docs/DESIGN.md`](docs/DESIGN.md)):

| Field | Purpose |
|---|---|
| `id`, `agent`, `platform`, `timestamp`, `type`, `summary`, `body` | core identity + content |
| `project_id`, `session_id`, `status`, `assigned_to` | task/workflow tracking |
| `review_of`, `revises`, `contradicted_by` | links between entries |
| `evidence[]` | pointers to supporting files / URLs / fabric refs / tool outputs |
| `source_tool` | which tool/hook produced this entry |
| `verified` | `unverified` / `verified` / `contradicted` / `rolled_back` |
| `verification_log[]` | append-only audit trail of status changes |
| `artifact_paths[]` | paths to files this entry produced or references |
| `training_value` | `high` / `normal` / `low` for downstream replacement-model training |

## Provenance and rollback

The mental model is: every memory claim should point at the evidence behind it, and a chain of revisions should be reversible. See [`docs/PROVENANCE.md`](docs/PROVENANCE.md) for the full evidence model and threat model.

## Roadmap

- Verifier-model integration (re-ground claims at retrieval time)
- Multi-agent CRDT-style merge of concurrent fabrics
- Web dashboard for browsing lineage and provenance

## License

MIT.
