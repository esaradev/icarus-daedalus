#!/usr/bin/env bash
# on-start.sh -- Claude Code SessionStart hook.
# Uses smart retrieval to load relevant fabric context.
# Outputs text to stdout which Claude Code adds to context.

set -euo pipefail

FABRIC_DIR="${FABRIC_DIR:-$HOME/fabric}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

INPUT=$(cat)
CWD=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null || echo "")
PROJECT=$(basename "$CWD" 2>/dev/null || echo "")

[ -d "$FABRIC_DIR" ] || exit 0

# Use smart retrieval with project name + any additional context
if [ -f "$REPO_DIR/fabric-retrieve.py" ] && [ -n "$PROJECT" ]; then
    # Build a rich query from all available project context
    QUERY="$PROJECT"
    # Add CLAUDE.md instructions (describes the project's patterns and rules)
    if [ -f "$CWD/CLAUDE.md" ]; then
        QUERY="$QUERY $(head -5 "$CWD/CLAUDE.md" | tr '\n' ' ')"
    elif [ -f "$CWD/README.md" ]; then
        QUERY="$QUERY $(head -3 "$CWD/README.md" | tr '\n' ' ')"
    fi
    # Add the most recent fabric summary for this project (last session's work)
    RECENT_SUMMARY=$(grep -rl "$PROJECT" "$FABRIC_DIR" --include="*.md" 2>/dev/null | head -1 | xargs head -20 2>/dev/null | grep "^summary:" | head -1 | sed 's/^summary: //')
    [ -n "$RECENT_SUMMARY" ] && QUERY="$QUERY $RECENT_SUMMARY"
    CONTEXT=$(FABRIC_DIR="$FABRIC_DIR" python3 "$REPO_DIR/fabric-retrieve.py" "$QUERY" \
        --max-results 5 --max-tokens 1500 --project "$PROJECT" 2>/dev/null || true)
    if [ -n "$CONTEXT" ] && [ "$CONTEXT" != "no relevant entries found" ]; then
        echo "Recent relevant work from fabric memory:"
        echo "$CONTEXT"
        exit 0
    fi
fi

# Fallback: basic recent entries if retrieval isn't available
SEEN=$(mktemp)
trap "rm -f $SEEN" EXIT

add_file() {
    local f="$1"
    [ -f "$f" ] || return
    local base=$(basename "$f")
    grep -qx "$base" "$SEEN" 2>/dev/null && return
    echo "$base" >> "$SEEN"
    local SUMMARY AGENT TS
    SUMMARY=$(head -20 "$f" | grep "^summary:" | head -1 | sed 's/^summary: //')
    [ -z "$SUMMARY" ] && SUMMARY=$(awk '/^---$/{n++; next} n>=2{print; exit}' "$f" 2>/dev/null | head -1)
    AGENT=$(head -10 "$f" | grep "^agent:" | head -1 | sed 's/^agent: //')
    TS=$(head -10 "$f" | grep "^timestamp:" | head -1 | sed 's/^timestamp: //')
    [ -n "$SUMMARY" ] && echo "[${TS}] ${AGENT}: ${SUMMARY}"
}

CONTEXT=""
if [ -n "$PROJECT" ]; then
    for f in $(grep -rl "$PROJECT" "$FABRIC_DIR" --include="*.md" 2>/dev/null | head -5); do
        line=$(add_file "$f")
        [ -n "$line" ] && CONTEXT="${CONTEXT}
${line}"
    done
fi
for f in $(ls -t "$FABRIC_DIR"/claude-code-*.md 2>/dev/null | head -3); do
    line=$(add_file "$f")
    [ -n "$line" ] && CONTEXT="${CONTEXT}
${line}"
done

if [ -n "$CONTEXT" ]; then
    echo "Recent work from fabric memory:${CONTEXT}"
fi

exit 0
