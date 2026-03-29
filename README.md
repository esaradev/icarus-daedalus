# icarus

Shared memory for AI agents. One folder. Any platform. Any framework.

## What it does

Every agent writes to `~/fabric/`. Every other agent reads it. Markdown files with YAML frontmatter. Write, read, search in 50 lines of bash. No database.

```bash
source fabric-adapter.sh
fabric_write "icarus" "slack" "code-session" "built a rate limiter"
fabric_read "icarus" "hot"
fabric_search "rate limiter"
```

## Install

```bash
git clone https://github.com/esaradev/icarus-daedalus.git
cd icarus-daedalus
bash setup.sh
```

Or for Claude Code only:

```bash
node cli/fabric.js init
```

## How it works

Three functions. `fabric_write` creates a markdown file with YAML frontmatter in `~/fabric/`. `fabric_read` reads entries filtered by agent and tier. `fabric_search` greps across all entries.

Tiers by age: hot (< 24h, always loaded), warm (1-7 days, loaded on query), cold (> 7 days, archived to `cold/`). The curator daemon (`curator.py`) re-tiers, compacts warm entries with Claude, and builds `index.json`.

A real entry from `~/fabric/`:

```markdown
---
agent: icarus
platform: slack
timestamp: 2026-03-27T16:59:17Z
type: code-session
tier: hot
refs: [daedalus:4]
tags: [websocket, node]
summary: websocket broker code review
---

Built a WebSocket pub/sub broker in Node. Daedalus found missing methods.
```

See [PROTOCOL.md](PROTOCOL.md) for the full spec.

## Training data

Agents generate fine-tuning data as they work. `export-training.py` extracts pairs in OpenAI, HuggingFace, and raw formats.

```bash
python3 export-training.py --output ./training-data/
```

Three pair types: basic task completion, review-correction (original + feedback → improved version), and cross-platform context (memory from platform A used on platform B). The longer agents run, the more data accumulates. Reviews and cross-platform recalls produce the highest-quality training signal.

## Hermes plugin

Zero-friction memory via hermes v0.5.0 plugin hooks. Install the `plugins/fabric-memory/` plugin in any hermes agent's home directory:

- **on_session_end**: auto-writes session summary to `~/fabric/`
- **on_session_start**: loads recent fabric entries and injects them as agent context
- **post_llm_call**: detects decisions and completions in real time, writes them to fabric

The agent never calls fabric_write. The plugin does it.

## Claude Code hooks

```bash
node cli/fabric.js init
```

Installs two hooks in `~/.claude/settings.json`:

- **Stop hook**: captures what was built after every response, writes to `~/fabric/`
- **SessionStart hook**: loads relevant entries at session start, deduplicates, injects as context

## Sync

Git-based cross-machine memory:

```bash
bash fabric-sync.sh init
cd ~/fabric && git remote add origin git@github.com:YOU/fabric.git
bash fabric-sync.sh watch    # auto-sync every 60 seconds
```

## Demo

See `examples/hermes-demo/` for two hermes agents (Icarus and Daedalus) proving cross-platform memory works. Icarus writes code on Slack, Daedalus reviews on Telegram, both recall each other's work from any platform.

## Files

```
fabric-adapter.sh        write, read, search -- 50 lines of bash
curator.py               re-tier, compact, build index.json
export-training.py       extract fine-tuning data from fabric entries
PROTOCOL.md              memory format spec
setup.sh                 setup wizard
test.sh                  core infrastructure tests
fabric-sync.sh           git-based cross-machine sync
cli/fabric.js            npx icarus-fabric init|status|context|sync
hooks/on-stop.sh         Claude Code auto-write hook
hooks/on-start.sh        Claude Code context loading hook
plugins/fabric-memory/   hermes plugin (on_session_end, on_session_start, post_llm_call)
skills/fabric-memory/    hermes skill for manual fabric access
examples/hermes-demo/    two-agent demo with dialogue loop, compaction, multi-platform
```
