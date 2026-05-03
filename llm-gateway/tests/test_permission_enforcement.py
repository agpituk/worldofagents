"""Gateway permission-token enforcement.

FIX_PLAN P0-1 done-when:
    A hero with INT 5 cannot request more tokens per tick than a hero with
    INT 25, verified by a unit test that signs two tokens and asserts the
    gateway rejects the over-budget one.

These tests sign permission tokens directly with the same shared secret
the world-api would use, so the gateway test stays self-contained — no
world-api process needed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.permission import PermissionTokenError, verify


def _sign_permission(
    *, hero_id: str, max_tokens: int, ttl: int = 30, jti: str | None = "auto"
) -> str:
    """Mirror world-api/app/core/gateway_permission.issue_permission_token."""
    import secrets as _secrets
    now = int(time.time())
    payload: dict = {
        "hero_id": hero_id,
        "max_tokens": int(max_tokens),
        "iat": now,
        "exp": now + ttl,
    }
    if jti == "auto":
        payload["jti"] = _secrets.token_urlsafe(16)
    elif jti is not None:
        payload["jti"] = jti
    # else: omit jti entirely (legacy token shape)
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(
        settings.arena_shared_secret.encode(), payload_bytes, hashlib.sha256
    ).digest()

    def _b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    return f"{_b64(payload_bytes)}.{_b64(sig)}"


# ---- pure verifier tests --------------------------------------------------


def test_verify_round_trip():
    token = _sign_permission(hero_id="hero-a", max_tokens=512)
    claims = verify(token)
    assert claims.hero_id == "hero-a"
    assert claims.max_tokens == 512


def test_verify_rejects_tampered_payload():
    token = _sign_permission(hero_id="hero-a", max_tokens=512)
    payload_b64, sig_b64 = token.split(".", 1)
    # Decode, bump max_tokens, re-encode without re-signing.
    pad = "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
    payload["max_tokens"] = 9999
    new_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).rstrip(b"=").decode()
    tampered = f"{new_payload}.{sig_b64}"
    with pytest.raises(PermissionTokenError):
        verify(tampered)


def test_verify_rejects_expired():
    token = _sign_permission(hero_id="hero-a", max_tokens=512, ttl=-5)
    with pytest.raises(PermissionTokenError):
        verify(token)


def test_verify_rejects_replay():
    """Same token consumed twice within its TTL → second call raises."""
    token = _sign_permission(hero_id="hero-replay", max_tokens=128)
    claims1 = verify(token)
    assert claims1.jti is not None
    with pytest.raises(PermissionTokenError) as exc_info:
        verify(token)
    assert "replay" in str(exc_info.value)


def test_verify_legacy_token_without_jti_still_accepted():
    """Tokens minted before the jti rollout don't have one. They still
    verify (signature + expiry only), just without replay protection."""
    token = _sign_permission(hero_id="hero-legacy", max_tokens=128, jti=None)
    claims = verify(token)
    assert claims.jti is None
    # Same legacy token verifies again — no jti, no replay guard.
    verify(token)


# ---- gateway enforcement (the FIX_PLAN done-when) -------------------------


@pytest.fixture
def client():
    # Plug a deterministic offline provider into the registry for the duration
    # of the test, so /think reaches the permission gate without needing an
    # actual model server.
    from app import providers

    class _StubProvider:
        async def complete(self, **_kwargs):
            return providers.CompletionResult(
                completion='{"do": "wait"}',
                tokens_in=10,
                tokens_out=5,
                latency_ms=1,
            )

    providers._PROVIDERS["stubtest"] = _StubProvider()
    try:
        yield TestClient(app)
    finally:
        providers._PROVIDERS.pop("stubtest", None)


def _think_payload(*, hero_id: str, max_tokens: int, permission_token: str | None) -> dict:
    payload = {
        "hero_id": hero_id,
        "model": "stub",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": max_tokens,
        "provider": "stubtest",
    }
    if permission_token is not None:
        payload["permission_token"] = permission_token
    return payload


# Budgets cribbed from world-api/app/core/hero_budgets.max_tokens_per_tick:
# INT 5 → 416, INT 25 → 1056.
INT5_BUDGET = 416
INT25_BUDGET = 1056


def test_int5_hero_cannot_request_int25_budget(client):
    """The headline FIX_PLAN P0-1 test: a low-INT hero presenting their
    own (low) permission token must be rejected when they ask for the
    high-INT hero's budget."""
    int5_token = _sign_permission(hero_id="hero-int5", max_tokens=INT5_BUDGET)
    r = client.post(
        "/think",
        json=_think_payload(
            hero_id="hero-int5", max_tokens=INT25_BUDGET, permission_token=int5_token,
        ),
    )
    assert r.status_code == 403, r.text
    assert "exceeds permission cap" in r.text


def test_int25_hero_can_request_int25_budget(client):
    int25_token = _sign_permission(hero_id="hero-int25", max_tokens=INT25_BUDGET)
    r = client.post(
        "/think",
        json=_think_payload(
            hero_id="hero-int25", max_tokens=INT25_BUDGET, permission_token=int25_token,
        ),
    )
    assert r.status_code == 200, r.text


def test_int5_hero_within_their_budget_passes(client):
    """Sanity: a within-budget request from the low-INT hero is fine."""
    int5_token = _sign_permission(hero_id="hero-int5", max_tokens=INT5_BUDGET)
    r = client.post(
        "/think",
        json=_think_payload(
            hero_id="hero-int5", max_tokens=INT5_BUDGET, permission_token=int5_token,
        ),
    )
    assert r.status_code == 200, r.text


def test_missing_permission_token_rejected_when_required(client):
    r = client.post(
        "/think",
        json=_think_payload(
            hero_id="hero-int5", max_tokens=100, permission_token=None,
        ),
    )
    assert r.status_code == 401, r.text


def test_invalid_permission_token_rejected(client):
    r = client.post(
        "/think",
        json=_think_payload(
            hero_id="hero-int5", max_tokens=100, permission_token="not-a-token",
        ),
    )
    assert r.status_code == 401, r.text
