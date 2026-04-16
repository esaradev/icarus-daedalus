"""
Icarus v4 — Self-memory, persistent wiki, and replacement models for Hermes agents.

Remember your work. Train your replacement.

Memory tools:
  fabric_recall        — ranked retrieval from shared fabric
  fabric_write         — write entry with linking, training_value, and handoff fields
  fabric_search        — keyword grep across fabric
  fabric_pending       — work assigned to this agent
  fabric_curate        — set training value (high/normal/low) on an entry

Training tools:
  fabric_export        — export training pairs with quality filtering (high-precision/normal/high-volume)
  fabric_train         — start Together AI fine-tune, registers model in registry
  fabric_train_status  — check job, update registry on completion

Replacement-model tools:
  fabric_models        — list all trained models with eval scores
  fabric_eval          — compare candidate vs base model on fabric-derived eval set
  fabric_switch_model  — activate a replacement model if eval passes threshold
  fabric_rollback_model — emergency rollback to .env.backup

Daily driver:
  fabric_brief         — operational brief: pending, recent work, suggested action
  fabric_telemetry     — retrieval/usage stats: what gets recalled, what gets used
  fabric_wiki_init     — initialize the persistent Obsidian-friendly wiki layer
  fabric_wiki_get_page — read a synthesized wiki page by title
  fabric_wiki_upsert_page — create or update a synthesized wiki page
  fabric_wiki_search   — search across wiki pages
  fabric_wiki_overview — inspect wiki shape and recent changes

Hooks (automatic):
  on_session_start  — loads SOUL, pending handoffs, recent context
  pre_llm_call      — injects relevant memories on topic change
  post_llm_call     — captures high-value decisions (requires outcome indicator)
  on_session_end    — writes best exchange as session entry (skips thin sessions)
"""

import logging

from . import schemas, tools, hooks

logger = logging.getLogger(__name__)


def register(ctx):
    # memory
    ctx.register_tool(name="fabric_recall", toolset="fabric",
                      schema=schemas.FABRIC_RECALL, handler=tools.fabric_recall)
    ctx.register_tool(name="fabric_write", toolset="fabric",
                      schema=schemas.FABRIC_WRITE, handler=tools.fabric_write)
    ctx.register_tool(name="fabric_search", toolset="fabric",
                      schema=schemas.FABRIC_SEARCH, handler=tools.fabric_search)
    ctx.register_tool(name="fabric_pending", toolset="fabric",
                      schema=schemas.FABRIC_PENDING, handler=tools.fabric_pending)
    ctx.register_tool(name="fabric_curate", toolset="fabric",
                      schema=schemas.FABRIC_CURATE, handler=tools.fabric_curate)

    # training
    ctx.register_tool(name="fabric_export", toolset="fabric",
                      schema=schemas.FABRIC_EXPORT, handler=tools.fabric_export)
    ctx.register_tool(name="fabric_train", toolset="fabric",
                      schema=schemas.FABRIC_TRAIN, handler=tools.fabric_train)
    ctx.register_tool(name="fabric_train_status", toolset="fabric",
                      schema=schemas.FABRIC_TRAIN_STATUS, handler=tools.fabric_train_status)

    # replacement models
    ctx.register_tool(name="fabric_models", toolset="fabric",
                      schema=schemas.FABRIC_MODELS, handler=tools.fabric_models)
    ctx.register_tool(name="fabric_eval", toolset="fabric",
                      schema=schemas.FABRIC_EVAL, handler=tools.fabric_eval)
    ctx.register_tool(name="fabric_switch_model", toolset="fabric",
                      schema=schemas.FABRIC_SWITCH_MODEL, handler=tools.fabric_switch_model)
    ctx.register_tool(name="fabric_rollback_model", toolset="fabric",
                      schema=schemas.FABRIC_ROLLBACK_MODEL, handler=tools.fabric_rollback_model)

    # daily driver
    ctx.register_tool(name="fabric_brief", toolset="fabric",
                      schema=schemas.FABRIC_BRIEF, handler=tools.fabric_brief)
    ctx.register_tool(name="fabric_telemetry", toolset="fabric",
                      schema=schemas.FABRIC_TELEMETRY, handler=tools.fabric_telemetry)
    ctx.register_tool(name="fabric_init_obsidian", toolset="fabric",
                      schema=schemas.FABRIC_INIT_OBSIDIAN, handler=tools.fabric_init_obsidian)
    ctx.register_tool(name="fabric_report", toolset="fabric",
                      schema=schemas.FABRIC_REPORT, handler=tools.fabric_report)
    ctx.register_tool(name="fabric_wiki_init", toolset="fabric",
                      schema=schemas.FABRIC_WIKI_INIT, handler=tools.fabric_wiki_init)
    ctx.register_tool(name="fabric_wiki_get_page", toolset="fabric",
                      schema=schemas.FABRIC_WIKI_GET_PAGE, handler=tools.fabric_wiki_get_page)
    ctx.register_tool(name="fabric_wiki_upsert_page", toolset="fabric",
                      schema=schemas.FABRIC_WIKI_UPSERT_PAGE, handler=tools.fabric_wiki_upsert_page)
    ctx.register_tool(name="fabric_wiki_search", toolset="fabric",
                      schema=schemas.FABRIC_WIKI_SEARCH, handler=tools.fabric_wiki_search)
    ctx.register_tool(name="fabric_wiki_overview", toolset="fabric",
                      schema=schemas.FABRIC_WIKI_OVERVIEW, handler=tools.fabric_wiki_overview)

    # hooks
    ctx.register_hook("on_session_start", hooks.on_session_start)
    ctx.register_hook("pre_llm_call", hooks.pre_llm_call)
    ctx.register_hook("post_llm_call", hooks.post_llm_call)
    ctx.register_hook("on_session_end", hooks.on_session_end)

    logger.info("icarus v4 registered (21 tools, 4 hooks)")
