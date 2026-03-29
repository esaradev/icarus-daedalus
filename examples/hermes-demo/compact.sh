#!/usr/bin/env bash
# compact.sh -- Self-reflecting memory compaction for agent dialogue logs.
# Shared by all dialogue.sh variants. Source it and call compact_if_needed.
#
# Usage:
#   source compact.sh
#   compact_if_needed "$AGENT_A_LOG" "$AGENT_B_LOG" "$CYCLE" "$AGENT_A_NAME" "$AGENT_B_NAME"
#
# Env: ANTHROPIC_API_KEY (required), FORCE_COMPACT=1 (optional, forces compaction)

COMPACT_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPACT_LINE_THRESHOLD=150
COMPACT_CYCLE_INTERVAL=10
COMPACT_LOG_TARGET=100
COMPACT_MEM_TARGET=1800
COMPACT_HOME="${HOME:-}"
COMPACT_HISTORY="$COMPACT_SCRIPT_DIR/compaction-history.md"

_compact_call_claude() {
    local system="$1" prompt="$2" max_tokens="${3:-1500}"
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
        print('UNEXPECTED: ' + json.dumps(data)[:500], file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f'PARSE_ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"
}

_compact_archive() {
    local src="$1" dest_dir="$2"
    [ -f "$src" ] || return 0
    mkdir -p "$dest_dir"
    local ts
    ts=$(date -u '+%Y-%m-%d-%H%M')
    local base
    base=$(basename "$src" .md)
    cp "$src" "$dest_dir/${base}-${ts}.md"
}

_compact_tag_cycles() {
    # Reads a log file, tags each cycle block with [HOT], [WARM], or [COLD]
    # based on distance from current cycle. Prepends agent name to each block.
    local logfile="$1" current_cycle="$2" agent_name="$3"
    local hot_start=$((current_cycle - 4))  # last 5 cycles
    local warm_start=$((current_cycle - 14)) # cycles 6-15 back

    python3 -c "
import sys, re

logfile = sys.argv[1]
current = int(sys.argv[2])
agent = sys.argv[3]
hot_start = current - 4
warm_start = current - 14

with open(logfile, 'r') as f:
    content = f.read()

blocks = re.split(r'^---$', content, flags=re.MULTILINE)
for block in blocks:
    m = re.search(r'## Cycle (\d+)', block)
    if not m:
        continue
    cycle_num = int(m.group(1))
    if cycle_num >= hot_start:
        tier = 'HOT'
    elif cycle_num >= warm_start:
        tier = 'WARM'
    else:
        tier = 'COLD'
    print(f'[{tier}] [{agent}]')
    print(block.strip())
    print()
" "$logfile" "$current_cycle" "$agent_name"
}

_compact_log_entry() {
    local ts="$1" a_name="$2" b_name="$3" a_before="$4" a_after="$5" b_before="$6" b_after="$7" dropped="$8" compressed="$9"
    [ -f "$COMPACT_HISTORY" ] || printf "# Compaction History\n\n" > "$COMPACT_HISTORY"
    cat >> "$COMPACT_HISTORY" << EOF

---

## $ts

$a_name log: $a_before -> $a_after lines
$b_name log: $b_before -> $b_after lines
Cycles compressed: $compressed
Cycles dropped: $dropped

EOF
}

_compact_restart_gateways() {
    local a_home="$1" b_home="$2"
    # Only restart if gateway processes are running
    local restarted=false
    if pgrep -f "hermes gateway run" > /dev/null 2>&1; then
        pkill -f "hermes gateway run" 2>/dev/null || true
        sleep 2
        if [ -d "$a_home" ]; then
            HERMES_HOME="$a_home" nohup hermes gateway run > /dev/null 2>&1 &
        fi
        if [ -d "$b_home" ]; then
            HERMES_HOME="$b_home" nohup hermes gateway run > /dev/null 2>&1 &
        fi
        sleep 2
        restarted=true
    fi
    $restarted && echo "compact> gateways restarted" || echo "compact> no gateways running, skipped restart"
}

compact_if_needed() {
    local a_log="$1" b_log="$2" cycle="$3"
    local a_name="${4:-agent-a}" b_name="${5:-agent-b}"

    # Check if compaction is needed
    local a_lines=0 b_lines=0
    [ -f "$a_log" ] && a_lines=$(wc -l < "$a_log" 2>/dev/null | tr -d ' ')
    [ -f "$b_log" ] && b_lines=$(wc -l < "$b_log" 2>/dev/null | tr -d ' ')

    local should_compact=false
    if [ "${FORCE_COMPACT:-0}" = "1" ]; then
        should_compact=true
        echo "compact> forced"
    elif [ "${a_lines:-0}" -gt "$COMPACT_LINE_THRESHOLD" ] || [ "${b_lines:-0}" -gt "$COMPACT_LINE_THRESHOLD" ]; then
        should_compact=true
        echo "compact> triggered (${a_lines}/${b_lines} lines, threshold: $COMPACT_LINE_THRESHOLD)"
    elif [ "$cycle" -gt "$COMPACT_CYCLE_INTERVAL" ] && [ $((cycle % COMPACT_CYCLE_INTERVAL)) -eq 0 ]; then
        should_compact=true
        echo "compact> triggered (cycle $cycle, interval: $COMPACT_CYCLE_INTERVAL)"
    fi

    $should_compact || return 0

    echo "compact> archiving..."

    # Archive current files
    local archive_dir="$COMPACT_SCRIPT_DIR/archive"
    _compact_archive "$a_log" "$archive_dir"
    _compact_archive "$b_log" "$archive_dir"

    local a_hermes="$COMPACT_HOME/.hermes-${a_name}"
    local b_hermes="$COMPACT_HOME/.hermes-${b_name}"
    _compact_archive "$a_hermes/memories/MEMORY.md" "$a_hermes/memories/archive"
    _compact_archive "$b_hermes/memories/MEMORY.md" "$b_hermes/memories/archive"

    echo "compact> curating logs..."

    # Build tagged input: both logs interleaved with agent labels
    local tagged_a tagged_b
    tagged_a=$(_compact_tag_cycles "$a_log" "$cycle" "$a_name" 2>/dev/null) || tagged_a=""
    tagged_b=$(_compact_tag_cycles "$b_log" "$cycle" "$b_name" 2>/dev/null) || tagged_b=""

    if [ -z "$tagged_a" ] && [ -z "$tagged_b" ]; then
        echo "compact> no cycles to compact"
        return 0
    fi

    local curator_system="You are a memory curator. You compact conversation logs between two agents.
You do NOT participate in the conversation. You do NOT have opinions about the content. You are a librarian.

You receive cycle entries from two agents, tagged with tiers and agent names.

Rules:
1. [HOT] entries: return VERBATIM. Do not change a single word. Copy exactly.
2. [WARM] entries: compress to 2-3 sentences preserving what was said, decided, or debated. If a HOT entry references something from a WARM entry, keep that detail.
3. [COLD] entries: compress to one line. Drop entirely if nothing in WARM or HOT entries references them.
4. Cross-references matter. If agent-a cycle 7 responds to agent-b cycle 4, keep enough of cycle 4 for cycle 7 to make sense.

Output format -- output TWO sections separated by ===SPLIT===

SECTION 1: ${a_name} compacted log
For each kept cycle:
---

## Cycle N
[timestamp]

[content -- verbatim for HOT, summarized for WARM/COLD]

SECTION 2 (after ===SPLIT===): ${b_name} compacted log
Same format.

Do not add commentary. Do not change cycle numbers or timestamps. Do not invent content."

    local curator_prompt="Current cycle: $cycle

${a_name} log entries:
$tagged_a

${b_name} log entries:
$tagged_b

Compact these logs. Output both sections separated by ===SPLIT==="

    local curator_output
    curator_output=$(_compact_call_claude "$curator_system" "$curator_prompt" 2500 2>/dev/null)

    if [ -z "$curator_output" ]; then
        echo "compact> curator call failed, keeping original logs"
        return 0
    fi

    # Split curator output into two logs
    local a_header b_header
    a_header=$(head -4 "$a_log" 2>/dev/null | grep -v '^---' | head -3)
    b_header=$(head -4 "$b_log" 2>/dev/null | grep -v '^---' | head -3)

    local a_compacted b_compacted
    a_compacted=$(echo "$curator_output" | sed -n '1,/===SPLIT===/p' | sed '/===SPLIT===/d')
    b_compacted=$(echo "$curator_output" | sed -n '/===SPLIT===/,$ p' | sed '1d')

    if [ -z "$a_compacted" ] || [ -z "$b_compacted" ]; then
        echo "compact> curator output malformed, keeping original logs"
        return 0
    fi

    # Write compacted logs (preserve headers)
    printf "%s\n\n%s\n" "$a_header" "$a_compacted" > "$a_log"
    printf "%s\n\n%s\n" "$b_header" "$b_compacted" > "$b_log"

    local a_after b_after
    a_after=$(wc -l < "$a_log" 2>/dev/null | tr -d ' ')
    b_after=$(wc -l < "$b_log" 2>/dev/null | tr -d ' ')

    echo "compact> logs: ${a_name} ${a_lines}->${a_after} lines, ${b_name} ${b_lines}->${b_after} lines"

    # Count what changed
    local warm_count cold_count
    warm_count=$(echo "$tagged_a $tagged_b" | grep -c '\[WARM\]' || true)
    cold_count=$(echo "$tagged_a $tagged_b" | grep -c '\[COLD\]' || true)
    local dropped=0
    # Count cold entries that didn't make it into output
    if [ "$cold_count" -gt 0 ]; then
        local kept_cold
        kept_cold=$(echo "$curator_output" | grep -c '## Cycle' || true)
        local total_input
        total_input=$(echo "$tagged_a $tagged_b" | grep -c '## Cycle' || true)
        dropped=$((total_input - kept_cold))
        [ "$dropped" -lt 0 ] && dropped=0
    fi

    echo "compact> curating MEMORY.md..."

    # Compact MEMORY.md using the curator
    local a_mem="$a_hermes/memories/MEMORY.md"
    local b_mem="$b_hermes/memories/MEMORY.md"
    local current_mem
    current_mem=$(cat "$a_mem" 2>/dev/null)

    if [ -n "$current_mem" ]; then
        local mem_system="You are a memory curator. You maintain a cross-platform memory file for AI agents.

This memory is injected into the agent's system prompt on Telegram and Slack. It must be under ${COMPACT_MEM_TARGET} characters.

You receive: the current memory file and a summary of recent compacted log content.

Rules:
1. Keep the most important context: decisions made, patterns identified, unresolved tensions, key references.
2. Drop redundant entries. If two entries say similar things, merge them.
3. Drop stale entries that recent cycles never reference.
4. Use the format: [timestamp] Type: brief summary
5. Most recent and most referenced entries get priority.

Output ONLY the new memory content. No commentary. No markdown headers. Target ${COMPACT_MEM_TARGET} characters max."

        local mem_prompt="Current MEMORY.md (${#current_mem} chars):
$current_mem

Recent log summary (compacted):
$(echo "$a_compacted" | head -40)
$(echo "$b_compacted" | head -40)

Rewrite the memory to fit under ${COMPACT_MEM_TARGET} characters. Keep what matters, drop what's stale."

        local new_mem
        new_mem=$(_compact_call_claude "$mem_system" "$mem_prompt" 800 2>/dev/null)

        if [ -n "$new_mem" ]; then
            local mem_size
            mem_size=$(printf "%s" "$new_mem" | wc -c | tr -d ' ')
            if [ "$mem_size" -le 2200 ]; then
                echo "$new_mem" > "$a_mem"
                echo "$new_mem" > "$b_mem"
                echo "compact> MEMORY.md: ${#current_mem}->${mem_size} chars"
            else
                echo "compact> curator exceeded memory limit ($mem_size chars), keeping original"
            fi
        else
            echo "compact> memory curator failed, keeping original"
        fi
    fi

    # Log compaction history
    local ts
    ts=$(date -u '+%Y-%m-%d %H:%M UTC')
    _compact_log_entry "$ts" "$a_name" "$b_name" "$a_lines" "$a_after" "$b_lines" "$b_after" "$dropped" "$warm_count"

    # Restart gateways so they pick up new MEMORY.md
    _compact_restart_gateways "$a_hermes" "$b_hermes"

    echo "compact> done"
}
