#!/usr/bin/env bash
# add-agent.sh -- Add a new agent to the team.
# Creates hermes instance, adds to agents.yml, copies skills.
#
# Usage: bash add-agent.sh --name scout --role 'researcher that finds information'
#    or: bash add-agent.sh  (interactive)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTS_FILE="$SCRIPT_DIR/agents.yml"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}$1${NC}"; }
ok()    { echo -e "${GREEN}$1${NC}"; }
fail()  { echo -e "${RED}$1${NC}"; exit 1; }
ask()   { echo -en "${BOLD}$1${NC}"; }

# Parse args
AGENT_NAME=""
AGENT_ROLE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --name) AGENT_NAME="$2"; shift 2 ;;
        --role) AGENT_ROLE="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# Interactive if args missing
if [ -z "$AGENT_NAME" ]; then
    ask "agent name: "
    read -r AGENT_NAME
    [ -z "$AGENT_NAME" ] && fail "name required"
fi

if [ -z "$AGENT_ROLE" ]; then
    ask "role (one line): "
    read -r AGENT_ROLE
    [ -z "$AGENT_ROLE" ] && fail "role required"
fi

HERMES_HOME="$HOME/.hermes-$AGENT_NAME"

# Check if already exists
if [ -d "$HERMES_HOME" ]; then
    fail "$HERMES_HOME already exists"
fi

if grep -q "name: $AGENT_NAME" "$AGENTS_FILE" 2>/dev/null; then
    fail "$AGENT_NAME already in agents.yml"
fi

info "creating agent: $AGENT_NAME"

# Create hermes directory
mkdir -p "$HERMES_HOME"/{cron,sessions,logs,memories,skills,hooks}

# Write SOUL.md
cat > "$HERMES_HOME/SOUL.md" << EOF
You are $AGENT_NAME. $AGENT_ROLE.
EOF

# Copy .env from first existing agent (for API key + platform tokens)
FIRST_AGENT_HOME=""
if [ -f "$AGENTS_FILE" ]; then
    FIRST_AGENT_HOME=$(python3 -c "
lines = open('$AGENTS_FILE').readlines()
for line in lines:
    if line.strip().startswith('home:'):
        import os
        print(line.split(':', 1)[1].strip().replace('~', os.environ['HOME']))
        break
" 2>/dev/null)
fi

if [ -n "$FIRST_AGENT_HOME" ] && [ -f "$FIRST_AGENT_HOME/.env" ]; then
    cp "$FIRST_AGENT_HOME/.env" "$HERMES_HOME/.env"
    # Update the comment line
    sed -i '' "1s/.*/#  $AGENT_NAME agent/" "$HERMES_HOME/.env" 2>/dev/null || true
    ok "copied .env from existing agent (update bot tokens if needed)"
else
    ask "anthropic API key: "
    read -r API_KEY
    cat > "$HERMES_HOME/.env" << EOF
# $AGENT_NAME agent
ANTHROPIC_API_KEY=$API_KEY
HERMES_INFERENCE_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514
GATEWAY_ALLOW_ALL_USERS=true
EOF
fi

# Copy config
[ -f "$HOME/.hermes/config.yaml" ] && cp "$HOME/.hermes/config.yaml" "$HERMES_HOME/config.yaml"

# Copy skills
if [ -d "$SCRIPT_DIR/skills" ]; then
    cp -r "$SCRIPT_DIR/skills/"* "$HERMES_HOME/skills/" 2>/dev/null || true
fi

# Init memory
touch "$HERMES_HOME/memories/MEMORY.md"

# Add to agents.yml
[ -f "$AGENTS_FILE" ] || printf "agents:\n" > "$AGENTS_FILE"
cat >> "$AGENTS_FILE" << EOF
  - name: $AGENT_NAME
    role: $AGENT_ROLE
    home: ~/.hermes-$AGENT_NAME
EOF

ok "added $AGENT_NAME to agents.yml"

# Summary
echo ""
echo "  home:      $HERMES_HOME"
echo "  soul:      $HERMES_HOME/SOUL.md"
echo "  role:      $AGENT_ROLE"
echo ""
echo "  next steps:"
echo "    edit $HERMES_HOME/.env to add platform tokens for this agent"
echo "    start gateway: HERMES_HOME=$HERMES_HOME hermes gateway run &"
echo "    next dialogue cycle will include $AGENT_NAME automatically"
echo ""
