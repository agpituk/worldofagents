"""Hero registration + management + agent WebSocket.

Thin HTTP / WS adapter over `HeroService`. All DB access lives in the
service; the router only translates request → service call → response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.gateway_token import GatewayTokenError, verify as verify_gateway_token
from app.core.models import Event
from app.core.tick import tick_engine
from app.domains.hero.schemas import HeroOut, RegisterHeroResponse
from app.domains.hero.service import HeroService

logger = logging.getLogger("world.hero")

router = APIRouter(prefix="/heroes", tags=["heroes"])


@router.post("/register", response_model=RegisterHeroResponse, status_code=201)
async def register_hero(
    db: Annotated[Session, Depends(get_db)],
    manifest: UploadFile = File(..., description="YAML or JSON manifest file"),
    managed: bool = False,
):
    raw = await manifest.read()
    try:
        parsed = HeroService.parse_manifest(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"manifest validation failed: {exc}") from exc

    try:
        hero = HeroService.register(db, parsed, managed=managed)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if managed:
        # Spawn the bot loop server-side immediately so the hero starts
        # acting on the next tick without any client setup.
        from app.managed import registry
        registry.start(str(hero.id), hero.name, hero.manifest or {})

    return RegisterHeroResponse(
        id=hero.id, name=hero.name, division=hero.division, auth_token=hero.auth_token
    )


@router.get("", response_model=list[HeroOut])
def list_heroes(db: Annotated[Session, Depends(get_db)]):
    return [HeroOut.from_hero(h) for h in HeroService.list_all(db)]


@router.get("/longevity")
def longevity(db: Annotated[Session, Depends(get_db)], limit: int = 20):
    return HeroService.longevity(db, limit)


@router.get("/leaderboard/skills")
def skill_leaderboards(db: Annotated[Session, Depends(get_db)], top: int = 10):
    return HeroService.skill_leaderboards(db, top)


@router.get("/by-name/{name}", response_model=HeroOut)
def get_hero_by_name(name: str, db: Annotated[Session, Depends(get_db)]):
    """Resolve a hero by their unique name. Used by share-friendly URLs."""
    hero = HeroService.get_by_name(db, name)
    if hero is None:
        raise HTTPException(404, "hero not found")
    return HeroOut.from_hero(hero)


@router.get("/{hero_id}", response_model=HeroOut)
def get_hero(hero_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]):
    hero = HeroService.get_by_id(db, hero_id)
    if hero is None:
        raise HTTPException(404, "hero not found")
    return HeroOut.from_hero(hero)


@router.get("/{hero_id}/memory-trace")
def get_memory_trace(hero_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]):
    hero = HeroService.get_by_id(db, hero_id)
    if hero is None:
        raise HTTPException(404, "hero not found")
    return HeroService.memory_trace(db, hero)


@router.get("/{hero_id}/perception")
def get_perception(hero_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]):
    hero = HeroService.get_by_id(db, hero_id)
    if hero is None:
        raise HTTPException(404, "hero not found")
    return HeroService.perception(db, hero)


@router.get("/{hero_id}/quests")
def get_quests(hero_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]):
    return HeroService.quests(db, hero_id)


@router.get("/{hero_id}/journal")
def get_journal(
    hero_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    limit: int = 100,
):
    return HeroService.journal(db, hero_id, limit)


@router.get("/{hero_id}/death")
def get_death_page(hero_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]):
    """The hero's death page. Returns 404 if hero is alive."""
    hero = HeroService.get_by_id(db, hero_id)
    if hero is None:
        raise HTTPException(404, "hero not found")
    try:
        return HeroService.death_page(db, hero)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/respawn", response_model=RegisterHeroResponse, status_code=201)
async def respawn(
    db: Annotated[Session, Depends(get_db)],
    manifest: UploadFile = File(..., description="manifest of the dead hero (will get a new name)"),
    new_name: str | None = None,
):
    """Respawn after permadeath. Same build is reused; the old hero's
    death page persists."""
    raw = await manifest.read()
    try:
        parsed = HeroService.parse_manifest(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"manifest validation failed: {exc}") from exc

    try:
        new_hero = HeroService.respawn(db, parsed, new_name=new_name or "")
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        # Cover both "still alive" (409) and "new_name required" (422).
        if "required" in str(exc):
            raise HTTPException(422, str(exc)) from exc
        raise HTTPException(409, str(exc)) from exc

    return RegisterHeroResponse(
        id=new_hero.id,
        name=new_hero.name,
        division=new_hero.division,
        auth_token=new_hero.auth_token,
    )


# ---------------------------------------------------------------------------
# Agent WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/ws")
async def agent_socket(websocket: WebSocket):
    """Each hero opens one WS connection here. Auth via ?token=<auth_token>."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return

    db_gen = get_db()
    db = next(db_gen)
    try:
        hero = HeroService.get_by_auth_token(db, token)
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

    if hero is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    hero_id = str(hero.id)
    queue = tick_engine.register_agent(hero_id)

    await websocket.send_json(
        {"type": "welcome", "hero_id": hero_id, "name": hero.name, "tick": tick_engine.current_tick}
    )

    push_task = asyncio.create_task(_push_loop(websocket, queue))
    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_inbound(raw, hero_id)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS error for hero %s", hero_id)
    finally:
        push_task.cancel()
        tick_engine.unregister_agent(hero_id)


async def _push_loop(ws: WebSocket, queue: asyncio.Queue) -> None:
    try:
        while True:
            payload = await queue.get()
            await ws.send_json(payload)
    except asyncio.CancelledError:
        pass
    except WebSocketDisconnect:
        pass


async def _handle_inbound(raw: str, hero_id: str) -> None:
    """Validate one inbound message, persist a 'submitted' event, and
    enqueue the action for the tick engine to resolve at the next
    boundary."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("bad inbound json from %s", hero_id)
        return

    msg_type = msg.get("type")
    if msg_type != "action":
        logger.info("ignored inbound type=%s from %s", msg_type, hero_id)
        return

    kind = msg.get("kind")  # "reflex" | "llm"
    tick_id = msg.get("tick_id")
    action = msg.get("action")
    gateway_token = msg.get("gateway_token")

    # LLM-claimed actions must carry a valid gateway token.
    token_claims = None
    if kind == "llm":
        if not gateway_token:
            logger.warning("hero %s submitted llm action without gateway token", hero_id)
            return
        try:
            token_claims = verify_gateway_token(gateway_token)
        except GatewayTokenError as exc:
            logger.warning("hero %s submitted llm action with bad token: %s", hero_id, exc)
            return
        if token_claims.hero_id != hero_id:
            logger.warning(
                "hero %s submitted llm action with token issued to %s",
                hero_id, token_claims.hero_id,
            )
            return

    debug = msg.get("debug")  # optional reflex-debugger metadata from the SDK

    # If the SDK couldn't parse the model's output, mirror that into a
    # distinct parse_failure event so the spectator stream surfaces the
    # "wasted tick" instead of swallowing it as a silent wait.
    parse_failure_payload: dict[str, Any] | None = None
    if isinstance(debug, dict) and debug.get("parse_error"):
        parse_failure_payload = {
            "reason": str(debug.get("parse_error")),
            "raw_output": str(debug.get("raw_output", ""))[:500],
            "fallback_action": action,
        }

    # Persist the submission as an event (audit trail) ...
    db_gen = get_db()
    db = next(db_gen)
    try:
        db.add(
            Event(
                tick_id=int(tick_id) if tick_id is not None else 0,
                hero_id=uuid.UUID(hero_id),
                zone=None,
                kind="action.submitted",
                payload={
                    "kind": kind,
                    "action": action,
                    "verified_model": token_claims.model if token_claims else None,
                    "verified_tokens": token_claims.tokens if token_claims else None,
                    "debug": debug,
                },
            )
        )
        if parse_failure_payload is not None:
            db.add(
                Event(
                    tick_id=int(tick_id) if tick_id is not None else 0,
                    hero_id=uuid.UUID(hero_id),
                    zone=None,
                    kind="parse_failure",
                    payload=parse_failure_payload,
                )
            )
        db.commit()
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

    # ... then hand off to the tick engine for resolution.
    tick_engine.submit_action(
        hero_id, {"kind": kind, "action": action, "tick_id": tick_id, "debug": debug}
    )
