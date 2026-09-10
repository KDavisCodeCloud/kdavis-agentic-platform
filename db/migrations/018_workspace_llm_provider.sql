-- Migration 018: workspaces.llm_provider
--
-- api/routes/workspaces.py's new POST /api/v1/workspaces/llm-key lets a
-- customer pick Anthropic or OpenAI when they submit their BYOK key.
-- Without a place to remember which provider goes with the encrypted key
-- already stored in workspaces.encrypted_llm_key, nothing downstream could
-- tell which SDK the key belongs to. Wiring something to actually read this
-- column and pass it as provider_override into agent LLM calls is separate,
-- not-yet-done follow-up work (agents/base_agent.py currently defaults to
-- "anthropic" unless a caller explicitly overrides).

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS llm_provider VARCHAR(20) NOT NULL DEFAULT 'anthropic';
