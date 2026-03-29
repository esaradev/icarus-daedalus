#!/usr/bin/env bash
# test.sh -- tests for the hermes demo (dialogue, compaction, agents)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PASS=0; FAIL=0

pass() { PASS=$((PASS + 1)); echo "  pass: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "hermes demo tests"
echo ""

# dialogue.sh reads fabric entries
grep -q "fabric_read" "$SCRIPT_DIR/dialogue.sh" && pass "dialogue.sh calls fabric_read" || fail "dialogue.sh calls fabric_read"
grep -q "FABRIC_CONTEXT" "$SCRIPT_DIR/dialogue.sh" && pass "dialogue.sh uses FABRIC_CONTEXT in prompt" || fail "dialogue.sh uses FABRIC_CONTEXT"
grep -q "fabric-adapter.sh" "$SCRIPT_DIR/dialogue.sh" && pass "dialogue.sh sources fabric-adapter" || fail "dialogue.sh sources fabric-adapter"

# compact.sh processes all agents (no hardcoded SECOND_NAME)
grep -q "while.*read.*cname" "$SCRIPT_DIR/dialogue.sh" && pass "dialogue.sh compacts all agents" || fail "dialogue.sh compacts all agents"
! grep -q "SECOND_NAME" "$SCRIPT_DIR/dialogue.sh" && pass "no hardcoded SECOND_NAME" || fail "hardcoded SECOND_NAME found"

# add-agent.sh
bash -n "$SCRIPT_DIR/add-agent.sh" && pass "add-agent.sh syntax ok" || fail "add-agent.sh syntax"

# agents.yml exists
[ -f "$SCRIPT_DIR/agents.yml" ] && pass "agents.yml exists" || fail "agents.yml missing"

echo ""
echo "────────────────────────"
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && echo "  all tests pass" || echo "  FAILURES"
exit "$FAIL"
