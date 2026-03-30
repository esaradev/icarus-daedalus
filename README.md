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
| `fabric_pending` | Show work assigned to this agent, plus reviews of its work and open customer tickets. Use this first at session start. |
| `fabric_recall` | Retrieve relevant prior work from shared memory across agents and sessions before starting a task. |
| `fabric_write` | Write structured entries for handoffs, reviews, revisions, decisions, fixes, and completed work. This is the core collaboration tool. |
| `fabric_search` | Exact-term lookup across memory for function names, IDs, error strings, or specific keywords. |
| `fabric_export` | Export and inspect training data built from shared work history. |
| `fabric_train` | Start a fine-tune from collected shared work history. |
| `fabric_train_status` | Check training progress and retrieve the resulting model info. |

Plus 4 automatic hooks: context injection on session start, relevant memory retrieval on topic change, decision capture after every response, session summary on end.

These tools let Hermes agents share memory, hand off work, link reviews and fixes, and turn that history into training data.

For self-training, set `TOGETHER_API_KEY` in your agent's `.env`. The agent can then call `fabric_export` to check pair count and `fabric_train` to fine-tune itself.

To prove the handoff chain works locally without a live model call:

```bash
bash scripts/smoke-handoff.sh
```

That script creates temp Hermes-style homes plus a temp `fabric/`, writes a builder handoff, verifies pending pickup, writes a linked review, writes a linked fix, and checks recall for the chain.

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

Cross-platform memory, handoff workflows, and self-training via hermes plugin hooks. Install `plugins/icarus/` in any agent's home directory.

**7 tools:**

| Tool | Purpose |
|------|---------|
| `fabric_pending` | Show work assigned to this agent, reviews of its work, and open tickets |
| `fabric_recall` | Retrieve relevant prior work across agents and sessions |
| `fabric_write` | Write handoffs, reviews, revisions, fixes, and completed work with link fields |
| `fabric_search` | Exact-term lookup across shared memory |
| `fabric_export` | Export training pairs from shared work history |
| `fabric_train` | Start Together AI fine-tune from collected history |
| `fabric_train_status` | Check job progress and resulting model info |

**4 hooks:** context injection at session start (including pending handoffs), memory retrieval on topic change, decision capture with status detection, session summary on end.

**Runtime validation:** `type=review` requires `review_of`. `status=open` requires `assigned_to`. `review_of` and `revises` must be `agent:id` format pointing to an entry that exists in fabric. Malformed or dangling refs are rejected at write time.

### Builder -> reviewer -> fix

The plugin supports linked handoff chains. Here's the exact flow:

```
# 1. Builder finishes work, hands off to reviewer
fabric_write(
  type="code-session",
  content="Built sliding window rate limiter with Redis sorted sets...",
  summary="rate limiter ready for review",
  status="open",
  assigned_to="daedalus"
)
# writes entry with id: a3f29b01

# 2. Reviewer starts session, sees the handoff
#    on_session_start injects:
#    [fabric] 1 item(s) assigned to you:
#      - icarus: rate limiter ready for review (code-session, id a3f29b01)

# 3. Reviewer evaluates and writes a linked review
fabric_write(
  type="review",
  content="MUST FIX: race condition in zadd/zcard...",
  summary="reviewed rate limiter: race condition",
  review_of="icarus:a3f29b01",
  status="completed",
  outcome="MUST FIX race condition"
)
# writes entry with id: d5e1f8bb

# 4. Builder starts next session, sees the review
#    on_session_start injects:
#    [fabric] 1 review(s) of your work:
#      - daedalus: reviewed rate limiter (review id d5e1f8bb, of icarus:a3f29b01)

# 5. Builder fixes and links the revision
fabric_write(
  type="code-session",
  content="Fixed race condition: wrapped zadd+zcard in MULTI/EXEC...",
  summary="fixed rate limiter after review",
  revises="icarus:a3f29b01",
  status="completed"
)
```

The same pattern works for researcher -> implementer (research entry with `status=open`, implementer writes task), and triage -> resolver (task with `customer_id` and `status=open`, resolver writes resolution carrying `customer_id` forward).

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
