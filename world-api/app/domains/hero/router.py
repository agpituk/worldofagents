"""Hero registration + management + agent WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.gateway_token import GatewayTokenError, verify as verify_gateway_token
from app.core.models import Event, Hero
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
    """Two leaderboards in one payload — `alive` (current streaks, sorted by
    ticks_alive desc) and `hall_of_fame` (dead heroes, sorted by ticks they
    survived). The headline metric of the game."""
    from app.core.models import Tick
    from sqlalchemy import func as _func, desc

    current_tick = int(db.scalar(sa_select(_func.max(Tick.id))) or 0)
    alive_rows = list(db.scalars(sa_select(Hero).where(Hero.status == "alive")))
    dead_rows = list(
        db.scalars(
            sa_select(Hero)
            .where(Hero.status == "dead")
            .order_by(desc(Hero.died_at_tick - Hero.born_at_tick))
            .limit(limit)
        )
    )

    def _row(h, end_tick):
        return {
            "id": str(h.id),
            "name": h.name,
            "author": h.author,
            "division": h.division,
            "zone": h.zone,
            "born_at_tick": int(h.born_at_tick or 0),
            "died_at_tick": h.died_at_tick,
            "ticks_alive": max(0, int(end_tick) - int(h.born_at_tick or 0)),
        }

    alive = [_row(h, current_tick) for h in alive_rows]
    alive.sort(key=lambda r: -r["ticks_alive"])
    return {
        "current_tick": current_tick,
        "alive": alive[:limit],
        "hall_of_fame": [_row(h, h.died_at_tick or current_tick) for h in dead_rows],
    }


@router.get("/by-name/{name}", response_model=HeroOut)
def get_hero_by_name(name: str, db: Annotated[Session, Depends(get_db)]):
    """Resolve a hero by their unique name. Used by share-friendly URLs."""
    hero = db.scalar(sa_select(Hero).where(Hero.name == name))
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
    """The hero's recall surface — the data the LLM sees as "memories you
    carry" each tick. Surfaces:
      • `recall_tags`: manifest-declared bias for what to retrieve
      • `journal_relevant`: top-K retriever hits (what those tags actually pull)
      • `retriever_name`: which backend served the hits (sql / cq / cq-exchange)
    Players use this page to debug *why* their hero remembers what it does."""
    from app.core.actions import _journal_relevant
    from app.core.retriever import get_retriever
    hero = HeroService.get_by_id(db, hero_id)
    if hero is None:
        raise HTTPException(404, "hero not found")
    mem = hero.memory if isinstance(hero.memory, dict) else {}
    return {
        "hero_id": str(hero.id),
        "name": hero.name,
        "recall_tags": list(mem.get("recall_tags") or []),
        "system_summary": mem.get("system_summary"),
        "discovered_recipes": list(mem.get("discovered_recipes") or []),
        "titles": list(mem.get("titles") or []),
        "retriever_name": get_retriever().name,
        "journal_relevant": _journal_relevant(db, hero, n=10),
    }


@router.get("/{hero_id}/quests")
def get_quests(hero_id: uuid.UUID, db: Annotated[Session, Depends(get_db)] = None):
    """All quests for a hero, joined with their template metadata. Used by the
    hero page to show active progress + claimable quests + history."""
    from app.core.models import Quest, QuestTemplate
    rows = list(
        db.scalars(
            sa_select(Quest).where(Quest.hero_id == hero_id).order_by(Quest.accepted_at.desc())
        )
    )
    out = []
    for q in rows:
        tpl = db.get(QuestTemplate, q.template_slug)
        if tpl is None:
            continue
        out.append({
            "id": str(q.id),
            "template_slug": q.template_slug,
            "name": tpl.name,
            "description": tpl.description,
            "kind": tpl.kind,
            "target": tpl.target,
            "count_done": q.count_done,
            "count_required": tpl.count_required,
            "status": q.status,
            "reward_gold": tpl.reward_gold,
            "reward_faction": tpl.reward_faction,
            "reward_faction_amount": tpl.reward_faction_amount,
            "offered_by": tpl.offered_by,
        })
    return out


@router.get("/{hero_id}/journal")
def get_journal(hero_id: uuid.UUID, limit: int = 100, db: Annotated[Session, Depends(get_db)] = None):
    """The hero's episodic memory — milestone entries (auto) + player entries (LLM-curated).
    Newest last."""
    from app.core.models import JournalEntry
    rows = list(
        db.scalars(
            sa_select(JournalEntry)
            .where(JournalEntry.hero_id == hero_id)
            .order_by(JournalEntry.id.desc())
            .limit(min(limit, 500))
        )
    )
    rows.reverse()
    return [
        {
            "id": r.id,
            "tick_id": r.tick_id,
            "kind": r.kind,
            "text": r.text,
            "tags": list(r.tags or []),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/{hero_id}/death")
def get_death_page(hero_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]):
    """The hero's death page: when, where, killed by, last 30 thoughts.
    The viral monument. Returns 404 if hero is alive."""
    hero = HeroService.get_by_id(db, hero_id)
    if hero is None:
        raise HTTPException(404, "hero not found")
    if hero.status != "dead":
        raise HTTPException(404, "hero is alive")

    death_event = db.scalar(
        sa_select(Event)
        .where(Event.hero_id == hero_id, Event.kind == "hero.died")
        .order_by(Event.id.desc())
        .limit(1)
    )
    last_thoughts = list(
        db.scalars(
            sa_select(Event)
            .where(Event.hero_id == hero_id, Event.kind.in_(["action.resolved", "npc.reaction"]))
            .order_by(Event.id.desc())
            .limit(30)
        )
    )

    return {
        "id": str(hero.id),
        "name": hero.name,
        "author": hero.author,
        "division": hero.division,
        "bio": hero.bio,
        "build": {
            "str": hero.str_, "dex": hero.dex, "con": hero.con,
            "int": hero.int_, "wis": hero.wis, "cha": hero.cha,
        },
        "died_at_zone": hero.zone,
        "died_at_pos": [hero.pos_x, hero.pos_y],
        "killer": (death_event.payload or {}).get("killer") if death_event else None,
        "killer_kind": (death_event.payload or {}).get("killer_kind") if death_event else None,
        "killer_id": (death_event.payload or {}).get("killer_id") if death_event else None,
        "looted_gold": (death_event.payload or {}).get("looted_gold", 0) if death_event else 0,
        "final_gold": (hero.memory or {}).get("gold", 0) if isinstance(hero.memory, dict) else 0,
        "born_at_tick": int(hero.born_at_tick or 0),
        "died_at_tick": hero.died_at_tick,
        "ticks_alive": max(0, int(hero.died_at_tick or 0) - int(hero.born_at_tick or 0)),
        "faction_rep": dict(hero.faction_rep or {}),
        "epitaph_thoughts": [
            {"kind": e.kind, "tick_id": e.tick_id, "payload": e.payload} for e in last_thoughts
        ],
    }


@router.post("/respawn", response_model=RegisterHeroResponse, status_code=201)
async def respawn(
    db: Annotated[Session, Depends(get_db)],
    manifest: UploadFile = File(..., description="manifest of the dead hero (will get a new name)"),
    new_name: str | None = None,
):
    """Respawn after permadeath. Takes the previous manifest; the previous
    hero of the same name MUST be dead. Same build is reused. New name
    required (the player picks one); the old hero's death page persists.
    """
    raw = await manifest.read()
    try:
        parsed = HeroService.parse_manifest(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"manifest validation failed: {exc}") from exc

    # Find the original hero by name
    from sqlalchemy import select as _sel
    original = db.scalar(_sel(__import__("app.core.models", fromlist=["Hero"]).Hero).where(
        __import__("app.core.models", fromlist=["Hero"]).Hero.name == parsed.name
    ))
    if original is None:
        raise HTTPException(404, f"no prior hero named '{parsed.name}' to respawn from")
    if original.status != "dead":
        raise HTTPException(409, f"hero '{parsed.name}' is still alive — cannot respawn")
    if not new_name:
        raise HTTPException(422, "new_name required for respawn")

    # Override the name field for the new hero
    parsed_dict = parsed.model_dump(by_alias=True)
    parsed_dict["name"] = new_name
    parsed_v2 = parsed.__class__.model_validate(parsed_dict)

    try:
        new_hero = HeroService.register(db, parsed_v2)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    return RegisterHeroResponse(
        id=new_hero.id, name=new_hero.name, division=new_hero.division, auth_token=new_hero.auth_token
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

    # Resolve the hero by their per-hero auth token (created at registration).
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

    # Greet the bot
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
    """Validate one inbound message, persist a 'submitted' event, and enqueue
    the action for the tick engine to resolve at the next boundary."""
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
                "hero %s submitted llm action with token issued to %s", hero_id, token_claims.hero_id
            )
            return

    debug = msg.get("debug")  # optional reflex-debugger metadata from the SDK

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
