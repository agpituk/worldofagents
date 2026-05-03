"""Showcase API — leaderboards + per-tool detail + copy flow + compare.

Phase 6 of the agent-tools rollout. Thin FastAPI surface; business
logic lives in `service.py`, query helpers in `repository.py`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.showcase import service

router = APIRouter(prefix="/api/tools", tags=["showcase"])
compare_router = APIRouter(prefix="/api", tags=["showcase"])


class LeaderboardEntry(BaseModel):
    tool_id: str
    name: str
    kind: str
    author: str
    metric: float
    metric_label: str
    description: str


class CopyResponse(BaseModel):
    ok: bool
    appended: bool
    rename_to: str | None = None
    new_tool_id: str | None = None


@router.get("/leaderboards", response_model=dict)
def leaderboards(
    db: Annotated[Session, Depends(get_db)],
    board: str = "most_copied",
    limit: int = 10,
) -> dict[str, Any]:
    return service.leaderboard(db, board, limit)


@router.get("/{tool_id_value}")
def tool_detail(
    db: Annotated[Session, Depends(get_db)],
    tool_id_value: str,
) -> dict[str, Any]:
    return service.tool_detail(db, tool_id_value)


@router.post("/{tool_id_value}/copy", response_model=CopyResponse)
def copy_tool(
    db: Annotated[Session, Depends(get_db)],
    tool_id_value: str,
    by_hero: str,
    rename: str | None = None,
) -> CopyResponse:
    result = service.copy_tool(db, tool_id_value, by_hero, rename)
    return CopyResponse(**result)


@compare_router.get("/tools-gallery")
def gallery(
    db: Annotated[Session, Depends(get_db)],
    category: str | None = None,
) -> dict[str, Any]:
    return service.gallery(db, category)


@compare_router.get("/compare")
def compare_heroes(
    db: Annotated[Session, Depends(get_db)],
    heroes: str,
) -> dict[str, Any]:
    return service.compare(db, heroes)
