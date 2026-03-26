# icarus-daedalus

Two AI agents with persistent memory across platforms. They work together on Slack, talk on Telegram, and remember everything across both. What they do depends on you. Swap the SOUL files and they become a code review team, a research pair, a brand strategist and editor, a trading desk, or anything else that benefits from two perspectives and shared memory.

Built on [Hermes Agent](https://github.com/NousResearch/hermes-agent). Prototype of [NousResearch/hermes-agent#344](https://github.com/NousResearch/hermes-agent/issues/344) (Multi-Agent Architecture).

## Quick start

```bash
git clone https://github.com/esaradev/icarus-daedalus.git
cd icarus-daedalus
bash setup.sh
```

The wizard walks you through everything: picks a template, sets up Telegram/Slack, creates both agent instances, runs a test cycle. Five minutes to two agents working together.

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
setup.sh             # one-command setup wizard
dashboard.js         # web dashboard at localhost:3000
dialogue.sh          # agent-to-agent conversation loop (cron every 3h)
relay.py             # SQLite message relay for programmatic messaging
icarus-log.md        # Icarus's accumulated thoughts and questions
daedalus-log.md      # Daedalus's accumulated responses and challenges
icarus-SOUL.md       # Icarus personality (source of truth, copied to HERMES_HOME)
daedalus-SOUL.md     # Daedalus personality (source of truth, copied to HERMES_HOME)
templates/
  code-review/       # Icarus writes code, Daedalus reviews it
  research-validation/ # Explorer + Validator agent pair
  trading-strategy/  # Strategist + Risk Manager agent pair
skills/
  world-labs/
    SKILL.md          # World Labs Marble API skill
```

## Dashboard

```bash
node dashboard.js
# open http://localhost:3000
```

Live web dashboard showing both agents' work. No dependencies beyond Node.js.

- **Stats bar** -- dialogue cycles, code reviews, total messages, memory usage, world count
- **Dialogue tab** -- side-by-side view of Icarus's thoughts and Daedalus's responses, newest first
- **Code review tab** -- Icarus's code submissions alongside Daedalus's reviews with severity labels
- **Memory tab** -- current cross-platform memory contents with usage bars
- **Worlds tab** -- links to any generated World Labs worlds

Updates in real time via SSE. Run a dialogue cycle in another terminal and watch it appear.

## Manual setup

If you prefer to set things up yourself instead of using `setup.sh`:

1. Install [hermes-agent](https://github.com/NousResearch/hermes-agent): `curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash`
2. Create two HERMES_HOME directories with subdirs: `cron`, `sessions`, `logs`, `memories`, `skills`, `hooks`
3. Copy `SOUL.md` files to each instance
4. Copy `config.yaml` from `~/.hermes/config.yaml` to both
5. Create `.env` files with `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_HOME_CHANNEL`, `LLM_MODEL`
6. Start gateways: `HERMES_HOME=~/.hermes-icarus hermes gateway run &`
7. Run dialogue: `bash dialogue.sh`

## Slack integration (optional)

Post each dialogue cycle to a Slack channel alongside Telegram. The Slack adapter is optional -- if `SLACK_WEBHOOK_URL` is not set, nothing happens.

### Setup

1. Create a Slack app at [api.slack.com/apps](https://api.slack.com/apps)
2. Enable **Incoming Webhooks** and add one to a channel (e.g. `#agent-dialogue`)
3. Copy the webhook URL and add it to either hermes `.env` file:

```bash
# ~/.hermes-icarus/.env (or ~/.hermes-daedalus/.env)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
```

Or export it before running:

```bash
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
bash dialogue.sh
```

Each cycle posts two messages: Icarus's thought and Daedalus's response, formatted with Slack mrkdwn.

## Templates

Ready-to-use agent pairs for common two-agent workflows. Each template has its own `dialogue.sh`, `agent-a-SOUL.md`, and `agent-b-SOUL.md`. Clone the repo, pick a template, add your API key, run.

### code-review

**Architect** proposes code and explains every decision. **Reviewer** checks for bugs, security issues, performance, and maintainability. Reviewer labels issues as BLOCKING, WARNING, or NIT and tracks whether past feedback was incorporated.

```bash
cd templates/code-review
echo "ANTHROPIC_API_KEY=sk-..." > .env
bash dialogue.sh path/to/file-or-diff.patch
```

### research-validation

**Explorer** researches a topic deeply, finding new angles and connections. **Validator** fact-checks claims, catches contradictions across cycles, and labels issues as FACTUAL_ERROR, LOGICAL_ERROR, or GAP.

```bash
cd templates/research-validation
echo "ANTHROPIC_API_KEY=sk-..." > .env
bash dialogue.sh "the relationship between sleep deprivation and false memory formation"
```

### trading-strategy

**Strategist** proposes trade setups with entry, exit, stop, and thesis. **Risk Manager** stress-tests every setup, checks correlation/liquidity/event risk, and issues verdicts: APPROVED, REDUCE_SIZE, WIDEN_STOP, or REJECT.

```bash
cd templates/trading-strategy
echo "ANTHROPIC_API_KEY=sk-..." > .env
bash dialogue.sh "BTC consolidating at 65k, ETH/BTC ratio at 3-year low"
```

All templates support `SLACK_WEBHOOK_URL` in `.env` for Slack posting.

## Cross-platform memory

Agents share persistent memory across platforms. Code review sessions on Slack are recallable when talking to the agents on Telegram, and vice versa.

After each cycle, both `dialogue.sh` scripts write a structured summary to `$HERMES_HOME/memories/MEMORY.md` -- the file hermes injects into the system prompt at session start. Oldest entries rotate out when the file exceeds the 2200-char limit.

### How it works

1. **Code review cycle runs on Slack** via `templates/code-review/dialogue.sh`
2. Script summarizes the session (what was coded, what was reviewed, outcome) using a Claude call
3. Summary is appended to `~/.hermes-icarus/memories/MEMORY.md` and `~/.hermes-daedalus/memories/MEMORY.md`
4. Next time someone messages Icarus on Telegram: "what code did you work on today?"
5. Hermes loads MEMORY.md into the system prompt -- Icarus recalls the Slack coding session with specifics

The main dialogue loop (`dialogue.sh` in project root) does the same thing in reverse -- philosophical conversations on Telegram get written to memory so coding sessions can reference them.

### Example

After a code review cycle where Icarus wrote a websocket pub/sub broker:

```
> You: what do you remember about coding sessions?
> Icarus: I remember the most recent one. Cycle 4. I wrote a WebSocket pub/sub
>   broker in Node. Channel subscriptions, message history. Daedalus tore it
>   apart. Said my code was incomplete. Cut-off methods. Missing the core
>   methods. He was right. Complete rewrite needed.
```

### Important

Hermes caches agents in memory. After writing new entries to MEMORY.md, the gateway must be restarted for agents to see updated memory:

```bash
pkill -f "hermes gateway run"
HERMES_HOME=~/.hermes-icarus hermes gateway run &
HERMES_HOME=~/.hermes-daedalus hermes gateway run &
```

## Requirements

- [hermes-agent](https://github.com/NousResearch/hermes-agent) v0.4.0+
- Anthropic API key (`ANTHROPIC_API_KEY`)
- Two Telegram bot tokens + a shared group
- Python 3 (for relay.py and JSON escaping in dialogue.sh)
- Optional: World Labs API key (`WLT_API_KEY`) for 3D world generation

## References

- [NousResearch/hermes-agent#344](https://github.com/NousResearch/hermes-agent/issues/344) -- Multi-Agent Architecture
- [World Labs Marble API](https://platform.worldlabs.ai)
