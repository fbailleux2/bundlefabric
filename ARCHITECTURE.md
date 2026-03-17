# BundleFabric — Architecture Technique Complète

## 1. Vue d'ensemble — Les 5 couches

### Layer 1 — Interface Humaine
```
WebUI (React/Svelte) | CLI | WhatsApp | Discord | API REST | IoT
```
Point d'entrée : l'intention humaine (pas un outil, pas une commande).

### Layer 2 — Orchestrateur BundleFabric (cerveau décisionnel)

Le seul composant permanent du système. Il :
1. **Comprend** l'intention humaine (NLP + extraction structurée)
2. **Cherche** les bundles existants (registry local + Friend Mesh P2P)
3. **Décide** : utiliser / fusionner / créer
4. **Délègue** à DeerFlow pour l'exécution

```python
# Pipeline orchestrateur
class Orchestrator:
    def process(self, human_input: str) -> Result:
        intent = self.extract_intent(human_input)
        # intent = {goal, domains, tools, complexity, user_level}
        
        bundle = self.resolve_bundle(intent)
        # 1. Search local registry
        # 2. Query Friend Mesh
        # 3. If not found → trigger Factory
        
        return self.execute_via_deerflow(bundle, intent)
```

### Layer 3 — Bundle System

Un **bundle** = contexte cognitif exécutable et portable.

```
bundle-gtm-debug-v1.2/
├── manifest.yaml          ← identité + capacités + métadonnées temporelles
├── identity/
│   └── bundle.id          ← hash + signature publique
├── agents/
│   └── workflows.yaml     ← définition workflows DeerFlow
├── rag/
│   ├── doctrine.md        ← règles fondamentales du domaine
│   ├── cookbook.md        ← recettes opérationnelles
│   ├── incidents.md       ← historique erreurs→solutions
│   ├── reference.md       ← doc officielle filtrée + annotée
│   └── architecture.md    ← structure réelle + décisions
├── tools/
│   └── tools.yaml         ← outils autorisés
├── policies/
│   └── reasoning_rules.md ← règles de raisonnement
├── memory/
│   └── context_patterns/  ← patterns appris à l'usage
├── tests/
│   └── scenarios.yaml     ← scénarios de validation
└── signatures/
    └── bundle.sig         ← signature ed25519
```

### Layer 4 — DeerFlow Engine (CPU cognitif)

DeerFlow est le moteur d'exécution. **Il ne décide pas — il exécute.**

```
Bundle chargé
    │
DeerFlow Planner
    │    (décompose la tâche en étapes)
    │
DeerFlow Agents
    │    (agents spécialisés parallèles)
    │
DeerFlow Tools
    │    (browser, code executor, search, APIs)
    │
DeerFlow Sandbox
    │    (exécution sécurisée)
    │
Résultat structuré
```

Services DeerFlow sur VPS3 :
- `deer-flow-langgraph` (port interne) — moteur LangGraph
- `deer-flow-gateway` — API gateway
- `deer-flow-nginx` → 19040 — proxy nginx
- `deer-flow-frontend` — interface web

### Layer 5 — Bundle Factory (usine)

```
Collecte (sources)
    → NiFi ingestion
    → Nettoyage + normalisation
    → Chunking intelligent
    → Embeddings (Ollama)
    → Indexation Qdrant
    → Génération agent (prompts + workflows)
    → Tests automatiques (scénarios)
    → Packaging (.bundle)
    → Versioning (Gitea)
    → Publication (registry local + P2P optionnel)
```

## 2. Flux de traitement complet

```
HUMAIN: "Je veux déboguer mes conversions WooCommerce dans GTM"
                    │
         ORCHESTRATEUR
         intent = {
           goal: debug_tracking
           domains: [GTM, WooCommerce, GA4]
           complexity: medium
         }
                    │
         ┌──────────┼──────────┐
         ↓          ↓          ↓
    Registry     Friend      Factory
    local        Mesh        (si vide)
    bundle-gtm   bundle?     → crée
    82% match               bundle-gtm
                    │
         Bundle sélectionné
                    │
         DeerFlow Engine charge bundle
         (mount RAG Qdrant + attach tools + load workflows)
                    │
         Exécution Planner→Agents→Tools→Sandbox
                    │
         Résultat structuré → HUMAIN
                    │
         Bundle scoring mis à jour (usage+1, pertinence mesurée)
```

## 3. Format Manifest YAML (bundle complet)

```yaml
# manifest.yaml
id: bundle-gtm-debug-woocommerce
version: 1.2.0
meta:
  domain: analytics
  subdomain: ecommerce_tracking
  created_by: factory_v1
  created_at: 2026-03-16
  author: franck
  description: "Debug complet tracking GTM/GA4 pour WooCommerce"

capabilities:
  - debug_gtm_tags
  - validate_ga4_events
  - diagnose_pixel_meta
  - fix_checkout_tracking

context:
  platforms: [wordpress, woocommerce, google_tag_manager]
  languages: [javascript, php]
  requires_tools: [browser_inspector, tag_validator, console_analyzer]

rag:
  index: rag/index.qdrant
  embeddings: rag/embeddings.bin
  chunks_count: 847

agent:
  runtime: deerflow
  prompt: agents/system_prompt.md
  workflows: agents/workflows.yaml
  model_preference: [claude-sonnet, mistral-7b]

temporal:
  freshness_score: 0.92
  last_verified: 2026-03-16
  usage_count: 0
  ecosystem_version: GTM3/GA4/WC9
  status: active  # active | stable | legacy | archival | experimental

security:
  shareable: true
  contains_secrets: false
  public_key: "ed25519:..."
  signature: "bundle.sig"

permissions:
  read: public
  modify: owner
  execute: public
```

## 4. Temporal Relevance Score (TPS)

```
TPS = (freshness × 0.4) + (usage_frequency × 0.3) + (ecosystem_alignment × 0.3)

freshness = 1 - (days_since_verified / 365)
usage_frequency = min(usage_count / 1000, 1)
ecosystem_alignment = compatibility_with_current_stack
```

Exemple :
- Bundle MS-DOS → TPS ≈ 0.05 (archival, niche)
- Bundle GTM GA4 2026 → TPS ≈ 0.91 (active, haute demande)

## 5. Friend Mesh P2P

```
Protocole : gossip protocol (inspiré BitTorrent + IPFS)

Node A (franck) ─┐
Node B (alice)  ─┼── gossip discovery
Node C (coop)   ─┘

Partage : manifest.yaml uniquement (pas le contenu RAG)
Hash de vérification : SHA-256 + signature ed25519
Contenu téléchargé après consentement explicite

friends.yaml :
  - alice.bundlefabric.local
  - coop-artisans.bundlefabric.local
```

## 6. Architecture des composants Python

| Fichier | Rôle |
|---------|------|
| `orchestrator/orchestrator.py` | Analyse intention + décision bundle |
| `orchestrator/intent_engine.py` | Extraction NLP de l'intention |
| `orchestrator/bundle_resolver.py` | Recherche + scoring bundles |
| `factory/builder.py` | Création nouveaux bundles |
| `factory/loader.py` | Chargement et validation bundles |
| `factory/fusion.py` | Fusion multi-bundles |
| `factory/evaluator.py` | Score pertinence + obsolescence |
| `factory/packager.py` | Export .bundle portable |
| `memory/rag_manager.py` | Interface Qdrant + embeddings |
| `memory/memory_manager.py` | Persistance tâches + historique |
| `security/crypto_manager.py` | Clés ed25519 + chiffrement AES-256 |
| `mesh/friend_mesh.py` | P2P discovery + téléchargement |
| `monitoring/monitoring.py` | Métriques + alertes Grafana |

## 7. Sécurité by design

```
Bundle (PARTAGEABLE)          Runtime (PRIVÉ)
├── manifest.yaml             ├── secrets_vault/
├── rag/ (knowledge)          ├── .env (API keys)
├── agents/ (workflows)       ├── credentials/
├── policies/                 └── usage_history/
└── signatures/
```

**Règle absolue :** jamais de secrets dans un bundle.
