#!/usr/bin/env bash
# self-train.sh -- Export fabric data, upload to Together AI, fine-tune.
#
# Usage: bash scripts/self-train.sh
# Env: TOGETHER_API_KEY (required)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$REPO_DIR/training-data"
MIN_PAIRS=20
POLL_INTERVAL=60
TIMEOUT=3600  # 60 minutes

# Load .env from first hermes agent if TOGETHER_API_KEY not set
if [ -z "${TOGETHER_API_KEY:-}" ]; then
    for d in "$HOME"/.hermes-*; do
        [ -f "$d/.env" ] || continue
        val=$(grep "^TOGETHER_API_KEY=" "$d/.env" 2>/dev/null | head -1 | cut -d'=' -f2-)
        if [ -n "$val" ]; then
            export TOGETHER_API_KEY="$val"
            break
        fi
    done
fi

if [ -z "${TOGETHER_API_KEY:-}" ]; then
    echo "error: TOGETHER_API_KEY not set"
    echo "set it in your .env or: export TOGETHER_API_KEY=your-key"
    exit 1
fi

# ── Step 1: Export ──
echo "step 1: exporting training data..."
EXPORT_OUTPUT=$(python3 "$REPO_DIR/export-training.py" --output "$OUTPUT_DIR" 2>&1)
echo "$EXPORT_OUTPUT"

if [ ! -f "$OUTPUT_DIR/openai.jsonl" ]; then
    echo "error: export failed, no openai.jsonl produced"
    exit 1
fi

# ── Step 2: Check pair count ──
PAIR_COUNT=$(echo "$EXPORT_OUTPUT" | grep "total pairs:" | sed 's/[^0-9]//g')
PAIR_COUNT="${PAIR_COUNT:-0}"
echo ""
echo "total pairs: $PAIR_COUNT"

if [ "$PAIR_COUNT" -lt "$MIN_PAIRS" ]; then
    echo "warning: only $PAIR_COUNT pairs. minimum $MIN_PAIRS recommended."
    echo "run more agent sessions to generate more training data."
    exit 1
fi

# ── Step 3: Upload ──
echo ""
echo "step 2: uploading to Together AI..."
UPLOAD_RESPONSE=$(curl -s -X POST "https://api.together.xyz/v1/files" \
    -H "Authorization: Bearer $TOGETHER_API_KEY" \
    -F "file=@$OUTPUT_DIR/openai.jsonl" \
    -F "purpose=fine-tune")

FILE_ID=$(echo "$UPLOAD_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")

if [ -z "$FILE_ID" ]; then
    echo "error: upload failed"
    echo "$UPLOAD_RESPONSE"
    exit 1
fi

echo "uploaded: $FILE_ID"

# ── Step 4: Fine-tune ──
echo ""
echo "step 3: starting fine-tune..."
FT_RESPONSE=$(curl -s -X POST "https://api.together.xyz/v1/fine-tunes" \
    -H "Authorization: Bearer $TOGETHER_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"training_file\": \"$FILE_ID\", \"model\": \"meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo\", \"n_epochs\": 3, \"suffix\": \"icarus-v1\"}")

JOB_ID=$(echo "$FT_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")

if [ -z "$JOB_ID" ]; then
    echo "error: fine-tune failed to start"
    echo "$FT_RESPONSE"
    exit 1
fi

echo "job started: $JOB_ID"

# ── Step 5: Poll ──
echo ""
echo "step 4: polling status every ${POLL_INTERVAL}s (timeout: ${TIMEOUT}s)..."
ELAPSED=0

while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))

    STATUS_RESPONSE=$(curl -s "https://api.together.xyz/v1/fine-tunes/$JOB_ID" \
        -H "Authorization: Bearer $TOGETHER_API_KEY")

    STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
    echo "  [${ELAPSED}s] status: $STATUS"

    if [ "$STATUS" = "completed" ]; then
        MODEL_ID=$(echo "$STATUS_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('output_name','') or d.get('fine_tuned_model','') or '')" 2>/dev/null || echo "")
        echo ""
        echo "fine-tune complete"
        echo "model: $MODEL_ID"
        echo ""
        echo "to switch: hermes model -> select together -> enter model ID above"
        exit 0
    fi

    if [ "$STATUS" = "failed" ] || [ "$STATUS" = "cancelled" ]; then
        ERROR=$(echo "$STATUS_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error','unknown error'))" 2>/dev/null || echo "unknown")
        echo ""
        echo "fine-tune failed: $ERROR"
        exit 1
    fi
done

echo ""
echo "timeout: fine-tune did not complete in ${TIMEOUT}s"
echo "check manually: curl -s https://api.together.xyz/v1/fine-tunes/$JOB_ID -H 'Authorization: Bearer \$TOGETHER_API_KEY'"
exit 1
