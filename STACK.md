# BundleFabric — Stack VPS3 Complète

**VPS3 (BundleFabric Server)**
- IP publique : 135.125.196.150
- IP Tailscale : 100.84.103.104
- OS : Debian 12 (6.1.0-44-cloud-amd64)
- Disque : 197G total, 52G utilisé, 138G libre
- Docker : 29.2.1 | Docker Compose : v5.1.0

---

## Services déployés et rôles BundleFabric

### Couche CPU cognitif
| Service | Containers | Port | Rôle BundleFabric |
|---------|-----------|------|-------------------|
| **DeerFlow** | deer-flow-langgraph, deer-flow-gateway, deer-flow-nginx, deer-flow-frontend | **19040** (tailscale) | CPU cognitif — Planner→Agents→Tools→Sandbox. C'est l'exécuteur de bundles. |

### Couche Mémoire & RAG
| Service | Container | Port | Rôle BundleFabric |
|---------|-----------|------|-------------------|
| **Qdrant** | qdrant | **18650** | Vector DB pour RAG de tous les bundles. Stocke embeddings + permet recherche sémantique. |
| **Supabase DB** | supabase-db | — | PostgreSQL pour métadonnées bundles, logs, tâches, mémoire persistante |
| **Supabase Storage** | supabase-storage | — | Stockage binaires bundles (index Qdrant, embeddings.bin) |

### Couche Ingestion & Streaming
| Service | Container | Port | Rôle BundleFabric |
|---------|-----------|------|-------------------|
| **NiFi** | nifi | **18422** | Pipeline d'ingestion : docs bruts → nettoyage → chunking → embeddings |
| **Redpanda** | redpanda | — | Kafka bus : streaming événements bundles, usage scoring en temps réel |
| **Redpanda Console** | redpanda-console | **18510** | Monitoring topics Kafka |

### Couche LLM Local
| Service | Container | Port | Rôle BundleFabric |
|---------|-----------|------|-------------------|
| **Ollama** | ollama | **18630** | LLMs locaux (Mistral-7B, Phi-3, Llama). Génération embeddings + inférence bundles légers |
| **LiteRT** | litert | **18660** | Runtime LLM optimisé (TFLite/Gemma) |

### Couche Interface & Automation
| Service | Container | Port | Rôle BundleFabric |
|---------|-----------|------|-------------------|
| **Open WebUI** | open-webui | **18019** | Interface IA généraliste (accès DeerFlow via Ollama) |
| **OpenClaw** | openclaw | **18857** | Agent IA avancé (Claude Sonnet) — proto-orchestrateur actuel |
| **N8N** | n8n | — | Workflows automation : triggers, pipelines ingestion NiFi→Qdrant |
| **AIO Sandbox** | aio-sandbox | **18480** | Sandbox sécurisé pour exécution code des bundles |

### Couche DevOps
| Service | Container | Port | Rôle BundleFabric |
|---------|-----------|------|-------------------|
| **Gitea** | gitea | — | Git server pour versioning bundles (.bundle files) |
| **Grafana** | grafana | **18720** | Monitoring : usage bundles, TPS scores, performance agents |
| **Portainer** | portainer | **18980** | Gestion Docker containers |
| **Uptime Kuma** | uptime-kuma | **18135** | Monitoring uptime services |

### Couche Sécurité
| Service | Container | Port | Rôle BundleFabric |
|---------|-----------|------|-------------------|
| **Vaultwarden** | vaultwarden | **18197** | Secrets vault (API keys, credentials — jamais dans les bundles) |

---

## Ports à réserver pour BundleFabric App

| Service futur | Port suggéré | Description |
|---------------|-------------|-------------|
| BundleFabric Orchestrator | **19100** | API principale orchestrateur |
| BundleFabric WebUI | **19101** | Interface web BundleFabric |
| Bundle Registry API | **19102** | API registry local bundles |
| Friend Mesh P2P | **19103** | Protocole gossip P2P |

---

## Accès Tailscale vs Public

| Accès | Interface | Usage |
|-------|-----------|-------|
| Tailscale uniquement | 100.84.103.104:443 | Tous les services internes (DeerFlow, Qdrant, etc.) |
| Public (à configurer) | 135.125.196.150:80/443 | bundlefabric.org → WebUI publique |

---

## Nginx configs existantes (Tailscale)
- `deerflow.infra-ia.fr` → 127.0.0.1:19040
- `gitea.infra-ia.fr` → 127.0.0.1:18522
- `grafana.infra-ia.fr` → 127.0.0.1:18720
