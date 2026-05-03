"""LLM-output JSON action parser. Tolerant of code fences; raises a
structured `ParseError` so the world records *why* a tick was wasted
(empty / no_json / multiple_objects / …) rather than silently waiting.
"""

from __future__ import annotations

import json
import re
from typing import Any

_OBJECT_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", re.DOTALL)

# Failure-mode taxonomy. Stable strings — they end up in events that the
# spectator UI will eventually render, and players will read them looking
# for "why is my hero waiting?". Don't reword these casually.
PARSE_REASON_EMPTY = "empty"
PARSE_REASON_NO_JSON = "no_json_found"
PARSE_REASON_INVALID_JSON = "invalid_json"
PARSE_REASON_NOT_OBJECT = "not_an_object"
PARSE_REASON_MISSING_DO = "missing_do"
PARSE_REASON_MULTIPLE_OBJECTS = "multiple_objects"


class ParseError(ValueError):
    """A structured LLM-output parse failure.

    Subclasses ValueError so existing `except ValueError` blocks still
    catch it, but carries the failure reason and a truncated raw output
    so callers can build a ParseFailure event the spectator can read.
    """

    def __init__(self, reason: str, *, raw_output: str = "", message: str | None = None) -> None:
        self.reason = reason
        self.raw_output = (raw_output or "")[:500]
        super().__init__(message or f"{reason}: {self.raw_output[:120]!r}")


def parse_json_action(text: str) -> dict[str, Any]:
    """Parse the LLM's completion into an action dict, raising ParseError
    with a stable `reason` so the world can record what went wrong rather
    than silently waiting."""
    raw = text or ""
    if not raw or not raw.strip():
        raise ParseError(PARSE_REASON_EMPTY, raw_output=raw)
    text = raw.strip()
    # Strip a leading/trailing code fence if present.
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try a whole-string parse first — the strict path. If the model
    # behaved, this is where the parse succeeds.
    obj: Any
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to first-object regex extraction; flag if there are
        # multiple top-level JSON objects so a second-action smuggle is
        # legible rather than silent.
        matches = _OBJECT_RE.findall(text)
        if not matches:
            raise ParseError(PARSE_REASON_NO_JSON, raw_output=raw) from None
        if len(matches) > 1:
            raise ParseError(
                PARSE_REASON_MULTIPLE_OBJECTS, raw_output=raw,
                message=f"{len(matches)} JSON objects in output; refusing to guess",
            ) from None
        try:
            obj = json.loads(matches[0])
        except json.JSONDecodeError as exc:
            raise ParseError(PARSE_REASON_INVALID_JSON, raw_output=raw) from exc

    if not isinstance(obj, dict):
        raise ParseError(
            PARSE_REASON_NOT_OBJECT, raw_output=raw,
            message=f"expected object, got {type(obj).__name__}",
        )
    if "do" not in obj:
        raise ParseError(
            PARSE_REASON_MISSING_DO, raw_output=raw,
            message=f"missing 'do' field in {obj!r}",
        )
    return obj
