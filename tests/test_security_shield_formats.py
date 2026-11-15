"""
tests/test_security_shield_formats.py
GAPS #35 (2026-11-14): DataSanitizationShield against the secret shapes that
actually appear in cloud logs, CLI output and k8s manifests. A probe found 13
of these 18 leaking before the 2026-11-14 hardening. Plus the other half of
the contract: ordinary diagnostic text an agent needs must survive.
"""

import pytest

from core.security import DataSanitizationShield

AWS_SK = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
AZ = "Q7d8Q~aBcDeFgHiJkLmNoPqRsTuVwXyZ01234567"
STS_TOKEN = "IQoJb3JpZ2luX2VjEHoaCXVzLWVhc3QtMSJHMEUCIQDabcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH"
# Token-shaped fakes are assembled at runtime so no token literal sits in the
# source: GitHub push protection (rightly) blocks a push containing one, even
# a fake. The shield only ever sees the assembled string.
GH_CLASSIC = "gh" + "p_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
GH_FINE = "github" + "_pat_" + "11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ01"
SLACK = "xo" + "xb-" + "123456789012-1234567890123-" + "AbCdEfGhIjKlMnOpQrStUvWx"
STRIPE = "sk" + "_live_" + "51ABCdefGHIjklMNOpqrSTUvwxYZ0123456789"

LEAK_CASES = {
    "env line AWS secret": (f"AWS_SECRET_ACCESS_KEY={AWS_SK}", AWS_SK),
    "JSON aws_secret_access_key": (f'{{"aws_secret_access_key": "{AWS_SK}"}}', AWS_SK),
    "aws sts JSON SecretAccessKey": (f'{{"AccessKeyId": "ASIAIOSFODNN7EXAMPLE", "SecretAccessKey": "{AWS_SK}"}}', AWS_SK),
    "STS temporary key id": ("AccessKeyId: ASIAIOSFODNN7EXAMPLE", "ASIAIOSFODNN7EXAMPLE"),
    "long-term key id": ("key AKIAIOSFODNN7EXAMPLE used", "AKIAIOSFODNN7EXAMPLE"),
    "STS session token": (f'{{"SessionToken": "{STS_TOKEN}"}}', STS_TOKEN),
    "inline log secret": (f"export creds aws_secret_access_key={AWS_SK} for deploy", AWS_SK),
    "Azure env line": (f"AZURE_CLIENT_SECRET={AZ}", AZ),
    "az ad sp create-for-rbac password": (f'{{"appId": "11111111-2222-3333-4444-555555555555", "password": "{AZ}"}}', AZ),
    "Azure ARM clientSecret": (f'"clientSecret": "{AZ}"', AZ),
    "k8s Secret data": ("data:\n  password: c3VwZXJzZWNyZXRwYXNzd29yZDEyMw==\n", "c3VwZXJzZWNyZXRwYXNzd29yZDEyMw=="),
    "GitHub classic PAT": (f"token {GH_CLASSIC}", GH_CLASSIC),
    "GitHub fine-grained PAT": (GH_FINE, GH_FINE),
    "Slack token": (f"SLACK {SLACK}", SLACK),
    "Stripe live key": (f"stripe key {STRIPE}", STRIPE),
    "Azure storage connection string": (
        "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/abcdefghijklmnopqrstuvw==;EndpointSuffix=core.windows.net",
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/abcdefghijklmnopqrstuvw=="),
    "postgres URL": ("postgres://admin:hunter2pass@db.internal:5432/app", "hunter2pass"),
    "lowercase password= in a log line": ("connecting with user=admin password=hunter2pass host=db", "hunter2pass"),
    "Bearer header": ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghij",
                      "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghij"),
}

KEEP_CASES = [
    "secretName: payment-db-credentials",
    'Error: secret "payment-db-credentials" not found',
    "tokenUrl: https://login.example.com/oauth2/token",
    "passwordPolicy: strict",
    "PWD=/home/runner/work/app",
    "token: null",
    "Warning  BackOff  pod/checkout-service-7f9d8  Back-off restarting failed container (OOMKilled)",
    "resources.limits.memory: 512Mi",
    'aws_security_group_rule.allow_5432: cidr_blocks = ["0.0.0.0/0"]',
    "AccessDenied: User: arn:aws:iam::123456789012:role/github-deploy-role is not authorized to perform: s3:PutObject",
    "Bearer token expired for service account ci-bot",
]


@pytest.fixture
def s():
    return DataSanitizationShield()


@pytest.mark.parametrize("name", sorted(LEAK_CASES))
def test_secret_never_survives(s, name):
    text, secret = LEAK_CASES[name]
    assert secret not in s.sanitize(text).sanitized_text


@pytest.mark.parametrize("text", KEEP_CASES)
def test_diagnostic_text_survives(s, text):
    assert s.sanitize(text).sanitized_text == text


def test_json_shape_and_credential_names_preserved(s):
    out = s.sanitize(f'{{"AccessKeyId": "ASIAIOSFODNN7EXAMPLE", "SecretAccessKey": "{AWS_SK}", "Expiration": "2026-11-15T01:00:00Z"}}').sanitized_text
    assert out == ('{"AccessKeyId": "[REDACTED:AWS_ACCESS_KEY]", "SecretAccessKey": "[REDACTED:AWS_SECRET_KEY]", '
                   '"Expiration": "2026-11-15T01:00:00Z"}')


def test_specific_label_not_overwritten_by_generic_pattern(s):
    out = s.sanitize(f"AZURE_CLIENT_SECRET={AZ}").sanitized_text
    assert out == "AZURE_CLIENT_SECRET=[REDACTED:AZURE_CLIENT_SECRET]"


def test_sanitize_dict_redacts_by_key(s):
    out = s.sanitize_dict({"user": "admin", "password": "x1", "nested": {"clientSecret": "abc"},
                           "secretName": "db-creds"})
    assert out == {"user": "admin", "password": "[REDACTED:SECRET_VALUE]",
                   "nested": {"clientSecret": "[REDACTED:SECRET_VALUE]"}, "secretName": "db-creds"}


def test_idempotent(s):
    once = s.sanitize(f'{{"SecretAccessKey": "{AWS_SK}", "password": "hunter2pass"}}').sanitized_text
    assert s.sanitize(once).sanitized_text == once
