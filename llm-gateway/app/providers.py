"""Provider dispatch.

Providers consume `messages` (and optional `tools`) and return a CompletionResult
that always has `completion` (text content) and may have `tool_calls` (when the
model used native tool calling). The gateway then signs the call and returns
both the completion + tool_calls + token to the bot.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings


@dataclass(frozen=True)
class CompletionResult:
    completion: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class StubProvider:
    """Returns a canned, tick-context-aware completion. No network. No cost. Deterministic."""

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> CompletionResult:
        start = time.monotonic()
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        completion = (
            '{"actions":[{"do":"wait"}],"thought":"(stub) heard: '
            + last_user[:60].replace('"', "'")
            + '"}'
        )
        # Crude token approximation: ~4 chars/token.
        tokens_in = sum(len(m.get("content", "")) for m in messages) // 4
        tokens_out = len(completion) // 4
        latency_ms = int((time.monotonic() - start) * 1000)
        return CompletionResult(
            completion=completion,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )


class CqProvider:
    """Placeholder. Will dispatch to ../cq once we wire it. Raises until then."""

    async def complete(self, **_: Any) -> CompletionResult:
        if not settings.cq_base_url:
            raise RuntimeError("cq provider not configured (set CQ_BASE_URL)")
        async with httpx.AsyncClient() as _:
            raise NotImplementedError("cq provider not yet wired")


class LlamafileProvider:
    """OpenAI-compatible client for a local llamafile server.

    Llamafile runs as `./model.llamafile --server --port 47080` and exposes
    `/v1/chat/completions`. We POST messages and read back content + usage.
    """

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> CompletionResult:
        if not settings.llamafile_base_url:
            raise RuntimeError("llamafile provider not configured (set LLAMAFILE_BASE_URL)")

        body: dict[str, Any] = {
            "model": model or "default",
            "messages": messages,
            "max_tokens": max_tokens or 512,
            "temperature": 0.4,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{settings.llamafile_base_url.rstrip('/')}/v1/chat/completions",
                json=body,
            )
            r.raise_for_status()
            data = r.json()
        latency_ms = int((time.monotonic() - start) * 1000)

        msg = data["choices"][0]["message"] or {}
        completion = msg.get("content") or ""

        # OpenAI-format tool_calls: [{id, type:"function", function:{name, arguments:JSON-string}}, ...]
        tool_calls: list[dict[str, Any]] = []
        for tc in (msg.get("tool_calls") or []):
            fn_block = tc.get("function") or {}
            args_raw = fn_block.get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {"_raw": args_raw}
            tool_calls.append(
                {
                    "id": tc.get("id", ""),
                    "name": fn_block.get("name", ""),
                    "arguments": args,
                }
            )

        usage = data.get("usage", {}) or {}
        tokens_in = int(usage.get("prompt_tokens", 0)) or sum(len(m.get("content", "") or "") for m in messages) // 4
        tokens_out = int(usage.get("completion_tokens", 0)) or (len(completion) // 4) + len(tool_calls)

        return CompletionResult(
            completion=completion,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
        )


_PROVIDERS = {
    "stub": StubProvider(),
    "cq": CqProvider(),
    "llamafile": LlamafileProvider(),
}


def get_provider(name: str | None = None):
    return _PROVIDERS[(name or settings.gateway_default_provider)]
