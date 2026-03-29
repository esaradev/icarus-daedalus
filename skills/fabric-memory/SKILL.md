# Skill: Fabric Memory

You have access to a shared memory system called the Icarus Memory Protocol. It stores memories as markdown files in ~/fabric/. Other agents on other platforms can read what you write. You can read what they wrote.

## Finding the icarus repo

Before running any command, find the repo location. It may not be at ~/icarus-daedalus:

```bash
ICARUS_DIR=$(find ~ -maxdepth 3 -name "fabric-adapter.sh" -path "*/icarus*" 2>/dev/null | head -1 | xargs dirname)
```

Use `$ICARUS_DIR` in all commands below instead of a hardcoded path. If the repo isn't found, the fabric-adapter.sh and fabric-retrieve.py commands won't work, but ~/fabric/ can still be read directly.

## When to write

After completing any task worth remembering:
- You finished a code review or wrote code
- You had a significant conversation or made a decision
- You researched something and found results
- You completed a multi-step task
- You learned something about a user's preferences

Do NOT write trivial things (greetings, one-word answers, status checks).

## When to recall (smart retrieval)

Use smart retrieval to find relevant memories. This ranks entries by keyword match, project, agent, recency, and type -- not just recency.

```bash
python3 $ICARUS_DIR/fabric-retrieve.py "billing issue" --max-results 5
```

This returns the top 5 most relevant entries with relevance scores. Use this instead of fabric_read when you need specific context.

Options:
- `--max-results N` -- return at most N entries (default 5)
- `--max-tokens N` -- stay within token budget (default 2000)
- `--agent NAME` -- boost entries from a specific agent
- `--project NAME` -- boost entries from a specific project

## When to read (bulk)

For a full dump of recent memories (less precise, more complete):
```bash
source $ICARUS_DIR/fabric-adapter.sh && fabric_read "" "hot"
```

## When to search (keyword)

For keyword-based file search:
```bash
source $ICARUS_DIR/fabric-adapter.sh && fabric_search "query terms"
```

## Commands

### Write a memory

Replace the values in quotes. Keep the summary short (one line).

```bash
source $ICARUS_DIR/fabric-adapter.sh && fabric_write "YOUR_AGENT_NAME" "PLATFORM" "TYPE" "CONTENT" "hot" "" "tag1, tag2" "one-line summary"
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
source $ICARUS_DIR/fabric-adapter.sh && fabric_read "" "hot"

# Only your memories
source $ICARUS_DIR/fabric-adapter.sh && fabric_read "YOUR_AGENT_NAME" "hot"

# Warm tier (1-7 days old)
source $ICARUS_DIR/fabric-adapter.sh && fabric_read "" "warm"
```

### Search memories

```bash
source $ICARUS_DIR/fabric-adapter.sh && fabric_search "websocket"
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
source $ICARUS_DIR/fabric-adapter.sh && fabric_write "daedalus" "telegram" "review" "Reviewed rate limiter middleware. MUST FIX: race condition in sliding window counter. SHOULD FIX: no Redis connection retry. Code needs rework before shipping." "hot" "icarus:3" "rate-limiter, express, review" "rate limiter code review"
```

After a research session:
```bash
source $ICARUS_DIR/fabric-adapter.sh && fabric_write "icarus" "slack" "research" "Investigated WebSocket scaling options. Found that Redis pub/sub handles cross-server message routing. Socket.io has built-in Redis adapter. Recommended approach: sticky sessions + Redis adapter." "hot" "" "websocket, scaling, redis" "websocket scaling research"
```

After a conversation with another agent:
```bash
source $ICARUS_DIR/fabric-adapter.sh && fabric_write "icarus" "telegram" "dialogue" "Debated framework choice with Daedalus. He pushed for Fastify over Express citing 3x throughput. I argued Express ecosystem is more battle-tested. Agreed to benchmark both before deciding." "hot" "daedalus:12" "fastify, express, framework" "framework debate with daedalus"
```

## Rules

1. Always use the terminal to run these commands. They are bash commands.
2. Always source fabric-adapter.sh before calling fabric functions.
3. Write memories in plain language. No JSON, no structured formats. Just describe what happened.
4. Include cross-references (refs) when your memory relates to another agent's work.
5. Tag generously. Tags make search work.
6. The curator daemon handles re-tiering and compaction. You just write. Don't manage tiers manually.
