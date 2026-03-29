#!/usr/bin/env bash
# fabric-sync.sh -- Git-based sync for ~/fabric/.
# Push local fabric entries to a git repo. Pull from other machines.
# Free cross-machine memory via GitHub/GitLab/any git remote.
#
# Usage:
#   bash fabric-sync.sh init              # init git repo in ~/fabric/
#   bash fabric-sync.sh push              # commit + push new entries
#   bash fabric-sync.sh pull              # pull from remote
#   bash fabric-sync.sh sync              # pull then push
#   bash fabric-sync.sh watch [interval]  # auto-sync every N seconds (default 60)

set -euo pipefail

FABRIC_DIR="${FABRIC_DIR:-$HOME/fabric}"

fail() { echo "error: $1" >&2; exit 1; }

fabric_init() {
    mkdir -p "$FABRIC_DIR"
    cd "$FABRIC_DIR"

    if [ -d .git ]; then
        echo "fabric: already a git repo"
        return 0
    fi

    git init
    echo "cold/" > .gitignore
    echo "*.tmp" >> .gitignore
    git add -A
    git commit -m "init fabric" --allow-empty

    echo ""
    echo "fabric repo initialized at $FABRIC_DIR"
    echo "add a remote:"
    echo "  cd $FABRIC_DIR && git remote add origin git@github.com:YOU/fabric.git"
    echo "  cd $FABRIC_DIR && git push -u origin main"
}

fabric_push() {
    cd "$FABRIC_DIR"
    [ -d .git ] || fail "$FABRIC_DIR is not a git repo. run: bash fabric-sync.sh init"

    # Stage new/changed files separately so one missing file doesn't block others
    git add *.md 2>/dev/null || true
    git add index.json 2>/dev/null || true
    git add cold/*.md 2>/dev/null || true

    # Check if there's anything to commit
    if git diff --cached --quiet 2>/dev/null; then
        echo "fabric: nothing to push"
        return 0
    fi

    local count
    count=$(git diff --cached --name-only | wc -l | tr -d ' ')
    git commit -m "fabric: $count entries updated" --quiet

    if git remote get-url origin > /dev/null 2>&1; then
        git push --quiet 2>/dev/null && echo "fabric: pushed $count entries" || echo "fabric: push failed (offline?)"
    else
        echo "fabric: committed $count entries (no remote configured)"
    fi
}

fabric_pull() {
    cd "$FABRIC_DIR"
    [ -d .git ] || fail "$FABRIC_DIR is not a git repo"

    if ! git remote get-url origin > /dev/null 2>&1; then
        echo "fabric: no remote configured"
        return 0
    fi

    git pull --quiet --rebase 2>/dev/null && echo "fabric: pulled" || echo "fabric: pull failed (offline?)"
}

fabric_sync() {
    fabric_pull
    fabric_push
}

fabric_watch() {
    local interval="${1:-60}"
    echo "fabric: watching $FABRIC_DIR every ${interval}s (ctrl-c to stop)"
    while true; do
        fabric_sync 2>/dev/null
        sleep "$interval"
    done
}

case "${1:-}" in
    init)  fabric_init ;;
    push)  fabric_push ;;
    pull)  fabric_pull ;;
    sync)  fabric_sync ;;
    watch) fabric_watch "${2:-60}" ;;
    *)
        echo "usage: fabric-sync.sh {init|push|pull|sync|watch [seconds]}"
        exit 1
        ;;
esac
