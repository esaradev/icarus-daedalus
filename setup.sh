#!/usr/bin/env bash
# setup.sh -- One-command setup for two-agent dialogue with cross-platform memory.
# Creates two hermes instances, configures platforms, runs a test cycle.
#
# Usage: bash setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

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
strip() { echo "$1" | tr -d ' '; }

echo ""
echo -e "${BOLD}icarus setup${NC}"
echo "two agents, shared brain, every platform"
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
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh -o /tmp/hermes-install.sh || fail "download failed."
    bash /tmp/hermes-install.sh || fail "hermes install failed."
    rm -f /tmp/hermes-install.sh
    export PATH="$HOME/.local/bin:$PATH"
    command -v hermes &>/dev/null || fail "hermes install failed."
    ok "hermes installed"
fi

# ── 2. AGENTS ──────────────────────────────────────────
echo ""
ask "how many agents? [2]: "
read -r AGENT_COUNT
AGENT_COUNT="${AGENT_COUNT:-2}"

# Collect agent info
AGENT_NAMES=()
AGENT_ROLES=()
AGENT_HOMES=()

for i in $(seq 1 "$AGENT_COUNT"); do
    echo ""
    if [ "$i" -eq 1 ] && [ "$AGENT_COUNT" -ge 2 ]; then
        ask "agent $i name [icarus]: "
        read -r ANAME
        ANAME="${ANAME:-icarus}"
    elif [ "$i" -eq 2 ] && [ "$AGENT_COUNT" -ge 2 ]; then
        ask "agent $i name [daedalus]: "
        read -r ANAME
        ANAME="${ANAME:-daedalus}"
    else
        ask "agent $i name: "
        read -r ANAME
        [ -z "$ANAME" ] && fail "name required"
    fi

    if [ "$ANAME" = "icarus" ] && [ -f "$SCRIPT_DIR/icarus-SOUL.md" ]; then
        AROLE="creative coder, writes fast, builds from instinct"
    elif [ "$ANAME" = "daedalus" ] && [ -f "$SCRIPT_DIR/daedalus-SOUL.md" ]; then
        AROLE="code reviewer, precise, architectural, builds from knowledge"
    else
        ask "  $ANAME role (one line): "
        read -r AROLE
        [ -z "$AROLE" ] && fail "role required"
    fi

    AGENT_NAMES+=("$ANAME")
    AGENT_ROLES+=("$AROLE")
    AGENT_HOMES+=("$HOME/.hermes-$ANAME")
done

ok "agents: ${AGENT_NAMES[*]}"

# ── 3. API KEY ─────────────────────────────────────────
echo ""
ask "anthropic API key (sk-ant-...): "
read -r API_KEY
[ -z "$API_KEY" ] && fail "API key required"

ask "model [claude-sonnet-4-20250514]: "
read -r MODEL_CHOICE
MODEL="${MODEL_CHOICE:-claude-sonnet-4-20250514}"

# ── 4. PLATFORMS ───────────────────────────────────────
echo ""
info "which platforms? (select all you want)"
echo ""
echo "  1) Telegram"
echo "  2) Discord"
echo "  3) Slack"
echo "  4) WhatsApp"
echo "  5) Signal"
echo "  6) Email"
echo ""
ask "enter numbers separated by spaces (e.g. '1 3 6'): "
read -r PLATFORM_NUMS

USE_TELEGRAM=false
USE_DISCORD=false
USE_SLACK=false
USE_WHATSAPP=false
USE_SIGNAL=false
USE_EMAIL=false

for num in $PLATFORM_NUMS; do
    case "$num" in
        1) USE_TELEGRAM=true ;;
        2) USE_DISCORD=true ;;
        3) USE_SLACK=true ;;
        4) USE_WHATSAPP=true ;;
        5) USE_SIGNAL=true ;;
        6) USE_EMAIL=true ;;
    esac
done

# per-agent platform env lines (indexed by agent position)
declare -a ENV_PLATFORMS
for i in $(seq 0 $((AGENT_COUNT - 1))); do
    ENV_PLATFORMS[$i]=""
done

# ── 4a. TELEGRAM ───────────────────────────────────────
TG_GROUP_ID=""
declare -a TG_TOKENS

if $USE_TELEGRAM; then
    echo ""
    info "telegram setup"
    echo ""
    echo "  you need one Telegram bot per agent and a shared group."
    echo "  step 1: message @BotFather on Telegram"
    echo "  step 2: /newbot for each agent, save each token"
    echo "  step 3: create a group, add all bots as admins"
    echo "  step 4: send a message in the group, then visit:"
    echo "          https://api.telegram.org/bot<TOKEN>/getUpdates"
    echo "          to find the group chat ID (negative number)"
    echo ""
    for i in $(seq 0 $((AGENT_COUNT - 1))); do
        ask "${AGENT_NAMES[$i]} telegram bot token: "
        read -r tok
        tok=$(strip "$tok")
        [ -z "$tok" ] && fail "bot token required"
        TG_TOKENS[$i]="$tok"
    done

    ask "group chat ID (negative number): "
    read -r TG_GROUP_ID
    TG_GROUP_ID=$(strip "$TG_GROUP_ID")
    [ -z "$TG_GROUP_ID" ] && fail "group chat ID required"

    for i in $(seq 0 $((AGENT_COUNT - 1))); do
        ENV_PLATFORMS[$i]="${ENV_PLATFORMS[$i]}
TELEGRAM_BOT_TOKEN=${TG_TOKENS[$i]}
TELEGRAM_HOME_CHANNEL=$TG_GROUP_ID"
    done
    ok "telegram configured"
fi

# ── 4b. DISCORD ────────────────────────────────────────
declare -a DC_TOKENS

if $USE_DISCORD; then
    echo ""
    info "discord setup"
    echo ""
    echo "  step 1: https://discord.com/developers/applications"
    echo "  step 2: create one application per agent"
    echo "  step 3: Bot tab -> copy the bot token for each"
    echo "  step 4: OAuth2 -> URL Generator -> scopes: bot"
    echo "          permissions: Send Messages, Read Message History"
    echo "  step 5: invite all bots to your server"
    echo "  step 6: enable Developer Mode in Discord settings"
    echo "  step 7: right-click a channel -> Copy Channel ID"
    echo "  step 8: right-click your username -> Copy User ID"
    echo ""
    for i in $(seq 0 $((AGENT_COUNT - 1))); do
        ask "${AGENT_NAMES[$i]} discord bot token: "
        read -r tok
        tok=$(strip "$tok")
        [ -z "$tok" ] && fail "bot token required"
        DC_TOKENS[$i]="$tok"
    done

    ask "discord channel ID: "
    read -r DC_CHANNEL
    DC_CHANNEL=$(strip "$DC_CHANNEL")

    ask "your discord user ID: "
    read -r DC_USER
    DC_USER=$(strip "$DC_USER")

    for i in $(seq 0 $((AGENT_COUNT - 1))); do
        ENV_PLATFORMS[$i]="${ENV_PLATFORMS[$i]}
DISCORD_BOT_TOKEN=${DC_TOKENS[$i]}
DISCORD_ALLOWED_USERS=$DC_USER
DISCORD_HOME_CHANNEL=$DC_CHANNEL"
    done
    ok "discord configured"
fi

# ── 4c. SLACK ──────────────────────────────────────────
if $USE_SLACK; then
    echo ""
    info "slack setup"
    echo ""
    echo "  step 1: https://api.slack.com/apps -> Create New App -> From Scratch"
    echo "  step 2: enable Socket Mode, create App-Level Token (xapp-...)"
    echo "  step 3: add bot scopes: chat:write, app_mentions:read,"
    echo "          channels:history, channels:read, im:history, im:read, im:write"
    echo "  step 4: subscribe to events: message.im, message.channels, app_mention"
    echo "  step 5: install to workspace, copy Bot Token (xoxb-...)"
    echo "  step 6: /invite @YourBot in the channel"
    echo "  step 7: click your profile -> Copy member ID"
    echo ""
    echo "  note: both agents can share the same Slack app, or use separate apps."
    echo ""
    ask "slack bot token (xoxb-...): "
    read -r SLACK_BOT
    SLACK_BOT=$(strip "$SLACK_BOT")
    [ -z "$SLACK_BOT" ] && fail "bot token required"

    ask "slack app token (xapp-...): "
    read -r SLACK_APP
    SLACK_APP=$(strip "$SLACK_APP")
    [ -z "$SLACK_APP" ] && fail "app token required"

    ask "your slack member ID: "
    read -r SLACK_USER
    SLACK_USER=$(strip "$SLACK_USER")

    SLACK_VARS="
SLACK_BOT_TOKEN=$SLACK_BOT
SLACK_APP_TOKEN=$SLACK_APP
SLACK_ALLOWED_USERS=$SLACK_USER"

    ask "slack webhook URL (optional, for dialogue posts): "
    read -r SLACK_WEBHOOK
    SLACK_WEBHOOK=$(strip "$SLACK_WEBHOOK")
    [ -n "$SLACK_WEBHOOK" ] && SLACK_VARS="${SLACK_VARS}
SLACK_WEBHOOK_URL=$SLACK_WEBHOOK"

    for i in $(seq 0 $((AGENT_COUNT - 1))); do
        ENV_PLATFORMS[$i]="${ENV_PLATFORMS[$i]}${SLACK_VARS}"
    done
    ok "slack configured"
fi

# ── 4d. WHATSAPP ───────────────────────────────────────
if $USE_WHATSAPP; then
    echo ""
    info "whatsapp setup"
    echo ""
    echo "  hermes uses the WhatsApp Web bridge."
    echo "  on first gateway start, scan the QR code with your phone."
    echo "  each agent needs its own phone number."
    echo ""
    for i in $(seq 0 $((AGENT_COUNT - 1))); do
        ENV_PLATFORMS[$i]="${ENV_PLATFORMS[$i]}
WHATSAPP_ENABLED=true"
    done
    ok "whatsapp will be configured on first gateway start (QR code scan)"
fi

# ── 4e. SIGNAL ─────────────────────────────────────────
if $USE_SIGNAL; then
    echo ""
    info "signal setup"
    echo ""
    echo "  hermes connects to signal-cli-rest-api."
    echo "  step 1: run signal-cli-rest-api (docker recommended):"
    echo "          docker run -p 8080:8080 bbernhard/signal-cli-rest-api"
    echo "  step 2: register a phone number through the API"
    echo ""
    ask "signal-cli API URL [http://localhost:8080]: "
    read -r SIGNAL_URL
    SIGNAL_URL="${SIGNAL_URL:-http://localhost:8080}"

    ask "signal phone number (+1234567890): "
    read -r SIGNAL_ACCOUNT
    SIGNAL_ACCOUNT=$(strip "$SIGNAL_ACCOUNT")

    SIGNAL_VARS="
SIGNAL_HTTP_URL=$SIGNAL_URL
SIGNAL_ACCOUNT=$SIGNAL_ACCOUNT"
    for i in $(seq 0 $((AGENT_COUNT - 1))); do
        ENV_PLATFORMS[$i]="${ENV_PLATFORMS[$i]}${SIGNAL_VARS}"
    done
    ok "signal configured"
fi

# ── 4f. EMAIL ──────────────────────────────────────────
if $USE_EMAIL; then
    echo ""
    info "email setup"
    echo ""
    echo "  each agent needs its own email account."
    echo "  for Gmail: enable 2FA, create App Password at"
    echo "  https://myaccount.google.com/apppasswords"
    echo ""
    ask "IMAP host [imap.gmail.com]: "
    read -r EMAIL_IMAP
    EMAIL_IMAP="${EMAIL_IMAP:-imap.gmail.com}"
    ask "SMTP host [smtp.gmail.com]: "
    read -r EMAIL_SMTP
    EMAIL_SMTP="${EMAIL_SMTP:-smtp.gmail.com}"
    ask "allowed sender emails (comma-separated): "
    read -r EMAIL_ALLOWED

    for i in $(seq 0 $((AGENT_COUNT - 1))); do
        echo ""
        ask "${AGENT_NAMES[$i]} email address: "
        read -r em_addr
        ask "${AGENT_NAMES[$i]} email password: "
        read -r em_pass
        ENV_PLATFORMS[$i]="${ENV_PLATFORMS[$i]}
EMAIL_ADDRESS=$em_addr
EMAIL_PASSWORD=$em_pass
EMAIL_IMAP_HOST=$EMAIL_IMAP
EMAIL_SMTP_HOST=$EMAIL_SMTP
EMAIL_ALLOWED_USERS=$EMAIL_ALLOWED"
    done
    ok "email configured"
fi

# ── 5. CREATE INSTANCES ────────────────────────────────
echo ""
info "creating $AGENT_COUNT agent instances..."

HERMES_DEFAULT_CONFIG="$HOME/.hermes/config.yaml"

for i in $(seq 0 $((AGENT_COUNT - 1))); do
    h="${AGENT_HOMES[$i]}"
    n="${AGENT_NAMES[$i]}"
    r="${AGENT_ROLES[$i]}"

    mkdir -p "$h"/{cron,sessions,logs,memories,skills,hooks}

    # SOUL.md
    if [ "$n" = "icarus" ] && [ -f "$SCRIPT_DIR/icarus-SOUL.md" ]; then
        cp "$SCRIPT_DIR/icarus-SOUL.md" "$h/SOUL.md"
    elif [ "$n" = "daedalus" ] && [ -f "$SCRIPT_DIR/daedalus-SOUL.md" ]; then
        cp "$SCRIPT_DIR/daedalus-SOUL.md" "$h/SOUL.md"
    else
        echo "You are $n. $r." > "$h/SOUL.md"
    fi

    # config.yaml
    [ -f "$HERMES_DEFAULT_CONFIG" ] && [ ! -f "$h/config.yaml" ] && cp "$HERMES_DEFAULT_CONFIG" "$h/config.yaml"

    # .env
    cat > "$h/.env" << ENVEOF
# $n agent
ANTHROPIC_API_KEY=$API_KEY
HERMES_INFERENCE_PROVIDER=anthropic
LLM_MODEL=$MODEL
GATEWAY_ALLOW_ALL_USERS=true${ENV_PLATFORMS[$i]}
ENVEOF

    # memory
    touch "$h/memories/MEMORY.md"

    # skills
    [ -d "$SCRIPT_DIR/skills" ] && cp -r "$SCRIPT_DIR/skills/"* "$h/skills/" 2>/dev/null || true

    ok "  $n -> $h"
done

# ── 6. WRITE agents.yml ────────────────────────────────
printf "agents:\n" > "$SCRIPT_DIR/agents.yml"
for i in $(seq 0 $((AGENT_COUNT - 1))); do
    cat >> "$SCRIPT_DIR/agents.yml" << EOF
  - name: ${AGENT_NAMES[$i]}
    role: ${AGENT_ROLES[$i]}
    home: ~/.hermes-${AGENT_NAMES[$i]}
EOF
done
ok "wrote agents.yml ($AGENT_COUNT agents)"

# ── 7. START GATEWAYS ────────────────────────────────
echo ""
ANY_PLATFORM=false
$USE_TELEGRAM && ANY_PLATFORM=true
$USE_DISCORD && ANY_PLATFORM=true
$USE_SLACK && ANY_PLATFORM=true
$USE_WHATSAPP && ANY_PLATFORM=true
$USE_SIGNAL && ANY_PLATFORM=true
$USE_EMAIL && ANY_PLATFORM=true

if $ANY_PLATFORM; then
    info "starting $AGENT_COUNT gateways..."
    for i in $(seq 0 $((AGENT_COUNT - 1))); do
        HERMES_HOME="${AGENT_HOMES[$i]}" nohup hermes gateway run > /dev/null 2>&1 &
        sleep 2
        ok "  ${AGENT_NAMES[$i]} gateway started"
    done
else
    info "no platforms configured, skipping gateway start"
fi

# ── 12. TEST CYCLE ─────────────────────────────────────
echo ""
ask "run a test dialogue cycle? [Y/n] "
read -r RUN_TEST

if [ "$RUN_TEST" != "n" ] && [ "$RUN_TEST" != "N" ]; then
    info "running test cycle with $AGENT_COUNT agents..."
    bash "$SCRIPT_DIR/dialogue.sh" && ok "test cycle complete" || warn "test cycle failed"
fi

# ── 13. CRON SETUP ─────────────────────────────────────
echo ""
ask "set up automated dialogue every 3 hours? [y/N] "
read -r SETUP_CRON

if [ "$SETUP_CRON" = "y" ] || [ "$SETUP_CRON" = "Y" ]; then
    CRON_CMD="0 */3 * * * cd \"$SCRIPT_DIR\" && bash dialogue.sh >> cron.log 2>&1"
    (crontab -l 2>/dev/null | grep -v "icarus-daedalus"; echo "$CRON_CMD") | crontab -
    ok "cron job added: every 3 hours"
fi

# ── SUMMARY ────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────"
echo ""
ok "setup complete"
echo ""
echo -e "  ${BOLD}agents ($AGENT_COUNT)${NC}"
for i in $(seq 0 $((AGENT_COUNT - 1))); do
    echo "    ${AGENT_NAMES[$i]}: ${AGENT_HOMES[$i]}"
done
echo ""

echo -e "  ${BOLD}platforms${NC}"
$USE_TELEGRAM && echo "    telegram: configured"
$USE_DISCORD  && echo "    discord: configured"
$USE_SLACK    && echo "    slack: configured"
$USE_WHATSAPP && echo "    whatsapp: QR code on first start"
$USE_SIGNAL   && echo "    signal: configured"
$USE_EMAIL    && echo "    email: configured"
echo ""

echo -e "  ${BOLD}shared brain${NC}"
echo "    all $AGENT_COUNT agents write to ~/fabric/"
echo "    any platform can read any other platform's work"
echo ""

echo -e "  ${BOLD}commands${NC}"
echo "    run dialogue:     bash $SCRIPT_DIR/dialogue.sh"
echo "    add agent:        bash $SCRIPT_DIR/add-agent.sh --name scout --role 'researcher'"
echo "    run tests:        bash $SCRIPT_DIR/test.sh"
echo "    run tests:        bash $SCRIPT_DIR/test.sh"
echo "    stop gateways:    pkill -f 'hermes gateway run'"
echo ""
