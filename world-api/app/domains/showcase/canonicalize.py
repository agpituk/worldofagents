"""Canonical YAML serialization for tool entries — drives the
content-addressed tool_id (sha256 of canonical bytes).

Two heroes' `shoot_and_flee` are the same tool iff their canonical
forms are byte-identical. This is what makes "copy this tool" detect
prior copies and the leaderboards aggregate correctly.

Canonicalization rules:
  • Keys ordered: name, override, description, parameters, when,
    clamp, after, steps, _meta. Unknown keys appended sorted.
  • Strings normalized (no trailing whitespace; multiline preserved).
  • Lists serialized in source order (semantic — order matters in
    `steps:` and `parameters:` so we don't sort).
  • _meta is always stripped before hashing — copy lineage doesn't
    change the tool's identity.
"""

from __future__ import annotations

import hashlib
from typing import Any

import yaml


_KEY_ORDER = (
    "name", "override", "description",
    "parameters", "when", "clamp", "after", "steps",
)


def canonicalize(entry: dict[str, Any]) -> str:
    """Return the canonical YAML form of a single tools[] entry, with
    `_meta` stripped. Stable across Python versions."""
    if not isinstance(entry, dict):
        raise ValueError("tool entry must be a mapping")

    cleaned = {k: v for k, v in entry.items() if k != "_meta"}

    # Reorder keys per _KEY_ORDER, then any leftovers alphabetically.
    ordered: dict[str, Any] = {}
    for k in _KEY_ORDER:
        if k in cleaned:
            ordered[k] = cleaned[k]
    for k in sorted(cleaned.keys()):
        if k not in ordered:
            ordered[k] = cleaned[k]

    return yaml.safe_dump(
        ordered,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10000,  # avoid line wrapping
    ).strip() + "\n"


def tool_id(entry: dict[str, Any]) -> str:
    """sha256 of the canonical YAML, hex-encoded."""
    body = canonicalize(entry).encode("utf-8")
    return hashlib.sha256(body).hexdigest()
