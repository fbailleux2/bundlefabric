# BundleFabric — OS Cognitif v4.1

> **BundleFabric = OS cognitif | DeerFlow = CPU d'intelligence | Bundles = programmes exécutables**

## Vision

BundleFabric est une fabrique locale d'IA spécialisées. Un humain ne fait jamais face à une seule situation nécessitant l'IA — il fait face à des centaines. BundleFabric produit des **bundles** (contextes exécutables spécialisés) adaptés à chaque situation, les stocke, les partage, les fait évoluer.

## Analogie fondatrice

| Informatique classique | BundleFabric |
|------------------------|--------------|
| Linux kernel           | BundleFabric OS |
| Docker                 | Bundle IA    |
| Dockerfile             | Méthodologie |
| Docker Engine          | DeerFlow Runtime |
| Docker Hub             | Friend Mesh P2P |

## Architecture (V4.1 DeerFlow-Native)

```
HUMAIN (intention)
        │
   ORCHESTRATEUR
   BundleFabric
        │
 ┌──────┼──────┐
 │      │      │
Bundles  Mesh  Factory
locaux  P2P  (création)
        │
   DeerFlow Engine
   Planner → Agents → Tools → Sandbox
        │
   Résultat enrichi
```

## Stack VPS3 (135.125.196.150)

| Service | Port | Rôle |
|---------|------|------|
| DeerFlow | 19040 | CPU cognitif (déjà déployé) |
| Qdrant | 18650 | RAG Vector DB |
| Redpanda | 18510 | Bus événements |
| NiFi | 18422 | Ingestion données |
| Ollama | 18630 | LLMs locaux |
| Supabase | — | PostgreSQL + Auth |
| BundleFabric App | 19100 | Orchestrateur (à déployer) |

## Structure du projet

```
/opt/bundlefabric/
├── README.md              ← ce fichier
├── ARCHITECTURE.md        ← architecture détaillée
├── BUNDLE_SPEC.md         ← spécification format bundle
├── ROADMAP.md             ← roadmap 3 phases
├── STACK.md               ← services VPS3 + rôles
├── docker-compose.yml     ← déploiement BundleFabric app
├── docs/                  ← documentation technique
├── bundles/               ← bundles créés / registry local
├── factory/               ← code Bundle Factory
├── orchestrator/          ← code Orchestrateur
├── webui/                 ← interface web
├── nginx/                 ← configs nginx
├── scripts/               ← scripts utilitaires
└── tests/                 ← tests automatiques
```

## Domaine

- **bundlefabric.org** → 135.125.196.150 (VPS3)
- **www.bundlefabric.org** → 135.125.196.150 (VPS3)
- **app.bundlefabric.org** → WebUI BundleFabric
- **api.bundlefabric.org** → DeerFlow API

## Démarrage rapide (Phase 2)

```bash
cd /opt/bundlefabric
docker compose up -d
```

## Sécurité

Les bundles sont **partageables**. Les secrets ne le sont **jamais**.
- `/opt/bundlefabric/bundles/` → partageable
- `/opt/bundlefabric/secrets_vault/` → privé, jamais committé
