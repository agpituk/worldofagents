"""Hero registration helpers — pure HTTP/cache I/O, no Hero class.

`Hero.register` and `Hero.connect` (in `client.py`) are thin wrappers
over the helpers here. Splitting these out keeps the public Hero
class focused on the running bot loop and lets registration logic be
tested without spinning up a WebSocket.

The functions return `(hero_id, name, auth_token)` tuples; the caller
constructs the `Hero` instance. This avoids a circular import between
`client.py` and this module.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx
import yaml

log = logging.getLogger("arena_bot")


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "hero"


async def _hero_exists(world_url: str, hero_id: str) -> bool:
    try:
        async with httpx.AsyncClient(base_url=world_url.rstrip("/"), timeout=5.0) as client:
            r = await client.get(f"/heroes/{hero_id}")
            return r.status_code == 200
    except httpx.HTTPError:
        return False


async def _hero_id_by_name(world_url: str, name: str) -> str | None:
    """Resolve a hero's UUID by display name. Used when the user
    re-attaches to a web-created hero with `--token` and the SDK has
    no local cache yet — the only thing they have on hand is the name
    (in the manifest) and the token (from /create). Returns None on any
    error so the caller can fall back to fresh registration."""
    try:
        async with httpx.AsyncClient(base_url=world_url.rstrip("/"), timeout=5.0) as client:
            r = await client.get(f"/heroes/by-name/{name}")
            if r.status_code != 200:
                return None
            return r.json().get("id")
    except httpx.HTTPError:
        return None


HeroCreds = tuple[str, str, str]  # (hero_id, name, auth_token)


async def register_hero(*, manifest_path: str | Path, world_url: str) -> HeroCreds:
    """POST the manifest to /heroes/register and return the issued
    credentials. Raises httpx.HTTPStatusError on 4xx/5xx so the caller
    can disambiguate (notably 409 = name already taken)."""
    manifest_bytes = Path(manifest_path).read_bytes()
    async with httpx.AsyncClient(base_url=world_url.rstrip("/"), timeout=15.0) as client:
        files = {"manifest": (Path(manifest_path).name, manifest_bytes, "application/yaml")}
        r = await client.post("/heroes/register", files=files)
        r.raise_for_status()
        body = r.json()
    log.info("registered hero %s (%s)", body["name"], body["id"])
    return body["id"], body["name"], body["auth_token"]


async def connect_or_register(
    *,
    manifest_path: str | Path,
    world_url: str,
    cache_dir: str | Path | None = None,
    auth_token: str | None = None,
) -> HeroCreds:
    """Resolve hero credentials from local cache, an injected token, or
    a fresh registration — in that order. Writes a cache file on every
    successful resolution so subsequent runs skip the network."""
    manifest_path = Path(manifest_path)
    manifest = yaml.safe_load(manifest_path.read_bytes())
    inner = manifest["hero"] if "hero" in manifest and "name" not in manifest else manifest
    name = inner["name"]
    slug = _slugify(name)

    cache_root = Path(cache_dir) if cache_dir else manifest_path.parent / ".arena-cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_file = cache_root / f"{slug}.json"

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            if await _hero_exists(world_url, cached["hero_id"]):
                log.info("resuming cached hero %s (%s)", cached["name"], cached["hero_id"])
                return cached["hero_id"], cached["name"], cached["auth_token"]
            log.info("cached hero %s no longer in world — re-registering", name)
        except (KeyError, json.JSONDecodeError) as exc:
            log.warning("cache file unreadable (%s) — re-registering", exc)

    if auth_token:
        # Web-first flow: hero already exists server-side. Resolve
        # the hero_id by name, cache, and return — skip registration
        # entirely. If the name doesn't match anything in the world,
        # fall through to register so a manifest rename still works.
        hero_id = await _hero_id_by_name(world_url, name)
        if hero_id:
            log.info("attaching to existing hero %s (%s) via injected token", name, hero_id)
            cache_file.write_text(
                json.dumps({"hero_id": hero_id, "name": name, "auth_token": auth_token}, indent=2)
            )
            return hero_id, name, auth_token
        log.info("token provided but no hero named %s in world — registering fresh", name)

    try:
        hero_id, real_name, token = await register_hero(
            manifest_path=manifest_path, world_url=world_url
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            raise RuntimeError(
                f"Hero name '{name}' is already registered in the world but no "
                f"local cache for it exists. Either:\n"
                f"  • re-run with --token <auth_token from /create>\n"
                f"  • delete the orphan: docker compose exec -T postgres psql "
                f"-U arena -d arena -c \"DELETE FROM heroes WHERE name='{name}';\"\n"
                f"  • or wipe the world: docker compose down -v && docker compose up -d\n"
                f"  • or rename your hero in the manifest"
            ) from exc
        raise
    cache_file.write_text(
        json.dumps({"hero_id": hero_id, "name": real_name, "auth_token": token}, indent=2)
    )
    log.info("cached credentials at %s", cache_file)
    return hero_id, real_name, token
