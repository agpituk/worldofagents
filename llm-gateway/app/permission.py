"""Verify inbound permission tokens minted by world-api.

World-api signs a per-hero, per-tick claim of the form
    { "hero_id": str, "max_tokens": int, "iat": int, "exp": int }
with HMAC-SHA256 over the JSON payload, using the shared arena secret.
The gateway verifies the signature, checks expiry, and refuses to call
the provider with `max_tokens` above the claimed cap. Without this
check the gateway is just a signing oracle for whatever budget the
caller asks for.

The signing routine itself lives in world-api's gateway_permission.py.
This file is the verifier counterpart so the two services stay
symmetric (gateway never imports world-api code, and vice versa).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from app.config import settings
from app.nonce import NonceReplayError, default_store


class PermissionTokenError(Exception):
    """Raised when a permission token is malformed, mis-signed, expired, or
    being replayed."""


@dataclass(frozen=True)
class PermissionClaims:
    hero_id: str
    max_tokens: int
    issued_at: int
    expires_at: int
    jti: str | None


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify(token: str) -> PermissionClaims:
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError as exc:
        raise PermissionTokenError("malformed token") from exc

    payload_bytes = _b64url_decode(payload_b64)
    sig = _b64url_decode(sig_b64)
    expected = hmac.new(
        settings.arena_shared_secret.encode(), payload_bytes, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(sig, expected):
        raise PermissionTokenError("bad signature")

    try:
        claims = json.loads(payload_bytes)
    except json.JSONDecodeError as exc:
        raise PermissionTokenError("bad payload") from exc

    now = int(time.time())
    exp = int(claims.get("exp", 0))
    if exp < now:
        raise PermissionTokenError("token expired")

    # Replay guard. Tokens minted before the jti rollout still verify
    # (no jti claim → no replay protection on those legacy tokens), but
    # the world-api side now always emits a jti, so in practice every
    # production token goes through this gate.
    jti = claims.get("jti")
    if jti:
        try:
            default_store.consume(str(jti), exp)
        except NonceReplayError as exc:
            raise PermissionTokenError("token replay") from exc

    return PermissionClaims(
        hero_id=str(claims["hero_id"]),
        max_tokens=int(claims["max_tokens"]),
        issued_at=int(claims.get("iat", 0)),
        expires_at=exp,
        jti=str(jti) if jti else None,
    )
