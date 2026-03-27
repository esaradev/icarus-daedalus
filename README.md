# Icarus Memory Protocol

Universal agent memory. Markdown files in a directory. Any framework, any platform, shared memory in 50 lines of bash.

Agents write memories to `~/fabric/` as markdown files with YAML frontmatter. Other agents read them. A curator daemon compacts and tiers by age. That's the entire protocol. No database, no embeddings, no infrastructure. Human readable, git-friendly, works everywhere.

## The protocol

```bash
source fabric-adapter.sh
fabric_write "icarus" "slack" "code-session" "built a rate limiter, daedalus found a race condition"
fabric_read "icarus" "hot"
fabric_search "rate limiter"
```

A memory entry:

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
Daedalus reviewed it. MUST FIX: race condition in request counting --
zadd before zcard causes off-by-one. Needs rework.
```

Three tiers by age: hot (< 24h, always loaded), warm (1-7 days, loaded on relevant queries), cold (> 7 days, archived). The curator re-tiers automatically.

See [PROTOCOL.md](PROTOCOL.md) for the full spec.

## Use it

### Any bash-based agent

```bash
source fabric-adapter.sh
fabric_write "your-agent" "your-platform" "task" "what happened"
fabric_read "your-agent" "hot"
```

### Any Hermes agent

Copy `skills/fabric-memory/` to your hermes instance's skills directory. The agent learns to write, read, and search the fabric automatically.

```bash
cp -r skills/fabric-memory ~/.hermes/skills/
```

### AutoGPT, CrewAI, LangChain

Python adapters in `examples/`. Each under 50 lines:

```python
# AutoGPT
from examples.autogpt_adapter import fabric_write, fabric_read
fabric_write("my-agent", "cli", "task", "completed web search")

# CrewAI -- @tool decorated, drop into any crew
# LangChain -- @tool decorated, add to any chain
```

### Run the curator

Compacts warm entries, moves cold to archive, builds `index.json`:

```bash
python3 curator.py --once        # one-shot
python3 curator.py daemon        # watch mode (every 5 minutes)
```

## Why this over Mem0 / Zep / Letta

| | Icarus Memory Protocol | Mem0 | Zep | Letta |
|---|---|---|---|---|
| Setup | `source fabric-adapter.sh` | PostgreSQL + Neo4j | PostgreSQL + Neo4j | Full framework |
| Storage | Markdown files | Vector DB | Temporal graph | Custom tiers |
| Multi-agent sharing | Native (shared directory) | No standard protocol | Shared graphs only | Single-agent |
| Read your memories | `cat ~/fabric/*.md` | API query | API query | API query |
| Graph features | Refs field | $249/mo paywall | Included but 600K tokens/conversation | N/A |
| Compaction cost | ~1K tokens/batch | Continuous embedding | 600K+ tokens | Variable |
| Self-hosted | It's files in a directory | Docker + 2 databases | Docker + 2 databases | Docker + config |

The tradeoff is intentional. This is SQLite to their PostgreSQL. Simpler, dumber, sufficient for most agent memory needs.

## Files

```
PROTOCOL.md              # the spec
fabric-adapter.sh        # 50-line bash adapter (the entire API)
curator.py               # daemon: re-tier, compact, index
skills/
  fabric-memory/
    SKILL.md             # hermes skill -- teaches any agent to use the fabric
examples/
  autogpt-adapter.py     # AutoGPT integration
  crewai-adapter.py      # CrewAI integration
  langchain-adapter.py   # LangChain/LangGraph integration
```

## Reference implementation: icarus-daedalus

A working two-agent system built on the protocol. Two AI agents with persistent memory across Telegram and Slack.

```bash
bash setup.sh            # one-command setup wizard
```

### Quick start

```bash
git clone https://github.com/esaradev/icarus-daedalus.git
cd icarus-daedalus
bash setup.sh
```

The wizard picks a template, sets up platforms, creates both agent instances, runs a test cycle. Five minutes to two agents working together.

### Templates

Swap the SOUL files and the agents become anything:

- **code-review** -- one writes code, the other reviews with MUST FIX / SHOULD FIX / NIT
- **research-validation** -- one explores topics, the other fact-checks
- **trading-strategy** -- one proposes trades, the other stress-tests
- **creative** -- philosophical dialogue (the original icarus/daedalus)
- **custom** -- describe your own agents during setup

### Dashboard

```bash
node dashboard.js
# open http://localhost:3000
```

Live dashboard: dialogue history, code reviews, platform status, memory usage, compaction history.

### Architecture

```
~/fabric/                          shared memory (the protocol)
  icarus-dialogue-*.md
  daedalus-review-*.md
  index.json

~/.hermes-icarus/                  agent A
  SOUL.md, .env, memories/
  skills/fabric-memory/

~/.hermes-daedalus/                agent B
  SOUL.md, .env, memories/
  skills/fabric-memory/

dialogue.sh                        agent-to-agent loop
  -> writes to ~/fabric/
  -> writes to hermes MEMORY.md
  -> posts to Telegram + Slack
```

### Platforms

- **Telegram** -- hermes gateways handle human-to-agent chat
- **Slack** -- dialogue cycles post via webhook
- **Cross-platform memory** -- work on Slack is recallable on Telegram via `~/fabric/` and hermes `MEMORY.md`

### Self-reflecting compaction

Before each dialogue cycle, `compact.sh` checks if logs need compaction. If triggered, a "curator" role (not Icarus, not Daedalus) reads both logs, classifies entries into tiers (hot/warm/cold), compresses old entries, archives originals, and rewrites the logs. Template-agnostic.

## Requirements

- Python 3
- Anthropic API key (for dialogue cycles and curator compaction)
- Optional: [hermes-agent](https://github.com/NousResearch/hermes-agent) (for Telegram/Slack gateway)
- Optional: Node.js (for dashboard)

## References

- [PROTOCOL.md](PROTOCOL.md) -- full protocol spec
- [NousResearch/hermes-agent#344](https://github.com/NousResearch/hermes-agent/issues/344) -- Multi-Agent Architecture
