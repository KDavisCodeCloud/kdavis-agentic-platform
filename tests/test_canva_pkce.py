"""
Unit coverage for the PKCE pair generator used by the Canva OAuth connect
flow (api/routes/internal_marketing.py). The routes themselves aren't
covered end-to-end here — they need real Canva credentials and a live
Brand Template to exercise meaningfully, per that file's own docstring —
but the PKCE math has no external dependency and is worth getting right,
since a wrong code_challenge just fails silently as an opaque OAuth error
from Canva with no useful diagnostic on this side.
"""
import base64
import hashlib

from api.routes.internal_marketing import _generate_pkce_pair


def test_verifier_length_within_rfc7636_bounds():
    verifier, _ = _generate_pkce_pair()
    assert 43 <= len(verifier) <= 128


def test_challenge_is_sha256_s256_of_verifier():
    verifier, challenge = _generate_pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected


def test_challenge_has_no_padding_or_reserved_chars():
    _, challenge = _generate_pkce_pair()
    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge


def test_pairs_are_not_reused_across_calls():
    verifier_a, challenge_a = _generate_pkce_pair()
    verifier_b, challenge_b = _generate_pkce_pair()
    assert verifier_a != verifier_b
    assert challenge_a != challenge_b
