# Architecture Review Report — 2026-05-02

**Mode:** Full Scan
**Scope:** ~150 source files across `world-api`, `llm-gateway`, `frontend`, `bot-sdk-python`
**Branch:** `main` (HEAD `77d3e0c` — merge of `feature/agent-tools`)

> **Snapshot — preserved for history.** All Critical and most High items
> below were addressed in commit `006b2dd` (*arch-review cleanup: split
> god-files, enforce DDD layering, fix test wiring*). In particular:
> `world-api/app/core/actions.py` was split into the `actions/` package
> (per Suggested Action #1); the `tests/` bind-mount was added to
> `docker-compose.yml` (#2); the `showcase` and `hero` domains gained
> `service.py`/`repository.py` modules and stopped going around them
> (#3, #4); and `bot-sdk-python/client.py` was sliced into `client.py`
> + `prompt.py` + `parser.py` (#5). Treat the metrics and file sizes
> below as the pre-cleanup baseline; current line counts and coverage
> figures will differ. Re-run an arch review against `main` for a
> current picture.

---

## 🔴 Critical Issues (fix immediately)

### 1. `world-api/app/core/actions.py` — 3745 lines (cap 600)
41 `_resolve_*` verb handlers + helpers across at least 8 unrelated subjects in one file (skills, statuses, contracts, inventory, gathering/crafting, buy/sell, perception, combat, sandbox eviction, bounties, quests). Section comments already mark the seams. Late local imports (`from app.core.combat import …`, `from app.domains.quest.main_quest import …`, `from app.core.affixes import …`) exist solely to dodge circular imports — the size is now causing structural rot. Coverage **21%**.

### 2. `world-api/app/core/models.py` — 572 lines, 22 SQLAlchemy classes
Soft cap 400, near hard cap. Multiple aggregates jammed together (Hero, NPC, Quest, Tournament, Contract, Spell, Item, Tool*, etc.). Splitting per-aggregate (or moving each into its owning domain) is the next move.

### 3. `world-api/app/domains/showcase/router.py` — 786 lines (hard cap 500). Layer violation
6 endpoints + helpers call `db.execute(select(...))` directly inside the router — there's no `service.py` or `repository.py` in the showcase domain. Helpers `_index_hero`, `_index_all`, `_most_copied`, `_best_success`, `_aggregate_tool_calls`, `_david_tools`, etc. are business logic living in the route module. Coverage 83% though, so refactor risk is low.

### 4. `world-api/app/domains/hero/router.py` — 507 lines, 13 endpoints, all bypass the service layer
Every endpoint hits `db.scalar(sa_select(...))` / `db.scalars(...)` directly. `HeroService` exists (137 lines) but is barely used. Coverage **20%**.

### 5. `bot-sdk-python/src/arena_bot/client.py` — 759 lines (cap 400)
Mixes WS client, prompt builder (`build_action_prompt`, `build_tool_action_prompt`), action JSON parser (`parse_json_action`), and dataclasses. Coverage 30%.

### 6. `bot-sdk-python/src/arena_bot/actions.py` — 697 lines (cap 400)
41 thin verb-builder helpers — could split by category mirroring world-api action verbs (combat / movement / inventory / social / contract / etc.), or collapse into a single registry-driven module. Coverage 42%.

### 7. `bot-sdk-python/src/arena_bot/tool_dispatch.py` — 517 lines (cap 400)
Tool expansion + clamping + dispatch + budget enforcement in one module. Coverage 87% — splitting is safe.

### 8. Frontend pages over 300-line .tsx hard cap
- `frontend/src/app/heroes/[id]/page.tsx` — 584
- `frontend/src/app/deploy/page.tsx` — 510
- `frontend/src/components/ZoneMap.tsx` — 386
- `frontend/src/app/page.tsx` — 383

Multiple responsibilities per page (data fetching, layout, sub-section rendering).

### 9. World-api test infrastructure is broken
`world-api/Dockerfile` only `COPY`s `app/`, `alembic/`, `alembic.ini` — not `tests/`. `docker-compose.yml` does not bind-mount `./world-api/tests`. So `make test` (`docker compose exec world-api pytest`) finds no tests in the container. To run them I had to `docker compose cp world-api/tests world-api:/app/tests`. Fix: either bind-mount the tests dir in compose, or `COPY tests/` in the Dockerfile.

---

## 🟡 Warnings (fix soon)

### 10. Frontend `fetch()` calls scattered outside `src/lib/api.ts`
The rule says all HTTP goes through `api.ts`. Violations:
- `src/app/tools/page.tsx:68`
- `src/app/tools/[toolId]/page.tsx:32`
- `src/app/tools/gallery/page.tsx:36`
- `src/app/heroes/[id]/death/page.tsx:38`
- `src/app/compare/page.tsx:52`
- `src/components/showcase/CopyToolModal.tsx:24,47`

### 11. `world-api/app/core/tick.py` — 479 lines (soft cap 400)
Still single-purpose (TickEngine), but several late local imports (`from app.core.actions import _evict_expired_sandbox_heroes, tick_statuses` at line 213) are workarounds for the actions.py monolith — they'll dissolve once #1 is split.

### 12. `world-api/app/domains/manifest_validate/router.py` — 399 lines
Right at routes soft cap. `_walk_strings` helper and `VALID_VERBS` constant could move to `shared.py`. `VALID_VERBS` is the canonical action-verb list and arguably belongs in `app/core/`.

### 13. Domains missing service layer entirely
`bounty`, `contract`, `highlight`, `recipe`, `tournament`, `world_event`, `inspector`. They're routes-only today. Most are small enough that this is fine, but as they grow the rule says split.

### 14. Frontend BlockEditor lib files large but uncapped
- `yamlToBlocks.ts` — 559
- `exprParser.ts` — 466
- `blocksToYaml.ts` — 406
- `verbSpec.ts` — 397

No formal cap for non-component .ts in the rules — flagging because each handles a distinct concern that could be modularized.

### 15. `bot-sdk-python` borderline files
- `reflexes.py` — 342
- `tool_schema.py` — 315

Over 300 soft cap, under 400 hard. Watch.

### 16. Coverage gates not configured
No `pytest-cov` in any Python service's `pyproject.toml`, no `make test-cov` target, no CI gate. World-api container doesn't ship pytest in the production image (probably correct), but there's no clean "run coverage" path. Bot-sdk and llm-gateway also have no coverage tooling configured.

### 17. Pre-existing test failure
`world-api/tests/test_retriever.py::test_build_cq_enabled_but_unimportable_falls_through` — unrelated to architecture, but failing on `main`.

---

## 🟢 Good Patterns (keep doing this)

- **`llm-gateway` is exemplary.** All 5 files (config, signing, permission, providers, main) ≤ 153 lines, clean abstraction, no provider names outside `providers.py`, stateless, 74% coverage. Use as the template for slicing other services.
- **Cross-domain access is consistently via `*Service`**, not via repository or routes (`zone/router.py:15` imports `NPCService`, `manifest_validate/router.py:32` imports `HeroService`). This is the correct DDD seam.
- **`world-api/manifest_validate/tools_validator.py:25` imports parsing from `arena_bot.tool_schema`** — single source of truth for tool grammar across SDK and server. Drift risk eliminated.
- **`bot-sdk-python` does not import `world-api`** at all (✓ direction-of-dependency rule).
- **`bot-sdk-python/__init__.py`** exposes 5 deliberate symbols — public surface stays tiny and stable.
- **No `print()` in committed Python code** anywhere — logger is used consistently.
- **BlockEditor has property/round-trip tests** (`exprParser.test.ts`, `roundtrip.test.ts`) — exemplary for a dual-encoding format.

---

## 📊 Metrics

| Metric | Value |
|---|---|
| Files over **hard cap** | 9 (4 world-api, 4 frontend, 3 bot-sdk) |
| Files over **soft cap** (excluding hard-cap files) | 5+ |
| Layer violations (route → DB direct) | 2 routers, ~19 sites |
| DDD boundary violations | 0 |
| Cross-domain repo imports | 0 |
| Dead code instances | 0 surfaced |
| `print()` in committed code | 0 |
| Provider names outside `llm-gateway/providers.py` | 0 |
| `actions.py` line count | **3745** (god-file watch) |

### Coverage by service (target 70%)

| Service | Coverage | Status |
|---|---|---|
| world-api | **35%** | 🔴 fail (target 70%, critical-path floor 50%) |
| └ `actions.py` | **21%** | 🔴 critical (core target 80%) |
| └ `combat.py` | **13%** | 🔴 critical |
| └ `tick.py` | **29%** | 🔴 critical |
| bot-sdk-python | **62%** | 🟡 close |
| llm-gateway | **74%** | 🟢 pass |
| frontend | 2 test files (BlockEditor lib only) | 🟡 ungated |

---

## 🔧 Suggested Actions (priority order)

1. **[Critical]** Split `world-api/app/core/actions.py` into `app/core/actions/` package, one module per category (combat, contract, inventory, social, perception, sandbox, etc.) plus `_helpers.py`. The section comments already mark the seams. This will dissolve circular-import workarounds in `tick.py` and `combat.py` simultaneously.
2. **[Critical]** Fix the world-api test wiring: add `./world-api/tests:/app/tests` to the `world-api` service's `volumes:` in `docker-compose.yml`.
3. **[Critical]** Add a `service.py` to `showcase/` and move all 6 router-level DB queries into it; introduce a `repository.py` for the indexing/aggregation queries (`_most_copied`, `_aggregate_tool_calls`, `_david_tools`).
4. **[Critical]** Move the 13 direct `db.scalar/db.scalars` calls in `hero/router.py` into `HeroService` (already exists, under-used).
5. **[High]** Split `bot-sdk-python/client.py`: extract `build_action_prompt`/`build_tool_action_prompt` into `prompt.py`, `parse_json_action` + `Decision` into `parser.py`, leave the WS client in `client.py`.
6. **[High]** Split `world-api/app/core/models.py` per aggregate — one option is per-domain (`app/domains/<name>/models.py`), another is `app/core/models/{hero,quest,tool,...}.py`.
7. **[Medium]** Refactor 4 oversized frontend pages by extracting their sections into per-route `components/` subfolders.
8. **[Medium]** Move all 6 stray `fetch()` sites in frontend into `src/lib/api.ts`.
9. **[Medium]** Add `pytest-cov` to dev deps for `world-api`, `bot-sdk-python`, `llm-gateway`; add a `make test-cov` target.
10. **[Low]** Investigate the pre-existing `test_retriever.py` failure and either fix or skip with reason.
11. **[Low]** Promote `VALID_VERBS` from `manifest_validate/router.py` to `app/core/verbs.py` so SDK-side and server-side share the constant directly.

---

## Recommended starting point

The highest-leverage fix is **(1) actions.py split** — it unlocks the `tick.py`/`combat.py` late imports and makes coverage tractable. **(2) test wiring** is a one-line fix to `docker-compose.yml`. Recommended order: (2) → (1) → (3) → (4).
