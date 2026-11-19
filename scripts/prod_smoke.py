#!/usr/bin/env python3
"""
Post-deploy production smoke test for theclouddecoded.com.

Born from 2026-11-18: PR #11 shipped Supabase login/signup, but Vercel
production had no NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY, so every visitor
would have hit "not configured". Nothing failed: the build passed, the
pages returned 200, and nobody noticed until a manual check.

This checks what a real visitor gets, read from the live site itself:
  1. /signup and /login return 200 and render their email + password fields.
  2. The JavaScript those pages ship has a Supabase project URL and an anon
     key baked in (role=anon, same project), and an API URL that isn't the
     localhost fallback.
  3. Supabase's password-login endpoint answers a sign-in for a random,
     nonexistent address with 400 invalid_credentials. That proves the
     baked-in URL and key are accepted, without creating an account or
     sending an email.
  4. The API those pages call is up (/health, /health/db), and the signup
     endpoint answers an empty body with 422 (route alive, nothing created).

No secrets: everything it needs is public, taken from the pages.
Stdlib only. Exits 1 with a list of every failed check.

  python scripts/prod_smoke.py [--base https://theclouddecoded.com]
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.request

UA = {"User-Agent": "cloud-decoded-prod-smoke"}
SUPABASE_URL_RE = re.compile(r"https://([a-z0-9]{20})\.supabase\.co")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
CHUNK_RE = re.compile(r"""/_next/static/[^"'\s]+?\.js""")
API_URL_RE = re.compile(r"https://[a-z0-9.-]+\.up\.railway\.app")


def http(method: str, url: str, body: dict | None = None, headers: dict | None = None,
         retries: int = 3) -> tuple[int, str]:
    """One request -> (status, text). Retries network errors and 5xx only."""
    data = json.dumps(body).encode() if body is not None else None
    h = dict(UA, **(headers or {}))
    if data is not None:
        h["Content-Type"] = "application/json"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method),
                                        timeout=20) as r:
                return r.status, r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == retries - 1:
                return e.code, e.read().decode("utf-8", "ignore")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries - 1:
                return 0, str(e)
        time.sleep(5 * (attempt + 1))
    return 0, "unreachable"


def jwt_claims(token: str) -> dict:
    """Decode a JWT's payload without verifying it (we only read role/ref)."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def find_config(bundle: str) -> dict:
    """Pull the Supabase URL, anon key and API URL out of shipped JS."""
    refs = sorted(set(SUPABASE_URL_RE.findall(bundle)))
    anon = [t for t in JWT_RE.findall(bundle) if jwt_claims(t).get("role") == "anon"]
    apis = sorted(set(API_URL_RE.findall(bundle)))
    return {
        "supabase_refs": refs,
        "anon_keys": sorted(set(anon)),
        "api_urls": apis,
        "localhost_api": "localhost:8000" in bundle,
    }


def check_config(cfg: dict) -> list[str]:
    """Problems with the baked-in config, as human-readable strings."""
    problems = []
    if len(cfg["supabase_refs"]) != 1:
        problems.append(f"expected exactly one Supabase project URL in the bundle, found {cfg['supabase_refs'] or 'none'} "
                        "(is NEXT_PUBLIC_SUPABASE_URL set on Vercel production?)")
    if not cfg["anon_keys"]:
        problems.append("no Supabase anon key in the bundle (is NEXT_PUBLIC_SUPABASE_ANON_KEY set on Vercel production?)")
    elif cfg["supabase_refs"] and any(jwt_claims(k).get("ref") != cfg["supabase_refs"][0] for k in cfg["anon_keys"]):
        problems.append("the anon key in the bundle belongs to a different Supabase project than the URL")
    if len(cfg["api_urls"]) != 1:
        problems.append(f"expected exactly one API URL in the bundle, found {cfg['api_urls'] or 'none'} "
                        "(is NEXT_PUBLIC_API_URL set on Vercel production?)")
    return problems


def run(base: str) -> list[str]:
    failures: list[str] = []
    bundle = ""

    for page, markers in (("/signup", ('type="email"', 'type="password"')),
                          ("/login", ('type="email"', 'type="password"'))):
        status, html = http("GET", base + page)
        if status != 200:
            failures.append(f"GET {page} returned {status}")
            continue
        missing = [m for m in markers if m not in html]
        if missing:
            failures.append(f"GET {page} is missing {missing} -- the form didn't render")
        for chunk in sorted(set(CHUNK_RE.findall(html))):
            c_status, js = http("GET", base + chunk)
            if c_status == 200:
                bundle += js
            else:
                failures.append(f"GET {chunk} returned {c_status}")

    if not bundle:
        failures.append("no JavaScript fetched from /signup or /login; can't check the config")
        return failures

    cfg = find_config(bundle)
    problems = check_config(cfg)
    failures += problems
    print(f"bundle config: supabase={cfg['supabase_refs']} anon_keys={len(cfg['anon_keys'])} api={cfg['api_urls']}")

    if not problems:
        sb = f"https://{cfg['supabase_refs'][0]}.supabase.co"
        anon = cfg["anon_keys"][0]
        nobody = f"prod-smoke-{secrets.token_hex(6)}@example.invalid"
        status, text = http("POST", f"{sb}/auth/v1/token?grant_type=password",
                            {"email": nobody, "password": secrets.token_urlsafe(16)},
                            {"apikey": anon, "Authorization": f"Bearer {anon}"})
        if status != 400 or "invalid" not in text.lower():
            failures.append(f"Supabase password login for a nonexistent user returned {status} {text[:200]!r}, "
                            "expected 400 invalid_credentials")
        else:
            print("supabase login endpoint: 400 invalid_credentials (expected)")

        api = cfg["api_urls"][0]
        for path in ("/health", "/health/db"):
            status, text = http("GET", api + path)
            if status != 200 or '"ok"' not in text:
                failures.append(f"GET {api}{path} returned {status} {text[:200]!r}")
        status, text = http("POST", f"{api}/api/v1/workspaces", {})
        if status != 422:
            failures.append(f"POST {api}/api/v1/workspaces with an empty body returned {status}, expected 422")
        else:
            print("signup endpoint: 422 on an empty body (expected)")

    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--base", default="https://theclouddecoded.com")
    base = ap.parse_args().base.rstrip("/")
    failures = run(base)
    if failures:
        print(f"\nPRODUCTION SMOKE TEST FAILED for {base} -- {len(failures)} problem(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\nproduction smoke test passed for {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
