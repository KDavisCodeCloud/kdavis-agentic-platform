"""
LLM Router — kdavis-agentic-platform
.llm/router.py

Single entry point for ALL LLM calls in the system.
Agents never call provider SDKs directly — they call:
    router.complete(task_type, messages, system_prompt)
"""

import os
import yaml
import time
import logging
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path(__file__).parent / "config.yaml"
PROVIDERS_PATH = Path(__file__).parent / "providers"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [ROUTER] %(message)s")
log = logging.getLogger("llm-router")


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_provider_config(provider_name):
    provider_file = PROVIDERS_PATH / f"{provider_name}.yaml"
    if not provider_file.exists():
        raise FileNotFoundError(f"No provider config found: {provider_file}")
    with open(provider_file) as f:
        return yaml.safe_load(f)


def resolve_model(config, task_type, provider):
    task_tier_map = config.get("task_tier_map", {})
    model_routing = config.get("model_routing", {})
    tier = task_tier_map.get(task_type, "tier_2_standard")
    tier_models = model_routing.get(tier, {})
    model = tier_models.get(provider)
    if not model:
        raise ValueError(f"No model for provider '{provider}' in tier '{tier}'")
    log.info(f"Task '{task_type}' -> '{tier}' -> '{provider}' -> '{model}'")
    return model


def call_anthropic(model, messages, system, max_tokens, temperature):
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=messages,
    )
    return response.content[0].text


def call_openai(model, messages, system, max_tokens, temperature):
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY not set")
    client = OpenAI(api_key=api_key)
    full_messages = [{"role": "system", "content": system}] + messages
    response = client.chat.completions.create(
        model=model, messages=full_messages,
        max_tokens=max_tokens, temperature=temperature,
    )
    return response.choices[0].message.content


def call_openrouter(model, messages, system, max_tokens, temperature):
    from openai import OpenAI
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY not set")
    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/KDavisCodeCloud/kdavis-agentic-platform",
            "X-Title": "KDavis Agentic Platform",
        }
    )
    full_messages = [{"role": "system", "content": system}] + messages
    response = client.chat.completions.create(
        model=model, messages=full_messages,
        max_tokens=max_tokens, temperature=temperature,
    )
    return response.choices[0].message.content


def call_ollama(model, messages, system, max_tokens, temperature):
    from openai import OpenAI
    base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434") + "/v1"
    client = OpenAI(api_key="ollama", base_url=base_url)
    full_messages = [{"role": "system", "content": system}] + messages
    response = client.chat.completions.create(
        model=model, messages=full_messages,
        max_tokens=max_tokens, temperature=temperature,
    )
    return response.choices[0].message.content


PROVIDER_DISPATCH = {
    "anthropic":  call_anthropic,
    "openai":     call_openai,
    "openrouter": call_openrouter,
    "ollama":     call_ollama,
}


def complete(
    task_type,
    messages,
    system_prompt="You are a helpful DevOps platform engineering agent.",
    provider_override=None,
    max_tokens=None,
    temperature=None,
):
    config = load_config()
    budget = config.get("budget_caps", {})
    active_provider = provider_override or config.get("active_provider", "anthropic")
    failover_chain = config.get("failover_chain", ["anthropic", "openrouter", "ollama"])
    attempt_order = [active_provider] + [p for p in failover_chain if p != active_provider]

    last_error = None
    for provider in attempt_order:
        try:
            provider_cfg = load_provider_config(provider)
            if not provider_cfg.get("enabled", False):
                log.info(f"Provider '{provider}' disabled — skipping")
                continue
            model = resolve_model(config, task_type, provider)
            defaults = provider_cfg.get("defaults", {})
            _max_tokens = max_tokens or min(
                defaults.get("max_tokens", 4096),
                budget.get("max_tokens_per_run", 50000)
            )
            _temperature = temperature if temperature is not None else defaults.get("temperature", 0.2)

            log.info(f"Calling '{provider}' model '{model}'")
            start = time.time()

            if provider not in PROVIDER_DISPATCH:
                raise ValueError(f"No dispatch handler for '{provider}'")

            result = PROVIDER_DISPATCH[provider](model, messages, system_prompt, _max_tokens, _temperature)
            elapsed = round(time.time() - start, 2)
            log.info(f"Success — {provider} / {model} / {elapsed}s")
            _write_audit_log(config, provider, model, task_type, elapsed)
            return result

        except Exception as e:
            log.warning(f"Provider '{provider}' failed: {e}")
            last_error = e
            continue

    raise RuntimeError(f"All providers exhausted. Last error: {last_error}")


def _write_audit_log(config, provider, model, task_type, elapsed):
    log_cfg = config.get("logging", {})
    if not log_cfg.get("log_provider_used", True):
        return
    log_path = Path(log_cfg.get("log_destination", "knowledge/operator/llm-audit.md"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"| {timestamp} | {task_type} | {provider} | {model} | {elapsed}s |\n"
    if not log_path.exists():
        with open(log_path, "w") as f:
            f.write("# LLM Audit Log\n\n")
            f.write("| Timestamp | Task Type | Provider | Model | Duration |\n")
            f.write("|-----------|-----------|----------|-------|----------|\n")
    with open(log_path, "a") as f:
        f.write(entry)


if __name__ == "__main__":
    print("Testing LLM Router...\n")
    try:
        response = complete(
            task_type="issue_triage",
            messages=[{"role": "user", "content": "Classify this: 'Pod CrashLoopBackOff on prod-api-deployment'. One sentence."}],
            system_prompt="You are a DevOps triage agent. Classify infrastructure issues briefly.",
        )
        print(f"Response: {response}")
    except Exception as e:
        print(f"Test failed: {e}")
        print("Make sure ANTHROPIC_API_KEY is set.")
