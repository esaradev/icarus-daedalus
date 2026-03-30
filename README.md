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

## Hermes plugin (quick start)

Add cross-platform memory and self-training to any Hermes agent in 3 commands:

```bash
git clone https://github.com/esaradev/icarus-daedalus.git
cd icarus-daedalus

# install to your hermes (global — all agents get it)
cp -r plugins/icarus ~/.hermes/plugins/
cp fabric-retrieve.py ~/.hermes/plugins/icarus/
cp export-training.py ~/.hermes/plugins/icarus/
```

Or install per-agent:

```bash
cp -r plugins/icarus ~/.hermes-YOUR_AGENT/plugins/
cp fabric-retrieve.py ~/.hermes-YOUR_AGENT/plugins/icarus/
cp export-training.py ~/.hermes-YOUR_AGENT/plugins/icarus/
```

Restart Hermes. Run `/plugins` to verify:

```
Plugins (1):
  ✓ icarus v0.2.0 (7 tools, 4 hooks)
```

**What your agent gets:**

| Tool | What it does |
|------|-------------|
| `fabric_recall` | Ranked retrieval from shared memory (keyword, project, agent, recency scoring) |
| `fabric_write` | Write entries any agent on any platform can read, including explicit handoffs via `assigned_to` |
| `fabric_search` | Keyword grep across all fabric entries |
| `fabric_pending` | Show open handoffs assigned to this agent plus reviews of its work |
| `fabric_export` | Export fabric entries as fine-tuning pairs (OpenAI, Together, HuggingFace formats) |
| `fabric_train` | Upload + start a Together AI fine-tune from your fabric data |
| `fabric_train_status` | Check job progress, get the output model ID when done |

Plus 4 automatic hooks: context injection on session start, relevant memory retrieval on topic change, decision capture after every response, session summary on end.

For self-training, set `TOGETHER_API_KEY` in your agent's `.env`. The agent can then call `fabric_export` to check pair count and `fabric_train` to fine-tune itself.

## Claude Code only

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

## Self-training

Agents accumulate training data as they work. When you have enough pairs (20+), fine-tune a cheaper model that mirrors your agents' behavior. The fine-tuned model runs on Together AI at a fraction of the cost.

```bash
bash scripts/self-train.sh
```

Default model: `Qwen/Qwen2-7B-Instruct` (validated). Override with `TOGETHER_MODEL=...`. Model availability is account-dependent on Together -- Llama 3.x may not be enabled for fine-tuning on all accounts.

Together requires explicit hyperparameters (batch_size >= 8, learning_rate > 0, n_checkpoints >= 1). The script sets all of these. Override via `TOGETHER_BATCH_SIZE`, `TOGETHER_LR`, `TOGETHER_CHECKPOINTS`, `TOGETHER_EPOCHS`.

Or tell your agent on any platform: "train yourself" and it handles export, upload, fine-tune, and polling through the `skills/self-train/` skill.

## Hermes plugin

Cross-platform memory and self-training via hermes v0.5.0 plugin hooks. Install the `plugins/icarus/` plugin in any hermes agent's home directory:

- **on_session_end**: auto-writes session summary to `~/fabric/`
- **on_session_start**: loads recent fabric entries and injects them as agent context
- **pre_llm_call**: retrieves relevant shared memory on topic change
- **post_llm_call**: captures decisions and tracks learnings/questions in real time
- **tools**: `fabric_recall`, `fabric_write`, `fabric_search`, `fabric_export`, `fabric_train`, `fabric_train_status`

The plugin gives Hermes agents both shared memory and a fine-tuning path.

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
SCHEMA.md                entry schema v1 (fields, types, examples)
setup.sh                 setup wizard
test.sh                  core infrastructure tests
fabric-sync.sh           git-based cross-machine sync
cli/fabric.js            npx icarus-fabric init|status|context|sync
hooks/on-stop.sh         Claude Code auto-write hook
hooks/on-start.sh        Claude Code context loading hook
plugins/icarus/          hermes plugin (memory + recall + training + hooks)
scripts/self-train.sh    export + upload + fine-tune pipeline for Together AI
skills/fabric-memory/    hermes skill for manual fabric access
skills/self-train/       hermes skill for conversational self-training
examples/hermes-demo/    two-agent demo with dialogue loop, compaction, multi-platform
```
