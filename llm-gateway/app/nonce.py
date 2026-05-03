"""Tiny TTL-bounded "have we seen this token before?" store.

Used to defeat replays of permission tokens. World-api mints a token
with a random `jti`; the gateway records it on first verify and rejects
on second verify within the token's lifetime. Once `exp` passes, the
entry is dropped — so the store size is bounded by `(rate of valid
tokens) × (token TTL)`, which is tiny in practice.

Single-process by design: the gateway runs as one uvicorn worker per
container. If you scale horizontally, swap this for a Redis-backed
implementation that exposes the same `consume()` interface.
"""

from __future__ import annotations

import threading
import time

# Sweep on every Nth consume call. With a 30s token TTL this keeps the
# dict bounded without making consume() O(n).
_SWEEP_EVERY = 256


class NonceReplayError(Exception):
    """The jti was already consumed within its TTL window."""


class InMemoryNonceStore:
    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()
        self._calls_since_sweep = 0

    def consume(self, jti: str, exp: int) -> None:
        """Record `jti` as seen until `exp` (unix seconds). Raises
        NonceReplayError if `jti` is already present and not yet expired."""
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


# Module-level singleton — tests can swap with a fresh instance via
# `permission._nonce_store = InMemoryNonceStore()` if isolation matters.
default_store = InMemoryNonceStore()
