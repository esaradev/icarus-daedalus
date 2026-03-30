#!/usr/bin/env bash
# smoke-handoff.sh -- prove the Icarus plugin handoff chain works end-to-end
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/icarus-smoke-XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

FABRIC_DIR="$TMP_ROOT/fabric"
ICARUS_HOME="$TMP_ROOT/.hermes-icarus"
DAEDALUS_HOME="$TMP_ROOT/.hermes-daedalus"

pass() { printf '  pass: %s\n' "$1"; }
fail() { printf '  FAIL: %s\n' "$1" >&2; exit 1; }

mkdir -p "$FABRIC_DIR" "$FABRIC_DIR/cold"
mkdir -p "$ICARUS_HOME/plugins" "$DAEDALUS_HOME/plugins"

cp -R "$REPO_DIR/plugins/icarus" "$ICARUS_HOME/plugins/"
cp -R "$REPO_DIR/plugins/icarus" "$DAEDALUS_HOME/plugins/"
cp "$REPO_DIR/fabric-retrieve.py" "$ICARUS_HOME/plugins/icarus/"
cp "$REPO_DIR/fabric-retrieve.py" "$DAEDALUS_HOME/plugins/icarus/"
[ -f "$REPO_DIR/export-training.py" ] && cp "$REPO_DIR/export-training.py" "$ICARUS_HOME/plugins/icarus/"
[ -f "$REPO_DIR/export-training.py" ] && cp "$REPO_DIR/export-training.py" "$DAEDALUS_HOME/plugins/icarus/"

export FABRIC_DIR
export ICARUS_HOME
export DAEDALUS_HOME
export REPO_DIR

python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

repo_dir = Path(os.environ["REPO_DIR"])
sys.path.insert(0, str(repo_dir / "plugins"))

from icarus import hooks, state, tools  # noqa: E402


def parse_id(path: str) -> str:
    for line in Path(path).read_text("utf-8").splitlines():
        if line.startswith("id: "):
            return line.split(": ", 1)[1].strip()
    raise RuntimeError(f"missing id in {path}")


def run_as(agent_name: str, home: str):
    os.environ["HERMES_AGENT_NAME"] = agent_name
    os.environ["HERMES_HOME"] = home
    state.AGENT_NAME = agent_name
    state.HERMES_HOME = Path(home)
    state.FABRIC_DIR = Path(os.environ["FABRIC_DIR"])
    state._JOB_FILE = state.HERMES_HOME / ".icarus-training-job.txt"
    state._STATE_FILE = state.HERMES_HOME / ".icarus-state.json"
    state.session_id = ""
    state.exchanges = []


def expect(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"  pass: {msg}")


icarus_home = os.environ["ICARUS_HOME"]
daedalus_home = os.environ["DAEDALUS_HOME"]

# 1. Builder writes an assigned handoff.
run_as("icarus", icarus_home)
raw = tools.fabric_write({
    "type": "code-session",
    "summary": "smoke handoff for daedalus",
    "content": "Built the relay patch. Needs review. Token amber relay.",
    "status": "open",
    "assigned_to": "daedalus",
})
payload = json.loads(raw)
expect(payload.get("status") == "written", "builder handoff written")
task_path = payload["path"]
task_id = parse_id(task_path)
expect(task_id, "builder handoff has entry id")

# 2. Reviewer sees the handoff in session-start context.
run_as("daedalus", daedalus_home)
ctx = hooks.on_session_start(session_id="smoke-daedalus")
context = (ctx or {}).get("context", "")
expect("smoke handoff for daedalus" in context, "reviewer session-start sees handoff")
expect(f"id {task_id}" in context, "reviewer session-start includes source id")

# 3. Reviewer sees the handoff in fabric_pending.
pending = json.loads(tools.fabric_pending({}))
expect(pending.get("total", 0) >= 1, "fabric_pending returns assigned work")
open_tasks = pending.get("open_tasks", [])
expect(any(t.get("id") == task_id for t in open_tasks), "fabric_pending exposes exact task id")

# 4. Reviewer writes a linked review.
review_ref = f"icarus:{task_id}"
raw = tools.fabric_write({
    "type": "review",
    "summary": "reviewed smoke handoff from icarus",
    "content": "Confirmed relay handoff pickup worked. One nit on naming.",
    "review_of": review_ref,
    "status": "completed",
    "outcome": "pickup worked",
})
payload = json.loads(raw)
expect(payload.get("status") == "written", "reviewer linked review written")
review_path = payload["path"]
review_id = parse_id(review_path)
expect(review_id, "review has entry id")

# 5. Builder sees the linked review.
run_as("icarus", icarus_home)
ctx = hooks.on_session_start(session_id="smoke-icarus")
context = (ctx or {}).get("context", "")
expect("reviewed smoke handoff from icarus" in context, "builder session-start sees linked review")
expect(review_ref in context, "builder context shows review_of link")

# 6. Builder writes a linked fix.
raw = tools.fabric_write({
    "type": "code-session",
    "summary": "fixed smoke handoff after review",
    "content": "Renamed relay variables and cleaned the patch after review.",
    "revises": review_ref,
    "status": "completed",
})
payload = json.loads(raw)
expect(payload.get("status") == "written", "builder linked fix written")

# 7. Recall retrieves the chain.
results = json.loads(tools.fabric_recall({"query": "amber relay handoff", "max_results": 5}))
entries = results.get("entries", [])
expect(any(e.get("id") == task_id for e in entries), "recall returns source handoff")
expect(any(e.get("review_of") == review_ref for e in entries), "recall returns linked review")

print("")
print("Smoke handoff OK")
print(f"  fabric:   {os.environ['FABRIC_DIR']}")
print(f"  task id:  {task_id}")
print(f"  review_of:{review_ref}")
PY
