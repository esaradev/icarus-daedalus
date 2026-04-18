# Icarus Dashboard

React frontend plus FastAPI backend for the Icarus shared-memory dashboard.

Hermes runs agents. Icarus maintains what they learn.

## What it reads

By default the backend reads from:

- `FABRIC_DIR` if set
- otherwise `~/fabric`

It expects Hermes/Icarus data in that fabric directory:

- `events.jsonl` for live append-only events
- `*.md` fabric entries for backfill into the event stream
- `wiki/` for promoted knowledge pages

The backend now bootstraps ingest automatically:

1. backfills existing fabric markdown into `events.jsonl`
2. ingests `events.jsonl` into SQLite
3. keeps watching for new Hermes events

The wiki worker is still opt-in.

## Run

Backend:

```bash
cd dashboard/backend
alembic upgrade head
/Users/ash/icarus-daedalus/dashboard/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload
```

Frontend:

```bash
cd dashboard/frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

## Environment

- `FABRIC_DIR`
  Hermes/Icarus fabric root. Default: `~/fabric`
- `ICARUS_DB`
  SQLite DB path. Default: `dashboard/backend/icarus.db`
- `ICARUS_INGEST_WORKER`
  Set to `0` to disable automatic backfill + event ingest. Default: enabled.
- `ICARUS_WIKI_WORKER`
  Set to `1` to enable background wiki promotion. Default: disabled.
- `ICARUS_PLUGIN_DIR`
  Override the Hermes Icarus plugin path used by the wiki bridge.

## Verification

Once both servers are up:

- UI: `http://127.0.0.1:5173`
- API health: `http://127.0.0.1:8787/health`
- Fleet: `http://127.0.0.1:8787/fleet`
- Source debug: `http://127.0.0.1:8787/debug/sources`

If Hermes is writing events correctly, the dashboard should populate without running a separate ingest command.
