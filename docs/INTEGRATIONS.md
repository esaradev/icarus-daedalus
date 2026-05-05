# Integrations

icarus-memory is framework-agnostic. Pick the surface that fits your stack.

## Python library

```python
from icarus_memory import IcarusMemory
mem = IcarusMemory(root="~/fabric")
```

Works in any Python codebase. No global state — each `IcarusMemory` instance owns its root.

## MCP server

```bash
icarus-memory serve
```

Stdio by default. `--http <port>` for streamable HTTP. The server reads `ICARUS_FABRIC_ROOT` from the environment.

### Claude Code

Add to `~/.claude/mcp_servers.json`:

```json
{
  "mcpServers": {
    "icarus": {
      "command": "icarus-memory",
      "args": ["serve"],
      "env": { "ICARUS_FABRIC_ROOT": "/Users/you/fabric" }
    }
  }
}
```

### Cursor

Add to `~/.cursor/mcp.json` with the same shape.

### LangChain

LangChain doesn't need a dedicated adapter — install `langchain-mcp-adapters` and point it at the icarus-memory MCP server.

## Hermes

See [`examples/hermes_adapter.py`](../examples/hermes_adapter.py). The adapter wires Hermes' session hooks onto `IcarusMemory.write`, so every Hermes decision/session/note becomes an icarus entry with provenance fields populated.

## Custom agent frameworks

If your framework doesn't speak MCP, the Python API is small enough to wrap directly. Three calls cover the common case:

```python
mem.write(agent=..., type=..., summary=..., evidence=[...], source_tool=...)
mem.recall(query, k=5)
mem.verify(entry_id, note="...")
```
