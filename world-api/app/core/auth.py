"""Owner-token extraction for endpoints that gate on hero ownership.

Resolution order:
  1. `X-Owner-Token: <token>`   — preferred. Not logged by browsers in
                                  history/Referer.
  2. `Authorization: Bearer <token>` — supported for API clients that
                                  default to RFC 6750.
  3. `?owner_token=<token>`     — legacy. Logged by browsers/proxies.
                                  Kept until the frontend has fully
                                  migrated, then drop.

Helpers come in two flavours: `optional_owner_token` returns `None`
when nothing is presented (use for endpoints that show different
content to owners vs spectators); `required_owner_token` raises 401
when missing (use for endpoints that mutate hero state).
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Query


def _from_authorization_header(header: str | None) -> str | None:
    if not header:
        return None
    if not header.lower().startswith("bearer "):
        return None
    return header.split(" ", 1)[1].strip() or None


def optional_owner_token(
    x_owner_token: str | None = Header(default=None, alias="X-Owner-Token"),
    authorization: str | None = Header(default=None),
    owner_token: str | None = Query(default=None),
) -> str | None:
    """Pull an owner token from any of the three accepted carriers, or
    None if absent. Header forms take precedence over the query param."""
    return (
        x_owner_token
        or _from_authorization_header(authorization)
        or owner_token
        or None
    )


def required_owner_token(
    x_owner_token: str | None = Header(default=None, alias="X-Owner-Token"),
    authorization: str | None = Header(default=None),
    owner_token: str | None = Query(default=None),
) -> str:
    """Same as `optional_owner_token` but raises 401 when no token is
    presented. Routes that mutate per-hero state should depend on this."""
    tok = (
        x_owner_token
        or _from_authorization_header(authorization)
        or owner_token
    )
    if not tok:
        raise HTTPException(
            status_code=401,
            detail="owner token required (X-Owner-Token header)",
        )
    return tok
