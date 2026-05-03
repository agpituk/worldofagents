"""ResolutionResult dataclass.

Shared return type for every action resolver in the actions package.
Lives in its own module so every category can import it without
pulling in the rest of the legacy file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResolutionResult:
    ok: bool
    outcome: dict[str, Any]
