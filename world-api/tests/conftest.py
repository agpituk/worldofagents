"""Shared pytest config:
  - put world-api root on sys.path so `app.*` imports resolve.
  - put bot-sdk-python's src/ on sys.path so the world-api's managed
    runner can import `arena_bot.*` under tests (the bot SDK is a
    sibling package in the same monorepo)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BOT_SDK_SRC = ROOT.parent / "bot-sdk-python" / "src"
if BOT_SDK_SRC.is_dir() and str(BOT_SDK_SRC) not in sys.path:
    sys.path.insert(0, str(BOT_SDK_SRC))
