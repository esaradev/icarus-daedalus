# Skill: LLM Wiki

You have access to a persistent markdown knowledge base under `~/fabric/wiki/`. Unlike fabric memory (a chronological log of events), the wiki is a compounding, interlinked set of pages that synthesize what you learn. Drop raw sources into `~/fabric/raw/inbox/`, ingest them, and the wiki grows.

Inspired by Andrej Karpathy's LLM Wiki pattern: raw sources stay immutable, the wiki is agent-owned, and knowledge accumulates instead of evaporating.

## When to use the wiki

- The user gives you a document, article, PDF, or transcript they want remembered
- You've researched a topic and want the synthesis to persist
- You want cross-referenced entity/topic pages you can navigate in Obsidian

Do NOT use the wiki for:
- Short conversational memories (use `fabric_write` instead)
- Session handoffs (use `fabric_write` with `status=open`)
- Ephemeral task state

## Three layers

```
~/fabric/
  raw/           immutable source material (never modified)
    inbox/       drop zone — put new sources here
    articles/    (optional typed subfolders after processing)
    pdfs/
    transcripts/
  wiki/          agent-owned markdown pages
    Home.md      landing page
    index.md     auto-maintained table of contents
    log.md       chronological ingest history
    _schema.json ingest rules
    entities/    people, projects, products, orgs
    topics/      concepts, themes, patterns
    sources/     one page per ingested source (provenance anchor)
    indexes/     cross-cut indexes
    notes/       free-form pages
```

## Tools

### wiki_init
Idempotent scaffold. Safe to call any time.

```
wiki_init()
```

### wiki_ingest
Ingest a raw file. The file MUST live under `~/fabric/raw/` (drop it in `raw/inbox/` first).

```
wiki_ingest(source_path="/Users/ash/fabric/raw/inbox/karpathy-llm-wiki.md")
```

What happens:
1. A source page is created at `wiki/sources/<slug>.md` with the original path, content hash, and excerpt
2. Up to 4 entity/topic pages are extracted (headings become topics, repeated capitalized phrases become entities)
3. `wiki/index.md` is rebuilt to include the new pages
4. `wiki/log.md` gets an append-only line with timestamp + wikilinks
5. Returns JSON with `pages_created`, `pages_updated`, `links`

### wiki_query
Search the wiki first, raw sources second. Returns paths + snippets.

```
wiki_query(question="LLM Wiki pattern")
```

Prefer this over re-reading raw files — the wiki is the synthesized view.

### wiki_lint
Report broken wikilinks, orphan pages, and pages without source provenance. Read-only.

```
wiki_lint()
```

Run after a batch of ingests to catch structural issues.

## Typical flow

```
# User drops a file into raw/inbox/
wiki_init()                                  # idempotent
wiki_ingest(source_path="~/fabric/raw/inbox/paper.md")
wiki_query(question="compounding artifact")  # find related pages
wiki_lint()                                  # optional health check
```

## Rules

1. Raw files are immutable. Never edit anything under `~/fabric/raw/`.
2. The wiki is agent-owned. You update it via tools, not by hand. Manual edits in Obsidian are fine for the human.
3. Every non-source page must reference at least one source. `wiki_lint` flags this.
4. Use wikilink style `[[folder/slug]]` — no markdown links. Keeps the Obsidian graph clean.
5. Before ingesting, confirm the file is already under `~/fabric/raw/`. The tool rejects paths outside that root.
6. If a source is already in the wiki, re-ingesting updates the existing pages rather than creating duplicates (hash-keyed upsert).

## Entity extraction: LLM with heuristic fallback (v1.1)

When `TOGETHER_API_KEY` is set the tool calls Together's chat endpoint to pick entity/topic candidates. Default model is `meta-llama/Llama-3.1-8B-Instruct-Turbo`; override with `WIKI_LLM_MODEL`. If the key is missing, the network call fails, or the response is malformed, ingest silently falls back to the v1 deterministic heuristic (headings + repeated capitalized phrases) — you still get pages, just cheaper ones. Force the heuristic with `WIKI_LLM_EXTRACTION=0`.

Every ingest response carries `extraction_mode`: `llm`, `heuristic`, `heuristic-no-key`, or `heuristic-fallback`. The same value is written into the source page's frontmatter so the dashboard can show a badge. Your hand-edits on entity/topic pages are preserved across re-ingests (content outside the `ICARUS_GENERATED` markers is never touched).

## Dashboard

The Hermes Dashboard has an `Icarus` view that browses the wiki: page list, search, rendered markdown with clickable wikilinks, source provenance footer. Point the user there after ingesting a few files.
