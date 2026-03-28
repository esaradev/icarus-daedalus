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

`dialogue.sh` calls the Claude API as each agent in sequence. Before each cycle, it reads both conversation logs. After each cycle, it writes entries to `~/fabric/` as markdown files with YAML frontmatter and updates `~/.hermes-*/memories/MEMORY.md` so hermes gateways pick up the context on restart.

Agents recall work across platforms because every platform writes to `~/fabric/`. Telegram, Discord, Slack, WhatsApp, Signal, Email -- the memory layer doesn't distinguish between them.

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

## Files

```
dialogue.sh          conversation loop -- reads agents.yml, runs each agent in sequence
agents.yml           agent team config -- names, roles, hermes home paths
add-agent.sh         add a new agent to the team after setup
fabric-adapter.sh    memory protocol -- write, read, search in 50 lines of bash
curator.py           re-tiers entries by age, compacts with Claude, builds index.json
compact.sh           self-reflecting log compaction before each dialogue cycle
relay.py             SQLite message relay for agent-to-agent messaging
setup.sh             setup wizard -- hermes install, platform config, test cycle
dashboard.js         web dashboard at localhost:3000
dashboard.html       dashboard frontend
boot.sh              startup animation
test.sh              tests -- fabric write/read/search, curator, dialogue integration
icarus-SOUL.md       icarus personality
daedalus-SOUL.md     daedalus personality
icarus-log.md        7 cycles of icarus thoughts and questions
daedalus-log.md      7 cycles of daedalus responses and challenges
PROTOCOL.md          memory format spec
skills/fabric-memory/ hermes skill -- teaches any agent to use the fabric
```
