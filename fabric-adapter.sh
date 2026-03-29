#!/usr/bin/env bash
# fabric-adapter.sh -- Icarus Memory Protocol. Source this file.
# fabric_write(agent, platform, type, content, [tier], [refs], [tags], [summary], [cycle])
# fabric_read(agent, tier)
# fabric_search(query)
FABRIC_DIR="${FABRIC_DIR:-$HOME/fabric}"

fabric_write() {
    local agent="$1" platform="$2" type="$3" content="$4"
    local tier="${5:-hot}" refs="${6:-}" tags="${7:-}" summary="${8:-}" cycle="${9:-}"
    mkdir -p "$FABRIC_DIR"
    local ts=$(date -u '+%Y-%m-%dT%H%MZ')
    local ts_iso=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    local suffix=$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 4)
    local entry_id=$(head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 8)
    local fp="$FABRIC_DIR/${agent}-${type}-${ts}-${suffix}.md"
    { echo "---"
      echo "id: $entry_id"
      echo "agent: $agent"
      echo "platform: $platform"
      echo "timestamp: $ts_iso"
      echo "type: $type"
      echo "tier: $tier"
      [ -n "$refs" ] && echo "refs: [$refs]"
      [ -n "$tags" ] && echo "tags: [$tags]"
      [ -n "$summary" ] && echo "summary: $summary"
      [ -n "$cycle" ] && echo "cycle: $cycle"
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
        [ -n "$agent" ] && { head -10 "$f" | grep -q "^agent: $agent" || continue; }
        head -10 "$f" | grep -q "^tier: $tier" || continue
        cat "$f"; echo ""
    done
}

fabric_search() {
    [ -d "$FABRIC_DIR" ] || return 0
    grep -rl "$1" "$FABRIC_DIR" --include="*.md" 2>/dev/null
}
