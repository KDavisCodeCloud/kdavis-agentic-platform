#!/bin/bash
# health-check.sh
# Verifies the platform is correctly configured and ready to run.
# Usage: bash scripts/health-check.sh

set -e

PASS=0
FAIL=0

check() {
  local label=$1
  local result=$2
  if [ "$result" = "ok" ]; then
    echo "  [PASS] $label"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $label — $result"
    FAIL=$((FAIL + 1))
  fi
}

echo ""
echo "KDavis Agentic Platform — Health Check"
echo "======================================="
echo ""

# Python
echo "Python:"
python3 --version > /dev/null 2>&1 && check "python3 available" "ok" || check "python3 available" "not found"
python3 -c "import yaml" > /dev/null 2>&1 && check "pyyaml installed" "ok" || check "pyyaml installed" "run: pip install pyyaml"
python3 -c "import anthropic" > /dev/null 2>&1 && check "anthropic sdk installed" "ok" || check "anthropic sdk installed" "run: pip install anthropic"
python3 -c "import openai" > /dev/null 2>&1 && check "openai sdk installed" "ok" || check "openai sdk installed" "run: pip install openai"

echo ""
echo "Environment:"
[ -n "$ANTHROPIC_API_KEY" ] && check "ANTHROPIC_API_KEY set" "ok" || check "ANTHROPIC_API_KEY set" "export ANTHROPIC_API_KEY=sk-ant-..."
[ -n "$OPENROUTER_API_KEY" ] && check "OPENROUTER_API_KEY set" "ok" || check "OPENROUTER_API_KEY set" "optional — needed for failover"

echo ""
echo "Config files:"
[ -f ".llm/config.yaml" ] && check ".llm/config.yaml" "ok" || check ".llm/config.yaml" "missing"
[ -f ".llm/router.py" ] && check ".llm/router.py" "ok" || check ".llm/router.py" "missing"
[ -f ".llm/fallback.yaml" ] && check ".llm/fallback.yaml" "ok" || check ".llm/fallback.yaml" "missing"

echo ""
echo "Provider configs:"
for p in anthropic openai openrouter ollama azure-openai aws-bedrock google-vertex; do
  [ -f ".llm/providers/$p.yaml" ] && check "$p.yaml" "ok" || check "$p.yaml" "missing"
done

echo ""
echo "Knowledge vault:"
[ -f "knowledge/README.md" ] && check "vault README" "ok" || check "vault README" "missing"
[ -d "knowledge/_templates" ] && check "templates directory" "ok" || check "templates directory" "missing"
[ -f "knowledge/operator/llm-audit.md" ] && check "llm audit log exists" "ok" || check "llm audit log" "not yet created — run router.py first"

echo ""
echo "======================================="
echo "  PASSED: $PASS"
echo "  FAILED: $FAIL"
echo ""
[ $FAIL -eq 0 ] && echo "  Platform ready." || echo "  Fix failures above before running agents."
echo ""
