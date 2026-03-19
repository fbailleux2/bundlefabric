# BundleFabric — Démonstration / Demo

> **English version below** — [Jump to English ↓](#bundlefabric--demo-en)

---

## BundleFabric — Démonstration (FR)

BundleFabric est un **OS cognitif** : il traduit vos intentions en langage naturel en actions exécutées par des agents IA spécialisés appelés **Bundles**.

```
Intention (langage naturel)
    → IntentEngine (extraction mots-clés + enrichissement Ollama)
    → RAG (recherche vectorielle Qdrant)
    → Bundle selection (score TPS)
    → DeerFlow execution (LLM reasoning + outils)
    → Réponse (streaming SSE)
```

### Instance publique

| Composant | URL |
|-----------|-----|
| API REST  | https://api.bundlefabric.org |
| WebUI     | https://app.bundlefabric.org |
| Docs      | https://bundlefabric.org/docs |

### Prérequis

- `curl` (démonstration bash)
- `python3` + `pip install requests` (démonstration Python)
- Une clé API (contacter l'administrateur ou auto-héberger)

---

### Étape 1 — Santé de l'API

```bash
curl https://api.bundlefabric.org/health
```

Réponse attendue :
```json
{
  "status": "healthy",
  "version": "2.1.0",
  "bundles_loaded": 2,
  "qdrant": "connected",
  "ollama": "connected"
}
```

---

### Étape 2 — Authentification

BundleFabric utilise un système JWT. Échangez votre clé API contre un token :

```bash
export BF_API_KEY="votre_clé_api"

TOKEN=$(curl -s -X POST https://api.bundlefabric.org/auth/token \
  -H "Content-Type: application/json" \
  -d "{\"api_key\": \"$BF_API_KEY\"}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('token') or d.get('access_token', ''))
")

echo "JWT: ${TOKEN:0:40}..."
```

---

### Étape 3 — Lister les Bundles disponibles

Un **Bundle** est un programme cognitif : il combine un manifeste YAML (domaines, capacités, mots-clés) avec des prompts système pour un agent DeerFlow spécialisé.

```bash
curl -s https://api.bundlefabric.org/bundles \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Bundles disponibles sur l'instance publique :

| Bundle ID | Domaine | TPS Score | Description |
|-----------|---------|-----------|-------------|
| `bundle-linux-ops` | Linux / DevOps | 0.885 | Expert Linux, nginx, Docker, systemd |
| `bundle-gtm-debug` | Analytics | 0.829 | Google Tag Manager, GA4, dataLayer |

> **TPS (Temporal Pertinence Score)** = fraîcheur × 0.4 + usage × 0.3 + alignement écosystème × 0.3

---

### Étape 4 — Extraction d'intention

L'IntentEngine analyse le texte et extrait les mots-clés et domaines pertinents :

```bash
curl -s -X POST https://api.bundlefabric.org/intent \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Comment vérifier les logs nginx sur un serveur Linux ?"}' \
  | python3 -m json.tool
```

Réponse :
```json
{
  "keywords": ["nginx", "logs", "linux", "server"],
  "domains": ["linux", "nginx"],
  "confidence": 0.92,
  "method": "keyword+ollama"
}
```

---

### Étape 5 — Résolution de Bundle (RAG + TPS)

BundleFabric recherche dans l'espace vectoriel Qdrant et sélectionne le meilleur Bundle en combinant similarité sémantique et score TPS :

```bash
curl -s -X POST https://api.bundlefabric.org/resolve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Comment vérifier les logs nginx sur un serveur Linux ?"}' \
  | python3 -m json.tool
```

Résultat attendu : `bundle-linux-ops` est sélectionné (domaines linux/nginx correspondent).

---

### Étape 6 — Exécution (DeerFlow)

DeerFlow est le **moteur de raisonnement** (inspiré de LangGraph). Il génère une réponse structurée en utilisant le prompt système du Bundle sélectionné :

```bash
curl -s -X POST https://api.bundlefabric.org/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "bundle_id": "bundle-linux-ops",
    "query": "Montre-moi les 50 dernières lignes des logs nginx"
  }'
```

> ⚠️ **Note performance** : Sur l'instance publique, DeerFlow utilise Ollama avec `qwen2.5:1.5b` sur CPU Haswell. La latence est de 30 à 120 secondes. Pour une expérience fluide, déployez votre propre instance avec un GPU ou une clé API cloud (OpenAI/Anthropic).

---

### Script de démonstration complet

```bash
# Clone le repo
git clone https://github.com/fbailleux2/bundlefabric
cd bundlefabric/demo

# Configure et lance
export BF_API_KEY="votre_clé_api"
./demo.sh
```

Ou avec Python :

```bash
pip install requests
export BF_API_KEY="votre_clé_api"
python demo_client.py
```

---

### WebUI interactive

L'interface web est disponible sur [app.bundlefabric.org](https://app.bundlefabric.org) :

1. Cliquez sur **"Configurer la clé API"** en haut de l'écran
2. Entrez votre clé API → le système s'authentifie automatiquement
3. Tapez votre question dans le champ de saisie
4. BundleFabric sélectionne le meilleur Bundle et génère une réponse

---

### Auto-hébergement

Voir [README.md](./README.md) pour l'installation complète. Résumé :

```bash
git clone https://github.com/fbailleux2/bundlefabric
cd bundlefabric

# Préparer les secrets
mkdir -p secrets_vault
echo '[{"username":"admin","api_key":"bf_admin_CHANGE_ME","role":"admin"}]' \
  > secrets_vault/users.json

# Lancer
docker network create sylvea_net
docker compose --profile phase2 up --build -d
```

---
---

## BundleFabric — Demo (EN)

<a name="bundlefabric--demo-en"></a>

BundleFabric is a **Cognitive OS**: it translates natural language intentions into actions executed by specialized AI agents called **Bundles**.

```
Intent (natural language)
    → IntentEngine (keyword extraction + Ollama enrichment)
    → RAG (Qdrant vector search)
    → Bundle selection (TPS score)
    → DeerFlow execution (LLM reasoning + tools)
    → Response (SSE streaming)
```

### Public Instance

| Component | URL |
|-----------|-----|
| REST API  | https://api.bundlefabric.org |
| WebUI     | https://app.bundlefabric.org |
| Docs      | https://bundlefabric.org/docs |

### Prerequisites

- `curl` (bash demo)
- `python3` + `pip install requests` (Python demo)
- An API key (contact admin or self-host)

---

### Step 1 — API Health Check

```bash
curl https://api.bundlefabric.org/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "2.1.0",
  "bundles_loaded": 2,
  "qdrant": "connected",
  "ollama": "connected"
}
```

---

### Step 2 — Authentication

BundleFabric uses JWT. Exchange your API key for a token:

```bash
export BF_API_KEY="your_api_key"

TOKEN=$(curl -s -X POST https://api.bundlefabric.org/auth/token \
  -H "Content-Type: application/json" \
  -d "{\"api_key\": \"$BF_API_KEY\"}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('token') or d.get('access_token', ''))
")

echo "JWT: ${TOKEN:0:40}..."
```

---

### Step 3 — List Available Bundles

A **Bundle** is a cognitive program: it combines a YAML manifest (domains, capabilities, keywords) with system prompts for a specialized DeerFlow agent.

```bash
curl -s https://api.bundlefabric.org/bundles \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Bundles available on the public instance:

| Bundle ID | Domain | TPS Score | Description |
|-----------|--------|-----------|-------------|
| `bundle-linux-ops` | Linux / DevOps | 0.885 | Linux, nginx, Docker, systemd expert |
| `bundle-gtm-debug` | Analytics | 0.829 | Google Tag Manager, GA4, dataLayer |

> **TPS (Temporal Pertinence Score)** = freshness × 0.4 + usage × 0.3 + ecosystem alignment × 0.3

---

### Step 4 — Intent Extraction

The IntentEngine analyzes text and extracts relevant keywords and domains:

```bash
curl -s -X POST https://api.bundlefabric.org/intent \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "How do I check nginx error logs on a Linux server?"}' \
  | python3 -m json.tool
```

Response:
```json
{
  "keywords": ["nginx", "logs", "linux", "server"],
  "domains": ["linux", "nginx"],
  "confidence": 0.92,
  "method": "keyword+ollama"
}
```

---

### Step 5 — Bundle Resolution (RAG + TPS)

BundleFabric searches the Qdrant vector space and selects the best Bundle by combining semantic similarity with TPS score:

```bash
curl -s -X POST https://api.bundlefabric.org/resolve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "How do I check nginx error logs on a Linux server?"}' \
  | python3 -m json.tool
```

Expected result: `bundle-linux-ops` is selected (linux/nginx domains match).

---

### Step 6 — Execution (DeerFlow)

DeerFlow is the **reasoning engine** (LangGraph-based). It generates a structured response using the selected Bundle's system prompt:

```bash
curl -s -X POST https://api.bundlefabric.org/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "bundle_id": "bundle-linux-ops",
    "query": "Show me the last 50 lines of nginx logs"
  }'
```

> ⚠️ **Performance note**: The public instance runs DeerFlow with Ollama `qwen2.5:1.5b` on a Haswell CPU. Latency is 30-120 seconds. For a smooth experience, deploy your own instance with a GPU or a cloud API key (OpenAI/Anthropic).

---

### Full Demo Script

```bash
# Clone the repo
git clone https://github.com/fbailleux2/bundlefabric
cd bundlefabric/demo

# Set your API key and run
export BF_API_KEY="your_api_key"
./demo.sh
```

Or with Python:

```bash
pip install requests
export BF_API_KEY="your_api_key"
python demo_client.py
```

---

### Interactive WebUI

The web interface is available at [app.bundlefabric.org](https://app.bundlefabric.org):

1. Click **"Configure API Key"** at the top of the screen
2. Enter your API key → the system authenticates automatically
3. Type your question in the input field
4. BundleFabric selects the best Bundle and generates a response

---

### Self-Hosting

See [README.md](./README.md) for full installation. Quick start:

```bash
git clone https://github.com/fbailleux2/bundlefabric
cd bundlefabric

# Prepare secrets
mkdir -p secrets_vault
echo '[{"username":"admin","api_key":"bf_admin_CHANGE_ME","role":"admin"}]' \
  > secrets_vault/users.json

# Launch
docker network create sylvea_net
docker compose --profile phase2 up --build -d
```

---

### Architecture

```
┌─────────────────────────────────────────────────┐
│                   BundleFabric                   │
│                                                  │
│   Intent ──→ IntentEngine ──→ RAG (Qdrant)       │
│                                   │              │
│                              Bundle (TPS)        │
│                                   │              │
│                          DeerFlow (LangGraph)    │
│                                   │              │
│                          Ollama / Cloud LLM      │
└─────────────────────────────────────────────────┘
```

### Creating Your Own Bundle

Bundles are YAML files with a system prompt. Here's a minimal example:

```yaml
# bundles/my-bundle/manifest.yaml
id: my-bundle
name: My Expert Bundle
description: Short description of what this bundle does
domains:
  - my-domain
keywords:
  - keyword1
  - keyword2
capabilities:
  - skill1
  - skill2
```

```
# bundles/my-bundle/prompts/system.md
You are an expert in [domain]. When answering:
- Be concise and precise
- Provide working examples
- Cite sources when relevant
```

Then add it via the API:

```bash
curl -X POST https://api.bundlefabric.org/bundles \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @manifest.json
```

---

*BundleFabric is open-source under the [MIT License](./LICENSE).*
*GitHub: [fbailleux2/bundlefabric](https://github.com/fbailleux2/bundlefabric)*
