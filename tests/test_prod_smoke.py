"""Unit tests for scripts/prod_smoke.py's bundle parsing -- no network."""
import base64
import importlib.util
import json
import pathlib

_spec = importlib.util.spec_from_file_location(
    "prod_smoke", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "prod_smoke.py"
)
prod_smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prod_smoke)

REF = "abcdefghijklmnopqrst"
OTHER_REF = "zyxwvutsrqponmlkjihg"


def _jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc(claims)}.{'s' * 43}"


def _bundle(url=True, anon_ref=REF, api="https://kdavis-agentic-platform-production.up.railway.app"):
    parts = ['var a="https://' + REF + '.supabase.co";' if url else ""]
    if anon_ref:
        parts.append(f'var k="{_jwt({"role": "anon", "ref": anon_ref, "iss": "supabase"})}";')
    if api:
        parts.append(f'var api="{api}";')
    else:
        parts.append('var api="http://localhost:8000";')
    return "".join(parts)


def test_healthy_bundle_has_no_problems():
    cfg = prod_smoke.find_config(_bundle())
    assert cfg["supabase_refs"] == [REF]
    assert len(cfg["anon_keys"]) == 1
    assert prod_smoke.check_config(cfg) == []


def test_missing_supabase_env_is_caught():
    """The 2026-11-18 failure: neither NEXT_PUBLIC_SUPABASE_* var set on Vercel prod."""
    problems = prod_smoke.check_config(prod_smoke.find_config(_bundle(url=False, anon_ref=None)))
    assert any("NEXT_PUBLIC_SUPABASE_URL" in p for p in problems)
    assert any("NEXT_PUBLIC_SUPABASE_ANON_KEY" in p for p in problems)


def test_service_role_key_is_not_mistaken_for_anon():
    bundle = _bundle(anon_ref=None) + f'var s="{_jwt({"role": "service_role", "ref": REF})}";'
    problems = prod_smoke.check_config(prod_smoke.find_config(bundle))
    assert any("anon key" in p for p in problems)


def test_anon_key_from_another_project_is_caught():
    problems = prod_smoke.check_config(prod_smoke.find_config(_bundle(anon_ref=OTHER_REF)))
    assert any("different Supabase project" in p for p in problems)


def test_localhost_api_fallback_is_caught():
    cfg = prod_smoke.find_config(_bundle(api=None))
    assert cfg["localhost_api"] is True
    assert any("NEXT_PUBLIC_API_URL" in p for p in prod_smoke.check_config(cfg))
