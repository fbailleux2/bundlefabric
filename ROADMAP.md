# BundleFabric — Roadmap

## Phase 1 — Infrastructure & Documentation (Mars 2026) ✅ COMPLÈTE

### Objectif
Poser les bases : serveur configuré, domaine opérationnel, documentation complète.

### Jalons
- [x] Analyse PDF BundleFabric V4.1 (238 pages)
- [x] Création structure /opt/bundlefabric sur VPS3
- [x] Documentation technique complète (ARCHITECTURE, BUNDLE_SPEC, STACK)
- [x] Configuration Nginx HTTP bundlefabric.org
- [x] DNS A record @ et www → 135.125.196.150
- [x] Certbot + SSL Let's Encrypt bundlefabric.org
- [x] Page de présentation HTML bundlefabric.org (public registry)
- [x] Premier bundle créé (bundle-linux-ops, bundle-gtm-debug)

### Stack disponible (déjà déployée)
✅ DeerFlow (CPU cognitif)
✅ Qdrant (RAG Vector DB)
✅ Redpanda / Kafka (bus événements)
✅ NiFi (ingestion données)
✅ Ollama (LLMs locaux)
✅ Supabase (PostgreSQL + Auth + Storage)
✅ Gitea (versioning bundles)
✅ Grafana (monitoring)

---

## Phase 2 — Orchestrateur v1 (Mars 2026) ✅ COMPLÈTE

### Objectif
Construire le cerveau de BundleFabric : l'orchestrateur qui transforme une intention humaine en action.

### Jalons
- [x] `orchestrator/intent_engine.py` — extraction NLP + Claude Haiku
- [x] `orchestrator/bundle_resolver.py` — recherche + scoring TPS
- [x] Pipeline complet intention→bundle→Claude Haiku SSE streaming
- [x] `factory/builder.py` — création + scaffold bundles
- [x] `factory/loader.py` — chargement bundles
- [x] `factory/evaluator.py` — TPS + obsolescence + health
- [x] `memory/rag_manager.py` — indexation Qdrant
- [x] WebUI SPA (French, dark theme, auth JWT, admin tab)
- [x] Docker compose phase2 — port 19100
- [x] Nginx HTTPS app.bundlefabric.org + api + bundlefabric.org

### Livraison
- Premier bundle créé automatiquement par la Factory
- Orchestrateur fonctionnel via WebUI ou CLI
- 3 bundles actifs : GTM Debug, WooCommerce Analytics, Linux Ops

---

## Phase 3 — Friend Mesh P2P & Auto-évolution (Mars 2026) ✅ COMPLÈTE

### Objectif
Rendre BundleFabric distribué et auto-améliorant.

### Jalons
- [x] `mesh/friend_mesh.py` — HTTP gossip, discover/advertise/download
- [x] `mesh/bundle_registry.py` — registry distribué JSON
- [x] Signing ed25519 — security/crypto_manager.py (node: 72b230ecf8414b33)
- [x] `factory/fusion.py` — merge capabilities + prompts + TPS
- [x] Meta-Agent fabricant — analyse history → Claude Haiku → suggestions
- [x] TPS auto-incrémenté à chaque exécution via increment_usage()
- [x] Cycle rebuild — POST /factory/rebuild/{id} via Claude Haiku
- [x] API publique — api.bundlefabric.org (HTTPS, JWT, 35+ routes)
- [x] bundlefabric.org — page publique registry (vitrine)

### Livraison
- Réseau P2P fonctionnel entre 2+ nodes
- Auto-création de bundles déclenchée par l'orchestrateur
- Score TPS mis à jour en temps réel

---

## Vision Long Terme (2027+)

- **GitHub du savoir humain** : décentralisé, chiffré, sans abonnement
- **Effet réseau** : communauté de partage de bundles spécialisés
- **Auto-évolution** : BundleFabric fabrique ses propres améliorations
- **Multi-modal** : bundles pour texte, image, audio, vidéo
- **Marchés de niches** : bundle MS-DOS pour passionnés, bundle cuisine moléculaire, etc.

---

## Prochaine action immédiate

```bash
# Sur VPS3 après configuration DNS :
sudo certbot --nginx -d bundlefabric.org -d www.bundlefabric.org
```

DNS à configurer chez le registrar :
- `A @ → 135.125.196.150`
- `A www → 135.125.196.150`
- `A app → 135.125.196.150`
- `A api → 135.125.196.150`
