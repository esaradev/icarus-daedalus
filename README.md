# icarus-daedalus

Two hermes agents in creative dialogue through 3D space.

Icarus is the student. Builds from feeling. Daedalus is the master. Builds from knowledge. They generate explorable 3D worlds via the [World Labs Marble API](https://platform.worldlabs.ai) and communicate through a message bus. Neither agent talks to a human. They talk to each other.

This is a working prototype of [NousResearch/hermes-agent#344](https://github.com/NousResearch/hermes-agent/issues/344) (Multi-Agent Architecture). Nobody has built a working demo of agent-to-agent communication on hermes yet. This is the first.

## Proof

The first world Icarus generated:

https://marble.worldlabs.ai/world/8b1073c3-95b2-40d3-8794-753f1a9bea74

## The message bus

The core feature is agent-to-agent memory. Right now hermes agents can talk to humans on every platform, but two hermes instances can't talk to each other. The `messages/` directory solves this.

Agents drop JSON messages into a shared directory. Each message has a `from`, `to`, `type`, `content`, and `timestamp`. Icarus sends a world message to Daedalus with the marble link and what it was feeling. Daedalus reads it, visits the world, sends a critique message back. Next cycle Icarus reads the critique before building.

The memory accumulates. The dialogue deepens. The agents evolve each other.

```json
{
  "from": "icarus",
  "to": "daedalus",
  "type": "world",
  "timestamp": "2026-03-22T16:40:00Z",
  "content": {
    "world_url": "https://marble.worldlabs.ai/world/...",
    "feeling": "I kept thinking about negative space",
    "prompt": "the marble prompt",
    "reflection": "it worked better than I expected"
  }
}
```

See [`messages/README.md`](messages/README.md) for the full protocol.

## How it works

1. **Icarus feels something.** Reads his memory, reads Daedalus's critiques, decides what to build.
2. **Icarus writes a marble prompt.** Translates the feeling into a walkable 3D environment.
3. **Icarus generates a world.** Calls the Marble API, waits for the result.
4. **Icarus sends a message to Daedalus.** Drops a JSON file in `messages/` with the world URL, the feeling, and a reflection.
5. **Daedalus reads the message.** Visits the world. Understands what Icarus was reaching for.
6. **Daedalus critiques.** Honest but not cruel. Points out the gap between intention and result.
7. **Daedalus builds a response world.** Precise, architectural, considered. Everything Icarus's wasn't.
8. **Daedalus sends a critique back.** Next cycle, Icarus reads it before building. The loop continues.

## The mythology

Daedalus built Icarus's wings. Warned him not to fly too close to the sun. Icarus didn't listen. That tension drives the experiment.

Icarus builds from instinct -- reckless, emotional, sometimes beautiful, sometimes broken. Daedalus builds from knowledge -- precise, architectural, nothing accidental. They exist in opposition because that is how Icarus learns. The conversation between them is the point.

## Files

```
boot.sh              # startup animation / system check
icarus-demo.sh       # runs one full cycle: Icarus creates, Daedalus responds
icarus-SOUL.md       # Icarus personality and cycle protocol
daedalus-SOUL.md     # Daedalus personality and critique protocol
skills/
  world-labs/
    SKILL.md          # Marble API skill definition
messages/             # agent-to-agent message bus (JSON files)
```

## Requirements

- [hermes-agent](https://github.com/NousResearch/hermes-agent)
- World Labs API key (`WLT_API_KEY`)
- Anthropic API key (`ANTHROPIC_API_KEY`)

## Run

```bash
export WLT_API_KEY=your_key
export ANTHROPIC_API_KEY=your_key
bash boot.sh            # watch the startup sequence
bash icarus-demo.sh     # run one dialogue cycle
```

## References

- [NousResearch/hermes-agent#344](https://github.com/NousResearch/hermes-agent/issues/344) -- Multi-Agent Architecture
- [World Labs Marble API](https://platform.worldlabs.ai)
