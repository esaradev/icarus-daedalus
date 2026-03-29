#!/usr/bin/env bash
# test.sh -- test core fabric infrastructure
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
T=$(mktemp -d)
trap "rm -rf $T" EXIT

pass() { PASS=$((PASS + 1)); echo "  pass: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "fabric-adapter"
echo ""

FABRIC_DIR="$T/fabric" source "$SCRIPT_DIR/fabric-adapter.sh"

# write
fp=$(FABRIC_DIR="$T/fabric" fabric_write "test-agent" "cli" "task" "built a websocket broker" "hot" "other:1" "websocket, node" "ws broker" "1")
[ -f "$fp" ] && pass "write creates file" || fail "write creates file"
head -10 "$fp" | grep -q "^agent: test-agent" && pass "frontmatter agent" || fail "frontmatter agent"
head -10 "$fp" | grep -q "^tier: hot" && pass "frontmatter tier" || fail "frontmatter tier"
head -10 "$fp" | grep -q "^refs: \[other:1\]" && pass "frontmatter refs" || fail "frontmatter refs"
grep -q "websocket broker" "$fp" && pass "body content" || fail "body content"

# uniqueness
fp2=$(FABRIC_DIR="$T/fabric" fabric_write "test-agent" "cli" "task" "second entry")
[ "$fp" != "$fp2" ] && pass "unique filenames" || fail "unique filenames"

# read
output=$(FABRIC_DIR="$T/fabric" fabric_read "test-agent" "hot")
echo "$output" | grep -q "websocket broker" && pass "read returns entries" || fail "read returns entries"

# read filters
FABRIC_DIR="$T/fabric" fabric_write "other-agent" "slack" "dialogue" "unrelated" > /dev/null
output=$(FABRIC_DIR="$T/fabric" fabric_read "test-agent" "hot")
echo "$output" | grep -q "unrelated" && fail "read filters by agent" || pass "read filters by agent"

# search
results=$(FABRIC_DIR="$T/fabric" fabric_search "websocket")
[ -n "$results" ] && pass "search finds matches" || fail "search finds matches"
results=$(FABRIC_DIR="$T/fabric" fabric_search "nonexistent_xyz" || true)
[ -z "$results" ] && pass "search empty on miss" || fail "search empty on miss"

echo ""
echo "curator"
echo ""

FABRIC_DIR="$T/fabric" python3 "$SCRIPT_DIR/curator.py" --once 2>/dev/null
[ -f "$T/fabric/index.json" ] && pass "curator builds index.json" || fail "curator builds index.json"
python3 -c "
import json
idx = json.load(open('$T/fabric/index.json'))
assert len(idx['entries']) >= 3, f'expected >= 3 entries, got {len(idx[\"entries\"])}'
assert all(e['tier'] == 'hot' for e in idx['entries']), 'expected all hot'
print('  pass: index has correct entries and tiers')
" || fail "index entries and tiers"

echo ""
echo "yaml parsing (both formats)"
echo ""

# Create entry with multiline YAML arrays (PROTOCOL.md spec)
cat > "$T/fabric/multiline-test.md" << 'YAMLEOF'
---
agent: test
platform: cli
timestamp: 2026-03-29T00:00:00Z
type: task
tier: hot
refs:
  - daedalus:7
  - scout:3
tags:
  - architecture
  - review
summary: multiline yaml test
---

This entry uses multiline YAML arrays per PROTOCOL.md spec.
YAMLEOF

# Create entry with inline bracket syntax
cat > "$T/fabric/inline-test.md" << 'YAMLEOF'
---
agent: test
platform: cli
timestamp: 2026-03-29T00:00:00Z
type: task
tier: hot
refs: [daedalus:7, scout:3]
tags: [architecture, review]
summary: inline yaml test
---

This entry uses inline bracket YAML arrays.
YAMLEOF

# Test curator parses both
python3 -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR')
from pathlib import Path
sys.modules.pop('curator', None)
import importlib.util
spec = importlib.util.spec_from_file_location('curator', '$SCRIPT_DIR/curator.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ml = mod.parse_entry(Path('$T/fabric/multiline-test.md'))
il = mod.parse_entry(Path('$T/fabric/inline-test.md'))

# multiline should have refs as list
refs_ml = ml.get('refs', [])
assert isinstance(refs_ml, list), f'multiline refs should be list, got {type(refs_ml)}'
assert len(refs_ml) == 2, f'multiline refs should have 2 items, got {len(refs_ml)}'
print('  pass: curator parses multiline YAML arrays')

refs_il = il.get('refs', [])
assert isinstance(refs_il, list), f'inline refs should be list, got {type(refs_il)}'
assert len(refs_il) == 2, f'inline refs should have 2 items, got {len(refs_il)}'
print('  pass: curator parses inline bracket arrays')
" || { fail "curator yaml parsing"; }

# Test export-training.py parses both
python3 -c "
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('exp', '$SCRIPT_DIR/export-training.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ml = mod.parse_entry(Path('$T/fabric/multiline-test.md'))
il = mod.parse_entry(Path('$T/fabric/inline-test.md'))

refs_ml = ml.get('refs', [])
assert isinstance(refs_ml, list) and len(refs_ml) == 2, f'export multiline refs failed: {refs_ml}'
print('  pass: export parses multiline YAML arrays')

refs_il = il.get('refs', [])
assert isinstance(refs_il, list) and len(refs_il) == 2, f'export inline refs failed: {refs_il}'
print('  pass: export parses inline bracket arrays')
" || { fail "export yaml parsing"; }

echo ""
echo "export-training ref matching"
echo ""

# Clean test entries (remove earlier ones from yaml test)
rm -f "$T/fabric/multiline-test.md" "$T/fabric/inline-test.md"

# ── Scenario: original (cycle 8), review, unrelated decoy, real fix ──
# This is the exact case Codex reproduced where an unrelated later
# entry from the same author was incorrectly selected as the revision.

# Target entry: alice cycle 8 (the original work)
cat > "$T/fabric/alice-code-001.md" << 'EOF'
---
agent: alice
platform: slack
timestamp: 2026-03-28T10:00:00Z
type: code-session
tier: hot
cycle: 8
summary: built rate limiter
---

Built a rate limiter with sliding window.
EOF

# Decoy original: alice cycle 5 (wrong cycle, should not match ref alice:8)
cat > "$T/fabric/alice-code-decoy.md" << 'EOF'
---
agent: alice
platform: slack
timestamp: 2026-03-27T08:00:00Z
type: code-session
tier: hot
cycle: 5
summary: decoy older task
---

This is an older unrelated task. Should not be paired.
EOF

# Review referencing alice:8
cat > "$T/fabric/bob-review-002.md" << 'EOF'
---
agent: bob
platform: telegram
timestamp: 2026-03-28T11:00:00Z
type: review
tier: hot
refs: [alice:8]
summary: reviewed rate limiter
---

MUST FIX: race condition in counter.
EOF

# Decoy revision: alice's UNRELATED later entry (no refs back, should be skipped)
cat > "$T/fabric/alice-research-decoy.md" << 'EOF'
---
agent: alice
platform: slack
timestamp: 2026-03-28T11:30:00Z
type: research
tier: hot
summary: researched postgres indexes
---

Researched postgres partial indexes for query optimization.
EOF

# Real fix: alice refs back to the review (bob) explicitly
cat > "$T/fabric/alice-fix-003.md" << 'EOF'
---
agent: alice
platform: slack
timestamp: 2026-03-28T12:00:00Z
type: code-session
tier: hot
cycle: 9
refs: [bob:11]
summary: fixed rate limiter after review
---

Fixed the race condition. Moved zadd after zcard.
EOF

python3 -c "
from pathlib import Path
import importlib.util, os
os.environ['FABRIC_DIR'] = '$T/fabric'
spec = importlib.util.spec_from_file_location('exp', '$SCRIPT_DIR/export-training.py')
mod = importlib.util.module_from_spec(spec)
mod.FABRIC_DIR = Path('$T/fabric')
spec.loader.exec_module(mod)

entries = mod.scan_all()
pairs, rev, xp = mod.extract_pairs(entries)

rc = [p for p in pairs if p['metadata'].get('type') == 'review-correction']
assert len(rc) == 1, f'expected 1 review-correction pair, got {len(rc)}'

# Verify the original was alice:8 (rate limiter), not decoy cycle 5
assert 'sliding window' in rc[0]['input'].lower(), \
    f'original should be the rate limiter (cycle 8), got: {rc[0][\"input\"][:100]}'
assert 'decoy' not in rc[0]['input'].lower(), \
    f'decoy original (cycle 5) selected: {rc[0][\"input\"][:100]}'

# Verify the output is the real fix, not the postgres research decoy
assert 'zadd' in rc[0]['output'].lower() or 'fixed' in rc[0]['output'].lower(), \
    f'output should be the fix, got: {rc[0][\"output\"][:100]}'
assert 'postgres' not in rc[0]['output'].lower(), \
    f'unrelated research entry selected as revision: {rc[0][\"output\"][:100]}'

print('  pass: review-correction uses agent:cycle matching')
print('  pass: decoy original (wrong cycle) not selected')
print('  pass: unrelated later entry not selected as revision')
print('  pass: only explicitly-linked revision used')
" || fail "export ref matching"

echo ""
echo "fabric-sync staging"
echo ""

# Test that .md files get staged even without index.json
SYNC_DIR=$(mktemp -d)
trap "rm -rf $T $SYNC_DIR" EXIT
cd "$SYNC_DIR"
git init -q
echo "test" > test.md
FABRIC_DIR="$SYNC_DIR" bash "$SCRIPT_DIR/fabric-sync.sh" init > /dev/null 2>&1
echo "new content" > new-entry.md
FABRIC_DIR="$SYNC_DIR" bash "$SCRIPT_DIR/fabric-sync.sh" push 2>&1 | grep -q "nothing to push\|entries" && pass "sync stages without index.json" || fail "sync stages without index.json"

echo ""
echo "hooks deduplication"
echo ""

# Test on-start.sh doesn't duplicate
mkdir -p "$T/hooktest"
# Create a fabric entry that matches both project name and claude-code pattern
mkdir -p "$T/hookfabric"
cat > "$T/hookfabric/claude-code-session-2026-03-28T0500Z-abc1.md" << EOF
---
agent: claude-code
platform: cli
timestamp: 2026-03-28T05:00:00Z
type: session
tier: hot
summary: worked on hooktest project
---

Did some work on hooktest.
EOF

output=$(echo '{"session_id":"t","cwd":"'$T'/hooktest","source":"startup"}' | FABRIC_DIR="$T/hookfabric" bash "$SCRIPT_DIR/hooks/on-start.sh" 2>/dev/null || true)
dupes=$(echo "$output" | sort | uniq -d | wc -l | tr -d ' ')
[ "$dupes" -eq 0 ] && pass "on-start.sh no duplicates" || fail "on-start.sh duplicates found ($dupes)"

echo ""
echo "────────────────────────"
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && echo "  all tests pass" || echo "  FAILURES"
exit "$FAIL"
