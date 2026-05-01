"""Unit tests for hero_budgets — INT/WIS-derived limits.

These guard the contract from FIX_PLAN P0-1: a default 10/10 hero must
reproduce the values that were hard-coded before this module existed,
*and* heroes at the extremes (5 / 25) must see strictly different
budgets so the stats stop being decorative.
"""

from dataclasses import dataclass

from app.core.hero_budgets import (
    journal_recent_limit,
    journal_relevant_k,
    look_radius,
    mana_regen_per_tick,
    max_tokens_per_tick,
)


@dataclass
class _StatBag:
    int_: int = 10
    wis: int = 10


# --- defaults must match the previous hard-coded values --------------------


def test_defaults_at_10_match_legacy_constants():
    h = _StatBag()
    assert mana_regen_per_tick(h) == 1            # was hard-coded `+= 1` in tick.py
    assert journal_recent_limit(h) == 12          # was `n: int = 12`
    assert journal_relevant_k(h) == 5             # was `n: int = 5`
    assert look_radius(h) == 4                    # was `max(2, 2 + 10//4)`


# --- INT must drive both mana regen and the token budget -------------------


def test_mana_regen_scales_with_int():
    assert mana_regen_per_tick(_StatBag(int_=5)) == 1   # below threshold, floor at 1
    assert mana_regen_per_tick(_StatBag(int_=10)) == 1
    assert mana_regen_per_tick(_StatBag(int_=14)) == 2
    assert mana_regen_per_tick(_StatBag(int_=18)) == 3
    assert mana_regen_per_tick(_StatBag(int_=25)) == 4


def test_max_tokens_strictly_monotonic_in_int():
    # The headline claim: a smarter hero can request more tokens per tick.
    cheap = max_tokens_per_tick(_StatBag(int_=5))
    avg = max_tokens_per_tick(_StatBag(int_=10))
    smart = max_tokens_per_tick(_StatBag(int_=25))
    assert cheap < avg < smart


# --- WIS must drive perception size ----------------------------------------


def test_journal_recent_strictly_monotonic_in_wis():
    dim = journal_recent_limit(_StatBag(wis=5))
    avg = journal_recent_limit(_StatBag(wis=10))
    sage = journal_recent_limit(_StatBag(wis=25))
    assert dim < avg < sage


def test_journal_relevant_k_strictly_monotonic_in_wis():
    dim = journal_relevant_k(_StatBag(wis=5))
    avg = journal_relevant_k(_StatBag(wis=10))
    sage = journal_relevant_k(_StatBag(wis=25))
    assert dim < avg < sage


def test_look_radius_strictly_monotonic_in_wis():
    dim = look_radius(_StatBag(wis=5))
    avg = look_radius(_StatBag(wis=10))
    sage = look_radius(_StatBag(wis=25))
    assert dim < avg < sage


# --- a single-stat extreme leaves the other budgets untouched --------------


def test_int_does_not_leak_into_wis_budgets():
    low_int = _StatBag(int_=5, wis=10)
    high_int = _StatBag(int_=25, wis=10)
    assert journal_recent_limit(low_int) == journal_recent_limit(high_int)
    assert journal_relevant_k(low_int) == journal_relevant_k(high_int)
    assert look_radius(low_int) == look_radius(high_int)


def test_wis_does_not_leak_into_int_budgets():
    low_wis = _StatBag(int_=10, wis=5)
    high_wis = _StatBag(int_=10, wis=25)
    assert mana_regen_per_tick(low_wis) == mana_regen_per_tick(high_wis)
    assert max_tokens_per_tick(low_wis) == max_tokens_per_tick(high_wis)
