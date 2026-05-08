# icarus-dashboard

Operations console for [icarus-memory](https://github.com/esaradev/icarus-memory-infra). Three views over a live fabric: Wiki, Activity, Review Queue.

This is a separate Python package that lives in the icarus-memory repo. It depends on `icarus-memory` but never modifies it — no new endpoints in the substrate, no schema changes, no migrations.

## Requirements

- Python 3.10+ (the substrate requires it; system 3.9 won't work)
- A populated fabric directory, or `ICARUS_FABRIC_ROOT` pointing at one

## Install (local dev)

```bash
cd dashboard
python3.13 -m venv .venv          # any 3.10+ interpreter
.venv/bin/pip install -e ..       # icarus-memory editable
.venv/bin/pip install -e .        # icarus-dashboard editable
```

## Run

```bash
.venv/bin/python -m icarus_dashboard
# → http://127.0.0.1:5170
```

Or pointed at a non-default fabric:

```bash
ICARUS_FABRIC_ROOT=/path/to/fabric .venv/bin/python -m icarus_dashboard
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ICARUS_FABRIC_ROOT` | `~/fabric` | Fabric directory the dashboard reads (matches the substrate's own resolution rule) |
| `ICARUS_DASHBOARD_HOST` | `127.0.0.1` | Bind address |
| `ICARUS_DASHBOARD_PORT` | `5170` | Listen port |

## Views

**Wiki.** Pages grouped by substrate `page_type` (decision / topic / project / agent / uncategorized) and sorted by `updated_at`. Detail pane renders linked entries as structured rows with verified glyph, evidence, and a per-entry provenance footnote. Superseded entries collapsed behind a toggle by default.

**Activity.** Filesystem-tailing event stream (`watchfiles` over the fabric root). Initial seed of up to 100 recent events on page load; live tail via Server-Sent Events. Filters by event kind and agent run client-side. Pause toggle freezes the merge but keeps the connection.

**Review Queue.** Five live detectors run as pure reads:

- **Contradictions** — `Entry.verified == "contradicted"`
- **Stale facts** — active entries older than 90 days with no verification log
- **Unsourced memories** — active entries with no evidence and no `source_tool`
- **Disconnected agents** — agents whose newest archived session is more than 30 days old
- **Briefing errors** — briefings where both `source_ids` and `page_paths` are empty

Resolve / dismiss / supersede actions write ordinary substrate entries; the audit trail lives in the same store as everything else.

## Design choices visible in the UI

These are documented as features, not gaps:

- **Reads aren't directly observable.** The substrate emits no read log. The Activity view shows a banner explaining this; the only honest indirect signal is briefings (each briefing reads its `source_ids` and `page_paths`). No fabricated read events.
- **Sync failures has no substrate signal yet.** The Review Queue keeps the filter visible so the category is discoverable; selecting it shows an explanatory detail pane instead of a fake list.
- **Wiki "Append or Supersede", not "Edit".** `WikiManager.write_page()` regenerates page bodies from linked entries on every write, so freeform body edits would be silently overwritten. The dashboard only exposes operations the substrate actually supports.

## Deviations from the original brief

- **Page-type filter list.** The brief asked for *Decisions / Facts / Failed Attempts / Superseded / Briefings / Sources / Uncategorized*. The substrate's `PageType` literal is `decision | topic | project | agent | uncategorized` (see `src/icarus_memory/wiki.py`). The filter mirrors the actual enum rather than fabricating categories the data does not support.
- **Datastar.** The plan referenced Datastar for client-side reactivity. In practice the views needed only a few dozen lines of vanilla JS — pause toggle, kind/agent filters, SSE merge — and adding a framework dependency for that footprint wasn't worth it. `static/activity.js` and `static/review.js` are the only client scripts.

## Constraints / single-process

- The activity bus is an in-memory ring buffer with an asyncio fan-out. It's a single-process singleton; running multiple uvicorn workers would mean each worker has its own bus and its own watcher. Run with one worker.
- Detectors iterate `MarkdownStore.iter_entries()` on every Review Queue render. Fine at fabric sizes in the low thousands; at higher scale, add caching with a wiki/version + archive/version cache key.
- `fabric_root()` resolves the configured path because watchfiles reports canonical macOS paths (`/private/tmp/...`) while env vars typically point at the alias (`/tmp/...`). Without `.resolve()`, every change is ignored.

## Layout

```
dashboard/
├── README.md
├── pyproject.toml
└── src/icarus_dashboard/
    ├── __main__.py          uvicorn entrypoint
    ├── app.py               FastHTML routes
    ├── theme.py             palette + typography constants
    ├── layout.py            three-pane shell
    ├── views/               wiki / activity / review
    ├── data/                memory adapter, activity bus, review detectors
    └── static/              app.css, activity.js, review.js
```
