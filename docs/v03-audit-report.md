# icarus-memory v0.3 audit report

Independent audit of the three-layer agent memory architecture shipped on `codex/v2-architecture` between commits `d42b5c4` and `d47a2de`. Audit started from baseline `f6e649c` (189 tests). Mode: read-only review and gap stubbing; no production code modified.

Live findings are tracked in [`v03-audit-gaps.md`](v03-audit-gaps.md). Skipped test stubs (one per material gap) live at [`tests/test_three_layer_adversarial.py`](../tests/test_three_layer_adversarial.py). 39 stubs total, all `@pytest.mark.skip` with audit-trail reasons.

## 1. Per-Part status

| Part | Commit | What shipped | Status |
|---|---|---|---|
| 1: wiki | `d42b5c4` | `_layers.py` (helpers), `wiki.py` (WikiManager + WikiPage) + 9 tests | **shipped with concerns** |
| 2: working memory | `4c032f8` | `working_memory.py` (WorkingMemory, observations/attempts/hypotheses) + 3 tests | **shipped with concerns** |
| 3: session archive | `74754a0` | `session_archive.py` (SessionArchive, ArchivedSession) + 3 tests | **shipped clean** |
| 4: briefings | `82921fb` | `briefing.py` (BriefingGenerator, Briefing, cache) + 3 tests | **shipped with concerns** |
| 5: public API | `7d265c9` | 112 lines on IcarusMemory: `start_session`, `end_session`, `get_briefing`, `get_wiki_page`, `search_wiki`, automatic wiki classification on write + 32 lines README | **shipped with concerns (significant)** |
| 6: integration coverage | `d47a2de` | `tests/test_three_layer_integration.py` (1 test) | **shipped with concerns** |

Gates at HEAD: 209 passed, 39 audit stubs skipped, ruff clean, mypy --strict clean (17 source files).

## 2. Architectural concerns

Severity scale: **blocker** = should not merge, **caveat** = merge but document and follow up, **nit** = take it or leave it.

| ID | Where | What | Severity |
|---|---|---|---|
| API-A1 | `__init__.py:165-168` | Every `mem.write(...)` triggers `wiki.classify_and_add` → `call_openai_json` with a 10s urllib timeout. No opt-out kwarg. Existing v0.2 callers (esp. `icarus-memory-eval`) silently incur per-write OpenAI cost and up-to-10s latency on every entry. The `except Exception: return` swallows failures so writes don't break visibly, but the slow path always runs. **This is the single biggest behavioral break in v0.3.** | **blocker** |
| API-A2 | `__init__.py:443-461` | `end_session(promote_to_wiki=[...])` writes a session_summary Entry which, via API-A1, triggers auto-classification. Then the code explicitly calls `wiki.add_entry(page_path, ...)`. Result: one entry linked to TWO wiki pages — the user's chosen one AND an LLM-picked one. | caveat |
| W-A2 | `wiki.py` | Wiki pages are global with no `agent_id` partitioning. By design (wiki = shared promoted knowledge) this is intentional — but the brief explicitly listed cross-agent leak via wiki promotion as a tracked gap. The integration test confirms two agents see the same wiki page after promotion. Either document this in DESIGN.md as the chosen model, or add agent scoping. **Decision required.** | caveat |
| WM-A3 | `working_memory.py:170` | Session files are stored at `.icarus/sessions/<session_id>.json` — keyed by `session_id` alone, not `(agent_id, session_id)`. If two agents pick the same `session_id` literal, they collide. `start_session` in v0.3 generates random IDs so collision in practice is negligible, but a caller using their own session_id semantics would be at risk. | caveat |
| W-A1 | `wiki.py:62` | Wiki pages live at `<root>/.icarus/wiki/<safe_path>.md` — separate from the existing `<YYYY>/<MM>/icarus-<id>.md` substrate. Provenance lives in substrate (`Entry` records); page metadata lives wiki-side. `audit_search`, `lineage`, and `rollback` do not see wiki pages. Partial substrate violation; flag in DESIGN.md so users don't expect wiki pages to flow through audit/rollback. | caveat |
| WM-A2 | `working_memory.py:130, 156-160` | `_drop_expired` is called inside `get_context()` (a read), mutates `self`, but does not persist. Disk retains expired records until the next `touch()`. | nit |
| B-A2 | `briefing.py:88, 152` | Briefing cache is a 4th on-disk artifact at `.icarus/briefings/<sha>.json`, distinct from the three layers it composes. Self-managed via wiki+archive version hashes. Acceptable; document as part of the v0.3 disk layout. | nit |
| B-A3 | `briefing.py:111` | `MAX_LLM_COST_USD = 0.05` is effectively unreachable: with `_estimate_cost_usd` math, you'd need ~333k prompt tokens to trip it. The cap is a no-op; the only fallback path is `call_openai_json` returning None. | nit |
| API-A3 | `__init__.py:407-419` | `start_session` always generates a briefing (LLM cost on every session start). No `briefing=False` opt-out. | caveat |
| API-A4 | `__init__.py:407` | No resume-existing-session API. Process restart loses access to in-progress sessions through the public API; caller has to reach into `WorkingMemory.load`. | caveat |

## 3. Test coverage gaps

Each row maps a gap to where Codex's tests stop and what the corresponding stub asserts. Full list in `v03-audit-gaps.md`. Stubs in `tests/test_three_layer_adversarial.py`.

| Gap | Codex's tests stop at | Stub asserts |
|---|---|---|
| WM-1: double `start_session` | n/a (untested) | second call refuses, resumes, or warns; never silent clobber |
| WM-2: expired session disk leak | n/a | TTL-expired file is unlinked on next `load()` |
| WM-3: `_truncate_tokens` math | offline test of structure only | `get_context(max_tokens=N)` returns ≤ N actual tokens |
| WM-4: concurrent `add_observation` | n/a | 50-thread spawn → 50 observations end up persisted |
| WM-A3: session path collision | n/a | two agents w/ same session_id literal don't clobber |
| W-1: stale wiki body on Entry mutation | n/a | wiki body reflects post-contradict state, or staleness is documented |
| W-2: `classify_and_add` race | n/a | 10-thread classify on same page → 10 entry IDs preserved |
| W-A2: cross-agent wiki visibility | offline single-agent test | explicit assertion of chosen visibility model |
| W-4: write-time OpenAI call | offline-only test (env unset) | `IcarusMemory(enable_wiki_classification=False)` makes no HTTP requests |
| W-9: unbounded entries-per-page | n/a | 10k entries either capped/evicted or growth is documented |
| W-10: classification prompt unbounded | small N | 1000 wiki pages → prompt token count bounded |
| SA-1: corrupted JSON crashes search | offline single-session test | bad file is skip-and-warn, not raise |
| SA-2: tiebreak by oldest | n/a | newer same-score session sorts first |
| SA-5: re-archive clobber | n/a | second `archive(wm)` for same key errors or no-ops |
| B-1: `_recent_superseded` time anchor | n/a | recently-invalidated old entries appear; logic uses supersession time |
| B-3: 10s timeout vs 8s budget | n/a | mocked-slow LLM still returns ≤8s via fallback |
| B-4: cache mid-flight stale | n/a | wiki update during `generate()` is reflected next call |
| B-5: cache TTL | n/a | clock past 1h → cache regenerates |
| B-8: corrupt cache crash | n/a | bad cache file is treated as miss |
| API-A1: write triggers OpenAI | n/a | opt-out flag suppresses HTTP call |
| API-A2: double-linkage | n/a | `end_session` promoted entry lives in ONE page |
| API-7: version not bumped | n/a | `__version__ == "0.3.0"` |
| INT-1: concurrent sessions | n/a | two start_sessions for same agent both work, isolated |
| INT-3: live LLM path | offline only | mocked-success LLM exercises the live code path AND privacy still holds |

## 4. Performance

Per-part performance budgets from the audit brief. Audit measured via inspection only; no benchmarks run because that would imply running the eval (out of scope) or building a fresh load harness (out of scope).

| Metric | Budget | Observed | Verdict |
|---|---|---|---|
| Briefing cold cache | <8s | LLM timeout = 10s, no retry. If OpenAI is slow, exceeds budget. Template fallback is fast (~10ms). | **flag (B-3)** |
| Briefing warm cache | <2s | Cache hit avoids LLM, but `_cache_key` recomputes `wiki.version()` (O(wiki pages)) and `archive.agent_version()` (O(agent's sessions)) on every call. Should fit budget at expected scale. | likely fine, untimed |
| Session archive search | <500ms for 100 sessions | Linear scan, JSON-parse per file, simple substring scoring. Should fit. | likely fine, untimed |
| Working memory `get_context` | <50ms with truncation | In-memory list comprehension + `_truncate_tokens`. Fine, but truncation budget math is wrong (WM-3 — allows ~3x intended tokens). | functionally fine, semantically wrong |
| Wiki page search | <300ms for 1000 pages | `iter_pages` reads + parses YAML for every wiki file on every call. 1000 files = 1000 reads. Almost certainly under 300ms but unbounded. | likely fine, untimed; flag at scale |

The non-LLM bottleneck most likely to surface first is **B-2** (`_recent_superseded` walks all entries on every cache miss). At 100k entries this dominates.

## 5. Documentation

| What | Status |
|---|---|
| README "Three-layer agent loop" section | Added in 7d265c9. Shows happy path. Missing: OPENAI_API_KEY setup note, mention of automatic wiki classification on every write, mention that wiki is global across agents. |
| `__version__` bump | **NOT done.** Still `"0.2.0"` (API-7). Trivial fix; reported in stub form. |
| `CHANGELOG.md` | Not inspected as part of audit; flag for Codex/user to confirm v0.3 entry. |
| `DESIGN.md` | Not updated for v0.3. Should at minimum cover: (a) the three-layer model, (b) cross-agent visibility rules, (c) the four on-disk locations under `.icarus/` (wiki, sessions, agents, briefings), (d) automatic-classification side effect on `mem.write`. |
| `PROVENANCE.md` | Not updated. Should cover: wiki body is a snapshot (W-1), session_summary entries link archive ref via `tool_output` evidence kind, briefing source_ids are heterogeneous (entry IDs + archive refs). |

## 6. Recommendation

**Merge with caveats.** The core architecture is sound — invariants 2 (cross-agent isolation in archive) and 3 (briefing read-only) hold; invariant 4 (wiki uses substrate) is partially honored as documented in W-A1; invariant 1 (no auto-promotion to wiki) holds inside `working_memory.py`. The integration test exercises the privacy-critical end-to-end path correctly.

But two items should be addressed before this is exercised by real callers (especially `icarus-memory-eval`):

1. **API-A1 needs an opt-out** before merge into anything that ingests at volume. Either `IcarusMemory(enable_wiki_classification=False)` or a per-write `classify=False` flag. The eval harness was already paying ~10 minutes per Mem0 trace; adding a 10-second urllib timeout per icarus write would dominate wall-clock and silently spend OpenAI tokens. **This is the only blocker.**

2. **Decide and document the cross-agent visibility model for the wiki** (W-A2). Either ship as "wiki is shared knowledge across agents in the same fabric" with a one-paragraph DESIGN.md addition, or partition by agent. Don't leave it implicit.

Items 3-5 below are merge-with-caveats:

3. **Bump `__version__` to `"0.3.0"`** (API-7).
4. **Fix B-1** (`_recent_superseded` time anchor): one-line change, big briefing-quality lift.
5. **Fix API-A2** (`end_session` double-linkage): probably the same fix as API-A1 — when called from `end_session`, suppress auto-classification on the inner `self.write`.

Everything else in the gaps doc is real but follow-up work. The 39 skipped stubs in `test_three_layer_adversarial.py` are the worklist for v0.3.1+.

Audit complete.
