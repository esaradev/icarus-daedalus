#!/usr/bin/env bash
# fabric-adapter.sh -- Icarus Memory Protocol v1. Source this file.
# fabric_write(agent, platform, type, content, [tier], [refs], [tags], [summary], [cycle])
# fabric_read(agent, tier)
# fabric_search(query)
#
# Schema v1 fields set via env vars (computed at write time, not source time):
#   FABRIC_PROJECT_ID  -- project namespace (default: basename of cwd)
#   FABRIC_SESSION_ID  -- session grouping (default: generated per write)
#
# Lineage/scoping fields set via env vars (optional, cleared after write):
#   FABRIC_REVIEW_OF   -- entry being reviewed (agent:id)
#   FABRIC_REVISES     -- entry being revised (agent:id)
#   FABRIC_CUSTOMER_ID -- customer/account scope
#   FABRIC_STATUS      -- open, completed, blocked, superseded
#   FABRIC_OUTCOME     -- result or conclusion
FABRIC_DIR="${FABRIC_DIR:-$HOME/fabric}"

fabric_write() {
    local agent="$1" platform="$2" type="$3" content="$4"
    local tier="${5:-hot}" refs="${6:-}" tags="${7:-}" summary="${8:-}" cycle="${9:-}"
    mkdir -p "$FABRIC_DIR"
    local ts=$(date -u '+%Y-%m-%dT%H%MZ')
    local ts_iso=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    local suffix=$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 4)
    local entry_id=$(head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 8)
    # Compute project_id and session_id at write time
    local project_id="${FABRIC_PROJECT_ID:-$(basename "$(pwd)" 2>/dev/null || echo "unknown")}"
    local session_id="${FABRIC_SESSION_ID:-sess-$(date -u '+%Y%m%d-%H%M%S')-$$}"
    local fp="$FABRIC_DIR/${agent}-${type}-${ts}-${suffix}.md"
    { echo "---"
      echo "id: $entry_id"
      echo "agent: $agent"
      echo "platform: $platform"
      echo "timestamp: $ts_iso"
      echo "type: $type"
      echo "tier: $tier"
      echo "summary: ${summary:-$type entry by $agent}"
      echo "project_id: $project_id"
      echo "session_id: $session_id"
      [ -n "$refs" ] && echo "refs: [$refs]"
      [ -n "$tags" ] && echo "tags: [$tags]"
      [ -n "$cycle" ] && echo "cycle: $cycle"
      [ -n "${FABRIC_REVIEW_OF:-}" ] && echo "review_of: $FABRIC_REVIEW_OF"
      [ -n "${FABRIC_REVISES:-}" ] && echo "revises: $FABRIC_REVISES"
      [ -n "${FABRIC_CUSTOMER_ID:-}" ] && echo "customer_id: $FABRIC_CUSTOMER_ID"
      [ -n "${FABRIC_STATUS:-}" ] && echo "status: $FABRIC_STATUS"
      [ -n "${FABRIC_OUTCOME:-}" ] && echo "outcome: $FABRIC_OUTCOME"
      echo "---"
      echo ""
      echo "$content"
    } > "$fp"
    echo "$fp"
}

fabric_read() {
    local agent="${1:-}" tier="${2:-hot}"
    local dir="$FABRIC_DIR"
    [ "$tier" = "cold" ] && dir="$FABRIC_DIR/cold"
    [ -d "$dir" ] || return 0
    for f in "$dir"/*.md; do
        [ -f "$f" ] || continue
        [ -n "$agent" ] && { head -15 "$f" | grep -q "^agent: $agent" || continue; }
        head -15 "$f" | grep -q "^tier: $tier" || continue
        cat "$f"; echo ""
    done
}

fabric_search() {
    [ -d "$FABRIC_DIR" ] || return 0
    grep -rl "$1" "$FABRIC_DIR" --include="*.md" 2>/dev/null
}
