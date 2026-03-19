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

## Demo

Try the public instance in 30 seconds:

```bash
# Health check — no auth required
curl https://api.bundlefabric.org/health

# Authenticate and resolve an intent
export BF_API_KEY="your_api_key"
TOKEN=$(curl -s -X POST https://api.bundlefabric.org/auth/token \
  -H "Content-Type: application/json" \
  -d "{\"api_key\":\"$BF_API_KEY\"}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('token') or d.get('access_token',''))")

curl -s -X POST https://api.bundlefabric.org/resolve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"How do I check nginx error logs?"}' | python3 -m json.tool
```

→ **Full bilingual walkthrough (FR/EN):** [DEMO.md](./DEMO.md)
→ **WebUI:** [app.bundlefabric.org](https://app.bundlefabric.org)
→ **Demo scripts:** [`demo/demo.sh`](./demo/demo.sh) · [`demo/demo_client.py`](./demo/demo_client.py)

---

## Features

- **Intent extraction** — keyword (instant) + Ollama enrichment (async) + Claude Haiku (Tailscale-only)
- **RAG bundle resolution** — Qdrant vector search, top-K ranked by TPS score
- **SSE streaming** — real-time token streaming via Claude Haiku with bundle system prompt
- **Execution history** — SQLite persistence, replay from WebUI
- **TPS scoring** — auto-incremented `usage_frequency` on every execution
- **Full CRUD** — create, edit, delete bundles from WebUI
- **Multi-user** — JWT auth, admin-managed user accounts
- **GitHub OAuth** — login via GitHub, auto-provision users
- **JWT secret rotation** — admin UI to rotate secret without touching docker-compose

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
| `GITHUB_CLIENT_ID` | — | GitHub OAuth App client ID (optional) |
| `GITHUB_CLIENT_SECRET` | — | GitHub OAuth App client secret (optional) |
| `WEBUI_URL` | `https://app.bundlefabric.org` | WebUI public URL (used in OAuth redirect) |
| `API_URL` | `https://api.bundlefabric.org` | API public URL (used in OAuth callback) |

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
| GET | /auth/oauth/providers | — | List enabled OAuth providers |
| GET | /auth/oauth/github | — | Start GitHub OAuth flow (redirect) |
| GET | /auth/oauth/github/callback | — | GitHub OAuth callback (internal) |
| POST | /admin/jwt/rotate | Admin JWT | Rotate JWT signing secret |

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

## GitHub OAuth

Enable login via GitHub account — users are auto-provisioned on first login with `role: user`.

### Setup

1. **Create a GitHub OAuth App** at `https://github.com/settings/developers`

   | Field | Value |
   |-------|-------|
   | Application name | `BundleFabric` |
   | Homepage URL | `https://app.bundlefabric.org` |
   | Authorization callback URL | `https://api.bundlefabric.org/auth/oauth/github/callback` |

2. **Configure credentials** on the server:

   ```bash
   cat > secrets_vault/github_oauth.json << EOF
   {
     "client_id": "YOUR_CLIENT_ID",
     "client_secret": "YOUR_CLIENT_SECRET"
   }
   EOF
   docker compose --profile phase2 restart bundlefabric-api
   ```

3. **Verify** — the WebUI login modal will show a **Login with GitHub** button.

> **Note:** `github_oauth.json` takes priority over env vars `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`.

### OAuth flow

```
User clicks "Login with GitHub"
    → GET /auth/oauth/github (redirect to github.com with HMAC state nonce)
    → GitHub authorization page
    → GET /auth/oauth/github/callback (code exchange + user lookup/provision)
    → Redirect to app.bundlefabric.org/#oauth_token=JWT&oauth_user=X&oauth_role=Y
    → WebUI reads fragment, stores JWT in localStorage, clears hash
```

### User provisioning

- **Known user** (matched by `github_username` field or username): returns existing role
- **Unknown user**: auto-created with `role: user`, `github_username` stored in `users.json`
- To promote an OAuth user to admin, edit `secrets_vault/users.json` manually


## Phase 3 — P2P Mesh, Signing & Auto-Evolution

### Bundle Signing (ed25519)

Each bundle can be cryptographically signed by its node. Signatures cover `manifest.yaml` (SHA-256 → ed25519).

```bash
# Generate node keypair (one-time)
docker exec bundlefabric-api python3 -c "
import sys; sys.path.insert(0, '/app')
from security.crypto_manager import BundleCryptoManager
cm = BundleCryptoManager()
result = cm.generate_node_keypair()
print('Node ID:', result['node_id'])
"

# Sign a bundle
docker exec bundlefabric-api python3 -c "
import sys; sys.path.insert(0, '/app')
from security.crypto_manager import BundleCryptoManager
from pathlib import Path
cm = BundleCryptoManager()
cm.sign_bundle(Path('/app/bundles/bundle-linux-ops'))
print('Signed ✓')
"

# Check bundle hash + signature status
curl -H "Authorization: Bearer $JWT" \
  https://api.bundlefabric.org/bundles/bundle-linux-ops/hash
# → {"bundle_id":"bundle-linux-ops","hash":"8fc625c1...","signed":true,"node_id":"72b230ecf8414b33"}
```

Keys are stored in `secrets_vault/node_keys/` (private key chmod 600).

---

### Friend Mesh (P2P HTTP Gossip)

BundleFabric uses a lightweight HTTP gossip protocol between nodes. By default the mesh is **disabled** — activate it when you have at least one peer.

**Configure peers** (`friends.yaml` at project root):
```yaml
node_id: "my-node"
peers:
  - url: "https://api.friend.bundlefabric.org"
    name: "Alice Node"
```

**Enable mesh** in `docker-compose.yml`:
```yaml
environment:
  - MESH_ENABLED=true
```

**Mesh API routes:**

| Route | Description |
|-------|-------------|
| `GET /mesh/status` | Node status: enabled, node_id, peer_count |
| `GET /mesh/peers` | Online/offline status of all peers |
| `GET /mesh/bundles` | Advertise local bundles (manifest metadata only, no RAG) |
| `GET /mesh/bundles/{id}/manifest` | Get a specific bundle manifest |
| `POST /mesh/bundles/{id}/request` | Download bundle from peer (verifies signature) |
| `GET /mesh/registry` | Full distributed registry (local + all peers) |

Downloaded bundles are verified against the peer's ed25519 signature before installation. Bundles with invalid signatures are rejected.

---

### Bundle Fusion

Merge two or more bundles into a composite bundle that combines their capabilities and system prompts.

```bash
curl -X POST https://api.bundlefabric.org/bundles/fuse \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"bundle_ids": ["bundle-linux-ops", "bundle-gtm-debug"]}'
# → {"id":"fusion-bundle-gtm-debug-bundle-linux-ops-9aafede0","sources":[...],...}
```

The fusion bundle has:
- **capabilities** = union of all source capabilities (deduplicated)
- **system.md** = concatenation of source prompts with `--- [source_id] ---` separators
- **freshness_score** = average of source scores
- `fusion_sources` field listing source bundle IDs

---

### Meta-Agent (Bundle Fabricant)

The Meta-Agent analyzes execution history to identify unresolved intents and suggests new bundles via Claude Haiku.

```bash
# 1. Analyze history for patterns
curl -X POST https://api.bundlefabric.org/meta/analyze \
  -H "Authorization: Bearer $ADMIN_JWT"
# → {"patterns": [{"pattern": "debug kubernetes pods", "count": 5}], "count": 1}

# 2. Generate bundle suggestions (uses Claude Haiku)
curl -X POST https://api.bundlefabric.org/meta/analyze-and-suggest \
  -H "Authorization: Bearer $ADMIN_JWT"

# 3. Review pending suggestions
curl https://api.bundlefabric.org/meta/suggestions \
  -H "Authorization: Bearer $ADMIN_JWT"

# 4. Create bundle from approved suggestion
curl -X POST https://api.bundlefabric.org/meta/suggestions/{suggestion_id}/create \
  -H "Authorization: Bearer $ADMIN_JWT"
```

Bundles created by the meta-agent have `created_by: meta_agent` in their manifest.
Suggestions are persisted in `data/meta_suggestions.json`.

> **Cost note:** `analyze-and-suggest` calls Claude Haiku (≈500 tokens/suggestion). Use manually.

---

### Factory Health & Rebuild

```bash
# Health report for all bundles
curl https://api.bundlefabric.org/factory/health \
  -H "Authorization: Bearer $ADMIN_JWT"
# → TPS, obsolescence score, age_days, signed status, alerts per bundle

# Health for a single bundle
curl https://api.bundlefabric.org/bundles/bundle-linux-ops/health \
  -H "Authorization: Bearer $JWT"

# Rebuild a bundle's system.md via Claude Haiku
curl -X POST https://api.bundlefabric.org/factory/rebuild/bundle-linux-ops \
  -H "Authorization: Bearer $ADMIN_JWT"
# → {"status":"rebuilt","bundle_id":"bundle-linux-ops","system_md_length":1842}
```

**Obsolescence criteria:** `freshness < 0.3 AND usage_count < 5 AND age > 30 days`

---

### Public Registry

Bundles marked `public: true` in their manifest are exposed without authentication:

```bash
curl https://api.bundlefabric.org/bundles/public
# → {"bundles": [...], "count": 2}
```

The public registry page is live at **[bundlefabric.org](https://bundlefabric.org)**.

To mark a bundle as public, add `public: true` to its `manifest.yaml`.

---

### Phase 3 API Summary

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/bundles/public` | GET | None | List public bundles |
| `/bundles/{id}/hash` | GET | JWT | Bundle SHA-256 hash + signed status |
| `/bundles/{id}/health` | GET | JWT | TPS, obsolescence, age, alerts |
| `/bundles/fuse` | POST | Admin | Merge 2+ bundles into composite |
| `/mesh/status` | GET | None | Mesh node status |
| `/mesh/peers` | GET | None | Peer online/offline status |
| `/mesh/bundles` | GET | None | Advertise local bundles |
| `/mesh/bundles/{id}/manifest` | GET | None | Bundle manifest for peers |
| `/mesh/bundles/{id}/request` | POST | JWT | Download bundle from peer |
| `/mesh/registry` | GET | JWT | Full distributed registry |
| `/meta/analyze` | POST | Admin | Analyze history for patterns |
| `/meta/analyze-and-suggest` | POST | Admin | Analyze + generate suggestions |
| `/meta/suggestions` | GET | Admin | List pending suggestions |
| `/meta/suggestions/{id}/create` | POST | Admin | Create bundle from suggestion |
| `/factory/health` | GET | Admin | All bundles health report |
| `/factory/rebuild/{id}` | POST | Admin | Rebuild system.md via Claude Haiku |

## JWT Secret Rotation

Rotate the JWT signing secret from the admin UI without restarting the container.

> ⚠️ **All existing tokens are immediately invalidated** — all users must re-authenticate.

### Via WebUI
1. Log in as admin → ⚙️ Admin tab → **⚠️ Rotation JWT Secret** section
2. Click **Rotation du secret JWT** → confirm the dialog
3. You are automatically logged out — log back in with your API key

### Via API
```bash
curl -X POST https://api.bundlefabric.org/admin/jwt/rotate \
  -H "Authorization: Bearer $ADMIN_JWT"
# Returns: {"status":"rotated","warning":"all tokens invalidated — all users must re-authenticate","secret_preview":"5835cbaf****"}
```

The new secret is written to `secrets_vault/jwt_secret.txt` which takes priority over the `JWT_SECRET` env var on next startup.

## Security

- JWT tokens expire after 24h — re-authenticate via `POST /auth/token`
- Claude Haiku streaming: **Tailscale-only** (nginx injects `X-Tailscale-Access: 1`)
- API keys and Anthropic key: stored in `secrets_vault/`, chmod 600, excluded from git
- Admin routes require `role: admin` in JWT
- GitHub OAuth: HMAC-signed state nonce (stateless, survives container restarts), 10 min validity
- `GITHUB_CLIENT_SECRET` never exposed in API responses or WebUI
- JWT secret rotation: new 32-byte hex secret persisted to `secrets_vault/jwt_secret.txt`

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-bundle`
3. Add your bundle to `bundles/` following [BUNDLE_SPEC.md](./BUNDLE_SPEC.md)
4. Open a pull request

## License

MIT — see [LICENSE](./LICENSE)
