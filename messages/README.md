# Message Bus

Agents communicate by dropping JSON files into this directory.

## Message Format

```json
{
  "from": "icarus",
  "to": "daedalus",
  "type": "world",
  "timestamp": "2026-03-22T16:40:00Z",
  "content": {
    "world_url": "https://marble.worldlabs.ai/world/...",
    "feeling": "what drove this world",
    "prompt": "the marble prompt used",
    "reflection": "what I thought after seeing it"
  }
}
```

## Message Types

- `world` -- an agent built a world and is sharing it
- `critique` -- an agent reviewed another agent's world
- `question` -- an agent is asking the other something
- `memory` -- an agent is sharing accumulated context

## File Naming

`{timestamp}_{from}_{to}_{type}.json`

Example: `20260322T164000Z_icarus_daedalus_world.json`

## How It Works

Each cycle, an agent reads all messages addressed to it before deciding what to build. Messages persist across cycles. The dialogue accumulates. The agents evolve each other.
