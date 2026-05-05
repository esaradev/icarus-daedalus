# Provenance and rollback

## The trust problem

LLM agents accumulate memory by writing. Every write is a claim — "I decided X," "the user prefers Y," "the test passed." Without a pointer to the evidence behind the claim, future recalls treat it as ground truth. One wrong claim, one prompt-injection that lands in memory, one stale fact that nobody updated, and the agent is now a confident liar.

icarus-memory addresses this with two pieces of structure on every entry: an evidence list, and a verification status.

## Evidence pointers

Every entry can carry `evidence: list[EvidencePointer]`. Each pointer is one of:

| `kind`         | `ref` example                              | What it points at |
|----------------|--------------------------------------------|-------------------|
| `file`         | `src/auth/middleware.py`                   | a path on disk |
| `url`          | `https://example.com/api/...`              | a network resource |
| `fabric_ref`   | `icarus:a3f29b01b1c2`                      | another entry |
| `tool_output`  | `tool_call_abc123`                         | the result of a specific tool invocation |
| `message`      | `session:20260505_012040:msg:14`           | a specific message in a session |

Each pointer can include an `excerpt` (≤500 chars) and a `hash` (sha256). The hash lets a verifier detect tampering — if the file at `ref` changed since the memory was written, the hash mismatches.

## Verification status

`verified` is one of four states:

- `unverified` — the default for new writes. The claim hasn't been re-grounded.
- `verified` — a verifier (human or model) confirmed the claim against its evidence.
- `contradicted` — another entry contradicts this one. Set via `contradict()`. Requires `contradicted_by` to point at the contradicting entry.
- `rolled_back` — the entry is part of a rollback chain. Set automatically by `rollback()`.

Recall sorts `verified > unverified > contradicted` and excludes `rolled_back` by default.

The `verification_log` is an append-only list of `VerificationRecord`s. Calling `verify()` twice doesn't replace anything — it appends a new record. The audit trail is complete.

## Rollback semantics

Rollback walks the `revises` chain backward from a target entry until it finds an ancestor with `verified='verified'`. That ancestor becomes the "current" version. Every entry between the target and the ancestor is marked `rolled_back`. A new entry of `type='rollback'` is written, pointing back at the verified ancestor.

The contract is **non-destructive**: no file is ever deleted. Every state transition is auditable from the on-disk fabric alone.

## Threat model

What this design defends against:

- **Drift**: a chain of revisions slowly diverging from ground truth. Verified ancestors anchor the chain; rollback restores the anchor.
- **Hallucination as memory**: an LLM writes a false claim. Without `verified='verified'`, that claim sorts below verified entries on recall and can be excluded entirely with `min_verified='verified'`.
- **Prompt injection that writes memory**: an attacker convinces an agent to write a malicious entry. The entry starts `unverified`. A downstream verifier — running periodically — can mark it `contradicted` if it can't reproduce the claim from cited evidence. `rollback()` then restores the chain.
- **Tampering with evidence**: the `hash` field on evidence pointers detects post-hoc edits to referenced files.

What this design does NOT defend against:

- **Compromise of the fabric directory itself.** If an attacker can write arbitrary entries with `verified='verified'` directly to disk, the audit trail is meaningless. Fabric integrity is the operator's responsibility (file permissions, Git signing, etc.).
- **A compromised verifier.** If the verifier blesses every claim, contradictory or not, the system degrades to "every memory is verified" — i.e., back to the trust problem this is trying to solve. Verifier independence matters.
- **Real-time poisoning of high-throughput pipelines.** Verification is a separate pass, not a write-time gate. There's a window between write and verify where bad memories are recallable. Use `min_verified='verified'` on critical recalls if that window is unacceptable.
