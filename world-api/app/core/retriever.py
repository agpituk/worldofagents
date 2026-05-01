"""Per-hero memory retriever — the seam where cq plugs in.

A `Retriever` knows how to:
  • `record(hero_id, text, tags, tick_id)` — index a memory
  • `recall(hero_id, query, tags, limit)` → list of {text, tags, tick_id, score}

Two implementations:

  • `SqlRetriever` (default): queries the JournalEntry table directly with
    cheap recency + tag-overlap + substring scoring. No external deps.

  • `CqRetriever` (opt-in): calls the cq SDK. Each `record` becomes a
    `cq.propose(...)`; each `recall` becomes a `cq.query(...)`. Falls back
    to SqlRetriever if cq is not importable or `CQ_ENABLED` is unset.

The world-api always has a Retriever instance available via
`get_retriever()`. The journal_write action records to it; the recall verb
queries it; perception's `journal_recent` is its top-K by recency.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import JournalEntry

log = logging.getLogger("world.retriever")


class Retriever(Protocol):
    name: str

    def record(self, db: Session, *, hero_id: uuid.UUID, text: str, tags: list[str], tick_id: int, kind: str) -> None: ...

    def recall(self, db: Session, *, hero_id: uuid.UUID, query: str = "", tags: list[str] | None = None, limit: int = 5) -> list[dict[str, Any]]: ...


class SqlRetriever:
    """Default retriever — tag-overlap + substring + recency scoring on JournalEntry.

    Score per entry:
        +5 per matched tag (exact)
        +3 if any query term substring-matches `text` (case-insensitive)
        +recency_decay (newest = +2, oldest in last 200 = +0)
    """

    name = "sql"

    def record(self, db: Session, *, hero_id: uuid.UUID, text: str, tags: list[str], tick_id: int, kind: str) -> None:
        # The Journal write itself happens in actions.py; SqlRetriever has no
        # additional indexing to do — its corpus IS the table.
        return None

    def recall(self, db: Session, *, hero_id: uuid.UUID, query: str = "", tags: list[str] | None = None, limit: int = 5) -> list[dict[str, Any]]:
        rows = list(
            db.scalars(
                select(JournalEntry)
                .where(JournalEntry.hero_id == hero_id)
                .order_by(JournalEntry.id.desc())
                .limit(200)
            )
        )
        wanted_tags = set((tags or []))
        terms = [t for t in (query or "").lower().split() if len(t) >= 3]

        scored: list[tuple[int, JournalEntry]] = []
        for i, r in enumerate(rows):
            row_tags = set(r.tags or [])
            score = 0
            score += 5 * len(wanted_tags & row_tags)
            text_lower = (r.text or "").lower()
            for t in terms:
                if t in text_lower:
                    score += 3
            # Recency boost — newest entries score higher even on tied content.
            score += max(0, 2 - i // 50)
            if score > 0:
                scored.append((score, r))

        scored.sort(key=lambda pair: (-pair[0], -pair[1].id))
        return [
            {
                "tick_id": r.tick_id,
                "kind": r.kind,
                "text": r.text,
                "tags": list(r.tags or []),
                "score": score,
            }
            for score, r in scored[:limit]
        ]


class CqRetriever:
    """Opt-in cq backend. Records each journal entry as a cq KnowledgeUnit
    scoped to the hero's id (used as a `domain`). Queries by domain + pattern."""

    name = "cq"

    def __init__(self, client: Any) -> None:
        self._cq = client

    def record(self, db: Session, *, hero_id: uuid.UUID, text: str, tags: list[str], tick_id: int, kind: str) -> None:
        try:
            self._cq.propose(
                summary=text[:100],
                detail=text,
                action="Remember this for future decisions.",
                domains=[str(hero_id), kind, *tags[:6]],
            )
        except Exception as exc:  # cq down / network blip — degrade quietly
            log.warning("cq.propose failed: %s", exc)

    def recall(self, db: Session, *, hero_id: uuid.UUID, query: str = "", tags: list[str] | None = None, limit: int = 5) -> list[dict[str, Any]]:
        try:
            domains = [str(hero_id)] + list(tags or [])
            result = self._cq.query(domains=domains, pattern=query or None, limit=limit)
            out: list[dict[str, Any]] = []
            for u in (result.units if hasattr(result, "units") else []):
                ins = getattr(u, "insight", None)
                detail = getattr(ins, "detail", None) if ins else None
                summary = getattr(ins, "summary", None) if ins else None
                out.append({
                    "tick_id": None,
                    "kind": "cq",
                    "text": detail or summary or "",
                    "tags": list(getattr(u, "domains", []) or []),
                    "score": float(getattr(getattr(u, "evidence", None), "confidence", 0.0) or 0.0),
                })
            return out
        except Exception as exc:
            log.warning("cq.query failed (%s) — falling back to SQL", exc)
            return SqlRetriever().recall(db, hero_id=hero_id, query=query, tags=tags, limit=limit)


class CqExchangeRetriever:
    """HTTP-based retriever pointed at a cq-exchange SaaS instance.

    cq-exchange is a hosted multi-tenant store using `cq-schema` models with
    flat field names + `namespace_id` scoping. We POST to /api/v1/propose
    on every journal entry and GET /api/v1/query on recall. Auth is a
    bearer API key issued per namespace.

    Falls back to SqlRetriever on any HTTP error.
    """

    name = "cq-exchange"

    def __init__(self, base_url: str, api_key: str, namespace_id: str) -> None:
        import httpx
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        self._namespace_id = namespace_id

    def record(self, db: Session, *, hero_id: uuid.UUID, text: str, tags: list[str], tick_id: int, kind: str) -> None:
        try:
            payload = {
                "namespace_id": self._namespace_id,
                "insight_summary": text[:100],
                "insight_detail": text,
                "insight_action": "Remember this for future decisions.",
                "context_languages": [],
                "context_frameworks": [],
                "context_pattern": " ".join(tags[:4]),
                # Use the hero id as a domain so a single namespace can host
                # multiple heroes' memories without bleeding across heroes.
                "domains": [str(hero_id), kind, *tags[:6]],
            }
            r = self._client.post("/api/v1/propose", json=payload)
            r.raise_for_status()
        except Exception as exc:
            log.warning("cq-exchange propose failed: %s", exc)

    def recall(self, db: Session, *, hero_id: uuid.UUID, query: str = "", tags: list[str] | None = None, limit: int = 5) -> list[dict[str, Any]]:
        try:
            params: list[tuple[str, str]] = [("domains", str(hero_id))]
            for t in (tags or []):
                params.append(("domains", str(t)))
            if query:
                params.append(("pattern", query))
            params.append(("limit", str(limit)))
            r = self._client.get("/api/v1/query", params=params)
            r.raise_for_status()
            data = r.json()
            units = data.get("units") if isinstance(data, dict) else (data if isinstance(data, list) else [])
            out: list[dict[str, Any]] = []
            for u in (units or []):
                ins_summary = u.get("insight_summary") if isinstance(u, dict) else None
                ins_detail = u.get("insight_detail") if isinstance(u, dict) else None
                out.append({
                    "tick_id": None,
                    "kind": "cq-exchange",
                    "text": ins_detail or ins_summary or "",
                    "tags": list(u.get("domains") or []) if isinstance(u, dict) else [],
                    "score": float(u.get("evidence_confidence", 0.0) or 0.0) if isinstance(u, dict) else 0.0,
                })
            return out
        except Exception as exc:
            log.warning("cq-exchange query failed (%s) — falling back to SQL", exc)
            return SqlRetriever().recall(db, hero_id=hero_id, query=query, tags=tags, limit=limit)


def _build_retriever() -> Retriever:
    # Priority: cq-exchange (world-shared, hosted) > local cq SDK > SQL fallback.
    if os.environ.get("CQ_EXCHANGE_ENABLED", "").lower() in ("1", "true", "yes"):
        url = os.environ.get("CQ_EXCHANGE_URL", "").strip()
        key = os.environ.get("CQ_EXCHANGE_API_KEY", "").strip()
        namespace = os.environ.get("CQ_EXCHANGE_NAMESPACE_ID", "").strip()
        if url and key and namespace:
            try:
                return CqExchangeRetriever(url, key, namespace)
            except Exception as exc:
                log.warning("cq-exchange init failed (%s) — falling through", exc)
        else:
            log.warning("CQ_EXCHANGE_ENABLED set but URL/API_KEY/NAMESPACE_ID missing")

    if os.environ.get("CQ_ENABLED", "").lower() in ("1", "true", "yes"):
        try:
            from cq import Client  # type: ignore[import-untyped]
            return CqRetriever(Client())
        except Exception as exc:
            log.warning("CQ_ENABLED set but cq import failed (%s) — using SqlRetriever", exc)
    return SqlRetriever()


_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = _build_retriever()
        log.info("retriever initialised: %s", _retriever.name)
    return _retriever
