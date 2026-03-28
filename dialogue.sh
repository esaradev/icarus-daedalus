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

# ── Parse agents.yml ───────────────────────────────────
# Simple YAML parser: extracts name, role, home for each agent
parse_agents() {
    python3 -c "
import sys
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
    home = a.get('home', '~/.hermes-' + a['name']).replace('~', '$HOME')
    print(a['name'] + '|' + a.get('role', '') + '|' + home)
" "$AGENTS_FILE"
}

AGENT_LIST=$(parse_agents)
AGENT_COUNT=$(echo "$AGENT_LIST" | wc -l | tr -d ' ')

echo "[$TIMESTAMP] agents: $AGENT_COUNT"

# ── Load env from first agent (for API key + platform tokens) ──
source_env() {
    local f="$1"
    [ -f "$f" ] && while IFS= read -r line; do
        [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
        local k="${line%%=*}"
        local v="${line#*=}"
        [ -n "$k" ] && export "$k"="$v"
    done < "$f"
}

FIRST_HOME=$(echo "$AGENT_LIST" | head -1 | cut -d'|' -f3)
FIRST_HOME=$(eval echo "$FIRST_HOME")
source_env "$FIRST_HOME/.env"

[ -z "${ANTHROPIC_API_KEY:-}" ] && { echo "error: ANTHROPIC_API_KEY not set in $FIRST_HOME/.env" >&2; exit 1; }

SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"
TELEGRAM_GROUP_ID="${TELEGRAM_HOME_CHANNEL:-}"

source "$SCRIPT_DIR/fabric-adapter.sh"

# ── Determine cycle number ─────────────────────────────
FIRST_NAME=$(echo "$AGENT_LIST" | head -1 | cut -d'|' -f1)
FIRST_LOG="$SCRIPT_DIR/${FIRST_NAME}-log.md"
CYCLE=$(grep -c '## Cycle' "$FIRST_LOG" 2>/dev/null || true)
CYCLE=$(( ${CYCLE:-0} + 1 ))

# ── Compaction ─────────────────────────────────────────
if [ -f "$SCRIPT_DIR/compact.sh" ]; then
    source "$SCRIPT_DIR/compact.sh"
    # Compact first two agents' logs if they exist
    SECOND_NAME=$(echo "$AGENT_LIST" | sed -n '2p' | cut -d'|' -f1)
    if [ -n "$SECOND_NAME" ]; then
        SECOND_LOG="$SCRIPT_DIR/${SECOND_NAME}-log.md"
        compact_if_needed "$FIRST_LOG" "$SECOND_LOG" "$CYCLE" "$FIRST_NAME" "$SECOND_NAME"
    fi
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
# Collect recent history from all agents
ALL_HISTORY=""
echo "$AGENT_LIST" | while IFS='|' read -r name role home; do
    home=$(eval echo "$home")
    local_log="$SCRIPT_DIR/${name}-log.md"
    if [ -f "$local_log" ]; then
        ALL_HISTORY="${ALL_HISTORY}
--- ${name} recent ---
$(tail -80 "$local_log" 2>/dev/null)
"
    fi
done

# Read all history into variable (subshell workaround)
ALL_HISTORY=""
for entry in $(echo "$AGENT_LIST" | tr '\n' ';'); do
    name=$(echo "$entry" | cut -d'|' -f1)
    local_log="$SCRIPT_DIR/${name}-log.md"
    if [ -f "$local_log" ]; then
        ALL_HISTORY="${ALL_HISTORY}
--- ${name} recent ---
$(tail -60 "$local_log" 2>/dev/null)
"
    fi
done

# ── Run each agent ─────────────────────────────────────
CYCLE_CONTEXT=""  # accumulates what each agent said this cycle
AGENT_IDX=0

echo "[$TIMESTAMP] cycle $CYCLE"
echo ""

echo "$AGENT_LIST" | while IFS='|' read -r name role home; do
    home=$(eval echo "$home")
    local_log="$SCRIPT_DIR/${name}-log.md"
    AGENT_IDX=$((AGENT_IDX + 1))

    # init log if missing
    [ -f "$local_log" ] || printf "# ${name} log\n\n${role}\n\n" > "$local_log"

    echo "${name}> thinking..."

    # Load this agent's telegram token if available
    local_token=""
    if [ -f "$home/.env" ]; then
        local_token=$(grep "^TELEGRAM_BOT_TOKEN=" "$home/.env" 2>/dev/null | head -1 | cut -d'=' -f2-)
    fi

    # Build system prompt from SOUL.md or role
    local_soul=""
    if [ -f "$home/SOUL.md" ]; then
        local_soul=$(cat "$home/SOUL.md")
    else
        local_soul="You are ${name}. ${role}."
    fi

    # Build prompt with full context
    local system_prompt="${local_soul}

You are in a multi-agent conversation. Cycle $CYCLE. There are $AGENT_COUNT agents total.

Respond with exactly two lines:
THOUGHT: [2-4 sentences. Your perspective based on your role. Reference what other agents said if relevant. Be specific.]
RESPONSE: [One direct statement or question to the group.]"

    local user_prompt="Cycle $CYCLE.

Full conversation history:
$ALL_HISTORY

This cycle so far:
${CYCLE_CONTEXT:-nothing yet, you go first}

Contribute something new based on your role. Don't repeat what others said."

    # Call Claude
    local raw
    raw=$(call_claude "$system_prompt" "$user_prompt") || { echo "FATAL: ${name} call failed" >&2; continue; }

    local thought response
    thought=$(echo "$raw" | sed -n 's/^[* ]*THOUGHT:[* ]* *//p')
    response=$(echo "$raw" | sed -n 's/^[* ]*RESPONSE:[* ]* *//p')

    # Fallback: use raw if parsing fails
    [ -z "$thought" ] && thought="$raw"
    [ -z "$response" ] && response=""

    echo "${name}> $thought"
    [ -n "$response" ] && echo "${name}> $response"
    echo ""

    # Log
    cat >> "$local_log" << EOF

---

## Cycle $CYCLE
$TIMESTAMP

**Thought:** $thought

**Response:** $response

EOF

    # Post to platforms
    if [ -n "$local_token" ]; then
        post_telegram "$local_token" "*${name} -- Cycle $CYCLE*

$thought

_${response}_"
    fi

    post_slack "*${name} -- Cycle $CYCLE*

$thought"

    # Write to fabric
    local refs=""
    # Reference all other agents from this cycle
    for other in $(echo "$AGENT_LIST" | cut -d'|' -f1); do
        [ "$other" = "$name" ] && continue
        refs="${refs}${refs:+, }${other}:${CYCLE}"
    done

    fabric_write "$name" "dialogue" "dialogue" \
        "Thought: $thought
Response: $response" \
        "hot" "$refs" "dialogue" "" "$CYCLE" > /dev/null

    # Write to hermes MEMORY.md
    local mem_file="$home/memories/MEMORY.md"
    if [ -d "$home/memories" ]; then
        append_memory "$mem_file" "
[$TIMESTAMP] Cycle $CYCLE
${name} said: $thought"
    fi

    # Add to cycle context for next agent
    CYCLE_CONTEXT="${CYCLE_CONTEXT}
${name}: $thought"

    sleep 1
done

echo "fabric> written to ~/fabric/"
echo "cycle $CYCLE complete ($AGENT_COUNT agents)"
