"""LLM Gateway — entry point.

Single endpoint: POST /think. The bot SDK calls here for any LLM completion;
the response includes a signed gateway token the bot then attaches to its
action submission so the World API knows the call really happened.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/think", response_model=ThinkResponse)
async def think(req: ThinkRequest) -> ThinkResponse:
    try:
        provider = get_provider(req.provider)
    except KeyError as exc:
        raise HTTPException(400, f"unknown provider: {exc}") from exc

    try:
        complete_kwargs = {
            "model": req.model,
            "messages": [m.model_dump() for m in req.messages],
            "max_tokens": req.max_tokens,
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
    )
