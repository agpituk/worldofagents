"""TTL-bounded nonce store for gateway-token replay protection.

Mirrors `llm-gateway/app/nonce.py`. The gateway records consumed
permission tokens; world-api records consumed gateway tokens (the
signed proof-of-LLM-call returned to the bot). Single-process, in-memory
— swap for a Redis-backed implementation when world-api scales out.
"""

from __future__ import annotations

import threading
import time

_SWEEP_EVERY = 256


class NonceReplayError(Exception):
    """The jti was already consumed within its TTL window."""


class InMemoryNonceStore:
    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()
        self._calls_since_sweep = 0

    def consume(self, jti: str, exp: int) -> None:
        now = int(time.time())
        with self._lock:
            self._calls_since_sweep += 1
            if self._calls_since_sweep >= _SWEEP_EVERY:
                self._calls_since_sweep = 0
                self._seen = {k: v for k, v in self._seen.items() if v > now}
            prior = self._seen.get(jti)
            if prior is not None and prior > now:
                raise NonceReplayError(f"token replay detected: jti={jti}")
            self._seen[jti] = exp


default_store = InMemoryNonceStore()
