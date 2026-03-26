#!/usr/bin/env bash
# dialogue.sh -- Code review loop between Icarus and Daedalus.
# Icarus ships code fast. Daedalus reviews with precision. Both post to Slack.
#
# Usage: bash dialogue.sh [path-to-code-or-diff]
# Env: ANTHROPIC_API_KEY, SLACK_WEBHOOK_URL (optional)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ICARUS_LOG="$SCRIPT_DIR/icarus-log.md"
DAEDALUS_LOG="$SCRIPT_DIR/daedalus-log.md"
ICARUS_SOUL="$SCRIPT_DIR/agent-a-SOUL.md"
DAEDALUS_SOUL="$SCRIPT_DIR/agent-b-SOUL.md"
TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')

# Load env from .env if present
[ -f "$SCRIPT_DIR/.env" ] && set -a && source "$SCRIPT_DIR/.env" && set +a

SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"

[ -z "${ANTHROPIC_API_KEY:-}" ] && echo "error: ANTHROPIC_API_KEY not set" && exit 1

# Optional: pass a file or diff as context
CODE_CONTEXT=""
if [ -n "${1:-}" ] && [ -f "$1" ]; then
    CODE_CONTEXT=$(cat "$1" | head -500)
elif [ -n "${1:-}" ]; then
    CODE_CONTEXT="$1"
fi

# Init logs
[ -f "$ICARUS_LOG" ] || printf "# Code Log\n\n" > "$ICARUS_LOG"
[ -f "$DAEDALUS_LOG" ] || printf "# Review Log\n\n" > "$DAEDALUS_LOG"

CYCLE=$(grep -c '## Cycle' "$ICARUS_LOG" 2>/dev/null || true)
CYCLE=$(( ${CYCLE:-0} + 1 ))

call_claude() {
    local system="$1" prompt="$2"
    local sys_json prompt_json
    sys_json=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$system")
    prompt_json=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$prompt")
    local raw
    raw=$(curl -s https://api.anthropic.com/v1/messages \
        -H "content-type: application/json" \
        -H "x-api-key: $ANTHROPIC_API_KEY" \
        -H "anthropic-version: 2023-06-01" \
        -d "{\"model\":\"claude-sonnet-4-20250514\",\"max_tokens\":1024,\"system\":$sys_json,\"messages\":[{\"role\":\"user\",\"content\":$prompt_json}]}")
    echo "$raw" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if 'content' in data and len(data['content']) > 0:
    print(data['content'][0]['text'])
elif 'error' in data:
    print('API_ERROR: ' + data['error'].get('message', str(data['error'])), file=sys.stderr)
    sys.exit(1)
else:
    print('UNEXPECTED: ' + json.dumps(data)[:500], file=sys.stderr)
    sys.exit(1)
"
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

# ── ICARUS ─────────────────────────────────────────────
echo "[$TIMESTAMP] cycle $CYCLE"
echo ""
echo "icarus> writing code..."

ICARUS_HISTORY=$(tail -80 "$ICARUS_LOG" 2>/dev/null)
DAEDALUS_HISTORY=$(tail -80 "$DAEDALUS_LOG" 2>/dev/null)
ICARUS_SOUL_TEXT=$(cat "$ICARUS_SOUL")

CONTEXT_BLOCK=""
[ -n "$CODE_CONTEXT" ] && CONTEXT_BLOCK="Code/diff to work with:
$CODE_CONTEXT
---
"

ICARUS_SYSTEM="$ICARUS_SOUL_TEXT"

ICARUS_PROMPT="Cycle $CYCLE. ${CONTEXT_BLOCK}Your previous code: $ICARUS_HISTORY --- Previous review feedback: $DAEDALUS_HISTORY --- Write code for this task. If there is review feedback, output the corrected code. Output only code, no conversation."

ICARUS_RAW=$(call_claude "$ICARUS_SYSTEM" "$ICARUS_PROMPT") || { echo "FATAL: icarus call failed" >&2; exit 1; }

echo "icarus> code shipped"
echo ""

cat >> "$ICARUS_LOG" << EOF

---

## Cycle $CYCLE
$TIMESTAMP

$ICARUS_RAW

EOF

post_slack "*Icarus -- Cycle $CYCLE*

$ICARUS_RAW"

# ── DAEDALUS ───────────────────────────────────────────
echo "daedalus> reviewing..."
sleep 2

DAEDALUS_SOUL_TEXT=$(cat "$DAEDALUS_SOUL")

DAEDALUS_SYSTEM="$DAEDALUS_SOUL_TEXT"

DAEDALUS_PROMPT="Cycle $CYCLE. Code to review: $ICARUS_RAW --- Your previous reviews: $DAEDALUS_HISTORY --- Review this code. Output only your review and corrected code, no conversation."

DAEDALUS_RAW=$(call_claude "$DAEDALUS_SYSTEM" "$DAEDALUS_PROMPT") || { echo "FATAL: daedalus call failed" >&2; exit 1; }

echo "daedalus> review done"
echo ""

cat >> "$DAEDALUS_LOG" << EOF

---

## Cycle $CYCLE
$TIMESTAMP

$DAEDALUS_RAW

EOF

post_slack "*Daedalus -- Cycle $CYCLE*

$DAEDALUS_RAW"

# ── MEMORY ─────────────────────────────────────────────
# Summarize this cycle into hermes memories so both agents can recall
# coding sessions when talking on Telegram.
SUMMARY_SYSTEM="You are a note-taker. Summarize a coding session in exactly 3 lines. No markdown. No code blocks. No preamble.
Line 1: Icarus wrote: [one sentence describing what was coded]
Line 2: Daedalus reviewed: [one sentence listing key issues found]
Line 3: Outcome: [one sentence on what was approved or needs changing]"

SUMMARY_PROMPT="Task: ${CODE_CONTEXT:-general coding}

Icarus output:
$(echo "$ICARUS_RAW" | head -30)

Daedalus output:
$(echo "$DAEDALUS_RAW" | head -30)

Summarize in exactly 3 lines."

SUMMARY=$(call_claude "$SUMMARY_SYSTEM" "$SUMMARY_PROMPT" 2>/dev/null) || SUMMARY="Icarus wrote code. Daedalus reviewed it."

MEMORY_ENTRY="
[$TIMESTAMP] Code session (cycle $CYCLE): ${CODE_CONTEXT:-general coding}
$SUMMARY
"

ICARUS_MEM="$HOME/.hermes-icarus/memories/MEMORY.md"
DAEDALUS_MEM="$HOME/.hermes-daedalus/memories/MEMORY.md"

# Append to MEMORY.md (hermes reads this into the system prompt each session).
# Keep it under 2200 chars total -- trim oldest entries if needed.
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

append_memory "$ICARUS_MEM" "$MEMORY_ENTRY"
append_memory "$DAEDALUS_MEM" "$MEMORY_ENTRY"

echo "memory> written to both hermes instances"

# ── DONE ───────────────────────────────────────────────
echo "cycle $CYCLE complete"
echo "  icarus-log.md  : $(wc -l < "$ICARUS_LOG" | tr -d ' ') lines"
echo "  daedalus-log.md: $(wc -l < "$DAEDALUS_LOG" | tr -d ' ') lines"
