"""Parser failure-mode taxonomy tests.

FIX_PLAN P0-3 named three specific failure modes that previously went
silent: trailing prose around an object, multiple JSON objects in one
output, and unknown verbs. The parser now raises ParseError with a
stable `reason`, and these tests pin the reasons so a future refactor
can't quietly drop one.
"""

from __future__ import annotations

import pytest

from arena_bot.client import (
    PARSE_REASON_EMPTY,
    PARSE_REASON_INVALID_JSON,
    PARSE_REASON_MISSING_DO,
    PARSE_REASON_MULTIPLE_OBJECTS,
    PARSE_REASON_NO_JSON,
    PARSE_REASON_NOT_OBJECT,
    ParseError,
    parse_json_action,
)


# --- happy path ------------------------------------------------------------


def test_parse_strict_json():
    assert parse_json_action('{"do":"wait"}') == {"do": "wait"}


def test_parse_inside_code_fence():
    assert parse_json_action('```json\n{"do":"wait"}\n```') == {"do": "wait"}


def test_parse_with_leading_prose_extracts_first_object():
    """Trailing prose alone is recoverable — pick the first object."""
    out = parse_json_action('I think: {"do":"wait"}')
    assert out == {"do": "wait"}


# --- failure modes — each must surface a distinct reason ------------------


def test_empty_input():
    with pytest.raises(ParseError) as exc:
        parse_json_action("")
    assert exc.value.reason == PARSE_REASON_EMPTY


def test_whitespace_only():
    with pytest.raises(ParseError) as exc:
        parse_json_action("   \n  ")
    assert exc.value.reason == PARSE_REASON_EMPTY


def test_no_json_in_output():
    with pytest.raises(ParseError) as exc:
        parse_json_action("nothing structured at all")
    assert exc.value.reason == PARSE_REASON_NO_JSON
    # raw_output is preserved so the spectator UI can show it.
    assert "nothing structured" in exc.value.raw_output


def test_multiple_top_level_objects_refused():
    """Previously the regex picked the first and dropped the second
    silently — now we refuse rather than guess which one the model meant."""
    with pytest.raises(ParseError) as exc:
        parse_json_action('{"do":"wait"} {"do":"attack"}')
    assert exc.value.reason == PARSE_REASON_MULTIPLE_OBJECTS


def test_invalid_json_in_object_match():
    """A line that matches the object regex but is invalid JSON inside
    surfaces as invalid_json, not a generic parse failure."""
    with pytest.raises(ParseError) as exc:
        parse_json_action("preamble {do: not_json,}")
    assert exc.value.reason == PARSE_REASON_INVALID_JSON


def test_array_not_object():
    with pytest.raises(ParseError) as exc:
        parse_json_action("[1, 2, 3]")
    assert exc.value.reason == PARSE_REASON_NOT_OBJECT


def test_missing_do_field():
    with pytest.raises(ParseError) as exc:
        parse_json_action('{"foo": "bar"}')
    assert exc.value.reason == PARSE_REASON_MISSING_DO


def test_parse_error_subclasses_value_error():
    """Existing call sites do `except ValueError` — we must not break them."""
    with pytest.raises(ValueError):
        parse_json_action("nope")


def test_raw_output_truncated_to_500_chars():
    big = "x" * 5000
    with pytest.raises(ParseError) as exc:
        parse_json_action(big)
    assert len(exc.value.raw_output) == 500
