"""Verify gateway-issued tokens.

The gateway signs a JSON payload with HMAC-SHA256 using the shared secret.
World API verifies the signature and (later) checks division/limits against
what the hero's manifest declared.

Token format (compact, JWT-ish but not JWT-compliant):
    base64url(json_payload).base64url(signature)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from app.core.config import settings
from app.core.nonce import NonceReplayError, default_store


class GatewayTokenError(Exception):
    pass


@dataclass(frozen=True)
class GatewayTokenClaims:
    hero_id: str
    model: str
    tokens: int
    tick_id: int | None
    issued_at: int
    expires_at: int
    jti: str | None


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify(token: str) -> GatewayTokenClaims:
    """Verify a gateway-issued token. Raises GatewayTokenError on any problem."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError as exc:
        raise GatewayTokenError("malformed token") from exc

    payload_bytes = _b64url_decode(payload_b64)
    sig = _b64url_decode(sig_b64)
    expected = hmac.new(
        settings.arena_shared_secret.encode(), payload_bytes, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(sig, expected):
        raise GatewayTokenError("bad signature")

    try:
        claims = json.loads(payload_bytes)
    except json.JSONDecodeError as exc:
        raise GatewayTokenError("bad payload") from exc

    now = int(time.time())
    exp = int(claims.get("exp", 0))
    if exp < now:
        raise GatewayTokenError("token expired")

    # Replay guard. Tokens minted before the jti rollout still verify
    # (no jti claim → no replay protection), but the gateway side now
    # always emits one.
    jti = claims.get("jti")
    if jti:
        try:
            default_store.consume(str(jti), exp)
        except NonceReplayError as exc:
            raise GatewayTokenError("token replay") from exc

    return GatewayTokenClaims(
        hero_id=str(claims["hero_id"]),
        model=str(claims["model"]),
        tokens=int(claims.get("tokens", 0)),
        tick_id=claims.get("tick_id"),
        issued_at=int(claims["iat"]),
        expires_at=exp,
        jti=str(jti) if jti else None,
    )
