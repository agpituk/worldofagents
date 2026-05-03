"""Tests for the registration helpers (extracted from client.py).

Covers the create-via-web → run-locally handoff: when a hero already
exists in the world (registered via the /create form) and the user
runs the SDK with `--token`, the SDK should resolve the hero_id by
name, write a cache file, and skip registration.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from arena_bot.registration import (
    _slugify,
    connect_or_register,
    register_hero,
)


MANIFEST_YAML = """\
manifest_version: 1
hero:
  name: "Test Hero"
  author: "@me"
  division: featherweight
  build: { str: 12, dex: 12, con: 12, int: 12, wis: 12, cha: 12 }
"""


@pytest.fixture
def manifest_file(tmp_path: Path) -> Path:
    p = tmp_path / "hero.yaml"
    p.write_text(MANIFEST_YAML)
    return p


def _make_transport(handler):
    """Build an httpx mock transport from a handler function."""
    return httpx.MockTransport(handler)


def test_slugify_strips_punctuation_and_lowercases():
    assert _slugify("Bromir the Stalwart") == "bromir_the_stalwart"
    assert _slugify("@@@") == "hero"
    assert _slugify("Élara!") == "lara"


def _patch_async_client(monkeypatch, transport):
    """Patch httpx.AsyncClient so the registration helpers hit our mock."""
    real_init = httpx.AsyncClient.__init__

    def fake_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", fake_init)


def test_register_hero_returns_credentials(manifest_file: Path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/heroes/register"
        return httpx.Response(
            200,
            json={"id": "abc-123", "name": "Test Hero", "auth_token": "tok-xyz"},
        )

    _patch_async_client(monkeypatch, _make_transport(handler))
    hero_id, name, token = asyncio.run(
        register_hero(manifest_path=manifest_file, world_url="http://x")
    )
    assert hero_id == "abc-123"
    assert name == "Test Hero"
    assert token == "tok-xyz"


def test_register_hero_propagates_409(manifest_file: Path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "name taken"})

    _patch_async_client(monkeypatch, _make_transport(handler))
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        asyncio.run(register_hero(manifest_path=manifest_file, world_url="http://x"))
    assert exc_info.value.response.status_code == 409


def test_connect_with_auth_token_attaches_to_existing_hero(
    manifest_file: Path, tmp_path: Path, monkeypatch,
):
    """The web-create flow: hero exists in the world, user has the
    token, no local cache. SDK should query /heroes/by-name to resolve
    the id and write a cache file."""

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/heroes/by-name/Test Hero":
            return httpx.Response(200, json={"id": "abc-123", "name": "Test Hero"})
        if request.url.path == "/heroes/register":
            pytest.fail("registration should be skipped when token resolves a hero")
        return httpx.Response(404)

    _patch_async_client(monkeypatch, _make_transport(handler))
    cache_dir = tmp_path / ".cache"
    hero_id, name, token = asyncio.run(
        connect_or_register(
            manifest_path=manifest_file,
            world_url="http://x",
            cache_dir=cache_dir,
            auth_token="given-token",
        )
    )
    assert hero_id == "abc-123"
    assert name == "Test Hero"
    assert token == "given-token"
    assert "/heroes/by-name/Test Hero" in calls
    # Cache file written so subsequent runs skip the network entirely.
    cache_file = cache_dir / "test_hero.json"
    assert cache_file.exists()
    cached = json.loads(cache_file.read_text())
    assert cached == {"hero_id": "abc-123", "name": "Test Hero", "auth_token": "given-token"}


def test_connect_resumes_from_cache_when_hero_still_exists(
    manifest_file: Path, tmp_path: Path, monkeypatch,
):
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    (cache_dir / "test_hero.json").write_text(json.dumps({
        "hero_id": "uuid-1", "name": "Test Hero", "auth_token": "cached-token",
    }))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/heroes/uuid-1":
            return httpx.Response(200, json={"id": "uuid-1"})
        if request.url.path == "/heroes/register":
            pytest.fail("registration should be skipped when cache is valid")
        return httpx.Response(404)

    _patch_async_client(monkeypatch, _make_transport(handler))
    hero_id, name, token = asyncio.run(
        connect_or_register(manifest_path=manifest_file, world_url="http://x", cache_dir=cache_dir)
    )
    assert (hero_id, name, token) == ("uuid-1", "Test Hero", "cached-token")


def test_connect_falls_back_to_register_when_token_name_not_found(
    manifest_file: Path, tmp_path: Path, monkeypatch,
):
    """Token provided but the hero name doesn't match anything in the
    world (e.g. user renamed the hero locally). SDK should fall through
    to fresh registration rather than failing."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/heroes/by-name/Test Hero":
            return httpx.Response(404)
        if request.url.path == "/heroes/register":
            return httpx.Response(
                200,
                json={"id": "fresh-1", "name": "Test Hero", "auth_token": "fresh-token"},
            )
        return httpx.Response(404)

    _patch_async_client(monkeypatch, _make_transport(handler))
    hero_id, name, token = asyncio.run(
        connect_or_register(
            manifest_path=manifest_file,
            world_url="http://x",
            cache_dir=tmp_path / ".cache",
            auth_token="stale-token",
        )
    )
    assert hero_id == "fresh-1"
    assert token == "fresh-token"


def test_connect_409_includes_token_hint_in_message(
    manifest_file: Path, tmp_path: Path, monkeypatch,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/heroes/register":
            return httpx.Response(409, json={"detail": "name taken"})
        return httpx.Response(404)

    _patch_async_client(monkeypatch, _make_transport(handler))
    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(
            connect_or_register(
                manifest_path=manifest_file,
                world_url="http://x",
                cache_dir=tmp_path / ".cache",
            )
        )
    msg = str(exc_info.value)
    # Most important: the error tells the user about the --token escape hatch.
    assert "--token" in msg
    assert "Test Hero" in msg
