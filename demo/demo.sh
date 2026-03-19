#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║          BundleFabric — API Demo Script (curl)                   ║
# ║  Demonstrates: auth → list bundles → intent → bundle resolution  ║
# ╚══════════════════════════════════════════════════════════════════╝
#
# Usage:
#   export BF_API_KEY="your_api_key_here"
#   chmod +x demo.sh && ./demo.sh
#
# Public instance:  https://api.bundlefabric.org
# WebUI:            https://app.bundlefabric.org

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE="${BF_API_URL:-https://api.bundlefabric.org}"
API_KEY="${BF_API_KEY:-}"

if [[ -z "$API_KEY" ]]; then
  echo "❌ BF_API_KEY is not set."
  echo "   Set it with: export BF_API_KEY=your_api_key_here"
  exit 1
fi

# ── Colors ────────────────────────────────────────────────────────────────────
CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RESET='\033[0m'
BOLD='\033[1m'

sep() { echo -e "${CYAN}────────────────────────────────────────${RESET}"; }
step() { echo -e "\n${BOLD}${YELLOW}▶ $1${RESET}"; }

# ── Step 1: Health check ──────────────────────────────────────────────────────
sep
echo -e "${BOLD}BundleFabric API Demo${RESET}"
sep

step "1/5 — Health check"
HEALTH=$(curl -sf "${API_BASE}/health" | python3 -m json.tool)
echo "$HEALTH"

# ── Step 2: Authenticate → get JWT ───────────────────────────────────────────
step "2/5 — Authentication (API key → JWT token)"
AUTH_RESP=$(curl -sf -X POST "${API_BASE}/auth/token" \
  -H "Content-Type: application/json" \
  -d "{\"api_key\": \"${API_KEY}\"}")

TOKEN=$(echo "$AUTH_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token') or json.load(open('/dev/stdin'))['access_token'])" 2>/dev/null || \
  echo "$AUTH_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('token', d.get('access_token','')))")

if [[ -z "$TOKEN" ]]; then
  echo "❌ Authentication failed. Check your API key."
  echo "Response: $AUTH_RESP"
  exit 1
fi
echo -e "${GREEN}✓ JWT obtained${RESET} (${#TOKEN} chars)"

# ── Step 3: List bundles ──────────────────────────────────────────────────────
step "3/5 — List available bundles"
BUNDLES=$(curl -sf "${API_BASE}/bundles" \
  -H "Authorization: Bearer ${TOKEN}")
echo "$BUNDLES" | python3 -c "
import sys, json
data = json.load(sys.stdin)
bundles = data if isinstance(data, list) else data.get('bundles', [])
print(f'  Found {len(bundles)} bundle(s):')
for b in bundles:
    tps = b.get('tps_score', b.get('temporal', {}).get('usage_frequency', '?'))
    print(f\"  • {b.get('id','?'):30s}  TPS={tps:.3f}  — {b.get('description','?')[:60]}\")
" 2>/dev/null || echo "$BUNDLES" | python3 -m json.tool

# ── Step 4: Intent extraction ─────────────────────────────────────────────────
step "4/5 — Intent extraction"
QUERY="How do I check nginx error logs on a Linux server?"
echo "  Query: \"${QUERY}\""

INTENT=$(curl -sf -X POST "${API_BASE}/intent" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"${QUERY}\"}")
echo "$INTENT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  Keywords : {d.get('keywords', [])}\")
print(f\"  Domains  : {d.get('domains', [])}\")
print(f\"  Confidence: {d.get('confidence', '?')}\")
" 2>/dev/null || echo "$INTENT" | python3 -m json.tool

# ── Step 5: Bundle resolution ─────────────────────────────────────────────────
step "5/5 — Bundle resolution (RAG + TPS scoring)"
RESOLVE=$(curl -sf -X POST "${API_BASE}/resolve" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"${QUERY}\"}")
echo "$RESOLVE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
bundle = d.get('bundle') or d.get('resolved_bundle') or d
bid = bundle.get('id', bundle.get('bundle_id', '?')) if isinstance(bundle, dict) else d.get('bundle_id','?')
score = bundle.get('tps_score', bundle.get('score', d.get('tps_score','?'))) if isinstance(bundle, dict) else d.get('tps_score','?')
print(f'  ✓ Resolved → bundle: {bid}')
print(f'    TPS score: {score}')
print(f'    Method: RAG vector search + TPS ranking')
" 2>/dev/null || echo "$RESOLVE" | python3 -m json.tool

# ── Summary ───────────────────────────────────────────────────────────────────
sep
echo -e "${GREEN}${BOLD}✓ Demo complete!${RESET}"
echo ""
echo "  Next steps:"
echo "  • WebUI → https://app.bundlefabric.org"
echo "  • Full docs → https://bundlefabric.org/docs"
echo "  • Execute a bundle → POST ${API_BASE}/execute"
echo ""
echo "  Note: DeerFlow execution uses a local LLM (Ollama). On CPU-only"
echo "  hardware, responses may take 30-60 seconds. A GPU or cloud API"
echo "  key (OpenAI/Anthropic) significantly improves response time."
sep
