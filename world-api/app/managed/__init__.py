"""Managed runtime — runs the hero's bot loop server-side.

Each `Hero.managed=True` hero gets one asyncio task in the world-api
process. The task subscribes to `tick_engine` for perception, evaluates
the manifest's reflexes via the bot-sdk's `ReflexEngine`, calls the LLM
gateway on `invoke_llm`, and submits the resulting action back through
the tick engine. The same code paths a remote bot would use — just
in-process so no network hop and no local Python install required.

Lifecycle:
  • on world-api startup → `start_all_on_boot(db)` scans managed alive heroes
  • on /heroes/register with managed=true → `start_managed(...)` immediately
  • on hero death (`status='dead'`) → loop self-exits, runtime is removed
"""

from app.managed.runner import (  # noqa: F401
    ManagedRegistry,
    registry,
    start_all_on_boot,
)
