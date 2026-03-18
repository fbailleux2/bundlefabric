# BundleFabric MCP Server

Connect Claude Desktop (or any MCP client) directly to BundleFabric.
Discover and execute AI bundles from your conversations.

## Tools available

| Tool | Description |
|------|-------------|
| `list_bundles` | List all bundles with TPS scores and capabilities |
| `get_bundle` | Full manifest for a specific bundle |
| `execute_bundle` | Run a bundle against a natural-language intent |
| `system_status` | Aggregated health: API + DeerFlow + Ollama |

## Quickstart

### 1. Install

```bash
cd mcp/
pip install -e .
```

### 2. Set your API key

```bash
export BF_API_KEY=bf_<user>_<hex>
```

Get your key from the BundleFabric admin at `https://api.bundlefabric.org/admin/users`
or from the secrets vault on VPS3: `/opt/bundlefabric/secrets_vault/users.json`

### 3. Test the server

```bash
# Should print the list of tools and exit cleanly
python -m bundlefabric_mcp --help
```

### 4. Configure Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bundlefabric": {
      "command": "python",
      "args": ["-m", "bundlefabric_mcp"],
      "cwd": "/path/to/bundlefabric/mcp",
      "env": {
        "BF_API_KEY": "bf_<user>_<hex>",
        "BF_API_URL": "https://api.bundlefabric.org",
        "PYTHONPATH": "/path/to/bundlefabric/mcp/src"
      }
    }
  }
}
```

Replace `/path/to/bundlefabric` with your local clone path (e.g. `/Users/franck/git-work/bundlefabric`).

Restart Claude Desktop after saving. The BundleFabric tools will appear in Claude's tool panel.

### 5. Configure Cursor / VS Code (MCP extension)

```json
{
  "mcp": {
    "servers": {
      "bundlefabric": {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "bundlefabric_mcp"],
        "cwd": "/path/to/bundlefabric/mcp",
        "env": {
          "BF_API_KEY": "bf_<user>_<hex>",
          "PYTHONPATH": "/path/to/bundlefabric/mcp/src"
        }
      }
    }
  }
}
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BF_API_KEY` | *(required)* | Your BundleFabric API key |
| `BF_API_URL` | `https://api.bundlefabric.org` | BundleFabric API base URL |
| `BF_TRANSPORT` | `stdio` | MCP transport: `stdio` or `sse` |
| `BF_LOG_LEVEL` | `INFO` | Logging level |

## Development

```bash
cd mcp/

# Install in editable mode with dev extras
pip install -e ".[dev]"

# Run the server manually (stdio — type JSON to interact)
BF_API_KEY=bf_... python -m bundlefabric_mcp

# Verify tools are exposed
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | \
  BF_API_KEY=bf_... python -m bundlefabric_mcp
```

## Architecture

```
mcp/
├── pyproject.toml                  # deps: fastmcp, httpx, pydantic-settings
├── __main__.py                     # python -m bundlefabric_mcp entry point
├── README.md
└── src/
    └── bundlefabric_mcp/
        ├── __init__.py
        ├── config.py               # Settings (pydantic-settings, BF_ prefix)
        ├── auth.py                 # JWT auto-refresh manager
        ├── client.py               # Async httpx wrapper for BF REST API
        └── server.py               # FastMCP server + 4 tools
```

## Phase 2 / SSE transport

For remote MCP access (Cursor, custom agents), set `BF_TRANSPORT=sse` and run:

```bash
BF_API_KEY=bf_... BF_TRANSPORT=sse uvicorn bundlefabric_mcp.server:mcp --port 8080
```

Configure clients with `"type": "sse"` and `"url": "http://localhost:8080/sse"`.
