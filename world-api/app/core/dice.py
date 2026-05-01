"""Tiny dice helper. Parses strings like '1d8', '2d4+1', '1d3-1'."""

from __future__ import annotations

import random
import re

_PATTERN = re.compile(r"^\s*(\d+)d(\d+)\s*(?:([+-])\s*(\d+))?\s*$")


def roll(spec: str) -> int:
    if not spec:
        return 0
    m = _PATTERN.match(spec)
    if not m:
        raise ValueError(f"bad dice spec: {spec!r}")
    n = int(m.group(1))
    sides = int(m.group(2))
    if n == 0 or sides == 0:
        return 0
    total = sum(random.randint(1, sides) for _ in range(n))
    if m.group(3):
        bonus = int(m.group(4))
        total += bonus if m.group(3) == "+" else -bonus
    return total


def d20() -> int:
    return random.randint(1, 20)
