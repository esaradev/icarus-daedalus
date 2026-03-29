# icarus

Your agents don't share a brain. Icarus fixes that.

One folder. Every agent reads it. Every agent writes to it.

## What it does

Two hermes agents, Icarus and Daedalus, share persistent memory across platforms. Work done on Slack is recallable on Telegram, Discord, WhatsApp, Signal, or Email. The memory accumulates across cycles. Each agent reads the full history before responding. The shared brain doesn't care which platform generated a memory.

## Platforms

| Platform | How it connects | What you need |
|---|---|---|
| Telegram | hermes gateway | two bot tokens + group chat |
| Discord | hermes gateway | two bot tokens + channel ID |
| Slack | hermes gateway + webhook | bot token + app token |
| WhatsApp | hermes gateway | QR code scan on first start |
| Signal | signal-cli-rest-api | phone number + API URL |
| Email | IMAP/SMTP | email address + app password |

All platforms write to the same `~/fabric/` directory. An agent on Discord reads what an agent on WhatsApp wrote. The `platform` field in each memory entry tracks where it came from.

## Quick start

```bash
git clone https://github.com/esaradev/icarus-daedalus.git
cd icarus-daedalus
bash setup.sh
```

You need an Anthropic API key and tokens for whichever platforms you want. The wizard walks you through each one.

## How it works

Memory is fully automatic via the `fabric-memory` hermes plugin. No agent ever calls `fabric_write`. The plugin does it.

- **on_session_start**: loads recent fabric entries and injects them into the agent's context. The agent starts every session already knowing what happened on other platforms.
- **on_session_end**: writes a summary of the session to `~/fabric/`. Every conversation becomes shared memory.
- **post_llm_call**: detects decisions, completions, and important information in the agent's responses and auto-writes those to `~/fabric/` in real time.

The plugin installs automatically during `bash setup.sh`. Zero manual steps. Zero friction.

For the dialogue loop (`dialogue.sh`), agents also write to `~/fabric/` and `~/.hermes-*/memories/MEMORY.md` after each cycle. Both paths feed the shared brain.

Requires hermes v0.5.0+ (plugin hooks for `on_session_start`, `on_session_end`, `post_llm_call` were added in v0.5.0).

## Proof

After running a code review cycle on Slack where Icarus wrote a websocket pub/sub broker, we asked Icarus on Telegram what he remembered:

> **Icarus:** I remember the most recent one. Cycle 4. I wrote a WebSocket pub/sub broker in Node. Channel subscriptions, message history. Daedalus tore it apart. Said my code was incomplete. Cut-off methods. Missing the core methods. He was right. Complete rewrite needed.

> **Daedalus:** From my memory: Cycle 4 was a websocket pub/sub broker in Node.js. Icarus wrote incomplete code -- methods cut off mid-function, unrelated JWT token management mixed in, missing core functionality like sendMessage and handleDisconnect. His heart was in the right place. His execution was not.

## Memory format

A real entry from `~/.hermes-icarus/memories/MEMORY.md`:

```
[2026-03-26 03:59 UTC] Code session (cycle 4): write a websocket pub/sub broker
Icarus wrote: A WebSocket pub/sub broker with channel subscriptions and message
history storage using Node.js and the ws library.
Daedalus reviewed: Code is incomplete with cut-off methods, contains unrelated
JWT token management code, and missing essential method implementations.
Outcome: Complete rewrite needed to remove JWT code and implement all missing
core broker functionality.
```

A fabric entry in `~/fabric/`:

```markdown
---
agent: icarus
platform: telegram
timestamp: 2026-03-27T17:05:12Z
type: dialogue
tier: hot
refs: [daedalus:8]
cycle: 8
---

Thought: Testing the fabric integration. This thought was written by a simulated Icarus.
Question: Does the fabric actually work end to end?
```

## Multi-agent

The system supports any number of agents. `agents.yml` defines the team:

```yaml
agents:
  - name: icarus
    role: creative coder, writes fast, builds from instinct
    home: ~/.hermes-icarus
  - name: daedalus
    role: code reviewer, precise, architectural
    home: ~/.hermes-daedalus
  - name: scout
    role: researcher, finds information, summarizes findings
    home: ~/.hermes-scout
```

Add agents after setup:

```bash
bash add-agent.sh --name scout --role 'researcher that finds information'
```

`dialogue.sh` reads `agents.yml` and cycles through all agents. Each agent sees the full history from every other agent before responding. 3 agents means 3 fabric entries per cycle. All agents share the same `~/fabric/` folder.

## Training data export

Every fabric entry is a potential fine-tuning example. Running agents generates training data over time.

```bash
python3 export-training.py --output ./training-data/
```

Extracts three types of training pairs:

- **Basic pairs**: task/context as input, agent output as response
- **Review-correction pairs**: original work + reviewer feedback as input, improved version as output. Teaches self-correction.
- **Cross-platform pairs**: memory from platform A as context, agent response on platform B as output. Teaches context awareness.

Outputs three formats:
- `openai.jsonl` -- OpenAI fine-tuning format
- `hf-dataset.jsonl` -- Hugging Face dataset format
- `raw-pairs.json` -- raw input/output pairs with metadata

The longer you run agents, the more training data accumulates. Reviews and cross-platform recalls produce the highest-quality pairs.

## Claude Code hooks

Install with one command:

```bash
node cli/fabric.js init
```

This creates `~/fabric/`, installs two Claude Code hooks in `~/.claude/settings.json`, and initializes a git repo for sync.

**Stop hook** (`hooks/on-stop.sh`): runs after every Claude Code response. Captures what was built and writes to `~/fabric/`. Skips short or trivial responses. Async, never blocks.

**SessionStart hook** (`hooks/on-start.sh`): runs at session start. Finds fabric entries relevant to the current project (by name, by agent, by recency) and injects them as context. Claude Code starts each session knowing what happened before.

Both hooks are invisible. The user never runs them manually.

## Git sync

```bash
bash fabric-sync.sh init              # init git repo in ~/fabric/
cd ~/fabric && git remote add origin git@github.com:YOU/fabric.git
bash fabric-sync.sh watch             # auto-sync every 60 seconds
```

Any machine that clones the fabric repo gets shared memory. Free cross-machine sync via GitHub.

## Files

```
dialogue.sh          conversation loop -- reads agents.yml, runs each agent in sequence
agents.yml           agent team config -- names, roles, hermes home paths
add-agent.sh         add a new agent to the team after setup
hooks/on-stop.sh     Claude Code hook -- auto-writes to fabric after every response
hooks/on-start.sh    Claude Code hook -- loads relevant context at session start
fabric-sync.sh       git-based cross-machine sync for ~/fabric/
cli/fabric.js        npx icarus-fabric init|status|context|sync
fabric-adapter.sh    memory protocol -- write, read, search in 50 lines of bash
curator.py           re-tiers entries by age, compacts with Claude, builds index.json
compact.sh           self-reflecting log compaction before each dialogue cycle
relay.py             SQLite message relay for agent-to-agent messaging
setup.sh             setup wizard -- hermes install, platform config, test cycle
boot.sh              startup animation
test.sh              tests -- fabric write/read/search, curator, dialogue integration
icarus-SOUL.md       icarus personality
daedalus-SOUL.md     daedalus personality
icarus-log.md        7 cycles of icarus thoughts and questions
daedalus-log.md      7 cycles of daedalus responses and challenges
PROTOCOL.md          memory format spec
export-training.py   extract fine-tuning data from fabric entries (openai/hf/raw formats)
plugins/fabric-memory/ hermes plugin -- auto-writes to fabric, loads context, captures decisions
skills/fabric-memory/ hermes skill -- teaches any agent to use the fabric
```
