"""Put llm-gateway root on sys.path so `app.*` imports resolve under pytest."""

import os
import sys
from pathlib import Path

# Settings refuses to boot without a real ARENA_SHARED_SECRET (and
# specifically rejects the historic "dev-secret" placeholder). Tests
# don't care about the value — only that signing round-trips — but it
# must be set before `app.config` is imported.
os.environ.setdefault(
    "ARENA_SHARED_SECRET", "test-secret-not-for-prod-rotate-me-1234567890"
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
