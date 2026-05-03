"""Per-IP concurrent-connection caps for long-lived endpoints.

The SSE stream at /zones/{slug}/stream stays open indefinitely. Without
a cap, a single client can open thousands of streams and force the
tick engine to fan out N copies of every event. This module provides
a small in-memory counter keyed by client IP.

Single-process by design, like `nonce.py`. Swap for a Redis-backed
counter when world-api scales horizontally.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException, Request


class ConnectionLimiter:
    def __init__(self, *, max_per_ip: int) -> None:
        self.max_per_ip = max_per_ip
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def _client_ip(self, request: Request) -> str:
        # Trust the immediate peer in dev. Behind a reverse proxy you'd
        # parse X-Forwarded-For; configure that explicitly when deploying.
        client = request.client
        return client.host if client else "unknown"

    @contextmanager
    def slot(self, request: Request) -> Iterator[None]:
        ip = self._client_ip(request)
        with self._lock:
            if self._counts[ip] >= self.max_per_ip:
                raise HTTPException(
                    status_code=429,
                    detail=f"too many concurrent connections from {ip}",
                )
            self._counts[ip] += 1
        try:
            yield
        finally:
            with self._lock:
                self._counts[ip] = max(0, self._counts[ip] - 1)
                if self._counts[ip] == 0:
                    del self._counts[ip]


# 8 concurrent SSE streams per IP is plenty for legitimate use (a
# spectator browsing a few zones in tabs) and shuts down trivial
# fan-out abuse.
zone_stream_limiter = ConnectionLimiter(max_per_ip=8)
