# icarus-memory v0.2 Adversarial QA Addendum

## Scope

This is a focused follow-up to `docs/QA-REPORT-v0.1.md`. It verifies that the
four HIGH-severity issues from the v0.1 report are fixed after the v0.2 changes.

Tested local branch state after the fix commits, using Python 3.11 and the repo
virtualenv.

## Verification

Formal gates:

```bash
.venv/bin/pytest -q
# 179 passed

.venv/bin/ruff check .
# All checks passed

.venv/bin/mypy --strict src tests
# Success: no issues found in 27 source files
```

Focused QA replay:

```bash
.venv/bin/python <focused v0.2 QA probe>
# v0.2 focused QA passed
```

The focused probe replayed the original HIGH-severity repros and smoke-tested
the same workflow/adversarial/filesystem/API/MCP axes:

- Wrote 50 workflow entries across process restarts and confirmed disk-only
  persistence still works.
- Confirmed `search("admin access")` excludes rolled-back poison by default.
- Confirmed `audit_search("admin access")` is the explicit all-status retrieval
  surface and still returns rolled-back poison for audit workflows.
- Confirmed `verify()` on a rolled-back poisoned entry raises
  `IllegalStateTransition`.
- Confirmed rollback dry-run reports descendants in `tainted_descendants`.
- Confirmed `rollback(..., cascade=True)` marks descendants `rolled_back`.
- Confirmed malformed public API inputs raise typed `ValidationError`.
- Confirmed self-contradiction is rejected.
- Confirmed concurrent writes still produce unique readable entries.
- Confirmed MCP tool calls reject unknown arguments with `unknown argument: ...`.

## HIGH Issue Status

### HIGH 1: `search()` and MCP `memory_search` return rolled-back poison

Status: **fixed**.

`search()` and MCP `memory_search` now default to `status_filter="safe"`, which
excludes `contradicted` and `rolled_back` entries. `audit_search()` and
`memory_audit_search` provide explicit all-status retrieval for compliance and
debugging.

### HIGH 2: `verify()` resurrects contradicted or rolled-back entries

Status: **fixed**.

`IllegalStateTransition` now blocks `contradicted -> verified` and
`rolled_back -> verified`. Idempotent verify on an already verified entry remains
legal and appends to the verification log.

### HIGH 3: Rollback leaves poisoned descendants unquarantined

Status: **fixed**.

`RollbackPlan` now includes `tainted_descendants`. Default rollback surfaces
descendants without mutating them. `cascade=True` opts into recursive quarantine
and appends cascade verification records.

### HIGH 4: Bad public API inputs raise generic errors or are accepted

Status: **fixed**.

Public `IcarusMemory` methods now validate IDs, query strings, enum-like
arguments, bool flags, and top-level write inputs before storage access. Bad
inputs now raise typed `ValidationError`; self-contradiction is rejected.

## Residual Risk

The MEDIUM items from `docs/QA-REPORT-v0.1.md` were intentionally not all fixed.
Notably, retrieval quality, health/audit APIs for corrupt files, package weight,
and `py.typed` are still future work. MCP unknown-argument rejection was fixed
because it was explicitly included in the v0.2 scope.
