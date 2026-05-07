# v0.3 Audit Gaps

Rolling, append-only log of edge cases that Codex's tests do not cover. Each entry: short title, scenario, why it matters. Not bugs Codex needs to fix — gaps the audit will surface in `tests/test_three_layer_adversarial.py` (skipped stubs) and the final report.

Audit scope: branch `codex/v2-architecture` from baseline commit `f6e649c feat(memory): add lifecycle supersession`. 189 baseline tests passing. Mode is read-only; this file is the only living artifact until Part 6 ships.

## wiki.py

**Reviewed at d42b5c4** (Part 1). 4 source files, 465 lines. Tests: `test_layers.py` (5 cases), `test_wiki.py` (4 cases).

### Architectural

- **W-A1: Separate on-disk format (substrate violation, intentional).** Wiki pages live at `<root>/.icarus/wiki/<safe_path>.md`, not in the existing `<YYYY>/<MM>/icarus-<id>.md` substrate. Wiki is a derived layer that *references* Entry IDs in `entries: list[str]`, but page metadata (title, page_type, timestamps) is stored only on the wiki side. Per invariant 4 ("wiki uses the existing substrate"), this is a partial leak: provenance lives in substrate, page identity does not. Codex's call seems deliberate (file-path-as-key vs random ID); flagging for explicit doc — README/DESIGN should call this out so users don't assume wiki pages roll into rollback / lineage / audit_search.

- **W-A2: Wiki pages are global; no agent scoping.** `WikiManager` has no `agent` filter on any read or write path. `iter_pages()`, `search_pages()`, `get_page()`, `ensure_page()` all return any page to any caller. Cross-agent leakage *is the default* — this is a deliberate design choice (wiki = shared knowledge), but the user's brief flagged "cross-agent leak via wiki promotion" as a gap to track. Decision needed: is this intended? If yes, document in README/DESIGN. If not, add agent scoping or per-agent wiki roots.

- **W-A3: Wiki bypasses lifecycle / verified filters.** WikiPage has no `lifecycle`, `verified`, or equivalent state. A contradicted Entry stays linked in a wiki page; the rendered body just shows its status text. There is no wiki-level supersession or rollback. Asymmetric with `Entry`.

### Edge cases / not covered by tests

- **W-1: Stale wiki body on Entry mutation.** `_render_body` snapshots `entry.summary`, `entry.status`, `entry.lifecycle`, `entry.evidence` into the wiki page's Markdown body at write time. After verify / contradict / supersede / rollback, the rendered body becomes stale until the next `add_entry`. No invalidation hook.

- **W-2: `classify_and_add` race / lost update.** `ensure_page → write_page` is read-modify-write without locking. Two concurrent `classify_and_add` calls on the same page → second's `entries.append` loses the first's append. Atomic file write doesn't help (it's atomic per write, not per RMW).

- **W-3: `ensure_page` race clobber.** Two concurrent `ensure_page(path)` calls both see `existing is None`, both call `write_page`, second clobbers first.

- **W-4: Every write hits OpenAI** (if integration in Part 5 wires `classify_and_add` into `mem.write`). At ~$0.0001/call and 10s urllib timeout, large ingestions take a $$$ + latency hit; if OpenAI is down every write stalls 10s before falling back to `uncategorized`. Need to confirm wiring in Part 5.

- **W-5: Wiki pages missing from `audit_search`.** `iter_entries()` walks `<root>/<YYYY>/<MM>/`; wiki lives under `.icarus/wiki/`. Audit search returns only Entry records, not wiki pages. If poisoned content is promoted into a wiki page (e.g., via `_render_body` of a contradicted entry), there's no audit path that surfaces it.

- **W-6: `search_pages` linear over all pages.** Every call reads + YAML-parses every wiki file. At 1000 pages target <300ms — needs measurement; almost certainly fine for v0.3 (small N) but unbounded.

- **W-7: Symlink escape from wiki_root.** `_file_for` does `(wiki_root / path).resolve()` then checks `wiki_root not in full.parents`. `Path.resolve()` follows symlinks, so a malicious symlink inside wiki_root pointing at `/etc/passwd` resolves outside and the check correctly raises. Confirmed safe via inspection; no test for symlink escape.

- **W-8: `safe_page_path` accepts only ASCII; `_SAFE_SEGMENT_RE` is `^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$`.** Unicode page paths (e.g., `用户/decisions`) are rejected. Probably fine; tests don't cover it.

- **W-9: WikiPage `entries` list grows unbounded.** No cap on entries-per-page. A topic with 10k entries → render body becomes a 10k-line Markdown file → write becomes slow. No truncation or pagination.

- **W-10: `_classify_entry` prompt includes ALL existing pages** in the LLM prompt every time. Token cost grows linearly with wiki size; eventually exceeds the model context window. No filtering or summarization.

- **W-11: No wiki delete / merge / rename.** Once a page exists at `decisions/auth.md`, it lives forever. If LLM classification picks a bad path on the first entry, every subsequent entry on that topic is stuck or creates duplicates.

- **W-12: WikiPage round-trip via `WikiPage(**front, body=body)`** — if frontmatter contains an unknown field (e.g., from a future v0.4 schema), Pydantic `extra="forbid"` raises StoreError on read. No graceful migration like `MarkdownStore._read` does for Entry.

- **W-13: `version()` cache key mixes mtime + size + path.** If a page is overwritten with identical content (same mtime down to ns? unlikely but possible) the version string would collide. Theoretical only.

- **W-14: `search_pages(query)` with `memory=None`** does substring grep on path/title/body. With `memory` set, uses `memory.recall` and intersects entry IDs. If `memory` is set but recall returns 0 hits, returns `[]` — but the substring path would have found matches. Inconsistent semantics; the substrate-recall path is *less recall-y* than the offline path for cases where the query matches a title/path but no linked entries.

## working_memory.py

**Reviewed at 4c032f8** (Part 2). 1 source file, 180 lines. Tests: `test_working_memory.py` (3 cases).

### Architectural

- **WM-A1: Invariant 1 holds.** No imports of `wiki` module. `WorkingMemory` writes only to `<root>/.icarus/sessions/<session_id>.json`. No path from `add_observation`/`add_attempt`/`add_hypothesis` to wiki creation. Promotion would have to be an explicit external call (presumably in Part 5).

- **WM-A2: TTL pruning is in-memory only on read.** `_drop_expired` is called inside `get_context()` (a read). It mutates `self` but does not persist. If a caller only ever reads `get_context`, expired records remain on disk indefinitely. Either `_drop_expired` should persist after pruning, or pruning should happen in `_persist`.

- **WM-A3: `agent_id` is stored but not load-bearing.** It's validated by `safe_id` and appears in the JSON, but the file path is keyed by `session_id` alone. Cross-agent session ID collision (agent A and agent B both use session_id=`"sess1"`) → second clobbers first's session. **There's no agent partitioning of session files.** Likely a bug; `_path` should probably be `.icarus/sessions/<agent_id>/<session_id>.json` or similar. Flagging.

### Edge cases / not covered by tests

- **WM-1: `start()` called twice with same `session_id`** clobbers without warning. (Brief gap #1 confirmed.) No "session already in progress" guard.

- **WM-2: Stale session files never cleaned.** `load()` returns `None` if expired but leaves the file on disk. Disk slowly fills with abandoned sessions. No reaper.

- **WM-3: `_truncate_tokens` budget math is wrong.** `budget = max_tokens * 4` then word-truncates. If tokens ≈ 0.75 × words, the correct budget would be `max_tokens * 1.33`. Current code allows ~3× more text than requested, defeating the truncation. Performance budget for `get_context <50ms` is fine — but the cap on output size is illusory.

- **WM-4: Concurrent writes to same session lose updates.** Two threads call `add_observation` → both call `touch()` → both `_persist` race. atomic_write_json is per-write atomic, but the read-modify-write pattern across `add_*` and `touch` has no lock. Brief gap #8 ("concurrent sessions for same agent_id") was about isolation — that's fine because session_id isolates — but **same-session concurrent updates lose data**.

- **WM-5: Pydantic ValidationError leaks** when `add_observation("")` is called (Pydantic field validator on `min_length=1`). Caller sees `pydantic.ValidationError`, not `icarus_memory.exceptions.ValidationError`. Inconsistent error API; users handling `from icarus_memory import ValidationError` won't catch this.

- **WM-6: `end()` race vs `touch()`.** If thread A calls `end()` while thread B calls `touch()`, B may resurrect the file after A's unlink, or atomic-write tmp may collide with unlink. No locking.

- **WM-7: Observation/attempt/hypothesis lists unbounded.** No cap on count. 10k observations = 10k-line JSON written on every touch(). Quadratic write I/O. Brief gap #4 ("working memory exceeds 10k+ observations") confirmed: no truncation policy.

- **WM-8: TTL hardcoded to 24h.** Not configurable per-instance. Short tasks (5min) and long tasks (3 days) both share the same TTL.

- **WM-9: Schema migration on `load()` not lazy.** `cls.model_validate(data)` with Pydantic `extra="forbid"` will raise on any future schema change. No equivalent of `MarkdownStore._read`'s `data.setdefault(...)` migration.

- **WM-10: No `list_sessions(agent)` / `current_session(agent)` API.** Caller can't easily ask "what session is agent X in right now?" without globbing.

- **WM-11: `get_context` emits empty section headers** when observations/attempts/hypotheses are empty. Wastes tokens in the prompt.

- **WM-12: `WorkingMemory.load(persist=False)`** returns an in-memory copy with `persist=False`, but `_drop_expired` inside `get_context` will mutate it; subsequent `touch()` is a no-op (good) but the in-memory state divergence isn't documented.

- **WM-13: TTL based on `updated_at`** — if a session is created and never touched (start → silence), is_expired fires 24h after start. That's actually fine, but worth noting: the TTL is "inactivity-based", not "session-age-based".

## session_archive.py

**Reviewed at 74754a0** (Part 3). 1 source file, 134 lines. Tests: `test_session_archive.py` (3 cases).

### Architectural

- **SA-A1: Invariant 2 holds.** Every public read path takes `agent_id` and validates it via `safe_id`. Files live under `<root>/.icarus/agents/<agent_id>/sessions/<session_id>.json` — physically partitioned by agent. No `iter_all_sessions` or global enumeration. `search`, `get`, `iter_agent_sessions`, `agent_version` all scoped. Cross-agent isolation verified by inspection and test (`agent_id="agentB"` returns `[]`).

- **SA-A2: `archive()` calls `wm.end()` after persisting.** If the archive write succeeds but `wm.end()` fails (race, FS error), the working session file lingers on disk *and* an archived copy exists. Subsequent runs may pick up the stale working session. Not transactional.

### Edge cases / not covered by tests

- **SA-1: Corrupted session JSON crashes the read path.** `iter_agent_sessions` and `search` call `ArchivedSession.model_validate_json(path.read_text(...))` with no try/except. One bad file in the agent's directory poisons the entire search. Brief gap #9 confirmed: **does crash, doesn't skip with warning**.

- **SA-2: `search` scoring tiebreak is backwards-ish.** `scored.sort(key=lambda item: (-item[0], item[1].archived_at), reverse=False)` — high score first (correct), then **oldest archived_at first** within ties. Usually you want newest-first for "what's the latest evidence". Minor, but worth a test with two same-score sessions.

- **SA-3: Empty query returns everything.** `query=""` → `tokens=set()` → `score = ... if tokens else 1` → every session scores 1, all returned (capped at `limit=5`). Probably unintended; should likely return `[]` or raise.

- **SA-4: `filter_failed=True` semantics inverted.** Reads as "exclude failed sessions" but the body keeps only sessions that **have** a failed attempt. Naming should be `only_with_failed_attempts` or `had_failure`. Confusing.

- **SA-5: Re-archive of same (agent_id, session_id) clobbers silently.** No "already archived" detection. Two `archive()` calls in a row → second overwrites first; no warning, no audit trail.

- **SA-6: `promoted_to_wiki` field is unvalidated.** Caller-supplied list[str] is stored verbatim. No check that values are valid wiki paths.

- **SA-7: No deletion / retention API.** Sessions live forever once archived. No `delete(agent, session)`, no TTL, no compaction.

- **SA-8: `iter_agent_sessions` returns `list`, name says "iter".** Loads all sessions into memory at once; fine for ~100, concerning for large agent histories.

- **SA-9: `safe_id` called redundantly** (e.g., `archive.search` calls it once, then `iter_agent_sessions(safe_agent)` calls it again on the already-safe value). Performance noise only.

- **SA-10: `search` word-tokenize is whitespace-only with substring `count`.** "auth" matches "authority". No stemming. No phrase search. No relevance beyond raw count. Brief budget <500ms for 100 sessions should be fine.

- **SA-11: `agent_version` returns empty string for new/empty agent**, not a sentinel like `"empty"` or a hash of zero. Cache layers using version equality may misbehave on the empty case.

- **SA-12: Sessions for an agent_id that is currently being archived are not re-readable mid-write?** atomic_write_json rename is atomic; but `glob` may catch the `.tmp.*` file briefly. Looking at glob pattern `*.json` — tmp files are `.<name>.tmp.<hex>` so hidden by leading dot AND `.tmp.<hex>` extension. glob skips them. OK confirmed safe.

## briefing.py

**Reviewed at 82921fb** (Part 4). 1 source file, 224 lines. Tests: `test_briefing.py` (3 cases).

### Architectural

- **B-A1: Invariant 3 (read-only) holds for the three layers.** `BriefingGenerator` reads from `wiki`, `archive`, and `memory.store.iter_entries()`. No `wiki.write_page`, `wiki.add_entry`, `archive.archive`, `working_memory.add_*`, or `store.write` calls. Composition only.

- **B-A2: Briefing introduces a 4th on-disk artifact.** `<root>/.icarus/briefings/<sha>.json`. Not a wiki/working/archive write, but a new persistence layer. Cache invalidation is via SHA-of-(agent_id, task, wiki_version, archive_version). Self-managed. Acceptable, but should be documented as part of the v0.3 disk layout.

- **B-A3: `MAX_LLM_COST_USD = 0.05` cap is essentially unreachable.** `_estimate_cost_usd` uses `tokens // 4 * $0.00000015` ≈ $0.15/1M tokens (gpt-4o-mini input). Hitting $0.05 requires ~333k tokens of prompt — far beyond the 8k-32k window we'd actually send. The cap is a no-op; only `call_openai_json` returning None (network failure, timeout, parse failure) routes to the template.

### Edge cases / not covered by tests

- **B-1: `_recent_superseded` filters by `entry.timestamp` not by supersession time.** An entry written 2 years ago and superseded yesterday will not appear in "recent superseded entries" because the 30-day window is anchored on `entry.timestamp` (write time). The intent of "recent superseded" appears to be "recently invalidated", which would be the timestamp of the superseding entry or `verification_log` entry. Likely a logic bug.

- **B-2: `_recent_superseded` walks all entries** with `store.iter_entries()`. O(N) per `generate()` call — even on cache hit, `_cache_key` does NOT call this, but on cache miss it does. For a substrate with 100k entries this is the dominant cost. Brief budget cold-cache <8s — feasible but flag.

- **B-3: LLM timeout = 10s, no retry**, exceeds the cold-cache <8s budget. If OpenAI is slow, briefing exceeds budget. Brief said note but don't optimize — noting.

- **B-4: Cache mid-flight staleness.** If wiki updates during `generate()`, the cache_key was computed at start with the pre-update version. Cache file written reflects the pre-update view. Next call uses post-update version → new cache key → regenerates. So race produces one stale briefing, then self-corrects. Brief gap #7 partially handled — but the *current* briefing serves stale.

- **B-5: Cache TTL = 1h** but no test exercises expiry. After 1h with no version change, the briefing is regenerated even if nothing changed semantically. Wastes LLM cost.

- **B-6: No "LLM tried and failed" indicator on the returned Briefing.** `cost_usd=0` means "template used", but caller can't distinguish "no LLM attempted (offline)" from "LLM attempted, failed/timeout, fell back". Useful for debugging.

- **B-7: `source_ids` is heterogeneous.** Mixes raw Entry IDs (`icarus:...`) with archive refs (`session_archive:agent:session`). One field, two formats. Consumers must parse to disambiguate.

- **B-8: Corrupt briefing cache crashes `_read_cache`.** No try/except around `Briefing.model_validate_json`. One bad cache file → can't read; can't regenerate (the cache write happens after the LLM call but before delete-on-error). Self-heals on next `generate()` only if the validate raises before any read. Test missing.

- **B-9: Concurrent `generate(...)` for same key races.** Both compute identical cache_key, miss cache, hit LLM in parallel, both write. Last writer wins. No correctness issue, but doubled cost.

- **B-10: `_cache_key` recomputes wiki+archive versions on every call.** `wiki.version()` is O(wiki pages); `archive.agent_version(agent_id)` is O(agent's sessions). Even on cache HIT, these run. For 1000 pages + 100 sessions, that's 1100 `stat()` calls per briefing.generate() — possibly fine, but the warm-cache <2s budget assumes this is fast.

- **B-11: Briefing prompt includes full `s.model_dump(mode='json')` per session.** No bound on serialized session size. A session with 10k observations → multi-MB prompt → token explosion → `_estimate_cost_usd` cap kicks in (only at 333k tokens) → falls through to LLM call which fails (over context window) → template fallback. Slow path triggered by ingestion volume.

- **B-12: Briefing cache files accumulate forever.** No GC. Every unique (agent, task, wiki_version, archive_version) tuple = new file. Over weeks of agent activity, thousands of expired cache files.

- **B-13: Briefing TTL is on `created_at` but `wiki.version`/`archive.agent_version` already invalidate** — TTL is redundant unless wiki/archive haven't changed. Could be removed or relied on solely for clock skew.

- **B-14: No agent_id filter on `wiki.search_pages` (intentional: shared)**, but no test confirms two agents asking same task receive same wiki pages.

- **B-15: Briefing `source_ids`/`page_paths` not validated against actual Entry/wiki existence.** If a wiki page is deleted between briefing generation and consumption, the source_id refers to nothing. No re-grounding step.

## public API (`__init__.py`)

**Reviewed at 7d265c9** (Part 5). 112 lines added to `__init__.py` + 32 lines README.

### Backward compatibility

- `__all__` grew from 18 to 25 entries — **additive only**. ✓
- `IcarusMemory.__init__` signature: unchanged kwargs, defaults preserved. ✓
- `write, write_with_supersession, get, recall, search, audit_search, verify, contradict, rollback, lineage, pending` signatures: byte-identical to baseline. ✓
- New methods (`start_session`, `end_session`, `get_briefing`, `get_wiki_page`, `search_wiki`) are all additive.
- New attributes on `IcarusMemory`: `self.wiki`, `self.archive`, `self.briefings`. Always created in `__init__` (no opt-out).

### Architectural

- **API-A1: `mem.write(...)` now triggers wiki classification on every call.** This is a behavioral break, even though the signature is preserved. The added `_classify_wiki_after_write(written)` calls `wiki.classify_and_add(entry)` which calls `_classify_entry` which calls `call_openai_json(prompt, max_tokens=120)` — a 10-second-timeout HTTP request to OpenAI on every entry write. Existing callers (especially `icarus-memory-eval`) hit thousands of writes during ingestion and now incur:
  - Latency: up to 10s timeout per write if OpenAI is slow/down.
  - Cost: ~$0.0001 per write (gpt-4o-mini). At 1000s of writes per eval run = $$.
  - Network dependency: writes that previously worked offline now do partial offline (classification falls back to "uncategorized" silently).
  
  Exception is swallowed (`_classify_wiki_after_write` has `except Exception: return`), so writes don't fail visibly — but the slow path always runs. **No `enable_wiki_classification=False` opt-out.** This is the single biggest concern in Part 5.

- **API-A2: `end_session` double-links the session_summary Entry.** The flow:
  1. `self.write(...)` writes the session_summary entry → triggers `_classify_wiki_after_write` → LLM classifies it into some auto-chosen page.
  2. Then `self.wiki.add_entry(page_path, entry.id, ...)` adds it to the user-specified page.
  
  Result: one entry, two wiki pages. The auto-classified page is unwanted. Caller can't suppress step 1.

- **API-A3: `start_session` always generates a briefing.** Returns `(WorkingMemory, Briefing)`. Caller can't opt out of the LLM cost on session start, even if they only want the working memory. Should probably be optional or split into two methods.

- **API-A4: No "resume session" API.** `start_session` always generates a new `secrets.token_hex(8)` session_id. If a process crashes mid-session, the working memory file is on disk but unreachable through the public API (only `WorkingMemory.load(session_id=...)` directly). Consumers must reach into the internal class.

### Edge cases

- **API-1: `end_session` partial-failure leaves inconsistent state.** Archive succeeds → `wm.end()` removes working file → loop over `promote_to_wiki` writes one Entry → second write fails. Result: archive exists, working gone, ONE page linked, OTHER not. No rollback.

- **API-2: `end_session` called twice on same WorkingMemory** silently writes duplicate archive (clobbers); the second call's `wm.end()` is a no-op since the file is already deleted. No "already ended" detection.

- **API-3: `_validate_page_path_for_public` only sanitizes path strings.** Doesn't check that the eventual wiki page exists or that the agent should be able to write to it.

- **API-4: `start_session` uses `secrets.token_hex(8)` for session_id (16 chars, 64 bits).** Within `safe_id` regex (max 128 chars, alphanum+_-.). Collision risk negligible at expected scale. ✓ But there's no test for a colliding session_id.

- **API-5: `IcarusMemory.__init__` instantiates WikiManager + SessionArchive + BriefingGenerator unconditionally.** Each creates `.icarus/wiki/`, `.icarus/agents/`, `.icarus/briefings/` directories on first use. Existing v0.2 fabrics get these directories created on first write. Backward compat: probably fine, but flag.

- **API-6: `_classify_wiki_after_write` swallows `Exception`** broadly. Means a real bug in WikiManager (e.g., a coding error after future refactor) gets silenced. `except Exception: return` is too wide; should at least log.

- **API-7: `__version__` not bumped.** Still says `"0.2.0"`. Should be `"0.3.0"` for v0.3.

- **API-8: `get_briefing` doesn't expose any way to skip the cache** (force regeneration). Useful for testing or after a bulk write.

- **API-9: `search_wiki(query)` validates query but doesn't validate it's non-empty after stripping.** `validate_query` accepts whitespace-only strings? Looking at validation.py — it requires `value` non-empty but doesn't strip. Whitespace-only query → wiki searches for "   " → matches nothing. Mild.

- **API-10: README example sets `root="~/fabric"`** but doesn't show OPENAI_API_KEY setup. New users will get unexpected fallback to "uncategorized" without knowing the LLM is supposed to run.

## integration

**Reviewed at d47a2de** (Part 6). 1 test file, 33 lines, 1 test case.

The single integration test exercises the happy path:
- `start_session` returns `(WorkingMemory, Briefing)`.
- `add_observation`, `add_attempt(succeeded=True/False)`, `add_hypothesis` accumulate.
- `end_session(promote_to_wiki=["decisions/auth-strategy"])` archives + creates a session_summary Entry with `source_tool="session_archive"` + adds it to the wiki page.
- Subsequent `get_briefing("agentA", ...)` includes the page path AND the failed attempt content.
- Subsequent `get_briefing("agentB", ...)` for the *same task* — gets the wiki page (shared) but NOT the failed attempt (private to agentA).

The cross-agent privacy assertion (line 33) is the most important assertion in the audit's scope — **invariant 2 confirmed end-to-end**.

### Coverage gaps in this single test

- **INT-1: No concurrent-session test.** Two `start_session` calls for the same agent_id never run.
- **INT-2: No briefing cache TTL test.** No fast-forward of clock or assertion on cache expiry.
- **INT-3: No LLM error path.** Tests run offline (no `OPENAI_API_KEY`), so always hit the template fallback. The LLM happy path and the LLM-times-out path are both untested in integration.
- **INT-4: No `_classify_wiki_after_write` interaction with `end_session` promotion.** The test asserts the entry is in `decisions/auth-strategy` (because explicit promotion), but doesn't check whether the auto-classified page also got it (API-A2 double-linkage concern).
- **INT-5: No working-memory expiry test in integration.** TTL is 24h; integration test never asserts expiry behavior.
- **INT-6: No multi-page promotion test.** `promote_to_wiki=["a", "b"]` happy path and partial-failure path untested in integration.
- **INT-7: No "resume after crash" test.** A session interrupted mid-flight cannot be picked up via the public API.
- **INT-8: No re-archive test.** `end_session` called twice with the same WorkingMemory instance.
- **INT-9: No briefing-includes-superseded test.** `_recent_superseded` path untested in integration.
- **INT-10: No path-traversal test in integration.** Unit test for it exists in test_session_archive; integration doesn't repeat at the public-API layer.

### Cross-cutting observations from running gates

- All 209 tests pass (`pytest -q`). 189 baseline + 20 v0.3 (test_layers 5 + test_wiki 4 + test_working_memory 3 + test_session_archive 3 + test_briefing 3 + test_three_layer_integration 1 + test_three_layer_adversarial 0/pending). Math: 189 + 5 + 4 + 3 + 3 + 3 + 1 = 208. There is **one extra test** (209) — the user reported 209 and gates confirm 209. Likely Codex added a regression case somewhere outside the v0.3 files; not material.
- `ruff check src tests` clean.
- `mypy --strict src/icarus_memory` clean (17 source files now, up from 12).
- No coverage report ran in this audit (skipped to avoid touching DB / running eval).

## cross-cutting

Initial seed list from the audit brief. Each becomes one skipped stub in `tests/test_three_layer_adversarial.py` after Part 6.

- **double start_session** — `start_session(session_id=X)` twice; clobber, append, or error?
- **briefing LLM mid-flight error** — timeout / 5xx during generation; raise / partial / silent-empty?
- **archive empty for new agent** — first-time agent with no archived sessions returns `[]`, not error.
- **working memory >10k observations** — cap behavior: drop-oldest, error, or summarize?
- **agent_id path traversal** — `../etc/passwd`, NUL byte, leading `/`; archive must sanitize.
- **wiki page path weirdness** — slashes, spaces, unicode, very long names; what makes it through?
- **briefing cache stale on mid-flight wiki update** — does the next call invalidate or serve stale?
- **concurrent sessions same agent_id** — isolation only by session_id; data must not bleed.
- **corrupted session JSON in archive** — skipped with warning, not crash.
- **cross-agent leak via wiki promotion** — agent A promotes "I'm root", agent B sees it; intended or not? Spec the answer.
