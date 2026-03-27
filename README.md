# icarus-daedalus

Two AI agents that share memory across platforms. They talk on Telegram, work on Slack, and remember everything across both. What they do depends on the SOUL files -- code review, research, trading, creative dialogue, or anything you define.

Built on the Icarus Memory Protocol: agents write markdown files to `~/fabric/`, other agents read them. No database. See [PROTOCOL.md](PROTOCOL.md) for the spec.

## Quick start

```bash
git clone https://github.com/esaradev/icarus-daedalus.git
cd icarus-daedalus
bash setup.sh
```

The wizard handles hermes installation, template selection, Telegram/Slack setup, and runs a test cycle.

## The memory protocol

Agents write memories as markdown files with YAML frontmatter to `~/fabric/`. Three functions:

```bash
source fabric-adapter.sh
fabric_write "icarus" "slack" "code-session" "built a rate limiter, daedalus found a race condition"
fabric_read "icarus" "hot"
fabric_search "rate limiter"
```

Each entry looks like this:

```markdown
---
agent: icarus
platform: slack
timestamp: 2026-03-27T04:00:00Z
type: code-session
tier: hot
refs: [daedalus:3]
tags: [rate-limiter, express]
summary: rate limiter with race condition
---

Built an Express rate limiter with sliding window and Redis backend.
Daedalus reviewed it. MUST FIX: race condition in request counting.
```

Tiers by age: hot (< 24h), warm (1-7 days), cold (> 7 days, archived). `curator.py` re-tiers, compacts warm entries with Claude, and builds `index.json`.

Any framework can adopt this. Write a markdown file with frontmatter to a directory. Python adapters for AutoGPT, CrewAI, and LangChain are in `examples/`. A hermes skill at `skills/fabric-memory/` teaches any hermes agent to use the fabric.

## Templates

- **code-review** -- one agent writes code, the other reviews with MUST FIX / SHOULD FIX / NIT
- **research-validation** -- one explores topics, the other fact-checks
- **trading-strategy** -- one proposes trades, the other stress-tests
- **creative** -- philosophical dialogue (the original icarus/daedalus)

Each template has its own `dialogue.sh`, SOUL files, and log format. Pick one during `setup.sh` or run directly:

```bash
bash templates/code-review/dialogue.sh "write a rate limiter for Express"
bash templates/research-validation/dialogue.sh "sleep deprivation and false memory"
bash templates/trading-strategy/dialogue.sh "BTC at 65k, ETH ratio at 3-year low"
```

## Dashboard

```bash
node dashboard.js
# http://localhost:3000
```

Dialogue history, code reviews, platform status, memory usage, compaction history. Updates live via SSE.

## How it works

```
~/fabric/                          shared memory
~/.hermes-icarus/                  agent A (SOUL, env, skills)
~/.hermes-daedalus/                agent B (SOUL, env, skills)
dialogue.sh                        runs one cycle: A speaks, B responds
  -> writes to ~/fabric/           protocol memory
  -> writes to hermes MEMORY.md    platform memory (Telegram/Slack)
  -> posts to Telegram + Slack
compact.sh                         compacts logs before each cycle
curator.py                         re-tiers and indexes ~/fabric/
```

Cross-platform memory: work done on Slack is recallable on Telegram. Both `dialogue.sh` and the hermes `MEMORY.md` bridge are updated each cycle. Hermes gateways need a restart after MEMORY.md changes (`pkill -f "hermes gateway run"` then restart).

## Files

```
fabric-adapter.sh        50-line bash adapter (write/read/search)
curator.py               re-tier, compact, index ~/fabric/
compact.sh               self-reflecting log compaction
PROTOCOL.md              memory format spec
setup.sh                 one-command setup wizard
dashboard.js             web dashboard (localhost:3000)
dashboard.html           dashboard frontend
dialogue.sh              agent-to-agent conversation loop
skills/fabric-memory/    hermes skill for any agent
templates/               code-review, research, trading, creative
examples/                AutoGPT, CrewAI, LangChain adapters
```

## Requirements

- Python 3 (for curator, JSON escaping in dialogue scripts)
- Anthropic API key
- Optional: [hermes-agent](https://github.com/NousResearch/hermes-agent) for Telegram/Slack
- Optional: Node.js for dashboard
