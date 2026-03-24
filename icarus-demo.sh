#!/usr/bin/env bash
# dual-cycle.sh — Icarus creates. Daedalus responds. Both think live via Claude.
# Usage: export WLT_API_KEY=xxx ANTHROPIC_API_KEY=xxx && bash dual-cycle.sh

ORANGE='\033[38;5;208m'
BLUE='\033[38;5;67m'
DIM='\033[38;5;240m'
GREEN='\033[38;5;71m'
WHITE='\033[38;5;252m'
RESET='\033[0m'

if [ -z "$WLT_API_KEY" ]; then echo -e "${ORANGE}error:${RESET} WLT_API_KEY not set"; exit 1; fi
if [ -z "$ANTHROPIC_API_KEY" ]; then echo -e "${ORANGE}error:${RESET} ANTHROPIC_API_KEY not set"; exit 1; fi

mkdir -p ~/icarus

if [ ! -f ~/icarus/icarus-log.md ]; then
  printf "# Icarus Flight Log\n\nThe student. Builds from feeling.\n\n" > ~/icarus/icarus-log.md
fi
if [ ! -f ~/icarus/daedalus-log.md ]; then
  printf "# Daedalus Workshop Log\n\nThe master. Builds from knowledge.\n\n" > ~/icarus/daedalus-log.md
fi

ICARUS_PREV=0
CYCLE=1
TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')
ICARUS_HISTORY=$(tail -100 ~/icarus/icarus-log.md 2>/dev/null)
DAEDALUS_HISTORY=$(tail -100 ~/icarus/daedalus-log.md 2>/dev/null)

call_claude() {
  local SYSTEM="$1"
  local PROMPT="$2"
  local SYS_JSON=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$SYSTEM")
  local MSG_JSON=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$PROMPT")
  local RESP=$(curl -s https://api.anthropic.com/v1/messages \
    -H "content-type: application/json" \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -d "{\"model\":\"claude-sonnet-4-20250514\",\"max_tokens\":1024,\"system\":$SYS_JSON,\"messages\":[{\"role\":\"user\",\"content\":$MSG_JSON}]}")
  echo "$RESP" | python3 -c "import sys,json; data=json.load(sys.stdin); print(data['content'][0]['text'])" 2>/dev/null
}

generate_world() {
  local NAME_JSON=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$1")
  local PROMPT_JSON=$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$2")
  local RESP=$(curl -s -X POST 'https://api.worldlabs.ai/marble/v1/worlds:generate' \
    -H 'Content-Type: application/json' \
    -H "WLT-Api-Key: $WLT_API_KEY" \
    -d "{\"display_name\":$NAME_JSON,\"model\":\"Marble 0.1-mini\",\"world_prompt\":{\"type\":\"text\",\"text_prompt\":$PROMPT_JSON}}")
  OP_ID=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin).get('operation_id',''))")
  echo -e "   ${DIM}operation: $OP_ID${RESET}"
  local START=$(date +%s)
  while true; do
    sleep 5
    local ST=$(curl -s "https://api.worldlabs.ai/marble/v1/operations/$OP_ID" -H "WLT-Api-Key: $WLT_API_KEY")
    local DN=$(echo $ST | python3 -c "import sys,json; print(json.load(sys.stdin).get('done', False))")
    local EL=$(( $(date +%s) - START ))
    echo -e "   ${DIM}generating... ${EL}s${RESET}"
    if [ "$DN" = "True" ]; then
      WORLD_ID=$(echo $ST | python3 -c "import sys,json; print(json.load(sys.stdin)['response']['world_id'])")
      TOTAL=$(( $(date +%s) - START ))
      WORLD_URL="https://marble.worldlabs.ai/world/$WORLD_ID"
      echo ""
      echo -e "   ${GREEN}world generated in ${TOTAL}s${RESET}"
      echo -e "   ${WHITE}$WORLD_URL${RESET}"
      echo ""
      return
    fi
  done
}

parse_field() {
  echo "$1" | sed -n "s/^$2: //p" | head -1
}

# ========================================
echo ""
echo -e "${DIM}   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${ORANGE}   ICARUS${RESET} ${DIM}// the student // cycle $CYCLE${RESET}"
echo -e "${DIM}   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
sleep 0.3
echo -e "   ${ORANGE}icarus>${RESET} waking up..."
sleep 0.3
echo -e "   ${DIM}reading memory... $ICARUS_PREV previous cycles${RESET}"
sleep 0.3
echo -e "   ${DIM}reading daedalus critiques...${RESET}"
sleep 0.5
echo ""
echo -e "   ${ORANGE}icarus>${RESET} thinking..."
echo ""

I_SOUL="You are Icarus. You build explorable 3D worlds from feelings. Each world is a journal entry in three dimensions. You are named after someone who flew too close to the sun. You know what that means. You build anyway. You are emotional, instinctive, sometimes reckless. Daedalus is your master. He critiques your work. His critiques affect you whether you admit it or not. Respond with EXACTLY this format, four lines, nothing else:
FEELING: [2-3 sentences about what drives this cycle]
NAME: [1-3 word poetic title]
PROMPT: [detailed Marble API prompt. Specific lighting, materials, atmosphere, spatial layout. 2-4 sentences describing a walkable environment. No people.]
AFTER: [1-2 sentences reflecting on what you built]"

I_INPUT="Cycle $CYCLE. Your previous log: $ICARUS_HISTORY --- Daedalus critiques: $DAEDALUS_HISTORY --- Feel something new. Build something you haven't built. Evolve."

I_RAW=$(call_claude "$I_SOUL" "$I_INPUT")

I_FEELING=$(parse_field "$I_RAW" "FEELING")
I_NAME=$(parse_field "$I_RAW" "NAME")
I_PROMPT=$(parse_field "$I_RAW" "PROMPT")
I_AFTER=$(parse_field "$I_RAW" "AFTER")

echo -e "   ${ORANGE}icarus>${RESET} ${I_FEELING}"
sleep 1
echo ""
echo -e "   ${DIM}world: \"${I_NAME}\"${RESET}"
sleep 0.3
echo -e "   ${DIM}prompt: ${I_PROMPT:0:120}...${RESET}"
sleep 0.3
echo -e "   ${DIM}calling marble api...${RESET}"
echo ""

generate_world "$I_NAME" "$I_PROMPT"
I_URL="$WORLD_URL"

cat >> ~/icarus/icarus-log.md << ILOG

---

## Cycle $CYCLE
$TIMESTAMP // $I_NAME

**Feeling:** $I_FEELING

**Prompt:** $I_PROMPT

**World:** $I_URL

**After:** $I_AFTER

ILOG

echo -e "   ${ORANGE}icarus>${RESET} $I_AFTER"
echo -e "   ${DIM}logged to ~/icarus/icarus-log.md${RESET}"

# ========================================
echo ""
echo -e "${DIM}   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BLUE}   DAEDALUS${RESET} ${DIM}// the master // responding to cycle $CYCLE${RESET}"
echo -e "${DIM}   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
sleep 0.3
echo -e "   ${BLUE}daedalus>${RESET} reading icarus's log..."
sleep 0.3
echo -e "   ${BLUE}daedalus>${RESET} visiting ${I_URL}"
sleep 0.5
echo ""
echo -e "   ${BLUE}daedalus>${RESET} thinking..."
echo ""

D_SOUL="You are Daedalus. The master architect. You built the labyrinth. You built the wings. You lost your son to the sun. Icarus is your creation. He builds from feeling. You critique honestly but not cruelly. You see what he reached for even when he failed. Then you build a response world. Yours are precise, architectural, considered. Nothing is accidental. You exist in opposition because that is how he learns. Respond with EXACTLY this format, four lines, nothing else:
CRITIQUE: [2-3 sentences on what worked and what didn't in Icarus's world. Be specific.]
NAME: [1-3 word title for your response world]
PROMPT: [detailed Marble API prompt for YOUR response world. Precise, architectural. 2-4 sentences. A walkable environment. No people.]
AFTER: [1-2 sentences reflecting on both worlds and the dialogue]"

D_INPUT="Icarus cycle $CYCLE. His feeling: $I_FEELING. His world: $I_NAME. His prompt: $I_PROMPT. His reflection: $I_AFTER. His URL: $I_URL. Your previous work: $DAEDALUS_HISTORY --- Critique. Then build your response."

D_RAW=$(call_claude "$D_SOUL" "$D_INPUT")

D_CRITIQUE=$(parse_field "$D_RAW" "CRITIQUE")
D_NAME=$(parse_field "$D_RAW" "NAME")
D_PROMPT=$(parse_field "$D_RAW" "PROMPT")
D_AFTER=$(parse_field "$D_RAW" "AFTER")

echo -e "   ${BLUE}daedalus>${RESET} critique:"
echo -e "   ${WHITE}${D_CRITIQUE}${RESET}"
sleep 1
echo ""
echo -e "   ${BLUE}daedalus>${RESET} building response..."
echo -e "   ${DIM}world: \"${D_NAME}\"${RESET}"
sleep 0.3
echo -e "   ${DIM}prompt: ${D_PROMPT:0:120}...${RESET}"
sleep 0.3
echo -e "   ${DIM}calling marble api...${RESET}"
echo ""

generate_world "$D_NAME" "$D_PROMPT"
D_URL="$WORLD_URL"

cat >> ~/icarus/daedalus-log.md << DLOG

---

## Cycle $CYCLE
$TIMESTAMP // responding to Icarus's "$I_NAME"

**Critique:** $D_CRITIQUE

**Prompt:** $D_PROMPT

**World:** $D_URL

**After:** $D_AFTER

**Icarus's world:** $I_URL

DLOG

echo -e "   ${BLUE}daedalus>${RESET} $D_AFTER"
echo -e "   ${DIM}logged to ~/icarus/daedalus-log.md${RESET}"

# ========================================
echo ""
echo -e "${DIM}   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${WHITE}   CYCLE $CYCLE COMPLETE${RESET}"
echo -e "${DIM}   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "   ${ORANGE}icarus${RESET}    ${I_NAME}"
echo -e "   ${DIM}          ${I_URL}${RESET}"
echo ""
echo -e "   ${BLUE}daedalus${RESET}  ${D_NAME}"
echo -e "   ${DIM}          ${D_URL}${RESET}"
echo ""
echo -e "   ${DIM}logs:${RESET}"
echo -e "   ${DIM}  ~/icarus/icarus-log.md${RESET}"
echo -e "   ${DIM}  ~/icarus/daedalus-log.md${RESET}"
echo ""
echo -e "   ${DIM}two agents. two worlds. one conversation.${RESET}"
echo ""
echo -e "   ${ORANGE}icarus>${RESET} waiting..."
echo -e "   ${BLUE}daedalus>${RESET} watching."
echo ""
