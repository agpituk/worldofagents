"""Mint short-lived permission tokens that authorise a hero to spend tokens
at the LLM gateway this tick.

The world-api is the only thing that knows a hero's INT-derived budget;
the gateway is the only thing that knows the shared secret. So world-api
mints a signed permission claim per tick, the bot forwards it on /think,
and the gateway rejects requests that try to exceed the cap.

Token format mirrors the existing outbound gateway-token (compact b64url
of a JSON payload + HMAC-SHA256 signature):

    base64url(json_payload).base64url(signature)

Claim shape:
    { "hero_id": "<id-or-sentinel>", "max_tokens": int, "iat": int, "exp": int }

The hero_id is informational — the gateway authorises by signature + cap,
not by identity. NPC `llm_persona` reactions mint the same token shape
with a sentinel hero_id so all /think traffic is uniformly metered.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.core.config import settings

# NPC persona (and any other server-side LLM call without a hero owner)
# uses this sentinel so the gateway side's enforcement code stays uniform.
SYSTEM_HERO_ID = "__system__"

# Default permission TTL — long enough to survive a slow LLM call but short
# enough that a leaked token isn't useful next tick.
DEFAULT_TTL_SECONDS = 30


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def issue_permission_token(
    *, hero_id: str, max_tokens: int, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> str:
    now = int(time.time())
    payload = {
        "hero_id": hero_id,
        "max_tokens": int(max_tokens),
        "iat": now,
        "exp": now + ttl_seconds,
        # Per-token nonce — gateway records this on first verify and
        # rejects subsequent attempts within the TTL window. 16 random
        # bytes is overkill given the short lifetime.
        "jti": secrets.token_urlsafe(16),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(
        settings.arena_shared_secret.encode(), payload_bytes, hashlib.sha256
    ).digest()
    return f"{_b64url(payload_bytes)}.{_b64url(sig)}"
