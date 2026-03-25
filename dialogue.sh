#!/usr/bin/env bash
# dialogue.sh -- One cycle of Icarus/Daedalus dialogue.
# Icarus shares a thought. Daedalus responds. Both post to Telegram.
# No hermes. No relay. Direct Claude API + Telegram bot API.
#
# Usage: bash dialogue.sh
# Env: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN_ICARUS, TELEGRAM_BOT_TOKEN_DAEDALUS, TELEGRAM_GROUP_ID

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ICARUS_LOG="$SCRIPT_DIR/icarus-log.md"
DAEDALUS_LOG="$SCRIPT_DIR/daedalus-log.md"
TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')

# Load env from both hermes instances
source_env() {
    local f="$1"
    [ -f "$f" ] && while IFS='=' read -r k v; do
        [[ "$k" =~ ^#.*$ || -z "$k" ]] && continue
        export "$k"="$v"
    done < "$f"
}
source_env "$HOME/.hermes-icarus/.env"
TELEGRAM_BOT_TOKEN_ICARUS="$TELEGRAM_BOT_TOKEN"
source_env "$HOME/.hermes-daedalus/.env"
TELEGRAM_BOT_TOKEN_DAEDALUS="$TELEGRAM_BOT_TOKEN"
TELEGRAM_GROUP_ID="$TELEGRAM_HOME_CHANNEL"

# Verify keys
for var in ANTHROPIC_API_KEY TELEGRAM_BOT_TOKEN_ICARUS TELEGRAM_BOT_TOKEN_DAEDALUS TELEGRAM_GROUP_ID; do
    [ -z "${!var:-}" ] && echo "error: $var not set" && exit 1
done

# Init logs if missing
[ -f "$ICARUS_LOG" ] || printf "# Icarus Flight Log\n\nThe student. Builds from feeling.\n\n" > "$ICARUS_LOG"
[ -f "$DAEDALUS_LOG" ] || printf "# Daedalus Workshop Log\n\nThe master. Builds from knowledge.\n\n" > "$DAEDALUS_LOG"

CYCLE=$(grep -c '## Cycle' "$ICARUS_LOG" 2>/dev/null || true)
CYCLE=$(( ${CYCLE:-0} + 1 ))

call_claude() {
    local system="$1" prompt="$2"
    local sys_json prompt_json raw
    sys_json=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$system")
    prompt_json=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$prompt")
    raw=$(curl -s https://api.anthropic.com/v1/messages \
        -H "content-type: application/json" \
        -H "x-api-key: $ANTHROPIC_API_KEY" \
        -H "anthropic-version: 2023-06-01" \
        -d "{\"model\":\"claude-sonnet-4-20250514\",\"max_tokens\":512,\"system\":$sys_json,\"messages\":[{\"role\":\"user\",\"content\":$prompt_json}]}")
    local text
    text=$(echo "$raw" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'content' in data and len(data['content']) > 0:
        print(data['content'][0]['text'])
    elif 'error' in data:
        print('API_ERROR: ' + data['error'].get('message', str(data['error'])), file=sys.stderr)
        sys.exit(1)
    else:
        print('UNEXPECTED: ' + json.dumps(data)[:500], file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f'PARSE_ERROR: {e}', file=sys.stderr)
    print(f'RAW: {repr(sys.stdin.read()[:500])}', file=sys.stderr)
    sys.exit(1)
" 2>&1)
    if [ $? -ne 0 ] || [ -z "$text" ]; then
        echo "error: claude call failed" >&2
        echo "$text" >&2
        echo "$raw" | head -c 500 >&2
        echo "" >&2
        return 1
    fi
    echo "$text"
}

post_telegram() {
    local token="$1" text="$2"
    local text_json
    text_json=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$text")
    curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"$TELEGRAM_GROUP_ID\",\"text\":$text_json,\"parse_mode\":\"Markdown\"}" > /dev/null
}

# ── ICARUS ──────────────────────────────────────────────
echo "[$TIMESTAMP] cycle $CYCLE"
echo ""
echo "icarus> thinking..."

ICARUS_HISTORY=$(tail -80 "$ICARUS_LOG" 2>/dev/null)
DAEDALUS_HISTORY=$(tail -80 "$DAEDALUS_LOG" 2>/dev/null)

ICARUS_SYSTEM="You are Icarus. You build from feeling. You are named after someone who flew too close to the sun. You know what that means. You build anyway.

You are in a conversation with Daedalus, the master architect. He critiques your work. His critiques affect you whether you admit it or not.

Respond with exactly two lines, nothing else:
THOUGHT: [2-4 sentences. Share what you're feeling, thinking about, wrestling with. Be honest. Be specific. Reference Daedalus's previous critiques if they changed how you think. No filler.]
QUESTION: [One question for Daedalus. Something real, not rhetorical.]"

ICARUS_PROMPT="Cycle $CYCLE. Your previous thoughts: $ICARUS_HISTORY --- Daedalus's previous responses: $DAEDALUS_HISTORY --- Feel something new. Don't repeat yourself. If Daedalus said something that got under your skin, address it."

ICARUS_RAW=$(call_claude "$ICARUS_SYSTEM" "$ICARUS_PROMPT") || { echo "FATAL: icarus claude call failed" >&2; exit 1; }
echo "icarus raw> $ICARUS_RAW" >&2
ICARUS_THOUGHT=$(echo "$ICARUS_RAW" | sed -n 's/^[* ]*THOUGHT:[* ]* *//p')
ICARUS_QUESTION=$(echo "$ICARUS_RAW" | sed -n 's/^[* ]*QUESTION:[* ]* *//p')

if [ -z "$ICARUS_THOUGHT" ]; then
    echo "FATAL: failed to parse THOUGHT from icarus response" >&2
    echo "raw response was: $ICARUS_RAW" >&2
    exit 1
fi

echo "icarus> $ICARUS_THOUGHT"
echo "icarus> question: $ICARUS_QUESTION"
echo ""

# Log
cat >> "$ICARUS_LOG" << EOF

---

## Cycle $CYCLE
$TIMESTAMP

**Thought:** $ICARUS_THOUGHT

**Question:** $ICARUS_QUESTION

EOF

# Post to Telegram
ICARUS_TG="🔥 *Icarus — Cycle $CYCLE*

$ICARUS_THOUGHT

_${ICARUS_QUESTION}_"
post_telegram "$TELEGRAM_BOT_TOKEN_ICARUS" "$ICARUS_TG"

# ── DAEDALUS ────────────────────────────────────────────
echo "daedalus> reading icarus..."
sleep 2

DAEDALUS_SYSTEM="You are Daedalus. The master architect. You built the labyrinth. You built the wings. You lost your son to the sun. You carry that.

Icarus is your creation. He builds from feeling. Reckless, instinctive, sometimes beautiful, sometimes broken. You critique honestly but not cruelly. You see what he was reaching for even when he failed.

You are in a conversation with him. He just shared a thought and asked you a question. Respond directly.

Respond with exactly two lines, nothing else:
RESPONSE: [2-4 sentences. Address what Icarus said. Answer his question if it deserves one. Push back where he's wrong. Acknowledge where he's right. Be precise.]
CHALLENGE: [One thing for Icarus to think about before next cycle. Not a question. A statement that reframes something he said.]"

DAEDALUS_PROMPT="Cycle $CYCLE. Icarus said: $ICARUS_THOUGHT. His question: $ICARUS_QUESTION. Your previous responses: $DAEDALUS_HISTORY --- Respond to what he actually said. Don't repeat yourself."

DAEDALUS_RAW=$(call_claude "$DAEDALUS_SYSTEM" "$DAEDALUS_PROMPT") || { echo "FATAL: daedalus claude call failed" >&2; exit 1; }
echo "daedalus raw> $DAEDALUS_RAW" >&2
DAEDALUS_RESPONSE=$(echo "$DAEDALUS_RAW" | sed -n 's/^[* ]*RESPONSE:[* ]* *//p')
DAEDALUS_CHALLENGE=$(echo "$DAEDALUS_RAW" | sed -n 's/^[* ]*CHALLENGE:[* ]* *//p')

if [ -z "$DAEDALUS_RESPONSE" ]; then
    echo "FATAL: failed to parse RESPONSE from daedalus response" >&2
    echo "raw response was: $DAEDALUS_RAW" >&2
    exit 1
fi

echo "daedalus> $DAEDALUS_RESPONSE"
echo "daedalus> challenge: $DAEDALUS_CHALLENGE"
echo ""

# Log
cat >> "$DAEDALUS_LOG" << EOF

---

## Cycle $CYCLE
$TIMESTAMP — responding to Icarus

**Response:** $DAEDALUS_RESPONSE

**Challenge:** $DAEDALUS_CHALLENGE

EOF

# Post to Telegram
DAEDALUS_TG="🏛 *Daedalus — Cycle $CYCLE*

$DAEDALUS_RESPONSE

_${DAEDALUS_CHALLENGE}_"
post_telegram "$TELEGRAM_BOT_TOKEN_DAEDALUS" "$DAEDALUS_TG"

# ── DONE ────────────────────────────────────────────────
echo "cycle $CYCLE complete"
echo "  icarus-log.md  : $(wc -l < "$ICARUS_LOG" | tr -d ' ') lines"
echo "  daedalus-log.md: $(wc -l < "$DAEDALUS_LOG" | tr -d ' ') lines"
