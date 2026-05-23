# Lesson — LLM Abstraction Layer First

**Date:** 2026-05-23
**Phase:** Platform Build — Priority 1

## What Was Decided
Built the LLM abstraction layer before any agents or workflows.
All LLM calls route through .llm/router.py — no agent touches a provider SDK directly.

## Why It Matters
- Swapping providers is a config change, not a code rewrite
- Clients with existing Azure OpenAI or AWS Bedrock agreements plug in without rebuilding
- Failover chain (Anthropic → OpenRouter → Ollama) proved in live test
- Budget caps prevent runaway agent cost

## Proof
Live test routed issue_triage → tier_2_standard → claude-haiku-4-5.
Failover exercised through all three providers when credits were exhausted.
Response: "The pod is repeatedly crashing and restarting; investigate container logs, resource limits, and application health checks immediately."

## What to Tell Clients
"The system is not locked to any AI vendor. If you have an existing Azure OpenAI agreement,
we plug into it. If Anthropic changes pricing, we reroute in minutes, not weeks."
