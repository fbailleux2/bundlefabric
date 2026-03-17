# BundleFabric — Roadmap

## Phase 1 — Infrastructure & Documentation (Mars 2026) ✅ EN COURS

### Objectif
Poser les bases : serveur configuré, domaine opérationnel, documentation complète.

### Jalons
- [x] Analyse PDF BundleFabric V4.1 (238 pages)
- [x] Création structure /opt/bundlefabric sur VPS3
- [x] Documentation technique complète (ARCHITECTURE, BUNDLE_SPEC, STACK)
- [x] Configuration Nginx HTTP bundlefabric.org
- [ ] DNS A record @ et www → 135.125.196.150
- [ ] Certbot + SSL Let's Encrypt bundlefabric.org
- [ ] Page de présentation HTML bundlefabric.org
- [ ] Premier bundle de test créé manuellement

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

## Phase 2 — Orchestrateur v1 (Avril 2026)

### Objectif
Construire le cerveau de BundleFabric : l'orchestrateur qui transforme une intention humaine en action.

### Jalons
- [ ] `orchestrator/intent_engine.py` — extraction NLP d'intention
- [ ] `orchestrator/bundle_resolver.py` — recherche + scoring bundles (registry local)
- [ ] `orchestrator/orchestrator.py` — pipeline complet intention→bundle→DeerFlow
- [ ] `factory/builder.py` — création automatique bundle depuis sources
- [ ] `factory/loader.py` — chargement bundle dans DeerFlow
- [ ] `factory/evaluator.py` — calcul TPS score
- [ ] `memory/rag_manager.py` — indexation Qdrant
- [ ] Interface WebUI basique (React ou Svelte)
- [ ] Docker compose BundleFabric app (port 19100)
- [ ] Nginx HTTPS app.bundlefabric.org

### Livraison
- Premier bundle créé automatiquement par la Factory
- Orchestrateur fonctionnel via WebUI ou CLI
- 3 bundles actifs : GTM Debug, WooCommerce Analytics, Linux Ops

---

## Phase 3 — Friend Mesh P2P & Auto-évolution (Juin 2026)

### Objectif
Rendre BundleFabric distribué et auto-améliorant.

### Jalons
- [ ] `mesh/friend_mesh.py` — protocole gossip P2P
- [ ] `mesh/bundle_registry.py` — index distribué de bundles
- [ ] Partage sécurisé de bundles (manifest only + signature ed25519)
- [ ] `factory/fusion.py` — fusion automatique multi-bundles
- [ ] Meta-Agent fabricant (orchestrateur qui crée ses propres spécialisations)
- [ ] Temporal scoring automatique (TPS mis à jour à chaque usage)
- [ ] Cycle learn → rebuild automatique
- [ ] API publique REST bundlefabric.org/api
- [ ] Page publique registry bundles (bundlefabric.org)

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
