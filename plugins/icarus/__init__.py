"""
Icarus Plugin for Hermes
========================

Cross-platform memory, handoff workflows, and self-training
for any Hermes agent. Optimized for multi-agent patterns:
builder->reviewer, researcher->implementer, triage->resolver.

Memory tools:
  fabric_recall        — ranked retrieval from shared fabric
  fabric_write         — write entry with full schema v1 (status, review_of, revises, customer_id, assigned_to)
  fabric_search        — keyword grep across fabric

Workflow tools:
  fabric_pending       — what needs my attention (open tasks, reviews of my work, tickets)

Training tools:
  fabric_export        — export fabric entries as fine-tuning pairs
  fabric_train         — upload + start Together AI fine-tune
  fabric_train_status  — check job status, get output model ID

Hooks (automatic):
  on_session_start  — loads SOUL, pending handoffs, reviews of your work, recent context
  pre_llm_call      — injects relevant memories on topic change
  post_llm_call     — captures decisions with status, tracks learnings/questions
  on_session_end    — writes session summary, updates MEMORY.md
"""

import logging

from . import schemas, tools, hooks

logger = logging.getLogger(__name__)


def register(ctx):
    # memory tools
    ctx.register_tool(name="fabric_recall", toolset="fabric",
                      schema=schemas.FABRIC_RECALL, handler=tools.fabric_recall)
    ctx.register_tool(name="fabric_write", toolset="fabric",
                      schema=schemas.FABRIC_WRITE, handler=tools.fabric_write)
    ctx.register_tool(name="fabric_search", toolset="fabric",
                      schema=schemas.FABRIC_SEARCH, handler=tools.fabric_search)

    # workflow tools
    ctx.register_tool(name="fabric_pending", toolset="fabric",
                      schema=schemas.FABRIC_PENDING, handler=tools.fabric_pending)

    # training tools
    ctx.register_tool(name="fabric_export", toolset="fabric",
                      schema=schemas.FABRIC_EXPORT, handler=tools.fabric_export)
    ctx.register_tool(name="fabric_train", toolset="fabric",
                      schema=schemas.FABRIC_TRAIN, handler=tools.fabric_train)
    ctx.register_tool(name="fabric_train_status", toolset="fabric",
                      schema=schemas.FABRIC_TRAIN_STATUS, handler=tools.fabric_train_status)

    # hooks
    ctx.register_hook("on_session_start", hooks.on_session_start)
    ctx.register_hook("pre_llm_call", hooks.pre_llm_call)
    ctx.register_hook("post_llm_call", hooks.post_llm_call)
    ctx.register_hook("on_session_end", hooks.on_session_end)

    logger.info("icarus plugin registered (7 tools, 4 hooks)")
