# Changelog

## 0.1.0 (unreleased)

Initial release.

### Decisions

- Embeddings are an optional extra: `pip install 'icarus-memory[embeddings]'`. Default install is light. `recall(mode="auto")` falls back to keyword when the extra isn't present.
- Pydantic v2 for the data model. One system end-to-end (validation, JSON for MCP, YAML round-trip).
- MCP transports: stdio (default) + streamable HTTP. SSE is deprecated upstream and not supported.
- Entry IDs use 12 hex chars (48 bits) instead of 8, with retry-on-collision. ~280 trillion before birthday risk.
- No `langchain_adapter.py` example. LangChain memory interfaces are in flux; the MCP server covers the same use case via `langchain-mcp-adapters` upstream.
- Embedding cache key includes the model name, so switching models doesn't silently serve stale vectors.
- Filenames use `icarus-<id>.md` (no colon) for Windows compatibility. The `id` field inside the frontmatter keeps the canonical `icarus:<id>` form.
