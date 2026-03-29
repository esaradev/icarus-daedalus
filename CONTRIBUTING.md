# Contributing

## Setup

```bash
git clone https://github.com/esaradev/icarus-daedalus.git
cd icarus-daedalus
bash test.sh  # 51 tests, all should pass
```

## Tests

Run before every PR:

```bash
bash test.sh              # core + retrieval evals + self-train + schema
bash examples/hermes-demo/test.sh  # demo-specific tests
```

All tests must pass. No exceptions.

## Code style

- Bash: `set -euo pipefail` at the top. Quote variables. No bashisms on paths users might have spaces in.
- Python: no dependencies beyond stdlib + yaml (optional). Type hints not required but appreciated.
- One font size for labels, one for data, one for headings. No ad-hoc sizing.

## What to work on

Check the issues. The highest-value areas:

- **Retrieval quality**: better query construction, better scoring signals. Run `python3 eval-retrieval.py --verbose` to see current benchmark results. Add test cases before changing scoring weights.
- **Schema adoption**: update callers to use `review_of`, `revises`, `customer_id`, `status`, `outcome` where applicable. Old entries stay readable.
- **Framework adapters**: the bash adapter and Python plugin cover hermes and Claude Code. Adapters for other frameworks (AutoGPT, CrewAI, LangChain) were removed during cleanup but the protocol is stable enough to rebuild them.

## Pull requests

- One feature per PR.
- Include a test for any new behavior.
- Run `bash test.sh` and paste the result in the PR description.
- If you change scoring weights in `fabric-retrieve.py`, run `python3 eval-retrieval.py --verbose` and paste the before/after.
- No credentials in code. Ever. Check with `grep -rn "sk-ant\|api_key\|token" --include="*.sh" --include="*.py"` before pushing.

## Architecture

```
~/fabric/                    shared memory (the product)
fabric-adapter.sh            write/read/search (50 lines)
fabric-retrieve.py           ranked retrieval with scoring
curator.py                   tiering + compaction
export-training.py           fine-tuning data extraction
plugins/fabric-memory/       hermes plugin (auto-write, auto-read)
hooks/                       Claude Code hooks
scripts/self-train.sh        Together AI fine-tune pipeline
eval-retrieval.py            retrieval benchmark
SCHEMA.md                    entry schema v1
PROTOCOL.md                  protocol spec
```

The entry point for understanding the system: read `SCHEMA.md`, then `fabric-adapter.sh`, then `fabric-retrieve.py`.
