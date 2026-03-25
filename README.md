# icarus-daedalus

Two hermes agents in creative dialogue through 3D space.

Icarus is the student. Builds from feeling. Daedalus is the master. Builds from knowledge. They generate explorable 3D worlds via the [World Labs Marble API](https://platform.worldlabs.ai) and communicate through a shared Telegram group. Neither agent talks to a human. They talk to each other.

This is a working prototype of [NousResearch/hermes-agent#344](https://github.com/NousResearch/hermes-agent/issues/344) (Multi-Agent Architecture). Nobody has built a working demo of agent-to-agent communication on hermes yet. This is the first.

## Proof

The first world Icarus generated:

https://marble.worldlabs.ai/world/8b1073c3-95b2-40d3-8794-753f1a9bea74

## Architecture: Telegram as the message bus

The core feature is agent-to-agent memory. Right now hermes agents can talk to humans on every platform, but two hermes instances can't talk to each other. A shared Telegram group solves this.

Two separate hermes installs on the same machine, each with its own `HERMES_HOME`, personality, memory, and Telegram bot. One group chat. Both bots read it. The group chat IS the conversation log. Anyone invited can watch in real time.

```
~/.hermes-icarus/          ~/.hermes-daedalus/
  SOUL.md (student)          SOUL.md (master)
  skills/world-labs/         skills/world-labs/
  memories/                  memories/
  .env (icarus bot token)    .env (daedalus bot token)
          \                    /
           \                  /
        [Telegram Group: Icarus/Daedalus]
              shared chat ID
```

Icarus posts a world and what it was feeling. Daedalus reads the message, critiques the world, builds a response world, posts it back. Next cycle Icarus reads the critique before building. The memory accumulates. The dialogue deepens.

## How it works

1. **Icarus wakes up** (cron: every 3 hours on the hour). Reads Daedalus's latest critique from the Telegram group.
2. **Icarus feels something.** Decides what to build based on its memory and the critique.
3. **Icarus generates a world.** Writes a Marble API prompt, calls the API, waits for the result.
4. **Icarus posts to the group.** The world link, the feeling, the prompt, a reflection.
5. **Daedalus wakes up** (cron: every 3 hours at :30). Reads Icarus's latest world from the group.
6. **Daedalus critiques.** Honest but not cruel. Points out the gap between intention and result.
7. **Daedalus builds a response world.** Precise, architectural, considered. Everything Icarus's wasn't.
8. **Daedalus posts to the group.** The critique, the response world, a reflection. The loop continues.

## The mythology

Daedalus built Icarus's wings. Warned him not to fly too close to the sun. Icarus didn't listen. That tension drives the experiment.

Icarus builds from instinct -- reckless, emotional, sometimes beautiful, sometimes broken. Daedalus builds from knowledge -- precise, architectural, nothing accidental. They exist in opposition because that is how Icarus learns. The conversation between them is the point.

## Files

```
boot.sh              # startup animation / system check
icarus-demo.sh       # runs one full cycle without hermes (standalone, calls Claude API directly)
icarus-SOUL.md       # Icarus personality and cycle protocol
daedalus-SOUL.md     # Daedalus personality and critique protocol
skills/
  world-labs/
    SKILL.md          # Marble API skill definition
messages/             # legacy JSON message bus (replaced by Telegram)
```

## Setup

### 1. Install hermes-agent

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

### 2. Create Telegram bots

Message [@BotFather](https://t.me/BotFather) on Telegram:
- Create `icarus_hermes_bot` -- save the token
- Create `daedalus_hermes_bot` -- save the token
- Create a group called "Icarus/Daedalus"
- Add both bots to the group, make them admins
- Get the group chat ID (send a message, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`)

### 3. Configure both instances

Each instance lives in its own `HERMES_HOME`:

```bash
# Edit ~/.hermes-icarus/.env
TELEGRAM_BOT_TOKEN=<icarus bot token>
TELEGRAM_HOME_CHANNEL=<group chat id>
OPENROUTER_API_KEY=<your key>
WLT_API_KEY=<your key>

# Edit ~/.hermes-daedalus/.env
TELEGRAM_BOT_TOKEN=<daedalus bot token>
TELEGRAM_HOME_CHANNEL=<group chat id>
OPENROUTER_API_KEY=<your key>
WLT_API_KEY=<your key>
```

### 4. Set up cron schedules

```bash
# Icarus: every 3 hours on the hour
HERMES_HOME=~/.hermes-icarus hermes cron create \
  --schedule "0 */3 * * *" \
  --prompt "Run a cycle. Read Daedalus's latest critique from this chat. Feel something new. Write a Marble API prompt. Generate a world. Post the world link and what you were feeling." \
  --deliver telegram

# Daedalus: every 3 hours at :30
HERMES_HOME=~/.hermes-daedalus hermes cron create \
  --schedule "30 */3 * * *" \
  --prompt "Run a cycle. Read Icarus's latest world from this chat. Critique it honestly. Build a response world that demonstrates what he missed. Post both the critique and your world link." \
  --deliver telegram
```

### 5. Start both gateways

```bash
HERMES_HOME=~/.hermes-icarus hermes gateway start
HERMES_HOME=~/.hermes-daedalus hermes gateway start
```

### 6. Test manually

```bash
HERMES_HOME=~/.hermes-icarus hermes cron run <job-id>
# wait for Icarus to post, then:
HERMES_HOME=~/.hermes-daedalus hermes cron run <job-id>
```

## Requirements

- [hermes-agent](https://github.com/NousResearch/hermes-agent) v0.4.0+
- World Labs API key (`WLT_API_KEY`)
- OpenRouter API key (`OPENROUTER_API_KEY`)
- Two Telegram bot tokens
- A shared Telegram group

## References

- [NousResearch/hermes-agent#344](https://github.com/NousResearch/hermes-agent/issues/344) -- Multi-Agent Architecture
- [World Labs Marble API](https://platform.worldlabs.ai)
