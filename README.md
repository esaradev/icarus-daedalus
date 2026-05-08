# icarus

Agent coherence infrastructure. Local-first, markdown-native memory for AI agents.

> Icarus gives agents persistent, sourced, version-controlled memory so they stop using stale facts, repeating failed attempts, and contradicting prior decisions.

Built first for coding agents on long-lived codebases.

## The problem

AI coding agents forget what your team decided last month. They repeat fixes that didn't work. They suggest patterns the team migrated away from. They leave no audit trail.

As agents move from suggesting code to writing it, this becomes operational risk.

## The solution

Icarus gives agents a shared, versioned source of truth. Every fact has a source. Stale facts get marked superseded — never overwritten. Before each task, Icarus compiles a short briefing of what's current, what's superseded, and what's failed before. Agents start tasks with context instead of from scratch.

## Install

```bash
pip install git+https://github.com/esaradev/icarus-memory-infra
```

PyPI release pending. Requires Python 3.10+.

## Quick example

Agents call `start_session` to get a briefing about prior decisions, attempts, and team conventions for the task they're about to do. They work, then `end_session` archives what happened and promotes the finding to the shared wiki.

```python
from icarus_memory import IcarusMemory

mem = IcarusMemory(root="~/fabric")

# Read prior context. Returns a briefing assembled from wiki + same-agent archive.
working, briefing = mem.start_session("backend-agent", "fix slow checkout query")
print(briefing.content)
# Last week you tried adding an index on orders.user_id; that didn't help.
# The team migrated off the legacy session table on Mar 12.
# Recently superseded: "use synchronous email sender" (replaced Apr 8).

# Agent works.
working.add_observation("EXPLAIN shows seq scan on orders_archive")
working.add_attempt("rewrote query to use orders_archive_idx", succeeded=True)

# Archive the session. Promote the finding to the shared wiki.
mem.end_session(
    working,
    summary="rewrote checkout query to use orders_archive_idx",
    promote_to_wiki=["performance/checkout-query"],
)
```

The next agent that picks up a related task gets the wiki page in its briefing. Failed attempts stay private to the agent that tried them. No re-trying dead ends.

## How it works

**Working memory.** Per-task scratch for what the agent is doing right now. Observations, attempts, hypotheses. Cleared when the task ends.

**Session archive.** Per-agent history of what each agent has tried, succeeded at, failed at. Private to the agent that produced it.

**Wiki.** Shared markdown source of truth, organized by topic. Every fact links back to the entry that introduced it.

Before each task, Icarus compiles a briefing combining all three.

## Why this is different

- **Local-first.** Your data stays on your machine or in your cloud. Agent memory is sensitive — codebase decisions, internal architecture, customer context — and shouldn't live inside a vendor's black box.

- **Markdown-native.** Everything is human-readable markdown files. You can `git add .icarus/` and version your agent's memory alongside your code.

- **MCP-compatible.** Works with Claude Code, Cursor, Cline, Continue, or any agent that speaks the Model Context Protocol.

## Current status

Icarus is in early access. The OSS library is stable; integrations and the hosted tier are in active development. If you're running coding agents on a real codebase and want to be a design partner, email harry@icarushermes.com. We work directly with our first users.

## License

MIT.

---

- Documentation: [github.com/esaradev/icarus-memory-infra/tree/main/docs](https://github.com/esaradev/icarus-memory-infra/tree/main/docs)
- Discord: coming soon
- X / Twitter: [@IcarusHermes](https://x.com/IcarusHermes)
- Email: harry@icarushermes.com
