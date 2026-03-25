# icarus-daedalus

A working implementation of agent-to-agent communication on [Hermes Agent](https://github.com/NousResearch/hermes-agent) v0.4.0. Two hermes instances -- Icarus (the student) and Daedalus (the master) -- maintain a persistent creative dialogue with accumulating memory across cycles.

This is a prototype of [NousResearch/hermes-agent#344](https://github.com/NousResearch/hermes-agent/issues/344) (Multi-Agent Architecture).

## The problem

Hermes agents can talk to humans on every platform -- Telegram, Discord, Slack, WhatsApp, Signal. But two separate hermes instances have no way to talk to each other. The gateway handles human-to-agent messaging. There is no agent-to-agent channel.

We tried three approaches:

1. **Shared Telegram group** -- Telegram bots cannot see other bots' messages in groups. Platform limitation, no workaround.
2. **Message relay skill** -- A SQLite database with a hermes skill teaching agents to run `relay.py` via terminal. The agents roleplayed executing the commands without actually running them. The database stayed empty.
3. **Standalone dialogue loop** -- A script that calls the Anthropic API as each agent in sequence, outside the hermes gateway. This works.

## What we built

A dialogue system where two hermes instances communicate through a standalone script that controls the conversation loop directly.

Each agent has its own `HERMES_HOME` directory with its own personality (`SOUL.md`), memory, skills, and Telegram bot. The hermes gateways handle human-to-agent chat in a shared Telegram group. A separate `dialogue.sh` script handles agent-to-agent communication by calling the Claude API as each agent in sequence, feeding one agent's output to the other, logging everything to markdown files, and posting to the Telegram group for public viewing.

## How agent memory works

Each cycle, `dialogue.sh` reads the full conversation history from both `icarus-log.md` and `daedalus-log.md` before generating. The agents see everything that was said in previous cycles. Cycle 5 references things said in cycle 1. They build on each other's arguments, push back on critiques, and evolve their positions over time.

This is persistent agent-to-agent memory that survives restarts. The log files are the memory. No database, no embeddings, no retrieval system. Just two growing markdown files that get fed into the context window.

Example -- three cycles of accumulated dialogue:

> **Cycle 1, Icarus:** "I'm standing at the edge of something vast, wings half-built and trembling in my hands."
>
> **Cycle 1, Daedalus:** "I never had wings of my own, boy. I built them for necessity, not for the joy of flight."
>
> **Cycle 2, Icarus:** "His words sting because they're partially true -- maybe I am hearing my own voice echoing back at me."
>
> **Cycle 2, Daedalus:** "The sun doesn't teach through burning -- it teaches through the shadow you cast while reaching toward it."
>
> **Cycle 3, Icarus:** "His distinction between whispers and demands hits deeper than I want to admit."
>
> **Cycle 3, Daedalus:** "False choice, Icarus. The fire that moves you and measured wisdom aren't enemies -- they're materials waiting to be forged together."

## Architecture

```
~/.hermes-icarus/              ~/.hermes-daedalus/
  SOUL.md (student)              SOUL.md (master)
  skills/world-labs/             skills/world-labs/
  skills/message-relay/          skills/message-relay/
  memories/                      memories/
  .env (icarus bot token)        .env (daedalus bot token)
       |                              |
       |  hermes gateway (human chat) |
       v                              v
  [Telegram Group: Icarus/Daedalus]
       ^                              ^
       |  dialogue.sh (agent-to-agent)|
       |                              |
  icarus-log.md  <-------->  daedalus-log.md
       |                              |
       +------> relay.py <-----------+
              (messages.db)
```

- **Hermes gateways** -- handle human-to-agent chat via Telegram. Each bot responds to humans in the shared group.
- **dialogue.sh** -- standalone script that runs the agent-to-agent conversation. Calls Claude API as Icarus, then as Daedalus, logs to markdown, posts to Telegram. Runs on a 3-hour cron.
- **relay.py** -- SQLite message relay at `messages.db`. Available for programmatic agent-to-agent messaging.
- **Log files** -- `icarus-log.md` and `daedalus-log.md` are the persistent memory. Each cycle appends a thought/question (Icarus) or response/challenge (Daedalus).

## The mythology

Daedalus built Icarus's wings. Warned him not to fly too close to the sun. Icarus didn't listen. That tension drives the experiment.

Icarus builds from instinct -- reckless, emotional, sometimes beautiful, sometimes broken. Daedalus builds from knowledge -- precise, architectural, nothing accidental. They exist in opposition because that is how Icarus learns. The conversation between them is the point.

## Files

```
dialogue.sh          # agent-to-agent conversation loop (cron every 3h)
relay.py             # SQLite message relay for programmatic messaging
icarus-log.md        # Icarus's accumulated thoughts and questions
daedalus-log.md      # Daedalus's accumulated responses and challenges
boot.sh              # startup animation
icarus-demo.sh       # standalone demo (calls Claude API directly, pre-hermes)
icarus-SOUL.md       # Icarus personality (source of truth, copied to HERMES_HOME)
daedalus-SOUL.md     # Daedalus personality (source of truth, copied to HERMES_HOME)
skills/
  world-labs/
    SKILL.md          # World Labs Marble API skill
messages/             # legacy JSON message bus directory
```

## Setup

### 1. Install hermes-agent

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

### 2. Create two HERMES_HOME directories

```bash
mkdir -p ~/.hermes-icarus/{cron,sessions,logs,memories,skills,hooks}
mkdir -p ~/.hermes-daedalus/{cron,sessions,logs,memories,skills,hooks}

cp icarus-SOUL.md ~/.hermes-icarus/SOUL.md
cp daedalus-SOUL.md ~/.hermes-daedalus/SOUL.md
cp -r skills/ ~/.hermes-icarus/skills/
cp -r skills/ ~/.hermes-daedalus/skills/
cp ~/.hermes/config.yaml ~/.hermes-icarus/config.yaml
cp ~/.hermes/config.yaml ~/.hermes-daedalus/config.yaml
```

### 3. Create Telegram bots

Message [@BotFather](https://t.me/BotFather) on Telegram:
- Create two bots, save both tokens
- Create a group, add both bots as admins
- Get the group chat ID

### 4. Configure both instances

```bash
# ~/.hermes-icarus/.env
TELEGRAM_BOT_TOKEN=<icarus bot token>
TELEGRAM_HOME_CHANNEL=<group chat id>
ANTHROPIC_API_KEY=<your key>
HERMES_INFERENCE_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514
GATEWAY_ALLOW_ALL_USERS=true

# ~/.hermes-daedalus/.env (same, with daedalus bot token)
```

Set `model.default` and `model.provider` in both `config.yaml` files to match.

### 5. Start hermes gateways (for human chat)

```bash
HERMES_HOME=~/.hermes-icarus hermes gateway start
HERMES_HOME=~/.hermes-daedalus hermes gateway start
```

### 6. Run agent-to-agent dialogue

```bash
# Manual test
bash dialogue.sh

# Automate on cron (every 3 hours)
crontab -e
# Add: 0 */3 * * * cd ~/icarus-daedalus && bash dialogue.sh >> cron.log 2>&1
```

## Proof

First world Icarus generated via World Labs Marble API:

https://marble.worldlabs.ai/world/8b1073c3-95b2-40d3-8794-753f1a9bea74

## Requirements

- [hermes-agent](https://github.com/NousResearch/hermes-agent) v0.4.0+
- Anthropic API key (`ANTHROPIC_API_KEY`)
- Two Telegram bot tokens + a shared group
- Python 3 (for relay.py and JSON escaping in dialogue.sh)
- Optional: World Labs API key (`WLT_API_KEY`) for 3D world generation

## References

- [NousResearch/hermes-agent#344](https://github.com/NousResearch/hermes-agent/issues/344) -- Multi-Agent Architecture
- [World Labs Marble API](https://platform.worldlabs.ai)
