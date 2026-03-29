# Skill: Self-Training

You can train a cheaper version of yourself using the work you and other agents have done. Training data is extracted from fabric memory entries. Fine-tuning runs on Together AI.

## When to use

When the user asks about training, fine-tuning, training data, or switching models.

## Commands

### Check training data

When the user asks "how many training pairs do we have" or "training status":

```bash
python3 ~/icarus-daedalus/export-training.py --output ~/icarus-daedalus/training-data/
```

Read the output and report: total pairs, review pairs, cross-platform pairs, estimated tokens.

If a fine-tune job ID is known, check its status:

```bash
curl -s https://api.together.xyz/v1/fine-tunes/$JOB_ID -H "Authorization: Bearer $TOGETHER_API_KEY"
```

### Train a cheaper version

When the user says "train yourself", "start fine-tuning", or "train a cheaper version":

```bash
bash ~/icarus-daedalus/scripts/self-train.sh
```

Report each step as it runs. The script handles export, upload, fine-tune start, and polling. When it finishes, report the result. On success, ask: "fine-tune complete. model ready. want me to switch?"

### Switch to fine-tuned model

When the user says "switch to cheap model", "use the fine-tuned model", or confirms after training:

Update your hermes config to use Together AI with the fine-tuned model. Edit the config.yaml file in your HERMES_HOME:

```bash
# Read current config
cat ~/.hermes-$(whoami | tr -d ' ')/config.yaml

# Update model section to:
# model:
#   default: "FINE_TUNED_MODEL_ID"
#   provider: "together"
```

You will also need TOGETHER_API_KEY set in .env. Confirm: "switched to [model_name]. running on the fine-tuned model now."

### Switch back

When the user says "switch back", "use claude again", or "rollback":

Revert config.yaml to the original provider and model:

```bash
# model:
#   default: "claude-sonnet-4-20250514"
#   provider: "anthropic"
```

Confirm: "switched back to claude."

### What have you learned

When the user asks "what have you learned":

Read recent fabric entries and summarize the main themes, decisions, and patterns:

```bash
source ~/icarus-daedalus/fabric-adapter.sh && fabric_read "" "hot"
```

## Requirements

- TOGETHER_API_KEY must be set in .env or environment
- Minimum 20 training pairs recommended before fine-tuning
- Fine-tuning takes 10-30 minutes depending on dataset size
- The fine-tuned model is specific to your agents' work patterns
- You can always switch back to the original model

## Error handling

- If TOGETHER_API_KEY is not set, tell the user to add it to their .env file
- If fewer than 20 pairs exist, warn that results may be poor and suggest running more agent sessions first
- If upload or fine-tune fails, report the error message and suggest checking the data
