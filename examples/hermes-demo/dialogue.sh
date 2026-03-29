#!/usr/bin/env bash
# dialogue.sh -- One cycle of multi-agent dialogue.
# Reads agents.yml, runs each agent in sequence. Each agent sees all
# previous agents' output from this cycle + full history from fabric.
#
# Usage: bash dialogue.sh
# Config: agents.yml in the same directory

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTS_FILE="$SCRIPT_DIR/agents.yml"
TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')

[ -f "$AGENTS_FILE" ] || { echo "error: agents.yml not found" >&2; exit 1; }

# ── Parse agents.yml into temp file ────────────────────
AGENT_TMP=$(mktemp)
trap "rm -f $AGENT_TMP" EXIT

python3 -c "
import sys, os
lines = open(sys.argv[1]).readlines()
agents = []
current = {}
for line in lines:
    line = line.rstrip()
    if line.strip().startswith('- name:'):
        if current:
            agents.append(current)
        current = {'name': line.split(':', 1)[1].strip()}
    elif line.strip().startswith('role:'):
        current['role'] = line.split(':', 1)[1].strip()
    elif line.strip().startswith('home:'):
        current['home'] = line.split(':', 1)[1].strip()
if current:
    agents.append(current)
for a in agents:
    home = a.get('home', '~/.hermes-' + a['name']).replace('~', os.environ['HOME'])
    print(a['name'] + '|' + a.get('role', '') + '|' + home)
" "$AGENTS_FILE" > "$AGENT_TMP"

AGENT_COUNT=$(wc -l < "$AGENT_TMP" | tr -d ' ')
[ "$AGENT_COUNT" -eq 0 ] && { echo "error: no agents in agents.yml" >&2; exit 1; }

echo "[$TIMESTAMP] agents: $AGENT_COUNT"

# ── Load env from first agent ──────────────────────────
source_env() {
    local f="$1"
    [ -f "$f" ] && while IFS= read -r line; do
        [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
        local k="${line%%=*}"
        local v="${line#*=}"
        [ -n "$k" ] && export "$k"="$v"
    done < "$f"
}

FIRST_HOME=$(head -1 "$AGENT_TMP" | cut -d'|' -f3)
source_env "$FIRST_HOME/.env"

[ -z "${ANTHROPIC_API_KEY:-}" ] && { echo "error: ANTHROPIC_API_KEY not set in $FIRST_HOME/.env" >&2; exit 1; }

SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"
TELEGRAM_GROUP_ID="${TELEGRAM_HOME_CHANNEL:-}"

REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$REPO_DIR/fabric-adapter.sh"

# ── Determine cycle number ─────────────────────────────
FIRST_NAME=$(head -1 "$AGENT_TMP" | cut -d'|' -f1)
FIRST_LOG="$SCRIPT_DIR/${FIRST_NAME}-log.md"
CYCLE=$(grep -c '## Cycle' "$FIRST_LOG" 2>/dev/null || true)
CYCLE=$(( ${CYCLE:-0} + 1 ))

# ── Compaction (all agent pairs) ──────────────────────
if [ -f "$SCRIPT_DIR/compact.sh" ]; then
    source "$SCRIPT_DIR/compact.sh" # compact.sh stays in demo dir
    # Compact consecutive pairs from agents.yml
    PREV_NAME=""
    PREV_LOG=""
    while IFS='|' read -r cname crole chome; do
        CLOG="$SCRIPT_DIR/${cname}-log.md"
        if [ -n "$PREV_NAME" ] && [ -f "$PREV_LOG" ] && [ -f "$CLOG" ]; then
            compact_if_needed "$PREV_LOG" "$CLOG" "$CYCLE" "$PREV_NAME" "$cname"
        fi
        PREV_NAME="$cname"
        PREV_LOG="$CLOG"
    done < "$AGENT_TMP"
fi

# ── Shared functions ───────────────────────────────────
call_claude() {
    local system="$1" prompt="$2" max_tokens="${3:-512}"
    local sys_json prompt_json
    sys_json=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$system")
    prompt_json=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$prompt")
    local raw
    raw=$(curl -s https://api.anthropic.com/v1/messages \
        -H "content-type: application/json" \
        -H "x-api-key: $ANTHROPIC_API_KEY" \
        -H "anthropic-version: 2023-06-01" \
        -d "{\"model\":\"claude-sonnet-4-20250514\",\"max_tokens\":$max_tokens,\"system\":$sys_json,\"messages\":[{\"role\":\"user\",\"content\":$prompt_json}]}")
    echo "$raw" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'content' in data and len(data['content']) > 0:
        print(data['content'][0]['text'])
    elif 'error' in data:
        print('API_ERROR: ' + data['error'].get('message', str(data['error'])), file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(1)
except Exception as e:
    print(f'PARSE_ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1
}

post_telegram() {
    [ -z "$TELEGRAM_GROUP_ID" ] && return 0
    local token="$1" text="$2"
    local text_json
    text_json=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$text")
    curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"$TELEGRAM_GROUP_ID\",\"text\":$text_json,\"parse_mode\":\"Markdown\"}" > /dev/null
}

post_slack() {
    [ -z "$SLACK_WEBHOOK_URL" ] && return 0
    local text="$1"
    local text_json
    text_json=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$text")
    curl -s -X POST "$SLACK_WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"text\":$text_json}" > /dev/null
}

append_memory() {
    local memfile="$1" entry="$2"
    [ -f "$memfile" ] || printf "" > "$memfile"
    echo "$entry" >> "$memfile"
    local size
    size=$(wc -c < "$memfile" 2>/dev/null | tr -d ' ')
    local tries=0
    while [ "${size:-0}" -gt 2000 ] && [ "$tries" -lt 20 ]; do
        tail -n +5 "$memfile" > "$memfile.tmp" && mv "$memfile.tmp" "$memfile"
        size=$(wc -c < "$memfile" 2>/dev/null | tr -d ' ')
        tries=$((tries + 1))
    done
}

# ── Build shared context ───────────────────────────────
ALL_HISTORY=""
while IFS='|' read -r name role home; do
    alog="$SCRIPT_DIR/${name}-log.md"
    if [ -f "$alog" ]; then
        ALL_HISTORY="${ALL_HISTORY}
--- ${name} recent ---
$(tail -60 "$alog" 2>/dev/null)
"
    fi
done < "$AGENT_TMP"

# ── Load shared fabric memory (smart retrieval) ──────
FABRIC_CONTEXT=""
if [ -f "$REPO_DIR/fabric-retrieve.py" ]; then
    # Build a real query from the conversation so far
    QUERY=""
    if [ -n "$ALL_HISTORY" ]; then
        # Use the last 200 chars of conversation as the query
        QUERY=$(echo "$ALL_HISTORY" | tail -10 | tr '\n' ' ' | sed 's/.*\(.\{200\}\)/\1/')
    fi
    [ -z "$QUERY" ] && QUERY="agent conversation recent work"
    FABRIC_CONTEXT=$(python3 "$REPO_DIR/fabric-retrieve.py" "$QUERY" --max-results 5 --max-tokens 1500 2>/dev/null || true)
    if [ -n "$FABRIC_CONTEXT" ] && [ "$FABRIC_CONTEXT" != "no relevant entries found" ]; then
        FABRIC_CONTEXT="
--- relevant fabric memory ---
$FABRIC_CONTEXT
"
    else
        FABRIC_CONTEXT=""
    fi
fi
# Fallback to basic read
if [ -z "$FABRIC_CONTEXT" ]; then
    FABRIC_ENTRIES=$(fabric_read "" "hot" 2>/dev/null || true)
    if [ -n "$FABRIC_ENTRIES" ]; then
        FABRIC_CONTEXT="
--- shared fabric memory ---
$(echo "$FABRIC_ENTRIES" | head -80)
"
    fi
fi

# ── Run each agent ─────────────────────────────────────
CYCLE_CONTEXT=""
AGENT_IDX=0

echo "[$TIMESTAMP] cycle $CYCLE"
echo ""

while IFS='|' read -r name role home; do
    alog="$SCRIPT_DIR/${name}-log.md"
    AGENT_IDX=$((AGENT_IDX + 1))

    [ -f "$alog" ] || printf "# ${name} log\n\n${role}\n\n" > "$alog"

    echo "${name}> thinking..."

    # Telegram token for this agent
    tg_token=""
    if [ -f "$home/.env" ]; then
        tg_token=$(grep "^TELEGRAM_BOT_TOKEN=" "$home/.env" 2>/dev/null | head -1 | cut -d'=' -f2-)
    fi

    # System prompt from SOUL.md or role
    soul=""
    if [ -f "$home/SOUL.md" ]; then
        soul=$(cat "$home/SOUL.md")
    else
        soul="You are ${name}. ${role}."
    fi

    system_prompt="${soul}

You are in a multi-agent conversation. Cycle $CYCLE. There are $AGENT_COUNT agents total.

Respond with exactly two lines:
THOUGHT: [2-4 sentences. Your perspective based on your role. Reference what other agents said if relevant. Be specific.]
RESPONSE: [One direct statement or question to the group.]"

    user_prompt="Cycle $CYCLE.

Shared memory from fabric (cross-platform entries):
${FABRIC_CONTEXT:-no shared entries yet}

Full conversation history:
$ALL_HISTORY

This cycle so far:
${CYCLE_CONTEXT:-nothing yet, you go first}

Contribute something new based on your role. Don't repeat what others said."

    # Call Claude
    raw=$(call_claude "$system_prompt" "$user_prompt") || { echo "WARN: ${name} call failed" >&2; continue; }

    thought=$(echo "$raw" | sed -n 's/^[* ]*THOUGHT:[* ]* *//p')
    response=$(echo "$raw" | sed -n 's/^[* ]*RESPONSE:[* ]* *//p')

    [ -z "$thought" ] && thought="$raw"
    [ -z "$response" ] && response=""

    echo "${name}> $thought"
    [ -n "$response" ] && echo "${name}> $response"
    echo ""

    # Log
    cat >> "$alog" << EOF

---

## Cycle $CYCLE
$TIMESTAMP

**Thought:** $thought

**Response:** $response

EOF

    # Post to platforms
    if [ -n "$tg_token" ]; then
        post_telegram "$tg_token" "*${name} -- Cycle $CYCLE*

$thought

_${response}_"
    fi

    post_slack "*${name} -- Cycle $CYCLE*

$thought"

    # Write to fabric
    refs=""
    while IFS='|' read -r other_name _role _home; do
        [ "$other_name" = "$name" ] && continue
        refs="${refs}${refs:+, }${other_name}:${CYCLE}"
    done < "$AGENT_TMP"

    fabric_write "$name" "dialogue" "dialogue" \
        "Thought: $thought
Response: $response" \
        "hot" "$refs" "dialogue" "" "$CYCLE" > /dev/null

    # Write to hermes MEMORY.md
    if [ -d "$home/memories" ]; then
        append_memory "$home/memories/MEMORY.md" "
[$TIMESTAMP] Cycle $CYCLE
${name} said: $thought"
    fi

    CYCLE_CONTEXT="${CYCLE_CONTEXT}
${name}: $thought"

    sleep 1
done < "$AGENT_TMP"

echo "fabric> written to ~/fabric/"
echo "cycle $CYCLE complete ($AGENT_COUNT agents)"
