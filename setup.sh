#!/usr/bin/env bash
# setup.sh -- One-command setup for two-agent dialogue with cross-platform memory.
# Creates two hermes instances, configures platforms, runs a test cycle.
#
# Usage: bash setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}$1${NC}"; }
ok()    { echo -e "${GREEN}$1${NC}"; }
warn()  { echo -e "${YELLOW}$1${NC}"; }
fail()  { echo -e "${RED}$1${NC}"; exit 1; }
ask()   { echo -en "${BOLD}$1${NC}"; }

echo ""
echo -e "${BOLD}icarus-daedalus setup${NC}"
echo "two agents, persistent memory, cross-platform"
echo ""

# ── 1. CHECK HERMES ────────────────────────────────────
info "checking hermes..."

if command -v hermes &>/dev/null; then
    HERMES_VERSION=$(hermes version 2>/dev/null | head -1 || echo "unknown")
    ok "hermes found: $HERMES_VERSION"
else
    warn "hermes not installed."
    ask "install hermes-agent now? [Y/n] "
    read -r INSTALL_HERMES
    if [ "$INSTALL_HERMES" = "n" ] || [ "$INSTALL_HERMES" = "N" ]; then
        fail "hermes is required. install from https://github.com/NousResearch/hermes-agent"
    fi
    info "installing hermes-agent..."
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh -o /tmp/hermes-install.sh || fail "download failed. check your internet connection."
    bash /tmp/hermes-install.sh || fail "hermes install failed. check output above."
    rm -f /tmp/hermes-install.sh
    export PATH="$HOME/.local/bin:$PATH"
    command -v hermes &>/dev/null || fail "hermes install failed. check output above."
    ok "hermes installed"
fi

# ── 2. AGENT TEMPLATE ─────────────────────────────────
echo ""
info "what should your agents do?"
echo ""
echo "  1) code-review    -- one writes code, the other reviews it"
echo "  2) research        -- one explores topics, the other fact-checks"
echo "  3) trading         -- one proposes trades, the other stress-tests"
echo "  4) creative        -- philosophical dialogue (the original icarus/daedalus)"
echo "  5) custom          -- describe your own agents"
echo ""
ask "pick [1-5]: "
read -r TEMPLATE_CHOICE

AGENT_A_NAME="icarus"
AGENT_B_NAME="daedalus"
AGENT_A_SOUL=""
AGENT_B_SOUL=""
DIALOGUE_TEMPLATE=""

case "$TEMPLATE_CHOICE" in
    1)
        DIALOGUE_TEMPLATE="code-review"
        AGENT_A_SOUL=$(cat "$SCRIPT_DIR/templates/code-review/agent-a-SOUL.md")
        AGENT_B_SOUL=$(cat "$SCRIPT_DIR/templates/code-review/agent-b-SOUL.md")
        ok "code-review template selected"
        ;;
    2)
        DIALOGUE_TEMPLATE="research-validation"
        AGENT_A_SOUL=$(cat "$SCRIPT_DIR/templates/research-validation/agent-a-SOUL.md")
        AGENT_B_SOUL=$(cat "$SCRIPT_DIR/templates/research-validation/agent-b-SOUL.md")
        ok "research template selected"
        ;;
    3)
        DIALOGUE_TEMPLATE="trading-strategy"
        AGENT_A_SOUL=$(cat "$SCRIPT_DIR/templates/trading-strategy/agent-a-SOUL.md")
        AGENT_B_SOUL=$(cat "$SCRIPT_DIR/templates/trading-strategy/agent-b-SOUL.md")
        ok "trading template selected"
        ;;
    4)
        DIALOGUE_TEMPLATE="creative"
        AGENT_A_SOUL=$(cat "$SCRIPT_DIR/icarus-SOUL.md")
        AGENT_B_SOUL=$(cat "$SCRIPT_DIR/daedalus-SOUL.md")
        ok "creative dialogue template selected"
        ;;
    5)
        echo ""
        ask "agent A name [icarus]: "
        read -r CUSTOM_A_NAME
        [ -n "$CUSTOM_A_NAME" ] && AGENT_A_NAME="$CUSTOM_A_NAME"

        ask "agent B name [daedalus]: "
        read -r CUSTOM_B_NAME
        [ -n "$CUSTOM_B_NAME" ] && AGENT_B_NAME="$CUSTOM_B_NAME"

        ask "describe agent A in one line: "
        read -r A_DESC
        [ -z "$A_DESC" ] && fail "agent A needs a description"
        AGENT_A_SOUL="You are $AGENT_A_NAME. $A_DESC"

        ask "describe agent B in one line: "
        read -r B_DESC
        [ -z "$B_DESC" ] && fail "agent B needs a description"
        AGENT_B_SOUL="You are $AGENT_B_NAME. $B_DESC"

        DIALOGUE_TEMPLATE="custom"
        ok "custom agents: $AGENT_A_NAME + $AGENT_B_NAME"
        ;;
    *)
        fail "invalid choice"
        ;;
esac

HERMES_A="$HOME/.hermes-$AGENT_A_NAME"
HERMES_B="$HOME/.hermes-$AGENT_B_NAME"

# ── 3. PLATFORMS ───────────────────────────────────────
echo ""
info "which platforms?"
echo ""
echo "  1) Telegram only"
echo "  2) Slack only"
echo "  3) Both"
echo ""
ask "pick [1-3]: "
read -r PLATFORM_CHOICE

USE_TELEGRAM=false
USE_SLACK=false

case "$PLATFORM_CHOICE" in
    1) USE_TELEGRAM=true ;;
    2) USE_SLACK=true ;;
    3) USE_TELEGRAM=true; USE_SLACK=true ;;
    *) fail "invalid choice" ;;
esac

# ── 4. TELEGRAM SETUP ─────────────────────────────────
TG_TOKEN_A=""
TG_TOKEN_B=""
TG_GROUP_ID=""

if $USE_TELEGRAM; then
    echo ""
    info "telegram setup"
    echo ""
    echo "  you need two Telegram bots (one per agent) and a group chat."
    echo ""
    echo "  step 1: open Telegram, message @BotFather"
    echo "  step 2: send /newbot, name it '$AGENT_A_NAME', save the token"
    echo "  step 3: send /newbot again, name it '$AGENT_B_NAME', save the token"
    echo "  step 4: create a group, add both bots as admins"
    echo "  step 5: send a message in the group, then visit:"
    echo "          https://api.telegram.org/bot<TOKEN>/getUpdates"
    echo "          to find the group chat ID (negative number)"
    echo ""
    ask "$AGENT_A_NAME bot token: "
    read -r TG_TOKEN_A
    TG_TOKEN_A=$(echo "$TG_TOKEN_A" | tr -d ' ')
    [ -z "$TG_TOKEN_A" ] && fail "bot token required"

    ask "$AGENT_B_NAME bot token: "
    read -r TG_TOKEN_B
    TG_TOKEN_B=$(echo "$TG_TOKEN_B" | tr -d ' ')
    [ -z "$TG_TOKEN_B" ] && fail "bot token required"

    ask "group chat ID (negative number): "
    read -r TG_GROUP_ID
    TG_GROUP_ID=$(echo "$TG_GROUP_ID" | tr -d ' ')
    [ -z "$TG_GROUP_ID" ] && fail "group chat ID required"
fi

# ── 5. SLACK SETUP ─────────────────────────────────────
SLACK_WEBHOOK=""

if $USE_SLACK; then
    echo ""
    info "slack setup"
    echo ""
    echo "  step 1: go to https://api.slack.com/apps and create a new app"
    echo "  step 2: enable Incoming Webhooks"
    echo "  step 3: add a webhook to a channel (e.g. #agent-dialogue)"
    echo "  step 4: copy the webhook URL"
    echo ""
    ask "slack webhook URL: "
    read -r SLACK_WEBHOOK
    [ -z "$SLACK_WEBHOOK" ] && fail "webhook URL required"
fi

# ── 6. API KEY ─────────────────────────────────────────
echo ""
ask "anthropic API key (sk-ant-...): "
read -r API_KEY
[ -z "$API_KEY" ] && fail "API key required"

echo ""
ask "model [claude-sonnet-4-20250514]: "
read -r MODEL_CHOICE
MODEL="${MODEL_CHOICE:-claude-sonnet-4-20250514}"

# ── 7. CREATE DIRECTORIES ─────────────────────────────
echo ""
info "creating agent instances..."

for DIR in "$HERMES_A" "$HERMES_B"; do
    mkdir -p "$DIR"/{cron,sessions,logs,memories,skills,hooks}
done

# ── 8. WRITE SOUL FILES ───────────────────────────────
echo "$AGENT_A_SOUL" > "$HERMES_A/SOUL.md"
echo "$AGENT_B_SOUL" > "$HERMES_B/SOUL.md"
ok "wrote SOUL.md for both agents"

# ── 9. COPY CONFIG ─────────────────────────────────────
HERMES_DEFAULT_CONFIG="$HOME/.hermes/config.yaml"
if [ -f "$HERMES_DEFAULT_CONFIG" ]; then
    for DIR in "$HERMES_A" "$HERMES_B"; do
        if [ ! -f "$DIR/config.yaml" ]; then
            cp "$HERMES_DEFAULT_CONFIG" "$DIR/config.yaml"
        fi
    done
    ok "copied config.yaml to both instances"
else
    warn "no default config.yaml found at $HERMES_DEFAULT_CONFIG"
    warn "agents will use hermes defaults"
fi

# ── 10. WRITE .ENV FILES ──────────────────────────────
write_env() {
    local envfile="$1" token="$2" agent_name="$3"
    cat > "$envfile" << ENVEOF
# $agent_name agent
ANTHROPIC_API_KEY=$API_KEY
HERMES_INFERENCE_PROVIDER=anthropic
LLM_MODEL=$MODEL
GATEWAY_ALLOW_ALL_USERS=true
ENVEOF

    if $USE_TELEGRAM; then
        cat >> "$envfile" << ENVEOF
TELEGRAM_BOT_TOKEN=$token
TELEGRAM_HOME_CHANNEL=$TG_GROUP_ID
ENVEOF
    fi

    if [ -n "$SLACK_WEBHOOK" ]; then
        echo "SLACK_WEBHOOK_URL=$SLACK_WEBHOOK" >> "$envfile"
    fi
}

write_env "$HERMES_A/.env" "$TG_TOKEN_A" "$AGENT_A_NAME"
write_env "$HERMES_B/.env" "$TG_TOKEN_B" "$AGENT_B_NAME"
ok "wrote .env for both agents"

# ── 11. INITIALIZE MEMORY ─────────────────────────────
for DIR in "$HERMES_A" "$HERMES_B"; do
    touch "$DIR/memories/MEMORY.md"
done
ok "initialized MEMORY.md for cross-platform memory"

# ── 12. COPY SKILLS ───────────────────────────────────
if [ -d "$SCRIPT_DIR/skills" ]; then
    for DIR in "$HERMES_A" "$HERMES_B"; do
        cp -r "$SCRIPT_DIR/skills/"* "$DIR/skills/" 2>/dev/null || true
    done
    ok "copied skills"
fi

# ── 13. COPY TEMPLATE DIALOGUE SCRIPT ─────────────────
if [ "$DIALOGUE_TEMPLATE" != "custom" ] && [ "$DIALOGUE_TEMPLATE" != "creative" ]; then
    TEMPLATE_DIR="$SCRIPT_DIR/templates/$DIALOGUE_TEMPLATE"
    if [ -d "$TEMPLATE_DIR" ]; then
        info "template dialogue script available at: $TEMPLATE_DIR/dialogue.sh"
    fi
fi

# ── 14. START GATEWAYS ─────────────────────────────────
echo ""
info "starting gateways..."

if $USE_TELEGRAM; then
    HERMES_HOME="$HERMES_A" nohup hermes gateway run > /dev/null 2>&1 &
    PID_A=$!
    sleep 3
    HERMES_HOME="$HERMES_B" nohup hermes gateway run > /dev/null 2>&1 &
    PID_B=$!
    sleep 3

    if kill -0 $PID_A 2>/dev/null && kill -0 $PID_B 2>/dev/null; then
        ok "both gateways running (PIDs: $PID_A, $PID_B)"
    else
        warn "gateway startup may have failed. check with: ps aux | grep hermes"
    fi
else
    info "no Telegram configured, skipping gateway start"
fi

# ── 15. TEST CYCLE ─────────────────────────────────────
echo ""
ask "run a test dialogue cycle? [Y/n] "
read -r RUN_TEST

if [ "$RUN_TEST" != "n" ] && [ "$RUN_TEST" != "N" ]; then
    info "running test cycle..."

    if [ "$DIALOGUE_TEMPLATE" == "creative" ] || [ "$DIALOGUE_TEMPLATE" == "custom" ]; then
        # Use main dialogue.sh (needs Telegram)
        if $USE_TELEGRAM; then
            export SLACK_WEBHOOK_URL="${SLACK_WEBHOOK:-}"
            bash "$SCRIPT_DIR/dialogue.sh" && ok "test cycle complete" || warn "test cycle failed. check API key and tokens."
        else
            info "main dialogue.sh requires Telegram. skipping test."
        fi
    else
        # Use template dialogue.sh
        TEMPLATE_SCRIPT="$SCRIPT_DIR/templates/$DIALOGUE_TEMPLATE/dialogue.sh"
        if [ -f "$TEMPLATE_SCRIPT" ]; then
            export ANTHROPIC_API_KEY="$API_KEY"
            export SLACK_WEBHOOK_URL="${SLACK_WEBHOOK:-}"
            case "$DIALOGUE_TEMPLATE" in
                code-review)
                    bash "$TEMPLATE_SCRIPT" "write a function that validates email addresses" && ok "test cycle complete" || warn "test cycle failed"
                    ;;
                research-validation)
                    bash "$TEMPLATE_SCRIPT" "the effect of sleep on memory consolidation" && ok "test cycle complete" || warn "test cycle failed"
                    ;;
                trading-strategy)
                    bash "$TEMPLATE_SCRIPT" "S&P 500 at all-time highs with inverted yield curve" && ok "test cycle complete" || warn "test cycle failed"
                    ;;
            esac
        fi
    fi
fi

# ── 16. CRON SETUP ─────────────────────────────────────
echo ""
ask "set up automated dialogue every 3 hours? [y/N] "
read -r SETUP_CRON

if [ "$SETUP_CRON" = "y" ] || [ "$SETUP_CRON" = "Y" ]; then
    CRON_CMD="0 */3 * * * cd \"$SCRIPT_DIR\" && bash dialogue.sh >> cron.log 2>&1"
    (crontab -l 2>/dev/null | grep -v "icarus-daedalus"; echo "$CRON_CMD") | crontab -
    ok "cron job added: every 3 hours"
fi

# ── 17. SUMMARY ────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────"
echo ""
ok "setup complete"
echo ""
echo -e "  ${BOLD}agents${NC}"
echo "    $AGENT_A_NAME: $HERMES_A"
echo "    $AGENT_B_NAME: $HERMES_B"
echo ""

if $USE_TELEGRAM; then
    echo -e "  ${BOLD}telegram${NC}"
    echo "    group chat ID: $TG_GROUP_ID"
    echo "    message either bot in the group to talk to them"
    echo ""
fi

if [ -n "$SLACK_WEBHOOK" ]; then
    echo -e "  ${BOLD}slack${NC}"
    echo "    webhook configured, dialogue cycles post to your channel"
    echo ""
fi

echo -e "  ${BOLD}dialogue${NC}"
if [ "$DIALOGUE_TEMPLATE" == "creative" ] || [ "$DIALOGUE_TEMPLATE" == "custom" ]; then
    echo "    manual:  bash $SCRIPT_DIR/dialogue.sh"
else
    echo "    manual:  bash $SCRIPT_DIR/templates/$DIALOGUE_TEMPLATE/dialogue.sh \"your task\""
fi
echo "    logs:    $SCRIPT_DIR/*-log.md"
echo ""

echo -e "  ${BOLD}memory${NC}"
echo "    cross-platform memory is automatic"
echo "    Slack coding sessions are recallable on Telegram"
echo "    memory files: $HERMES_A/memories/MEMORY.md"
echo ""

echo -e "  ${BOLD}manage${NC}"
echo "    stop gateways:    pkill -f 'hermes gateway run'"
echo "    restart gateways: HERMES_HOME=$HERMES_A hermes gateway run &"
echo "                      HERMES_HOME=$HERMES_B hermes gateway run &"
echo "    view memory:      cat $HERMES_A/memories/MEMORY.md"
echo ""
