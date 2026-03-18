# BundleFabric — Cognitive OS

[![Version](https://img.shields.io/badge/version-2.1.0-7c3aed)](https://github.com/bundlefabric/bundlefabric)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![Docker](https://img.shields.io/badge/docker-compose-blue)](./docker-compose.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue)](./requirements.txt)

BundleFabric is a self-hosted Cognitive OS that maps natural language intentions to specialized AI bundles, executes them via a DeerFlow reasoning engine, and learns from every interaction through a TPS (Temporal Pertinence Score) system.

```
Intent (natural language)
    → IntentEngine (keyword + Ollama + Claude Haiku)
    → RAG (Qdrant vector search)
    → Bundle resolution (TPS scoring)
    → DeerFlow execution (LLM + tools)
    → Result (streamed SSE)
```

## Features

- **Intent extraction** — keyword (instant) + Ollama enrichment (async) + Claude Haiku (Tailscale-only)
- **RAG bundle resolution** — Qdrant vector search, top-K ranked by TPS score
- **SSE streaming** — real-time token streaming via Claude Haiku with bundle system prompt
- **Execution history** — SQLite persistence, replay from WebUI
- **TPS scoring** — auto-incremented `usage_frequency` on every execution
- **Full CRUD** — create, edit, delete bundles from WebUI
- **Multi-user** — JWT auth, admin-managed user accounts

## Quick Start

### Prerequisites

- Docker + Docker Compose
- Docker network `sylvea_net` (shared with Qdrant, Ollama, DeerFlow)
- Optional: Qdrant + Ollama containers on `sylvea_net`
- Optional: Anthropic API key for Claude Haiku

### Create the Docker network

```bash
docker network create sylvea_net
```

### Configure secrets

```bash
# Generate a secure API key
python3 -c "import secrets; print('bf_admin_' + secrets.token_hex(24))"

# Set up users
echo '[{"username": "admin", "api_key": "bf_admin_GENERATED_KEY", "role": "admin"}]' > secrets_vault/users.json

# Anthropic key (optional)
echo "YOUR_ANTHROPIC_API_KEY" > secrets_vault/anthropic_key.txt

chmod 600 secrets_vault/users.json secrets_vault/anthropic_key.txt
```

### Launch

```bash
git clone ssh://vps3/opt/git/bundlefabric.git
cd bundlefabric
docker compose --profile phase2 up --build -d
```

API live at `http://127.0.0.1:19100`

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | `change_me` | JWT signing secret — **change in production** |
| `USERS_FILE` | `/app/secrets_vault/users.json` | User store path |
| `ANTHROPIC_KEY_FILE` | `/app/secrets_vault/anthropic_key.txt` | Claude Haiku key |
| `USE_OLLAMA` | `true` | Enable Ollama enrichment |
| `OLLAMA_URL` | `http://ollama:11434` | Ollama endpoint (container DNS) |
| `OLLAMA_MODEL` | `qwen2.5:1.5b` | Ollama model name |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant endpoint (container DNS) |
| `DEERFLOW_URL` | `http://deer-flow-gateway:8001` | DeerFlow gateway |
| `HISTORY_DB` | `/app/data/history.db` | SQLite history DB path |

## API Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /health | — | Health check |
| GET | /status | — | Full system status |
| POST | /auth/token | — | Exchange API key → JWT (24h) |
| GET | /bundles | — | List all bundles |
| GET | /bundles/{id} | — | Bundle details |
| POST | /bundles/create | JWT | Create bundle |
| PUT | /bundles/{id} | JWT | Update bundle fields |
| DELETE | /bundles/{id} | JWT | Delete bundle |
| POST | /intent | — | Extract structured intent |
| POST | /resolve | — | Resolve best bundles |
| POST | /execute | JWT | Execute bundle (sync) |
| POST | /execute/stream | JWT + Tailscale | Execute bundle (SSE streaming) |
| GET | /history | — | Execution history (last 50) |
| GET | /history/{id} | — | Single execution record |
| GET | /admin/users | Admin JWT | List users |
| POST | /admin/users | Admin JWT | Create user |
| DELETE | /admin/users/{username} | Admin JWT | Delete user |
| GET | /deerflow/status | — | DeerFlow health |

## Bundle Format

```
bundles/
  bundle-linux-ops/
    manifest.yaml       # Bundle definition + TPS config
    prompts/
      system.md         # Expert system prompt injected at execution
```

```yaml
id: bundle-linux-ops
version: 1.0.0
name: Linux Operations Expert
description: Comprehensive Linux system administration expert.
capabilities:
  - bash-scripting
  - linux-sysadmin
temporal:
  status: active
  freshness_score: 0.9
  usage_frequency: 0.0
  ecosystem_alignment: 0.9
  usage_count: 0
```

See [BUNDLE_SPEC.md](./BUNDLE_SPEC.md) for the full bundle specification.

## TPS Score

**TPS = freshness × 0.4 + usage_frequency × 0.3 + ecosystem_alignment × 0.3**

| Field | Set by | Description |
|-------|--------|-------------|
| `freshness_score` | Manual | How current the bundle content is (0.0–1.0) |
| `usage_frequency` | Auto | Incremented logarithmically on each execution |
| `ecosystem_alignment` | Manual | Alignment with current ecosystem trends |
| `usage_count` | Auto | Raw execution counter |

## Add a User

### Via WebUI (Admin tab)
1. Log in as admin → ⚙️ Admin tab appears
2. Fill in username + select role → click **Créer**
3. Copy the generated API key — shown once, not stored in clear

### Via API
```bash
curl -X POST https://api.bundlefabric.org/admin/users \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "role": "user"}'
# Returns: {"username": "alice", "api_key": "bf_alice_...", "role": "user"}
```

### Manually
Edit `secrets_vault/users.json` and restart the container (or call `POST /admin/users/reload`).

## Security

- JWT tokens expire after 24h — re-authenticate via `POST /auth/token`
- Claude Haiku streaming: **Tailscale-only** (nginx injects `X-Tailscale-Access: 1`)
- API keys and Anthropic key: stored in `secrets_vault/`, chmod 600, excluded from git
- Admin routes require `role: admin` in JWT

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-bundle`
3. Add your bundle to `bundles/` following [BUNDLE_SPEC.md](./BUNDLE_SPEC.md)
4. Open a pull request

## License

MIT — see [LICENSE](./LICENSE)
