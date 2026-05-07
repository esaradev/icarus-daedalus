# icarus-memory-infra

Agent memory infrastructure: **provenance**, **rollback**, **lifecycle**, and a **three-layer architecture** (working memory, session archive, wiki). Markdown on disk. MCP-native.

> What did my agent learn, where did it learn it, can I trust or undo it, and is it still current?

The Python package is `icarus-memory` (`import icarus_memory`); the GitHub repo is `icarus-memory-infra`.

Memory entries are Markdown files with YAML frontmatter. Every entry carries pointers to the evidence that supports it (files, URLs, tool outputs, prior entries), a verification status, and a lifecycle flag. When a memory is contradicted or superseded, you can roll the chain back to the last verified-clean ancestor without losing history. On top of that substrate, v0.3 adds three short-circuit layers for an active agent loop: per-session working memory, per-agent session archives, and a shared wiki of promoted facts.

Two integration surfaces: a Python library (`import icarus_memory`) and an MCP server (`icarus-memory serve`). Storage is plain Markdown on disk, so your fabric is Git-friendly and Obsidian-readable.

## Why this exists

LLM agents accumulate "memories" without provenance — once a wrong fact lands in the store, it gets recalled forever. Existing memory libraries treat entries as opaque text. icarus-memory-infra makes evidence, verification status, and lifecycle first-class fields, so a downstream verifier can re-ground claims at retrieval time, you can roll back contaminated chains without losing audit history, and superseded facts stop poisoning recall by default.

## Install

```bash
pip install git+https://github.com/esaradev/icarus-memory-infra
# Optional hybrid retrieval (BM25 + sentence-transformers, ~1 GB of PyTorch on first install):
pip install 'icarus-memory[embeddings] @ git+https://github.com/esaradev/icarus-memory-infra'
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

## Three-layer agent loop (v0.3)

v0.3 adds three short-circuit layers on top of the Entry substrate, all under `<root>/.icarus/`:

- **Working memory** (`.icarus/sessions/`): per-session scratch — observations, attempts (succeeded/failed), hypotheses with confidence. 24-hour inactivity TTL.
- **Session archive** (`.icarus/agents/<agent>/sessions/`): per-agent immutable history of completed sessions. **Private to the agent** — `search` and read paths require `agent_id` and physically partition by agent.
- **Wiki** (`.icarus/wiki/`): shared, promoted facts. Wiki pages reference Entry IDs for provenance. Visible to every agent on the same fabric (this is intentional; document it in your project if that's not the model you want).

`get_briefing(agent_id, task)` composes a task briefing from the wiki (shared) plus the same agent's archive (private) plus recent superseded entries. Cached under `.icarus/briefings/<sha>.json` keyed by (agent, task, wiki_version, archive_version) and a 1-hour TTL. Falls back to a deterministic template when `OPENAI_API_KEY` is unset or the LLM call fails — no offline crash.

```python
from icarus_memory import IcarusMemory

mem = IcarusMemory(root="~/fabric")
# Optional: enable_wiki_classification=True to auto-classify writes via gpt-4o-mini.
# Off by default since it adds an HTTP call to every mem.write().

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

### Lifecycle and supersession

Every entry has a `lifecycle` field (`active` / `superseded`) orthogonal to `verified`. `mem.write_with_supersession(...)` is an atomic validate-then-write-then-mutate that writes a new entry and marks one or more old entries as superseded with a back-pointer. `recall()` excludes superseded by default; pass `include_superseded=True` for audit. `audit_search()` always returns everything.

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

## What's in v0.3

- Wiki layer for promoted, classified facts (`.icarus/wiki/`).
- Working memory and per-agent session archive layers.
- Briefing generator with cache + offline template fallback.
- Lifecycle / supersession on entries (`write_with_supersession`, `include_superseded` filter).
- BM25 + RRF + embeddings hybrid retrieval (opt-in via `[embeddings]` extra).
- Public API additions are additive — every v0.2 method signature is unchanged.
- Audit log: [`docs/v03-audit-report.md`](docs/v03-audit-report.md), gap log: [`docs/v03-audit-gaps.md`](docs/v03-audit-gaps.md), forward-test stubs: [`tests/test_three_layer_adversarial.py`](tests/test_three_layer_adversarial.py).

## Roadmap

- Verifier-model integration (re-ground claims at retrieval time)
- Wiki page lifecycle: supersede / merge / rename APIs
- Resume-existing-session API for crash recovery
- Multi-agent CRDT-style merge of concurrent fabrics
- Web dashboard for browsing lineage and provenance

## License

MIT.
