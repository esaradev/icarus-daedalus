# Dashboard Plan v1

Operations console for icarus-memory. Three views: Wiki, Activity, Review Queue. Lives in `dashboard/` at the repo root, ships with its own deps, never modifies the substrate.

## Framework choice: FastHTML + Datastar + handcrafted CSS

Picked over Next.js + Tailwind + shadcn for one reason that overrides visual ceiling: the substrate is Python and we are told to use `IcarusMemory` directly. Next.js means JS land, which forces either (a) a Python sidecar with IPC, or (b) reimplementing all the parsing/lifecycle logic in Node. Both add complexity that the dashboard does not need.

FastHTML gives us:

- Direct `IcarusMemory` access — no API duplication, no schema drift.
- Single process: `python -m icarus_dashboard` and you're up.
- Server-Sent Events for the activity stream are trivial (Starlette under the hood).
- Datastar handles client-side reactivity (filter toggles, list/detail swaps, SSE merges) with HTML attributes — no React build chain.

Tradeoff I'm accepting: visual ceiling is lower than shadcn's polished primitives. The mitigation is that the design spec is intentionally narrow — five colors, three font sizes, no gradients/shadows/glow. Vanilla CSS is actually the right tool when the system is that constrained; there's less to fight than there is to compose.

Streamlit was not in scope. The brief said don't pick framework defaults.

## File layout

```
dashboard/
├── README.md                run instructions
├── pyproject.toml           own deps; does not touch icarus-memory's
├── src/icarus_dashboard/
│   ├── __init__.py
│   ├── __main__.py          python -m icarus_dashboard entrypoint
│   ├── app.py               FastHTML routes
│   ├── theme.py             palette + typography constants
│   ├── layout.py            three-pane shell
│   ├── views/
│   │   ├── wiki.py          Wiki view
│   │   ├── activity.py      Activity view + SSE stream
│   │   └── review.py        Review Queue view
│   ├── data/
│   │   ├── memory.py        IcarusMemory adapter (lazy singleton)
│   │   ├── activity.py      filesystem watcher → event stream
│   │   └── review.py        contradiction / staleness / orphan detectors
│   └── static/
│       └── app.css          all styles, scoped CSS variables
```

## Data flow

The dashboard process instantiates one `IcarusMemory(root=ICARUS_FABRIC_ROOT)` at startup. All views go through it.

**Wiki view.** Lists pages from `WikiManager.iter_pages()`, grouped by `page_type`. Detail renders the existing page body (already includes provenance footnotes — see `wiki.py:_render_body`). Markdown rendered with `markdown-it-py`. Superseded entries are detected per-page by inspecting linked `Entry.lifecycle == "superseded"` and collapsed by default behind a "show N superseded" toggle.

**Activity view.** No reads in the substrate are logged today — I'll be honest about that. Filesystem `watchfiles` against:

| Path | Event derived |
|---|---|
| `<root>/<YYYY>/<MM>/icarus-*.md` (created) | `write` |
| `<root>/<YYYY>/<MM>/icarus-*.md` (mtime change) | `edit` (verify / contradict / supersede) |
| `.icarus/sessions/*.json` (created) | `session_start` |
| `.icarus/sessions/*.json` (deleted) | `session_end` |
| `.icarus/agents/<agent>/sessions/*.json` (created) | `archive` |
| `.icarus/briefings/*.json` (created) | `briefing` |

Reads are surfaced indirectly: each new briefing implies reads of its `source_ids` and `page_paths`. The "reads" filter shows briefing-derived reads plus a banner that direct read events aren't observable until the substrate emits them. No fake metrics.

Initial seed = mtime scan of those paths. Live tail = SSE pushed to the browser; Datastar merges new rows into the list. Pause toggle freezes the merge but keeps the connection.

**Review Queue view.** All issue types are derived queries against the existing data:

| Issue type | Detection |
|---|---|
| Contradictions | `Entry.verified == "contradicted"` (already a first-class state) |
| Stale facts | `lifecycle == "active"` and `(now - timestamp) > 90d` and `verification_log` empty |
| Unsourced memories | `evidence == []` and `source_tool is None` |
| Disconnected agents | `.icarus/agents/<agent>/sessions/` with newest mtime > 30d ago |
| Sync failures | **Not yet implementable** — the substrate has no sync log. Section will render an explanatory empty state, not a fake list. |
| Briefing errors | Briefings with empty `source_ids` *and* empty `page_paths` (template fallback when nothing matched) |

Detail-pane actions:

- **Mark resolved** → write a new entry with `type="review_resolved"`, `evidence=[{kind:"fabric_ref", ref:<issue_entry_id>}]`. Substrate's `Entry.type` is freeform `str`, so this works without schema change.
- **Supersede** → opens a form that calls `IcarusMemory.write_with_supersession(...)` against the offending entry.
- **Edit** → because `WikiManager.write_page` re-renders body from linked entries (it discards user-edited body), "edit" means "append or supersede an entry on this page" rather than freeform text edit. Honest call-out in the UI.
- **Dismiss** → write a `type="review_dismissed"` entry.

## Three-pane shell

Mail.app / Linear / GitHub Issues pattern.

- Left nav: 200px, sticky. Just three top-level items (Wiki, Activity, Review Queue) with view-specific filters underneath.
- Center list: ~360px, scrollable, the "list of things in this view".
- Right detail: flexes to fill, scrollable.
- Resize handles: not in v1. Fixed widths.

## Theme

Hardcoded palette, no theming system:

```
--bg:        #0a0a0a   page
--surface:   #1a1a1a   cards, panels
--border:    #2a2a2a   1px dividers
--text:      #e8e8e8   primary text
--muted:     #888888   timestamps, IDs, secondary
--accent:    #f5a524   icarus amber, used sparingly (active nav, type badge fill)
```

Type:

- Sans: Inter (system fallback `-apple-system`).
- Mono: JetBrains Mono (fallback `ui-monospace`).
- Sizes: 13px (mono detail), 14px (body), 18px (titles). Three only.
- Line-height 1.5.

Status indicators are typography-based: `✓` verified, `✗` contradicted, `⚠` stale, `↻` superseded. Single `--accent` dot for "needs review". No colored banners.

## Constraints I'm honoring

- New code only. Nothing under `src/icarus_memory/` is modified.
- No new deps in `pyproject.toml` at the repo root. Dashboard has its own.
- Three views, three nav items. No settings page, onboarding, help, or analytics.
- One commit per view, plus the shell/theme commit and the README commit.

## Commit sequence

1. `docs(dashboard): plan v1` — this file.
2. `feat(dashboard): shell, theme, IcarusMemory adapter` — three-pane layout, palette, `data/memory.py`. Stub views render "coming next".
3. `feat(dashboard): wiki view` — page list, detail, provenance, superseded toggle.
4. `feat(dashboard): activity view` — watcher, SSE, filters, pause.
5. `feat(dashboard): review queue view` — detectors, list, detail, actions.
6. `docs(dashboard): readme + run instructions` — final commit.

Branch is `dashboard-v1`. Won't merge to `main`. Won't push until the last commit lands.

## Risks worth flagging now

- **FastHTML is young.** Three views at this scale won't hit its limits, but if scope grows I'd revisit the framework choice rather than wedge complexity into FastHTML.
- **Reads aren't observable.** The activity view will surface what the filesystem reveals; "reads" are inferred from briefings. If you want true read-event observability, that's a substrate change, not a dashboard change.
- **Edit semantics on wiki pages.** The substrate's wiki body is regenerated from linked entries. The dashboard's "edit" therefore appends/supersedes entries. If you wanted freeform body editing, that's a substrate behavior change.
- **Sync failures category is empty until substrate ships sync logging.** Will render an explanation, not faked rows.
