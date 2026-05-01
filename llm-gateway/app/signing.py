"""Issue HMAC-SHA256 signed gateway tokens.

The gateway is the only thing that knows the shared secret + the call's true cost.
World API only verifies these tokens; it never issues them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.config import settings


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def issue_token(*, hero_id: str, model: str, tokens: int, tick_id: int | None) -> str:
    now = int(time.time())
    payload = {
        "hero_id": hero_id,
        "model": model,
        "tokens": tokens,
        "tick_id": tick_id,
        "iat": now,
        "exp": now + settings.token_ttl_seconds,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(
        settings.arena_shared_secret.encode(), payload_bytes, hashlib.sha256
    ).digest()
    return f"{_b64url(payload_bytes)}.{_b64url(sig)}"
