# Remaining Work — picked up after the FIX_PLAN sweep

The 16-commit branch landed every P0–P3 item from `FIX_PLAN.md` except
the items below, which were deliberately scoped out. Each is sized for
its own session — start the next one against any of them and they're
self-contained.

> **Note on file references.** Commit `006b2dd` split
> `world-api/app/core/actions.py` into the package
> `world-api/app/core/actions/` (`combat`, `contracts`, `dispatcher`,
> `equipment`, `gathering`, `inventory`, `magic`, `movement`,
> `perception`, `quests`, `sandbox`, `social`, `statuses`, `titles`,
> `trade`). Line numbers below were captured against the pre-split
> monolith; grep by symbol (`_resolve_look`, `_ranked_inventory`,
> `replace_memory`, etc.) to find current locations.

## High-leverage but deferred for scope/risk

### P0-3 step 1 — single-retry parse fallback
**Spec.** When the LLM output fails to parse, ask the model "return only
valid JSON matching this schema" with the original output appended;
parse the retry; on second failure, emit the parse_failure event we
already emit today.

**Why deferred.** Doubles the LLM call cost on bad outputs. Needs to be
designed against the gateway's per-tick INT budget — a hero whose
budget is 416 tokens shouldn't burn it twice on retries when the model
is just structurally bad. Probably wants a smaller `retry_max_tokens`
+ a per-tick retry counter so a manifest with a chronically broken
prompt fails noisily rather than silently spending double.

**Where to start.** `bot-sdk-python/src/arena_bot/client.py:llm_action` /
`llm_tool_action` — wrap the existing `parse_json_action` call. The
parse_failure event already exists, so the new code only adds the
"once more, with feeling" path before falling through to the existing
ParseError handler.

### P0-2 step 2 — `last_used_tick` inventory column
**Spec.** Add `last_used_tick: int` to Item; bump it whenever inventory
moves through `equip`/`unequip`/`gather`/`craft`/`give`. The
inventory ranker in `actions._ranked_inventory` uses it instead of
the current `id desc` proxy.

**Why deferred.** Schema migration + sweep of every inventory write
site. The current `id desc` proxy is right for newly-acquired items
(which is the dominant case) and only goes wrong for *long-held but
recently-used* items — a real but uncommon edge case worth its own
PR rather than rolling into the perception work.

**Where to start.** Alembic migration after `8c4c14e9a7d2` adding the
column with `server_default = "0"`. Then grep for inventory mutations
and bump on each. Update `_ranked_inventory`'s sort key.

### Per-verb Pydantic action models (literal P2-5 step 1)
**Spec.** A Pydantic model per verb (`MoveAction`, `AttackAction`, …);
dispatcher selects the model by verb, validates, runs the handler.

**Why deferred.** The `_VERB_SCHEMAS` registry shipped in `7884c50`
delivers the same coverage (FIX_PLAN's done-when test passes) at ~30
lines vs ~600 of Pydantic boilerplate. Pydantic-per-verb is the right
move *if* we need per-field validators (e.g. `target` is a valid
slug, `move.target` is in zone bounds), which the registry can't
express cheaply. Until that need lands, the registry is the better
shape.

**Where to start.** New `app/core/action_models.py`. Discriminated
union on `do` field. Replace `_validate_action_shape` call site with
`AnyAction.model_validate(action)` returning the typed model the
handler uses directly.

### Async-SQLAlchemy migration of `perception_for` + retrievers (P1-2 step 2)
**Spec.** Move `perception_for`, the visibility helpers, and the cq /
cq-exchange retrievers to async SQLAlchemy + `httpx.AsyncClient`.

**Why deferred.** P1-2 (`ff310f5`) gets the same parallelism via
`asyncio.to_thread` — concurrent I/O without an asyncpg dependency.
The async migration is correct long-term but not load-bearing for
the FIX_PLAN done-when ("100 heroes complete a tick in <1s"); the
thread-based path already does that.

**Where to start.** Drop a feature flag `WORLD_ASYNC_DB`. Mirror
`engine` / `SessionLocal` with async equivalents. Convert
`perception_for` and the visibility helpers to `async def`. The
retrievers are already isolated behind `Retriever` Protocol, so the
swap there is contained.

### Postgres test fixture (cross-cutting)
**Spec.** Add a Postgres testcontainer fixture so tests can exercise:

  - `with_for_update()` actually serialising in P1-3 (today's tests
    pin the recheck logic against SQLite's no-op lock).
  - The 1000-concurrent-accepts property test FIX_PLAN P1-3 names.
  - cq-exchange HTTP retriever path (would need an `httpx.AsyncClient`
    mock or a fixture HTTP server, but Postgres helps with the
    surrounding integration).

**Where to start.** `pytest-postgresql` or `testcontainers-python`.
Mark the heavyweight tests as `@pytest.mark.postgres` and skip when
not available; CI runs them.

## Smaller follow-ups

### Cap `look` verb's unbounded list
The dispatcher's `look` verb (`actions.py:_resolve_look`) returns the
unbounded `_visible_npcs_in_zone`/`_visible_heroes_in_zone`/
`_visible_items_in_zone` results — bypassing the WIS-derived caps
that constrain the per-tick perception payload. A malicious bot
could `look` every tick to grab everything within radius and
sidestep the budget. Apply the same per-verb truncation to the
`look` outcome. Small change, lives at `actions.py:1453`.

### give/buy/sell/store/withdraw row locks (P1-3 step 4)
P1-3's current commit (`c8b2180`) only locks `accept_offer` and
`pickup`. The same shape applies to `give`, `buy`, `sell`, `store`,
`withdraw` — all resolve against shared assets that another
transaction could mutate between check and write. Mechanical sweep,
same `with_for_update()` + recheck pattern.

### Audit `replace_memory` callers
The memory helper rolled in (`9593b4a`) covers every direct
`hero.memory =` site found at sweep time. A future direct write
will not pass code review (helper is the only documented path) but
adding a pre-commit grep would make that automatic. Small lint hook.

### NPC autonomous behaviours (P3-2)
Today `tick.py:run_mob_phase` only runs reactive mob retaliation —
mobs don't act outside hero stimulus. P3-2 wants NPCs (especially
hostile mobs) to take autonomous action on their own cadence:
patrol routes, prey on weakened heroes, retreat when wounded. This
is content/AI design as much as code; needs design decisions before
implementation.

### Explicit correlation IDs (P3-3)
The current `tick_id + hero_id` already pairs perception with action
deterministically — every event in the stream carries both. P3-3's
"a bot can prove I saw X then did Y" claim is mostly satisfied. An
explicit `correlation_id` field would be cosmetic plumbing unless
combined with a content hash of the perception (so a bot can prove
they acted on *that specific* perception, not a stale one) — which
is a security/audit feature, not a debugging one. Worth considering
together with any anti-replay work.

## Not deferred — flagged because they overlap with the above

- The `_VERB_SCHEMAS` registry from `7884c50` would be redundant once
  per-verb Pydantic models land; delete it as part of that PR.
- The thread-based parallelism in `ff310f5` would be replaced by the
  async-DB migration; delete `_build_perception_payload_sync` and
  `_build_perceptions_parallel` then.

## Test surface to extend

- The DB-backed tests use SQLite in-memory; the Postgres fixture
  story (above) unlocks property-based concurrency tests.
- The cq-exchange HTTP retriever has no test; add when there's an
  httpx mock or a fixture HTTP server in the suite.
- The frontend `parse_failure` rendering shipped without a runtime
  check (`d3199ce` commit message flagged this) — frontend
  `node_modules` weren't in the sandbox. Spin the dev server and
  verify the row renders with the rose-500 accent + collapsible
  raw-output details.
