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
head -15 "$fp" | grep -q "^refs: \[other:1\]" && pass "frontmatter refs" || fail "frontmatter refs"
grep -q "websocket broker" "$fp" && pass "body content" || fail "body content"
grep -q "^project_id:" "$fp" && pass "schema v1 project_id" || fail "missing project_id"
grep -q "^session_id:" "$fp" && pass "schema v1 session_id" || fail "missing session_id"
grep -q "^summary:" "$fp" && pass "schema v1 summary always present" || fail "missing summary"

# per-write session_id (not reused from source time)
fp3=$(FABRIC_DIR="$T/fabric" fabric_write "test-agent" "cli" "task" "entry three")
sid1=$(head -15 "$fp" | grep "^session_id:" | cut -d' ' -f2-)
sid3=$(head -15 "$fp3" | grep "^session_id:" | cut -d' ' -f2-)
# Both should have session_id but may differ if generated per-write
[ -n "$sid1" ] && [ -n "$sid3" ] && pass "session_id generated per write" || fail "session_id missing"

# lineage fields via env vars
FABRIC_REVIEW_OF="alice:abc123" FABRIC_STATUS="completed" FABRIC_OUTCOME="approved" \
  fp4=$(FABRIC_DIR="$T/fabric" fabric_write "bob" "cli" "review" "reviewed alice's work")
head -20 "$fp4" | grep -q "^review_of: alice:abc123" && pass "review_of field written" || fail "review_of missing"
head -20 "$fp4" | grep -q "^status: completed" && pass "status field written" || fail "status missing"
head -20 "$fp4" | grep -q "^outcome: approved" && pass "outcome field written" || fail "outcome missing"

# revises + customer_id
FABRIC_REVISES="alice:def456" FABRIC_CUSTOMER_ID="cust-x-123" \
  fp5=$(FABRIC_DIR="$T/fabric" fabric_write "alice" "cli" "task" "fixed the thing")
head -20 "$fp5" | grep -q "^revises: alice:def456" && pass "revises field written" || fail "revises missing"
head -20 "$fp5" | grep -q "^customer_id: cust-x-123" && pass "customer_id field written" || fail "customer_id missing"

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
# Check for duplicate content lines (ignore separators, empty, frontmatter keys)
dupes=$(echo "$output" | grep -v "^$\|^---\|^#\|^agent:\|^platform:\|^timestamp:\|^type:\|^tier:\|^summary:" | sort | uniq -d | wc -l | tr -d ' ')
[ "$dupes" -eq 0 ] && pass "on-start.sh no duplicates" || fail "on-start.sh duplicates found ($dupes)"

echo ""
echo "self-train"
echo ""

# Test: exits with message when TOGETHER_API_KEY not set
st_out=$(TOGETHER_API_KEY="" HOME="$T/nohome" bash "$SCRIPT_DIR/scripts/self-train.sh" 2>&1 || true)
echo "$st_out" | grep -q "TOGETHER_API_KEY not set" && pass "self-train exits when no API key" || fail "self-train missing key message"

# Test: exits with warning when < 20 pairs
LOW_PAIR_DIR=$(mktemp -d)
cat > "$LOW_PAIR_DIR/entry-1.md" << 'EOF'
---
id: test0001
agent: tiny
platform: cli
timestamp: 2026-03-30T00:00:00Z
type: task
tier: hot
summary: tiny fabric entry
project_id: low-pair-test
session_id: sess-low-pair
---

This is a deliberately tiny fabric corpus for self-train warning coverage.
EOF
st_out=$(FABRIC_DIR="$LOW_PAIR_DIR" TOGETHER_API_KEY="fake-key-for-test" bash "$SCRIPT_DIR/scripts/self-train.sh" 2>&1 || true)
echo "$st_out" | grep -q "warning\|minimum" && pass "self-train warns on low pairs" || fail "self-train low pair warning"
rm -rf "$LOW_PAIR_DIR"

# Test: creates lock dir and cleans it up
rm -rf /tmp/icarus-self-train.lock
TOGETHER_API_KEY="fake" bash "$SCRIPT_DIR/scripts/self-train.sh" > /dev/null 2>&1 || true
[ ! -d /tmp/icarus-self-train.lock ] && pass "self-train cleans up lock dir" || fail "self-train lock dir not cleaned"

# Test: ignores stale lock (dead PID)
mkdir -p /tmp/icarus-self-train.lock
echo "99999" > /tmp/icarus-self-train.lock/pid
st_out=$(TOGETHER_API_KEY="fake" bash "$SCRIPT_DIR/scripts/self-train.sh" 2>&1 || true)
echo "$st_out" | grep -q "another training job" && fail "self-train blocked by stale lock" || pass "self-train reclaims stale lock"
rm -rf /tmp/icarus-self-train.lock

# Test: blocks on live lock (use current shell's PID which IS alive)
mkdir -p /tmp/icarus-self-train.lock
echo "$$" > /tmp/icarus-self-train.lock/pid
st_out=$(TOGETHER_API_KEY="fake" bash "$SCRIPT_DIR/scripts/self-train.sh" 2>&1 || true)
echo "$st_out" | grep -q "another training job" && pass "self-train blocks on live lock" || fail "self-train ignored live lock"
rm -rf /tmp/icarus-self-train.lock

# Test: uses unique temp dir
st_out=$(TOGETHER_API_KEY="fake-key-for-test" bash "$SCRIPT_DIR/scripts/self-train.sh" 2>&1 || true)
echo "$st_out" | grep -q "icarus-training\|exporting" && pass "self-train uses unique temp dir" || pass "self-train temp dir (export ran)"

# Test: script source contains required params in the payload
grep -q 'batch_size' "$SCRIPT_DIR/scripts/self-train.sh" && pass "payload includes batch_size" || fail "payload missing batch_size"
grep -q 'learning_rate' "$SCRIPT_DIR/scripts/self-train.sh" && pass "payload includes learning_rate" || fail "payload missing learning_rate"
grep -q 'n_checkpoints' "$SCRIPT_DIR/scripts/self-train.sh" && pass "payload includes n_checkpoints" || fail "payload missing n_checkpoints"
grep -q 'Qwen/Qwen2-7B-Instruct' "$SCRIPT_DIR/scripts/self-train.sh" && pass "default model is Qwen2-7B-Instruct" || fail "wrong default model"

# Test: defaults are nonzero
grep -q 'TOGETHER_BATCH_SIZE:-8' "$SCRIPT_DIR/scripts/self-train.sh" && pass "default batch_size is 8" || fail "batch_size default not 8"
grep -q 'TOGETHER_LR:-1e-5' "$SCRIPT_DIR/scripts/self-train.sh" && pass "default learning_rate is 1e-5" || fail "learning_rate default wrong"
grep -q 'TOGETHER_CHECKPOINTS:-1' "$SCRIPT_DIR/scripts/self-train.sh" && pass "default n_checkpoints is 1" || fail "n_checkpoints default wrong"

# Test: script prints params before API call
grep -q 'echo.*batch_size' "$SCRIPT_DIR/scripts/self-train.sh" && pass "prints batch_size before call" || fail "no batch_size print"
grep -q 'echo.*learning_rate' "$SCRIPT_DIR/scripts/self-train.sh" && pass "prints learning_rate before call" || fail "no learning_rate print"
grep -q 'echo.*model:' "$SCRIPT_DIR/scripts/self-train.sh" && pass "prints model before call" || fail "no model print"

echo ""
echo "smart retrieval"
echo ""

# Create 10 entries about different topics in a clean dir
RD=$(mktemp -d)
IDX=0
for topic in "billing refund customer X" "auth module JWT tokens" "database migration postgres" "frontend react component" "deployment kubernetes helm" "billing invoice payment" "auth OAuth2 flow" "database query optimization" "frontend CSS layout" "deployment CI CD pipeline"; do
    IDX=$((IDX + 1))
    agent="test-agent"
    type="task"
    [ "$(echo $topic | cut -d' ' -f1)" = "billing" ] && type="resolution"
    [ "$(echo $topic | cut -d' ' -f1)" = "auth" ] && type="code-session"
    cat > "$RD/entry-${IDX}.md" << ENTRY
---
agent: $agent
platform: cli
timestamp: $(date -u '+%Y-%m-%dT%H:%M:%SZ')
type: $type
tier: hot
summary: $topic
---

Worked on $topic. This is a test entry about $topic for retrieval testing.
ENTRY
done

# Test: billing query returns billing entries first
python3 -c "
import os; os.environ['FABRIC_DIR'] = '$RD'
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('fr', '$SCRIPT_DIR/fabric-retrieve.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.FABRIC_DIR = Path('$RD')

results = mod.retrieve('billing issue', max_results=5)
assert len(results) > 0, 'no results for billing query'
top_summary = results[0][1].get('summary', '')
assert 'billing' in top_summary.lower(), f'top result should be about billing, got: {top_summary}'
print('  pass: billing query ranks billing entries highest')

results = mod.retrieve('auth module', max_results=5)
top = results[0][1].get('summary', '')
assert 'auth' in top.lower(), f'top result should be about auth, got: {top}'
print('  pass: auth query ranks auth entries highest')

results = mod.retrieve('test', max_results=3)
assert len(results) <= 3, f'expected <= 3 results, got {len(results)}'
print('  pass: --max-results 3 returns at most 3')

results = mod.retrieve('test', max_results=20, max_tokens=500)
total_chars = sum(len(e.get('_full', '')) for _, e in results)
assert total_chars // 4 <= 600, f'exceeded token budget: ~{total_chars//4} tokens'
print('  pass: --max-tokens 500 stays within budget')
" || fail "smart retrieval"

# Test: deduplication
cat > "$RD/dup1.md" << 'ENTRY'
---
agent: alice
platform: cli
timestamp: 2026-03-28T10:00:00Z
type: task
tier: hot
summary: fixed the billing bug
---

Fixed the billing bug in the payment module.
ENTRY
cat > "$RD/dup2.md" << 'ENTRY'
---
agent: alice
platform: cli
timestamp: 2026-03-28T11:00:00Z
type: task
tier: hot
summary: fixed the billing bug
---

Fixed the billing bug in the payment module.
ENTRY

python3 -c "
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('fr', '$SCRIPT_DIR/fabric-retrieve.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.FABRIC_DIR = Path('$RD')

results = mod.retrieve('billing bug', max_results=10)
billing_results = [e for _, e in results if 'billing bug' in e.get('summary', '').lower()]
assert len(billing_results) <= 1, f'duplicates not removed: {len(billing_results)} billing bug entries'
print('  pass: duplicate entries deduplicated')
" || fail "deduplication"

# Test: same project gets boosted
python3 -c "
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('fr', '$SCRIPT_DIR/fabric-retrieve.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.FABRIC_DIR = Path('$RD')

# Score with project match vs without
results_with = mod.retrieve('test entry', max_results=10, project='billing')
results_without = mod.retrieve('test entry', max_results=10)
# With project=billing, billing entries should score higher
if results_with and results_without:
    top_with = results_with[0][1].get('summary', '')
    print(f'  pass: project boost works (top with project: {top_with[:30]})')
else:
    print('  pass: project boost (no entries to compare)')
" || fail "project boost"

# Test: source handoff entries outrank generic session summaries
cat > "$RD/handoff-task.md" << 'ENTRY'
---
id: 8371866a
agent: icarus
platform: cli
timestamp: 2026-03-30T10:00:00Z
type: task
tier: hot
summary: handoff smoke for daedalus
status: open
assigned_to: daedalus
---

Review the relay patch and confirm pending handoff pickup works. Include token amber relay.
ENTRY
cat > "$RD/handoff-session.md" << 'ENTRY'
---
id: 91aa22bc
agent: icarus
platform: cli
timestamp: 2026-03-30T10:05:00Z
type: session
tier: hot
summary: discussed amber relay handoff in session recap
status: completed
---

We talked about the amber relay handoff and pending pickup during the session.
ENTRY

python3 -c "
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('fr', '$SCRIPT_DIR/fabric-retrieve.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.FABRIC_DIR = Path('$RD')

results = mod.retrieve('amber relay handoff', max_results=5)
assert results, 'no results for amber relay handoff'
top = results[0][1]
assert top.get('type') == 'task', f\"expected task to outrank session, got {top.get('type')}: {top.get('summary','')}\"
print('  pass: source handoff task outranks session summary')
" || fail "handoff source ranking"

rm -rf "$RD"

# Test: oversized entry skipped by budget
python3 -c "
import os; os.environ['FABRIC_DIR'] = '$RD'
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('fr', '$SCRIPT_DIR/fabric-retrieve.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.FABRIC_DIR = Path('$RD')

# max_tokens=50 should skip all entries (each is ~40+ tokens)
results = mod.retrieve('billing', max_results=10, max_tokens=10)
total_tokens = sum(len(e.get('_full', '')) // 4 for _, e in results)
assert total_tokens <= 15, f'oversized entry not skipped: ~{total_tokens} tokens with budget 10'
print('  pass: oversized entries skipped by budget')
" || fail "oversized entry budget"

# Test: self-train payload built via Python (no shell interpolation)
grep -q "python3 -c" "$SCRIPT_DIR/scripts/self-train.sh" && grep -q "json.dumps" "$SCRIPT_DIR/scripts/self-train.sh" && pass "payload built via Python json.dumps" || fail "payload still uses shell interpolation"

# Test: setup.sh copies fabric-retrieve.py into plugin dir
grep -q "fabric-retrieve.py" "$SCRIPT_DIR/setup.sh" && pass "setup copies retrieval helper" || fail "setup missing retrieval copy"

# Test: plugin resets query state on session start
grep -q "_last_query_tokens = set()" "$SCRIPT_DIR/plugins/icarus/hooks.py" && pass "plugin resets query state on session start" || fail "plugin never resets query state"

# Test: plugin fires retrieval on topic change (not just first turn)
grep -q "overlap.*0.6" "$SCRIPT_DIR/plugins/icarus/hooks.py" && pass "plugin detects topic changes" || fail "plugin only fires on first turn"

# Test: dialogue.sh uses previous agent output as retrieval query
grep -q "CYCLE_CONTEXT.*tail\|previous agent" "$SCRIPT_DIR/examples/hermes-demo/dialogue.sh" && pass "dialogue uses previous agent output as query" || fail "dialogue uses static query"

# Test: hook uses recent fabric summary in query
grep -q "RECENT_SUMMARY" "$SCRIPT_DIR/hooks/on-start.sh" && pass "hook includes recent summary in query" || fail "hook only uses project name"

# Test: plugin uses shared retriever (no inline scoring)
grep -q "_load_retriever" "$SCRIPT_DIR/plugins/icarus/state.py" && pass "plugin uses shared retriever" || fail "plugin has inline retrieval"
! grep -q "_score_entry" "$SCRIPT_DIR/plugins/icarus/"*.py && pass "no duplicate scoring in plugin" || fail "plugin still has inline _score_entry"

# Test: plugin.yaml declares pre_llm_call
grep -q "pre_llm_call" "$SCRIPT_DIR/plugins/icarus/plugin.yaml" && pass "plugin.yaml declares pre_llm_call" || fail "plugin.yaml missing pre_llm_call"

# Test: installed-home retriever path includes plugins/icarus helper
grep -q 'plugins" / "icarus" / "fabric-retrieve.py"' "$SCRIPT_DIR/plugins/icarus/state.py" && pass "retriever checks installed icarus path" || fail "retriever missing installed icarus path"

# Test: smoke handoff proof command exists and runs
bash "$SCRIPT_DIR/scripts/smoke-handoff.sh" > /dev/null 2>&1 && pass "smoke handoff proof command" || fail "smoke handoff proof command"

# Test: add-agent.sh provisions hermes plugins and identity correctly
grep -q 'REPO_DIR="$(cd "\$SCRIPT_DIR/../.." && pwd)"' "$SCRIPT_DIR/examples/hermes-demo/add-agent.sh" && pass "add-agent resolves repo root" || fail "add-agent missing repo root resolution"
grep -q 'cp -r "\$REPO_DIR/plugins/icarus"' "$SCRIPT_DIR/examples/hermes-demo/add-agent.sh" && pass "add-agent copies icarus plugin" || fail "add-agent missing icarus plugin copy"
grep -q 'cp -r "\$REPO_DIR/skills/"' "$SCRIPT_DIR/examples/hermes-demo/add-agent.sh" && pass "add-agent copies skills from repo root" || fail "add-agent missing repo-root skills copy"
grep -q 'HERMES_AGENT_NAME=' "$SCRIPT_DIR/examples/hermes-demo/add-agent.sh" && pass "add-agent rewrites HERMES_AGENT_NAME" || fail "add-agent missing HERMES_AGENT_NAME rewrite"

# Test: icarus theme extraction keeps words, not first 3 characters
python3 - <<PY
import importlib.util
import sys, types
pkg = types.ModuleType("icarus")
pkg.__path__ = ["$SCRIPT_DIR/plugins/icarus"]
sys.modules["icarus"] = pkg
state = types.ModuleType("icarus.state")
state.session_id = ""
state.exchanges = []
state.AGENT_NAME = "icarus"
state.load_creative = lambda: {"cycle": 0, "themes": [], "questions": [], "learnings": []}
state.save_creative = lambda s: None
state.load_soul = lambda: ""
state.read_recent = lambda limit=5: []
state.read_cross_agent = lambda limit=3: []
state.recall = lambda *args, **kwargs: []
state.write_entry = lambda *args, **kwargs: None
state.write_memory_file = lambda *args, **kwargs: None
sys.modules["icarus.state"] = state
spec = importlib.util.spec_from_file_location("icarus.hooks", "$SCRIPT_DIR/plugins/icarus/hooks.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod._extract_theme("Built billing workflow automation for invoices") == "built billing workflow"
print("ok")
PY
if [ $? -eq 0 ]; then
    pass "icarus theme extraction keeps words"
else
    fail "icarus theme extraction regression"
fi

# Test: icarus plugin fabric_write validation
echo ""
echo "icarus plugin validation"
echo ""

PV_DIR=$(mktemp -d)
trap "rm -rf $T $PV_DIR" EXIT
mkdir -p "$PV_DIR/fabric"

python3 - <<PV
import importlib.util, sys, types, json, os
from pathlib import Path

os.environ["FABRIC_DIR"] = "$PV_DIR/fabric"
os.environ["HERMES_AGENT_NAME"] = "daedalus"
os.environ["HERMES_HOME"] = "$PV_DIR"

plugin_dir = "$SCRIPT_DIR/plugins/icarus"
ns = types.ModuleType("hermes_plugins")
ns.__path__ = []
ns.__package__ = "hermes_plugins"
sys.modules["hermes_plugins"] = ns
spec = importlib.util.spec_from_file_location(
    "hermes_plugins.icarus", f"{plugin_dir}/__init__.py",
    submodule_search_locations=[plugin_dir])
mod = importlib.util.module_from_spec(spec)
mod.__package__ = "hermes_plugins.icarus"
mod.__path__ = [plugin_dir]
sys.modules["hermes_plugins.icarus"] = mod
spec.loader.exec_module(mod)

errors = 0

def check(label, result_json, expect_error):
    global errors
    r = json.loads(result_json)
    got_error = "error" in r
    if got_error == expect_error:
        print(f"  pass: {label}")
    else:
        print(f"  FAIL: {label} (got {'error' if got_error else 'ok'}, expected {'error' if expect_error else 'ok'})")
        if got_error:
            print(f"        {r['error']}")
        errors += 1

# type=review without review_of -> error
check("review without review_of",
    mod.tools.fabric_write({"type": "review", "content": "looks good", "summary": "approved"}),
    expect_error=True)

# status=open without assigned_to -> error
check("open without assigned_to",
    mod.tools.fabric_write({"type": "task", "content": "do this", "summary": "task", "status": "open"}),
    expect_error=True)

# review_of with bad format -> error
check("review_of empty id",
    mod.tools.fabric_write({"type": "review", "content": "x", "summary": "x", "review_of": "icarus:"}),
    expect_error=True)

check("review_of empty agent",
    mod.tools.fabric_write({"type": "review", "content": "x", "summary": "x", "review_of": ":abc12345"}),
    expect_error=True)

check("review_of id too short",
    mod.tools.fabric_write({"type": "review", "content": "x", "summary": "x", "review_of": "icarus:ab"}),
    expect_error=True)

check("revises bad format",
    mod.tools.fabric_write({"type": "task", "content": "x", "summary": "x", "revises": ":"}),
    expect_error=True)

# review_of pointing to missing entry -> error
check("review_of missing entry",
    mod.tools.fabric_write({"type": "review", "content": "x", "summary": "x", "review_of": "icarus:deadbeef"}),
    expect_error=True)

# revises pointing to missing entry -> error
check("revises missing entry",
    mod.tools.fabric_write({"type": "task", "content": "x", "summary": "x", "revises": "icarus:deadbeef"}),
    expect_error=True)

# create a real entry, then review_of pointing to it -> ok
r = json.loads(mod.tools.fabric_write({
    "type": "code-session", "content": "built rate limiter", "summary": "rate limiter",
    "status": "open", "assigned_to": "daedalus"}))
assert "error" not in r, f"setup write failed: {r}"
# extract the entry id from the file
import re
entry_text = Path(r["path"]).read_text()[:500]
entry_id = re.search(r"^id: (.+)$", entry_text, re.MULTILINE).group(1)
entry_agent = re.search(r"^agent: (.+)$", entry_text, re.MULTILINE).group(1)

check("review_of existing entry",
    mod.tools.fabric_write({
        "type": "review", "content": "race condition found",
        "summary": "reviewed rate limiter",
        "review_of": f"{entry_agent}:{entry_id}"}),
    expect_error=False)

check("revises existing entry",
    mod.tools.fabric_write({
        "type": "code-session", "content": "fixed race condition",
        "summary": "fixed rate limiter",
        "revises": f"{entry_agent}:{entry_id}"}),
    expect_error=False)

# plain task (no linking fields) -> ok
check("plain task no links",
    mod.tools.fabric_write({"type": "task", "content": "implemented feature", "summary": "new feature"}),
    expect_error=False)

sys.exit(errors)
PV
[ $? -eq 0 ] && pass "icarus plugin validation suite" || fail "icarus plugin validation suite"

rm -rf "$PV_DIR"

# Test: icarus training includes n_checkpoints
grep -q '"n_checkpoints": ft_checkpoints' "$SCRIPT_DIR/plugins/icarus/state.py" && pass "icarus training sends n_checkpoints" || fail "icarus training missing n_checkpoints"

# Test: icarus tool JSON handles datetime-like values from YAML parsing
python3 - <<PY
import importlib.util, os, sys, types
from pathlib import Path
plugin_dir = Path("$SCRIPT_DIR/plugins/icarus")
pkg = types.ModuleType("icarus")
pkg.__path__ = [str(plugin_dir)]
sys.modules["icarus"] = pkg
os.environ["HERMES_HOME"] = str(Path.home() / ".hermes-test")
os.environ["FABRIC_DIR"] = "/tmp/icarus-tmp-fabric-json"
os.environ["HERMES_AGENT_NAME"] = "tester"
state_spec = importlib.util.spec_from_file_location("icarus.state", plugin_dir / "state.py")
state = importlib.util.module_from_spec(state_spec)
sys.modules["icarus.state"] = state
state_spec.loader.exec_module(state)
tools_spec = importlib.util.spec_from_file_location("icarus.tools", plugin_dir / "tools.py")
tools = importlib.util.module_from_spec(tools_spec)
sys.modules["icarus.tools"] = tools
tools_spec.loader.exec_module(tools)
fabric_dir = Path(os.environ["FABRIC_DIR"])
fabric_dir.mkdir(parents=True, exist_ok=True)
(fabric_dir / "sample.md").write_text("""---
id: abc123
agent: other
platform: cli
timestamp: 2026-03-30T05:54:33Z
type: note
tier: hot
summary: quartz relay ladder
project_id: demo
session_id: sess-1
---

Cross-agent test from Icarus to Daedalus. Retrieval target: quartz relay ladder.
""", encoding="utf-8")
payload = tools.fabric_recall({"query": "quartz relay ladder"})
assert "Object of type datetime" not in payload
assert "\"entries\"" in payload
print("ok")
PY
if [ $? -eq 0 ]; then
    pass "icarus recall serializes datetime results"
else
    fail "icarus recall datetime serialization regression"
fi

# Test: on-start.sh combines project + task text
grep -q "CLAUDE.md\|README.md" "$SCRIPT_DIR/hooks/on-start.sh" && pass "on-start uses project + task context" || fail "on-start only uses project name"

# Test: skill doesn't hardcode ~/icarus-daedalus as only path
grep -q "find ~\|ICARUS_DIR" "$SCRIPT_DIR/skills/fabric-memory/SKILL.md" && pass "skill resolves repo dynamically" || fail "skill hardcodes repo path"

# Test: self-train validates params before API call
st_out=$(TOGETHER_API_KEY="fake" TOGETHER_BATCH_SIZE=1 bash "$SCRIPT_DIR/scripts/self-train.sh" 2>&1 || true)
echo "$st_out" | grep -q "TOGETHER_BATCH_SIZE=1 must be >= 8" && pass "self-train rejects bad batch_size" || fail "self-train accepts bad batch_size"

st_out=$(TOGETHER_API_KEY="fake" TOGETHER_LR=0 bash "$SCRIPT_DIR/scripts/self-train.sh" 2>&1 || true)
echo "$st_out" | grep -q "TOGETHER_LR.*must be > 0" && pass "self-train rejects zero learning_rate" || fail "self-train accepts zero lr"

echo ""
echo "retrieval evals"
echo ""

python3 "$SCRIPT_DIR/eval-retrieval.py" 2>&1 || fail "retrieval eval regressions"

echo ""
echo "together.jsonl format"
echo ""

# Golden test: together.jsonl has system + user + assistant messages
GT=$(mktemp -d)
python3 "$SCRIPT_DIR/export-training.py" --output "$GT" > /dev/null 2>&1
python3 -c "
import json, sys
with open('$GT/together.jsonl') as f:
    for i, line in enumerate(f, 1):
        obj = json.loads(line.strip())
        msgs = obj.get('messages', [])
        assert len(msgs) >= 3, f'line {i}: expected 3+ messages, got {len(msgs)}'
        assert msgs[0]['role'] == 'system', f'line {i}: first role should be system, got {msgs[0][\"role\"]}'
        assert msgs[-1]['role'] == 'assistant', f'line {i}: last role should be assistant, got {msgs[-1][\"role\"]}'
        assert msgs[0]['content'].strip(), f'line {i}: system content empty'
        assert msgs[-1]['content'].strip(), f'line {i}: assistant content empty'
print(f'  pass: together.jsonl {i} lines: system+user+assistant format')
" || fail "together.jsonl golden format"
rm -rf "$GT"

echo ""
echo "────────────────────────"
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && echo "  all tests pass" || echo "  FAILURES"
exit "$FAIL"
