"""World API — entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from alembic import command
from alembic.config import Config

from app.core.database import SessionLocal
from app.core import models  # noqa: F401  (register all models so the registry is populated)
from app.core.tick import tick_engine
from app.domains.bounty import router as bounty_router
from app.domains.contract import router as contract_router
from app.domains.inspector import router as inspector_router
from app.domains.manifest_validate import (
    admin_router as manifest_admin_router,
    router as manifest_validate_router,
)
from app.domains.hero import router as hero_router
from app.domains.highlight import router as highlight_router
from app.domains.item import router as item_router
from app.domains.item.seed import seed_items
from app.domains.building.seed import seed_buildings
from app.domains.npc import router as npc_router
from app.domains.npc.seed import seed_npcs
from app.domains.quest.main_quest import seed_main_quest
from app.domains.quest.seed import seed_quests
from app.domains.recipe import router as recipe_router
from app.domains.resource_node.seed import seed_world_economy
from app.domains.spell.seed import seed_spells
from app.domains.tournament import router as tournament_router
from app.domains.tournament.seed import seed_tournaments
from app.domains.world_event import router as world_event_router
from app.domains.zone import router as zone_router
from app.domains.zone.seed import seed_zones

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("world")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Apply Alembic migrations on startup. Idempotent: if the DB is already
    # at head, this is a no-op; if a fresh DB, it builds the schema.
    try:
        cfg = Config("/app/alembic.ini")
        cfg.set_main_option("script_location", "/app/alembic")
        command.upgrade(cfg, "head")
        log.info("alembic upgrade head — schema is current")
    except Exception:
        log.exception("alembic upgrade failed at startup")
        raise

    with SessionLocal() as db:
        seed_zones(db)
        seed_npcs(db)
        seed_items(db)
        seed_world_economy(db)
        seed_spells(db)
        seed_quests(db)
        seed_main_quest(db)
        seed_buildings(db)
        seed_tournaments(db)
    tick_engine.start()

    # Spawn managed bot loops for any hero with managed=True. Survives
    # world-api restarts without losing in-flight characters.
    from app.managed import registry, start_all_on_boot
    with SessionLocal() as db:
        start_all_on_boot(db)

    log.info("world-api ready")
    try:
        yield
    finally:
        await registry.stop_all()
        tick_engine.shutdown()


app = FastAPI(title="World of Agents — World API", version="0.1.0", lifespan=lifespan)

# Spectator UI is hosted on a different origin (frontend at :47900). Allow all
# origins in dev — the API is read-mostly and the WS path uses an auth token
# on its own. Tighten before exposing to the public internet.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "tick": str(tick_engine.current_tick)}


app.include_router(hero_router)
app.include_router(zone_router)
app.include_router(npc_router)
app.include_router(item_router)
app.include_router(recipe_router)
app.include_router(tournament_router)
app.include_router(bounty_router)
app.include_router(contract_router)
app.include_router(manifest_validate_router)
app.include_router(manifest_admin_router)
app.include_router(inspector_router)
app.include_router(world_event_router)
app.include_router(highlight_router)
