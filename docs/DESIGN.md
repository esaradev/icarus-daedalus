# Design

## Goals

1. Be a memory layer that any agent framework can adopt with one import or one MCP wire.
2. Make provenance a first-class field, not an afterthought.
3. Make rollback a non-destructive operation that any operator can run from a CLI.
4. Stay Git-friendly: human-readable Markdown on disk, no binary index.

## On-disk layout

```
<root>/
  YYYY/
    MM/
      icarus-<id>.md
  .cache/
    embeddings/
      <model-slug>/
        <id>.npy
        <id>.meta
```

`<root>` resolves from constructor arg → `ICARUS_FABRIC_ROOT` env → `~/fabric`.

Filenames omit the `:` so the format is portable to Windows. The canonical id (`icarus:<12-hex>`) lives in the YAML frontmatter.

## Entry shape

A complete entry:

```markdown
---
id: icarus:a3f29b01b1c2
agent: builder
platform: hermes
timestamp: 2026-05-05T01:23:45Z
type: decision
summary: chose postgres for user service
training_value: high
project_id: hermes-agent
session_id: 20260505_012040_a1b2c3
status: closed
review_of: icarus:b1c2d3e4f5a6
revises: icarus:c1d2e3f4a5b6
verified: verified
contradicted_by: null
source_tool: manual
artifact_paths:
  - docs/adr/0007-database-choice.md
evidence:
  - kind: file
    ref: docs/adr/0007-database-choice.md
    excerpt: "We will use PostgreSQL because..."
    hash: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
  - kind: fabric_ref
    ref: icarus:b1c2d3e4f5a6
verification_log:
  - verifier: manual
    timestamp: 2026-05-05T01:30:00Z
    status: verified
    note: confirmed by team review
---

# Postgres for user service

Long-form markdown body explaining the decision...
```

## Validation rules (write-time)

Enforced in `validation.py`:

- `id` is unique within the store.
- `revises`, `review_of`, and `evidence[*]` of kind `fabric_ref` must point to existing entries.
- `status='open'` requires `assigned_to`.
- `type='review'` requires `review_of`.
- `verified='verified'` cannot be set on initial write — only via `verify()`.
- `verified='contradicted'` requires `contradicted_by` to point to an existing entry.
- `summary` ≤ 200 chars, `evidence[*].excerpt` ≤ 500 chars.

## Recall

Default mode is keyword: simple token-overlap scoring across `summary` + `body`. Cheap, no model dependencies. Good enough for small-to-medium fabrics.

When the `[embeddings]` extra is installed, `mode="auto"` switches to a hybrid: keyword + embedding, fused via reciprocal rank fusion (k=60). Embeddings are cached per entry, keyed on `(model_name, file_mtime, file_size)`, so switching models invalidates the cache.

Filtering is applied before scoring. Sort key is `(verified-status-bucket, score)` so verified entries rise above unverified, contradicted always sinks below unverified.

## Rollback

The contract: rollback is **non-destructive**. No file is ever deleted.

1. Walk `revises` backward from the target.
2. Find the first ancestor with `verified='verified'`.
3. Mark every intermediate entry `verified='rolled_back'` (this just appends a `VerificationRecord` and persists).
4. Write a new entry of `type='rollback'` whose `revises` points at the verified ancestor. The summary records what got rolled back.

If no verified ancestor exists, the plan returns an error. Recall filters out `rolled_back` entries by default but they remain in the store.

## Concurrency

`generate_id` uses `secrets.token_hex(6)` (48 bits) and retries on collision against the live disk. With realistic fabric sizes the retry never trips.

Writes are atomic via `os.replace`. A crash during write leaves the previous version intact and a `.tmp.<random>` sibling that can be cleaned up by hand.

The store does not protect against two processes writing the same entry id concurrently — that case is impossible in practice (independent `generate_id` calls choose different ids) and the cost of a real lock is not worth the protection.
