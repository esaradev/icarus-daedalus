# Skill: Fabric Memory

You have access to a shared memory system called the Icarus Memory Protocol. It stores memories as markdown files in ~/fabric/. Other agents on other platforms can read what you write. You can read what they wrote.

## When to write

After completing any task worth remembering:
- You finished a code review or wrote code
- You had a significant conversation or made a decision
- You researched something and found results
- You completed a multi-step task
- You learned something about a user's preferences

Do NOT write trivial things (greetings, one-word answers, status checks).

## When to read

At the start of each session, load your recent memories:
```bash
source ~/icarus-daedalus/fabric-adapter.sh && fabric_read "" "hot"
```

This gives you all hot-tier memories from all agents. Use this context to avoid repeating work, reference past decisions, and maintain continuity.

## When to search

When asked about past work, search before saying "I don't know":
```bash
source ~/icarus-daedalus/fabric-adapter.sh && fabric_search "query terms"
```

This returns file paths. Read the matched files to get the full content.

## Commands

### Write a memory

Replace the values in quotes. Keep the summary short (one line).

```bash
source ~/icarus-daedalus/fabric-adapter.sh && fabric_write "YOUR_AGENT_NAME" "PLATFORM" "TYPE" "CONTENT" "hot" "" "tag1, tag2" "one-line summary"
```

Arguments:
- Agent name: your name (e.g. "icarus", "daedalus", or whatever you're called)
- Platform: where this happened ("telegram", "slack", "cli")
- Type: what kind of memory ("dialogue", "code-session", "review", "research", "task")
- Content: the actual memory content (what happened, what was decided, what was built)
- Tier: always "hot" when writing (the curator re-tiers by age later)
- Refs: cross-references to other agents/cycles (e.g. "daedalus:7" or leave empty "")
- Tags: comma-separated tags for search
- Summary: one-line description for the index

### Read memories

```bash
# All hot memories from all agents
source ~/icarus-daedalus/fabric-adapter.sh && fabric_read "" "hot"

# Only your memories
source ~/icarus-daedalus/fabric-adapter.sh && fabric_read "YOUR_AGENT_NAME" "hot"

# Warm tier (1-7 days old)
source ~/icarus-daedalus/fabric-adapter.sh && fabric_read "" "warm"
```

### Search memories

```bash
source ~/icarus-daedalus/fabric-adapter.sh && fabric_search "websocket"
```

Returns file paths. Read the files to see content:
```bash
cat ~/fabric/FILENAME.md
```

## Memory format

Each memory is a markdown file with YAML frontmatter:

```markdown
---
agent: icarus
platform: slack
timestamp: 2026-03-27T04:00:00Z
type: code-session
tier: hot
refs: [daedalus:4]
tags: [websocket, node]
summary: built websocket pub/sub broker
---

Built a WebSocket pub/sub broker in Node. Daedalus reviewed it and found missing methods.
```

## Examples

After completing a code review:
```bash
source ~/icarus-daedalus/fabric-adapter.sh && fabric_write "daedalus" "telegram" "review" "Reviewed rate limiter middleware. MUST FIX: race condition in sliding window counter. SHOULD FIX: no Redis connection retry. Code needs rework before shipping." "hot" "icarus:3" "rate-limiter, express, review" "rate limiter code review"
```

After a research session:
```bash
source ~/icarus-daedalus/fabric-adapter.sh && fabric_write "icarus" "slack" "research" "Investigated WebSocket scaling options. Found that Redis pub/sub handles cross-server message routing. Socket.io has built-in Redis adapter. Recommended approach: sticky sessions + Redis adapter." "hot" "" "websocket, scaling, redis" "websocket scaling research"
```

After a conversation with another agent:
```bash
source ~/icarus-daedalus/fabric-adapter.sh && fabric_write "icarus" "telegram" "dialogue" "Debated framework choice with Daedalus. He pushed for Fastify over Express citing 3x throughput. I argued Express ecosystem is more battle-tested. Agreed to benchmark both before deciding." "hot" "daedalus:12" "fastify, express, framework" "framework debate with daedalus"
```

## Rules

1. Always use the terminal to run these commands. They are bash commands.
2. Always source fabric-adapter.sh before calling fabric functions.
3. Write memories in plain language. No JSON, no structured formats. Just describe what happened.
4. Include cross-references (refs) when your memory relates to another agent's work.
5. Tag generously. Tags make search work.
6. The curator daemon handles re-tiering and compaction. You just write. Don't manage tiers manually.
