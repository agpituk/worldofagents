"""Schema-level guards on HeroManifest.

The @template author placeholder must be rejected so the on-ramp
template picker can't accidentally leak a placeholder author into the
leaderboard.
"""

import pytest
from pydantic import ValidationError

from app.domains.hero.schemas import HeroManifest


def _good_manifest(**overrides):
    base = {
        "name": "Test Hero",
        "author": "@somebody",
        "division": "featherweight",
        "bio": "x",
        "build": {
            "str": 12, "dex": 12, "con": 14,
            "int": 12, "wis": 14, "cha": 8,
        },
    }
    base.update(overrides)
    return base


def test_valid_manifest_parses():
    HeroManifest.model_validate(_good_manifest())


def test_template_placeholder_author_rejected():
    with pytest.raises(ValidationError) as exc:
        HeroManifest.model_validate(_good_manifest(author="@template"))
    assert "template placeholder" in str(exc.value)


def test_template_placeholder_author_rejected_case_insensitive():
    with pytest.raises(ValidationError):
        HeroManifest.model_validate(_good_manifest(author="@Template"))
    with pytest.raises(ValidationError):
        HeroManifest.model_validate(_good_manifest(author="  @template  "))


def test_other_at_handles_pass_through():
    # Tilde-suffixed or plain author handles must keep working.
    HeroManifest.model_validate(_good_manifest(author="@templates_handle"))
    HeroManifest.model_validate(_good_manifest(author="@you"))


def test_over_budget_build_still_rejected():
    with pytest.raises(ValidationError) as exc:
        HeroManifest.model_validate(_good_manifest(build={
            "str": 25, "dex": 25, "con": 25,
            "int": 25, "wis": 5, "cha": 5,
        }))
    assert "over budget" in str(exc.value)
