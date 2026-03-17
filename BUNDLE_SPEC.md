# BundleFabric — Spécification Format Bundle v1.0

## Définition

Un **bundle** est un contexte cognitif exécutable, portable et versionnable.

```
Bundle IA = modèle_preference + RAG_contextualisé + agents/outils + prompts_système + schémas_cognitifs
```

Il N'EST PAS une IA. C'est un contexte chargeable dynamiquement dans DeerFlow.

## Structure de fichiers

```
bundle-<nom>-v<version>/
├── manifest.yaml          OBLIGATOIRE - identité complète du bundle
├── identity/
│   ├── bundle.id          hash SHA-256 du contenu
│   └── bundle.sig         signature ed25519
├── agents/
│   ├── system_prompt.md   OBLIGATOIRE - prompt système de l'agent
│   └── workflows.yaml     workflows DeerFlow
├── rag/
│   ├── doctrine.md        règles fondamentales du domaine
│   ├── cookbook.md        recettes opérationnelles (cas réels)
│   ├── incidents.md       erreurs → causes → solutions (THE GOLD)
│   ├── reference.md       doc officielle filtrée + annotée
│   └── architecture.md    diagrammes + décisions architecturales
├── tools/
│   └── tools.yaml         outils autorisés pour ce bundle
├── policies/
│   └── reasoning_rules.md contraintes de raisonnement
├── memory/
│   └── context_patterns/  patterns appris à l'usage
├── tests/
│   └── scenarios.yaml     scénarios de validation qualité
└── signatures/
    └── bundle.sig         signature complète
```

## manifest.yaml — Spécification complète

```yaml
# === IDENTITÉ ===
id: bundle-{domaine}-{sous-domaine}        # ex: bundle-gtm-debug-woocommerce
version: "1.0.0"                           # semver obligatoire
name: "Titre humain lisible"
description: "Description en 1-2 phrases"

# === MÉTADONNÉES ===
meta:
  domain: analytics                        # domaine principal
  subdomain: ecommerce_tracking            # sous-domaine
  created_by: factory_v1 | human          # créateur
  created_at: "2026-03-16"               # ISO date
  updated_at: "2026-03-16"
  author: "franck"                        # propriétaire
  language: "fr"                          # langue principale

# === CAPACITÉS ===
capabilities:                              # liste de capacités atomiques
  - debug_gtm_tags
  - validate_ga4_events
  - diagnose_pixel_meta

# === CONTEXTE TECHNIQUE ===
context:
  platforms: [wordpress, woocommerce]      # plateformes ciblées
  languages: [javascript, php]            # langages maîtrisés
  tools_required:                         # outils nécessaires
    - browser_inspector
    - tag_validator
  prerequisites: []                       # bundles requis

# === RAG ===
rag:
  engine: qdrant                          # moteur vector DB
  collection: "bundle-gtm-debug"         # nom collection Qdrant
  chunks_count: 847                      # nb chunks indexés
  embedding_model: "nomic-embed-text"    # modèle embeddings
  last_indexed: "2026-03-16"

# === AGENT / RUNTIME ===
agent:
  runtime: deerflow                       # TOUJOURS deerflow pour v4.1
  prompt: "agents/system_prompt.md"
  workflows: "agents/workflows.yaml"
  model_preference:                       # ordre de préférence modèles
    - claude-sonnet-4-5
    - mistral-7b-instruct
    - phi-3-mini
  max_steps: 10
  timeout_seconds: 300

# === TEMPOREL (TPS) ===
temporal:
  status: active                          # active|stable|legacy|archival|experimental
  freshness_score: 1.0                   # 0.0-1.0 (décroît avec temps)
  last_verified: "2026-03-16"
  usage_count: 0                         # incrémenté à chaque usage
  usage_30d: 0
  ecosystem_version: "GTM3/GA4/WC9"     # versions éco-système ciblées
  decay_rate: 0.1                        # perte freshness par mois sans usage

# === SÉCURITÉ ===
security:
  shareable: true                         # peut être partagé
  contains_secrets: false                 # JAMAIS true si shareable
  encryption: none | aes-256-gcm
  public_key: "ed25519:..."
  
# === PERMISSIONS ===
permissions:
  read: public | friends | private
  execute: public | friends | private
  modify: owner
```

## tools.yaml — Format outils

```yaml
tools:
  - id: browser_inspector
    type: browser_automation
    runtime: playwright
    enabled: true
    
  - id: tag_validator
    type: api_call
    endpoint: "http://localhost:18480"  # aio-sandbox
    enabled: true
    
  - id: console_analyzer
    type: code_execution
    sandbox: true
    enabled: true
```

## workflows.yaml — Format DeerFlow

```yaml
name: "GTM Debug Workflow"
steps:
  - id: analyze_intent
    agent: planner
    prompt: "Analyse la demande de debug GTM"
    
  - id: collect_context
    agent: researcher
    tools: [browser_inspector]
    
  - id: diagnose
    agent: analyst
    rag: true
    
  - id: fix
    agent: implementer
    tools: [tag_validator, console_analyzer]
    
  - id: validate
    agent: validator
    tools: [tag_validator]
```

## scenarios.yaml — Format tests

```yaml
scenarios:
  - name: "Créer tag GA4 PageView"
    input: "Comment créer un tag GA4 pageview dans GTM ?"
    expected_capabilities: [debug_gtm_tags]
    min_score: 0.8
    
  - name: "Déboguer pixel Meta"
    input: "Mon pixel Meta ne fire pas sur checkout"
    expected_capabilities: [diagnose_pixel_meta]
    min_score: 0.75
```

## Cycle de vie d'un bundle

```
CREATE → TEST → ACTIVE → LEARNING → UPDATE → version++
                             ↓
                    STABLE (usage régulier)
                             ↓
                    LEGACY (usage déclinant)
                             ↓
                    ARCHIVAL (usage rare mais conservé)
```

**Règle :** jamais de suppression automatique. La longue traîne du savoir est respectée.

## Bundle Score Global

```
BundleScore = TPS × confiance × compatibilité_intent

TPS = (freshness × 0.4) + (usage_frequency × 0.3) + (ecosystem_alignment × 0.3)

Seuils :
  > 0.8  → recommandé
  0.6-0.8 → utilisable avec avertissement
  0.4-0.6 → legacy, demander confirmation
  < 0.4  → archival, usage expert uniquement
```

## Ce qui N'EST JAMAIS dans un bundle

- ❌ API keys, tokens, credentials
- ❌ Méthodes d'appel personnelles
- ❌ Historique personnel d'usage
- ❌ Adresses IP privées / endpoints internes
- ❌ Données personnelles utilisateur
