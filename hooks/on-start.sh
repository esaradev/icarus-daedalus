#!/usr/bin/env bash
# on-start.sh -- Claude Code SessionStart hook.
# Loads relevant fabric context and injects it into the session.
# Outputs text to stdout which Claude Code adds to context.
# Deduplicates entries so each file appears at most once.
#
# Receives JSON on stdin: { session_id, cwd, source }

set -euo pipefail

FABRIC_DIR="${FABRIC_DIR:-$HOME/fabric}"

INPUT=$(cat)
CWD=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null || echo "")
PROJECT=$(basename "$CWD" 2>/dev/null || echo "")

[ -d "$FABRIC_DIR" ] || exit 0

# Collect matching files into a deduplicated list
SEEN_FILES=$(mktemp)
trap "rm -f $SEEN_FILES" EXIT

add_file() {
    local f="$1"
    [ -f "$f" ] || return
    # deduplicate by filename
    local base
    base=$(basename "$f")
    grep -qx "$base" "$SEEN_FILES" 2>/dev/null && return
    echo "$base" >> "$SEEN_FILES"
    local SUMMARY AGENT TS
    SUMMARY=$(head -20 "$f" | grep "^summary:" | head -1 | sed 's/^summary: //')
    [ -z "$SUMMARY" ] && SUMMARY=$(awk '/^---$/{n++; next} n>=2{print; exit}' "$f" 2>/dev/null | head -1)
    AGENT=$(head -10 "$f" | grep "^agent:" | head -1 | sed 's/^agent: //')
    TS=$(head -10 "$f" | grep "^timestamp:" | head -1 | sed 's/^timestamp: //')
    [ -n "$SUMMARY" ] && echo "[${TS}] ${AGENT}: ${SUMMARY}"
}

CONTEXT=""

# 1. Project-relevant entries
if [ -n "$PROJECT" ]; then
    for f in $(grep -rl "$PROJECT" "$FABRIC_DIR" --include="*.md" 2>/dev/null | head -5); do
        line=$(add_file "$f")
        [ -n "$line" ] && CONTEXT="${CONTEXT}
${line}"
    done
fi

# 2. Recent claude-code entries
for f in $(ls -t "$FABRIC_DIR"/claude-code-*.md 2>/dev/null | head -3); do
    line=$(add_file "$f")
    [ -n "$line" ] && CONTEXT="${CONTEXT}
${line}"
done

if [ -n "$CONTEXT" ]; then
    echo "Recent work from fabric memory:${CONTEXT}"
fi

exit 0
