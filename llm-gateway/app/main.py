"""LLM Gateway — entry point.

Single endpoint: POST /think. The bot SDK calls here for any LLM completion;
the response includes a signed gateway token the bot then attaches to its
action submission so the World API knows the call really happened.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.permission import PermissionTokenError, verify as verify_permission
from app.providers import get_provider
from app.signing import issue_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("gateway")

app = FastAPI(title="World of Agents — LLM Gateway", version="0.1.0")


class ThinkMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class ThinkRequest(BaseModel):
    hero_id: str
    model: str
    messages: list[ThinkMessage]
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None
    tick_id: int | None = None
    max_tokens: int | None = None
    provider: str | None = None  # override the default at call time (mostly for testing)
    # World-api-issued permission token authorising this call's max_tokens.
    # Required when settings.require_permission_token is true (the default).
    permission_token: str | None = None


class ToolCallOut(BaseModel):
    id: str
    name: str
    arguments: dict


class ThinkResponse(BaseModel):
    completion: str
    tool_calls: list[ToolCallOut] = []
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    gateway_token: str
    # The per-tick token budget the permission claim authorised. Surfaced
    # so the runner (and downstream inspector) can show usage-vs-budget
    # without re-decoding the (signed, opaque) permission token.
    tokens_budget: int | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/think", response_model=ThinkResponse)
async def think(req: ThinkRequest) -> ThinkResponse:
    # Permission gate — world-api signs a per-hero, per-tick cap on
    # max_tokens. Reject anything that exceeds it. Requests without a
    # permission token are rejected when require_permission_token is on
    # (default) so a bot can't bypass INT-budgeting by omitting the field.
    permission_max_tokens: int | None = None
    if req.permission_token:
        try:
            claims = verify_permission(req.permission_token)
        except PermissionTokenError as exc:
            raise HTTPException(401, f"invalid permission_token: {exc}") from exc
        if req.max_tokens is not None and req.max_tokens > claims.max_tokens:
            raise HTTPException(
                403,
                f"max_tokens={req.max_tokens} exceeds permission cap {claims.max_tokens}",
            )
        permission_max_tokens = claims.max_tokens
    elif settings.require_permission_token:
        raise HTTPException(401, "permission_token required")

    try:
        provider = get_provider(req.provider)
    except KeyError as exc:
        raise HTTPException(400, f"unknown provider: {exc}") from exc

    # If the caller didn't specify max_tokens, fall back to the permission
    # cap so the provider call is always bounded — never unbounded just
    # because the bot was lazy.
    effective_max_tokens = req.max_tokens
    if effective_max_tokens is None and permission_max_tokens is not None:
        effective_max_tokens = permission_max_tokens

    try:
        complete_kwargs = {
            "model": req.model,
            "messages": [m.model_dump() for m in req.messages],
            "max_tokens": effective_max_tokens,
        }
        if req.tools is not None:
            complete_kwargs["tools"] = req.tools
            complete_kwargs["tool_choice"] = req.tool_choice
        result = await provider.complete(**complete_kwargs)
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc)) from exc
    except Exception as exc:
        log.exception("provider call failed")
        raise HTTPException(502, f"provider error: {exc}") from exc

    token = issue_token(
        hero_id=req.hero_id,
        model=req.model,
        tokens=result.tokens_in + result.tokens_out,
        tick_id=req.tick_id,
    )
    return ThinkResponse(
        completion=result.completion,
        tool_calls=[ToolCallOut(**tc) for tc in (result.tool_calls or [])],
        model=req.model,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        latency_ms=result.latency_ms,
        gateway_token=token,
        tokens_budget=permission_max_tokens,
    )
