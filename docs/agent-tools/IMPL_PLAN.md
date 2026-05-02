# Implementation Plan — Agent Tools Feature Group

**Status**: Active. Drives delivery of all 7 phases on `feature/agent-tools`.

This plan is the bridge between the spec set (`OVERVIEW.md`, `GRAMMAR.md`,
`BACKEND.md`, `BLOCK_EDITOR.md`, `INSPECTOR.md`, `SHOWCASE.md`,
`ROLLOUT.md`) and the actual code that lands. It records:

- The phase order I'm executing in.
- Divergences I found between specs and current code, plus how I'm
  resolving each.
- File-level deltas per phase.
- Scope reductions vs the full spec (this is delivered by one agent in
  one pass — polish and breadth get trimmed in favor of a working
  spine; trims are called out explicitly so a follow-up can pick them
  up).
- Test strategy.
- Commit cadence.

---

## 1. Phase order

| Order | Phase | Why this slot |
|---|---|---|
| 1 | **Phase 2** — backend composites + docstring overrides | Standalone shippable; unblocks the whole feature group. Pure backend, no UI dependency. |
| 2 | **Phase 3** — backend override grammar | Same surface as Phase 2; finishing the backend first means the frontend has a stable target. |
| 3 | **Phase 1** — block editor for existing reflex grammar | Frontend; depends on nothing new. UI win + foundation for Phase 4. |
| 4 | **Phase 4** — block editor extends to abilities + tools | Layers on Phase 1 + 3. |
| 5 | **Phase 5** — inspector + debugger | Needs Phase 3 trace events + Phase 4 read-only block render. |
| 6 | **Phase 6** — showcase | Builds on inspector aggregations. |

Phase 0 (grammar freeze) is already done — `GRAMMAR.md` is on `main`.

This is sequential, not parallel. ROLLOUT.md proposes Phase 1 + 2 in
parallel given two devs; with one agent, sequential is correct.

---

## 2. Divergences between spec and current code

The spec set was written against an idealized verb shape. The actual
code (`bot-sdk-python/src/arena_bot/actions.py:684-697`) and
`world-api/app/domains/manifest_validate/router.py:38-48` (`VALID_VERBS`)
diverge in places. Resolving each:

### 2.1 Verb signatures

| Verb | Spec param names | Actual signature | Resolution |
|---|---|---|---|
| `move` | `to`, `distance` | `target: list[int]` | Single `target` tile only. Drop `distance` from the clamp table; replace with `target` clamp (tile enum + `nearest_safe_tile()` semantics). The "half-distance" example in GRAMMAR.md §11.1 needs re-spec — convert to a `target` clamp that picks a nearer tile. |
| `give` | `to`, `item`, `quantity` | `target`, `item` | Use `target` not `to`; drop `quantity`. |
| `pickup` | `item` | `slug` | Use `slug` in clamp table. |
| `drop` | `item`, `quantity` | `slug` | Use `slug`; drop `quantity`. |
| `equip` | `item` | `slug` | Use `slug`. |
| `gather` | `node` | (no args) | Drop from clamp table. Gather is auto-resolved on tile. |
| `craft` | `recipe`, `quantity` | `recipe` | No `quantity`. |
| `say` | `text` | `message` | Use `message`. |
| `journal_write` | `text`, `tag` | `text`, `tags` (list) | Use `tags`; clamp via list-length + per-tag regex. |
| `recall` | `query`, `tag`, `limit` | `query`, `tags` (list), `limit` | Same. |
| `buy` | `item`, `from`, `quantity`, `price` | `target`, `item`, `qty` | Use `target`/`qty`; no `price` (not in signature). |
| `sell` | `item`, `to`, `quantity`, `price` | `target`, `item`, `qty` | Same. |
| `wait` | `ticks` | (no args) | Drop from clamp table. |
| `cast` | `spell`, `target` | matches | OK. |
| `attack`, `attack_hero` | `target` | matches | OK. |
| `accept_quest` | (not in clamp table) | `target` | Add `target` clamp. |
| `claim_reward` | (not in clamp table) | `quest` | Add `quest` clamp. |

**Decision**: `clamp_table.py` is built from the actual signatures in
`actions.py`, not from the GRAMMAR.md table. GRAMMAR.md §3.2 will get a
follow-up doc PR aligning with reality. The grammar shape (per-param
clamping, expressions in the sandbox) doesn't change.

### 2.2 Convenience verbs that don't exist as primitives

GRAMMAR.md examples reference `attack_nearest_hostile`,
`attack_nearest_hero`, `move_to_npc`, `move_to_nearest_hostile`,
`move_to_nearest_hero`. These are **not** in `DEFAULT_TOOLS` and **not**
in `VALID_VERBS`.

**Decision**: keep examples runnable by treating these as composite
shorthands. The Phase 2 worked example (`shoot_and_flee`) is written
using only real primitives — its first step `attack_nearest_hostile`
becomes either:

- A composite step that resolves to `attack` with a target picked from
  perception (out of scope for Phase 2 — too magical), **or**
- Replaced in the example with a plain `attack` step that takes a
  `target` parameter passed through from the composite's `parameters`.

I'll go with the second approach — explicit and aligned with primitives.
Update the integration test fixtures to reflect this.

### 2.3 Sandbox API

BACKEND.md §1.3 references `parse_safe(expr, allowed_funcs=...)`.
Actual API is `compile_safe(expr)` (`reflex_sandbox.py:65`). The
function whitelist is enforced via the eval namespace (no callable in
namespace = NameError at runtime), not via AST allowlist.

**Decision**: keep the existing model. Add new helpers (`min`, `max`,
`clamp`, etc.) into the eval namespace built by the dispatcher. The
"function whitelist" is implicit — whatever ends up in the namespace is
callable.

### 2.4 Missing `events.py` and `manifest.py`

- `world-api/app/core/events.py` doesn't exist. No central event bus.
  The existing tick path writes events via `world-api/app/core/tick.py`
  and gameplay-side modules.
- `bot-sdk-python/src/arena_bot/manifest.py` doesn't exist. Manifest
  parsing is inline in `world-api/app/domains/hero/service.py` (used by
  the validator) and in the SDK's manifest-loaded `HeroService`.

**Decision**:
- Trace events: emit through the existing event mechanism in `tick.py`
  / `actions.py`. Phase 5 inspector reads from there. If the volume
  warrants a dedicated `tool_events` table, add it in Phase 5.
- Manifest schema: extend `HeroService.parse_manifest` (path: see
  router.py:89) to accept `tools:` and round-trip it via `extras`. The
  SDK already loads YAML with `yaml.safe_load`; the new `tools:` key
  flows through automatically.

### 2.5 `hero_runtime.decide_one` shape

The current loop is reflex-eval → composite-expand (abilities) →
`invoke_llm`. Composite **tools** (Phase 2) are LLM-invoked, not
reflex-invoked. They need a new intercept point in the LLM dispatch
path.

**Decision**: the LLM wrapper in `bot-sdk-python/src/arena_bot/runner.py`
(SDK side) and `world-api/app/managed/runner.py` (server side) is where
tool-call results turn into actions. After parsing the LLM's tool call
into `(name, args)`, route through a new `tool_dispatch.py` module that:

1. Resolves whether `name` is a primitive, an override, or a composite.
2. For overrides: applies `when` → `clamp` → primitive → `after`.
3. For composites: expands `steps`, recursing.
4. Returns either a single primitive action dict (existing shape) or a
   queue of primitive action dicts.

The runtime then dispatches the queue through the same composite-queue
mechanism abilities already use (`HeroDecisionState.composite_queue`).
This is the smallest functional intercept that respects the existing
parity contract between SDK and managed runtimes.

### 2.6 VALID_VERBS missing `invoke_llm`

`invoke_llm` is referenced in `hero_runtime.py:180` but is not in
`VALID_VERBS`. It's a meta-verb the runtime intercepts. The validator
must not treat composites containing `invoke_llm` steps as valid —
composites can only chain primitives.

**Decision**: add `invoke_llm` to a separate `META_VERBS` set in the
validator; reject any composite step `do: invoke_llm`. Tool overrides
are also rejected on `invoke_llm`.

---

## 3. Per-phase concrete plan

### Phase 2 — backend composites + docstring overrides

**Files to create**:

- `world-api/app/domains/manifest_validate/tools_validator.py`
  - `validate_tools(tools_list, ctx) -> list[Issue]`
  - Pass 1: shape (override vs composite), name regex/uniqueness/no-shadow.
  - Pass 2: composite parameters (≤4, type valid, default valid).
  - Pass 2: composite steps (≤8, all `do:` resolve, no `invoke_llm`).
  - Pass 3: cycle detection (Tarjan SCC).
  - Pass 4: expansion-depth budget (≤16 primitives, branches counted as max).
  - Phase 2 only: reject any `when:`, `clamp:`, `after:`, `if`-step
    with a clear error pointing at IMPL_PLAN section.

- `bot-sdk-python/src/arena_bot/tool_dispatch.py`
  - `expand_tool_call(name, args, hero_tools, perception) -> list[ActionDict]`
  - Phase 2: composite expansion + docstring override (override only
    affects the LLM-facing description; runtime is a no-op pass-through
    for the verb name).
  - `ExpansionBudget` dataclass with `max_primitives=16`.
  - Cycle / depth re-checked at runtime as a defense-in-depth (validator
    catches at load).

**Files to touch**:

- `world-api/app/domains/manifest_validate/router.py`
  - Wire `validate_tools` into the existing flow.
  - Extend `VALID_VERBS` lint to include composite tool names from the
    manifest's own `tools:` list (so a reflex `do: shoot_and_flee` is
    accepted if `shoot_and_flee` is a composite).

- `bot-sdk-python/src/arena_bot/tools.py`
  - Add `build_tool_specs_for_hero(default_fns, manifest_tools) ->
    list[ToolSpec]`.
  - Apply Shape A (override): replace `description` only.
  - Append Shape B (composite): build a synthetic spec from name +
    description + parameters.

- `bot-sdk-python/src/arena_bot/runner.py` and
  `world-api/app/managed/runner.py`
  - After `on_invoke_llm` returns the action, if `action["do"]` is a
    composite tool name, expand via `tool_dispatch.expand_tool_call`.
  - Push the resulting primitive action queue into
    `HeroDecisionState.composite_queue` (reusing the abilities path).
  - First step is returned to the caller; rest queue.

**Trace events** (Phase 2 subset):
- `tool.expanded` — composite begins; payload `{tool, args, depth}`.
- `tool.budget_exceeded` — depth/wall-clock exceeded; payload
  `{tool, primitives_used, elapsed_ms}`.

Emit via existing tick-event mechanism (extend
`world-api/app/core/tick.py` `event_log` or whatever the current
sink is — confirm during impl).

**Tests**:
- `bot-sdk-python/tests/test_tool_dispatch.py`
  - Composite expands single-level + nested; respects budget.
  - Cycle detection rejects A→B→A at validate; defense-in-depth at
    runtime emits `tool.budget_exceeded`.
- `world-api/tests/test_tools_validator.py`
  - All Phase 2 rules in GRAMMAR.md §10 (subset 1, 2, 3, 5).
  - `when`/`clamp`/`after` rejected with phase-2-not-yet error.
- `bot-sdk-python/tests/test_tool_specs_per_hero.py`
  - Override replaces description.
  - Composite appears in spec list with correct schema.

**SDK ergonomics** (best-effort):
- `bot-sdk-python/src/arena_bot/user_tools.py` — `@user_tool`,
  `@override` decorators; full decorator suite is Phase 3 since `@when`,
  `@clamp`, `@after` need the override grammar.
- CLI `arena-bot tools simulate` deferred to Phase 3 (low ROI in
  Phase 2 because composite steps don't have gates yet).

### Phase 3 — backend override grammar

**Files to create**:

- `world-api/app/domains/manifest_validate/clamp_table.py`
  - Static dict mapping verb → param → ClampSpec (type, semantics,
    server cap function name).
  - Built from actual `actions.py` signatures (see §2.1).

- `world-api/app/domains/manifest_validate/override_validator.py` (or
  inline into `tools_validator.py`)
  - Validate `when`, `clamp.<param>`, `after`, `if`-step expressions
    using the existing sandbox `compile_safe`.
  - Type-check `when` / `if.condition` returns bool (best-effort AST
    surface check; runtime will assert).
  - Reject `clamp.<param>` for params not in the clamp table for that
    verb.

**Files to touch**:

- `bot-sdk-python/src/arena_bot/reflex_sandbox.py`
  - Add `min`, `max`, `clamp` (`clamp(x, lo, hi)` 3-arg), `floor`,
    `ceil`, `abs`, `len` to a default helper namespace exported as
    `OVERRIDE_HELPERS`.
  - Add `sandbox_eval_value(expr, namespace, *, requested=None,
    param_lookup=None)` and `sandbox_eval_bool(expr, namespace)`
    convenience entry points. Both use the existing `compile_safe`
    + `CallCounter` machinery.

- `bot-sdk-python/src/arena_bot/tool_dispatch.py`
  - Add override middleware:
    1. `when_expr` → eval bool; false → `tool.gated`, return
       `{ok: False, reason: blocked_by_override}`.
    2. `clamp` → per-param eval with `requested` bound; coerce + check
       against clamp_table; emit `tool.clamped` / `tool.clamp.invalid`
       / `tool.clamp.error`.
    3. Primitive runs (existing path).
    4. `after` → run step list; each step itself a primitive call or
       `if`-step.
  - `if`-step inside composite `steps:` (both simple and full forms).
  - `{{ expr }}` interpolation on string args; `{_expr: ...}` form for
    typed args.

**Trace events** (Phase 3):
- `tool.gated`, `tool.clamped`, `tool.clamp.invalid`, `tool.clamp.error`
- `tool.after.step`, `tool.after.step.failed`
- `tool.expression.type_error`

**Tests**:
- `bot-sdk-python/tests/test_sandbox_overrides.py` — every helper +
  `requested` + `param('name')`; 200-call cap honored.
- `bot-sdk-python/tests/test_tool_dispatch_overrides.py` — all five
  GRAMMAR.md §11 examples deploy + execute correctly.
- `world-api/tests/test_clamp_table.py` — every clampable param
  declared has a server-side validator hook somewhere.

**SDK ergonomics**:
- Round out `user_tools.py` decorators (`@when`, `@clamp`, `@after`).
- `arena-bot tools simulate` CLI: dispatcher dry-run against a
  synthetic perception.

**Admin endpoint**:
- `GET /admin/verb-catalog` returning the clamp table + verb shapes.
  Used by the block editor's verb-spec generator (Phase 4). Read-only,
  no auth.

### Phase 1 — block editor for existing reflex grammar

**Files to create** (frontend):

- `frontend/src/lib/blockEditor/index.ts`
- `frontend/src/lib/blockEditor/yamlToBlocks.ts`
- `frontend/src/lib/blockEditor/blocksToYaml.ts`
- `frontend/src/lib/blockEditor/exprParser.ts`
- `frontend/src/lib/blockEditor/blocks/reflex.ts`
- `frontend/src/lib/blockEditor/blocks/conditions.ts`
- `frontend/src/lib/blockEditor/blocks/actions.ts` (generated)
- `frontend/src/lib/blockEditor/blocks/values.ts`
- `frontend/src/lib/blockEditor/toolbox.ts`
- `frontend/src/lib/blockEditor/types.ts`
- `frontend/src/lib/blockEditor/verbSpec.ts` (generated; manual seed
  for Phase 1 if no admin endpoint yet)
- `frontend/src/components/BlockEditor.tsx`
- `frontend/src/components/HeroBlocksRO.tsx`
- `frontend/scripts/generate-verb-spec.ts`

**Files to touch**:

- `frontend/src/app/deploy/page.tsx` — split-pane workspace.
- `frontend/src/app/heroes/[id]/page.tsx` — embed `<HeroBlocksRO>`.

**Library**: `blockly@^11`, lazy-loaded (`next/dynamic`) only on
`/deploy` and hero detail.

**Round-trip CI**:
- Vitest test asserts `blocksToYaml(yamlToBlocks(y)) ≡ y` for all of
  `bot-sdk-python/examples/*.yaml`.

**Scope reduction vs spec**:
- First-tick simulation panel (BLOCK_EDITOR.md §11) trimmed to a stub
  that just renders the parsed manifest; full server-side dry-run
  endpoint becomes a Phase 4/5 follow-up.
- Mobile / dark-mode polish: leave default Blockly theme.

### Phase 4 — block editor extends to abilities + tools

**Files to create**:
- `frontend/src/lib/blockEditor/blocks/abilities.ts`
- `frontend/src/lib/blockEditor/blocks/tools.ts`
- `frontend/src/lib/blockEditor/blocks/control.ts` (`if_step`,
  `when_gate`, `clamp_param`, `after_chain`, `args_ref`,
  `requested_ref`, `param_def`, `do_composite`, `min_max`)

**Files to touch**:
- `frontend/src/components/BlockEditor.tsx` — toolbox extended.
- `frontend/src/components/HeroBlocksRO.tsx` — render new block kinds.
- `frontend/scripts/generate-verb-spec.ts` — fetch `/admin/verb-catalog`
  for clamp slots.

**Acceptance**: every example in GRAMMAR.md §11 round-trips losslessly.

### Phase 5 — inspector + debugger

**Files to create** (backend):
- `world-api/app/domains/inspector/__init__.py`
- `world-api/app/domains/inspector/router.py`
  - `GET /api/heroes/{hero_id}/tools/summary`
  - `GET /api/heroes/{hero_id}/tools/{tool_name}`
  - `GET /api/heroes/{hero_id}/ticks/{tick}/llm-call`
- `world-api/app/domains/inspector/aggregations.py` — daily rollup.

**Files to create** (frontend):
- `frontend/src/components/inspector/ToolListPanel.tsx`
- `frontend/src/components/inspector/ToolDetailDrawer.tsx`
- `frontend/src/components/inspector/TraceTree.tsx`
- `frontend/src/components/inspector/WhyDidntMyToolFire.tsx`
- `frontend/src/lib/api/inspector.ts`
- `frontend/src/app/heroes/[id]/ticks/[tick]/page.tsx`

**Files to touch**:
- `frontend/src/app/heroes/[id]/page.tsx` — mount panels.
- `frontend/src/components/EventStream.tsx` — "debug this choice" button.
- LLM gateway path — confirm `tools_offered` and `reasoning_trace` are
  persisted (likely already are; check during impl).

**Scope reduction**:
- `ToolStatsChart.tsx` (histograms, tick distribution) — start with a
  table view, charts are follow-up.

### Phase 6 — showcase

**Files to create** (backend):
- `world-api/app/domains/showcase/router.py`
- `world-api/app/domains/showcase/leaderboards.py`
- `world-api/app/domains/showcase/copy.py`
- `world-api/app/domains/showcase/aggregations.py`
- `world-api/alembic/versions/<rev>_tool_definitions.py` —
  `tool_definitions`, `hero_tools`, `tool_copies` tables.

**Files to create** (frontend):
- `frontend/src/app/tools/page.tsx`
- `frontend/src/app/tools/[toolId]/page.tsx`
- `frontend/src/app/tools/gallery/page.tsx`
- `frontend/src/app/compare/page.tsx`
- `frontend/src/components/showcase/Leaderboard.tsx`
- `frontend/src/components/showcase/ToolCard.tsx`
- `frontend/src/components/showcase/CopyToolModal.tsx`
- `frontend/src/components/showcase/CompareGrid.tsx`
- `frontend/src/components/showcase/ToolDiffPanel.tsx`

**Files to touch**:
- `frontend/src/app/page.tsx` — top tools panel.
- `frontend/src/app/deploy/page.tsx` — paste-from-copy flow.
- `frontend/src/components/inspector/ToolDetailDrawer.tsx` — link to
  showcase page.

**Scope reduction**:
- Six leaderboards in spec; ship two well (most-copied, best-success).
  Others stub with "coming soon" tabs.
- Gallery's category inference: simple keyword match only (per spec
  v1).
- Survival-lift methodology stat: include but mark as "experimental"
  with the honesty tooltip even more prominent than spec.

---

## 4. Test strategy

| Layer | Backbone | Where |
|---|---|---|
| Validator unit tests | All GRAMMAR.md §10 rules | `world-api/tests/test_tools_validator.py` |
| Sandbox unit tests | Helpers, `requested`, `param('name')`, 200-cap | `bot-sdk-python/tests/test_sandbox_overrides.py` |
| Dispatcher unit tests | Composite expand, override middleware, budgets | `bot-sdk-python/tests/test_tool_dispatch.py` |
| Integration tests | All 5 GRAMMAR.md §11 examples | `world-api/tests/test_tools_end_to_end.py` |
| Frontend round-trip | All `bot-sdk-python/examples/*.yaml` | `frontend/src/lib/blockEditor/__tests__/roundtrip.test.ts` |
| Frontend block kinds | One assertion per block + serialization | Same dir |

**Property tests** (BACKEND.md §8.3) on random-valid + random-invalid
manifests: deferred — high ROI but bigger investment than the spine
needs. Add in a follow-up if validator regressions show up.

---

## 5. Commit cadence

One commit per logical milestone, never bigger than ~500 LOC of net
change. Per phase, expect ~5–10 commits:

- `phase2: scaffold tools_validator + tool_dispatch`
- `phase2: composite expansion + budget`
- `phase2: tool spec assembly per hero`
- `phase2: SDK runner integration`
- `phase2: tests + integration fixtures`
- `phase3: clamp_table + sandbox helpers`
- `phase3: when/clamp/after middleware`
- `phase3: if-step + interpolation`
- `phase3: tests`
- ... etc.

Push at phase boundaries. PRs are out of scope for this delivery —
this lands as a single feature branch the user can review whole.

---

## 6. Open decisions to revisit during impl

1. **Trace event sink**: extend `tick.py` event log vs a new
   `tool_events` table. Decision deferred to first event emission in
   Phase 2; pick whichever has the least surface area.
2. **Composite-of-composite expansion**: depth-first vs queue-flatten.
   Spec says depth-first (recurse). Going with that — simpler trace
   tree, matches `if`-step semantics.
3. **`hero.spectator_visibility` and `hero.tool_visibility`**: defined
   in INSPECTOR.md §4.3 and SHOWCASE.md §6 separately. Coalesce into
   one `hero.visibility` block to avoid two flags users must remember.
4. **Survival-lift query cost**: matched-pair join on division +
   starting zone could be expensive. If so, materialize as a daily
   rollup or drop the stat from v1.
5. **Frontend bundle size**: Blockly is 280KB gzipped; lazy-loading
   should keep `/heroes/*` light, but verify.

These will surface in commits as TODO comments or follow-up tasks if
they bite.

---

## 7. Done definition for this delivery

The full feature group's done definition is in ROLLOUT.md §7. For
*this* implementation pass on `feature/agent-tools`:

- All 7 phases land as commits.
- Backend tests pass for Phase 2 + 3 spine.
- Frontend type-checks and the round-trip CI assertion passes.
- All 5 GRAMMAR.md §11 worked examples deploy and execute end-to-end.
- IMPL_PLAN.md updated with anything that diverged from this plan
  during execution.

Items explicitly outside this pass:
- Production traffic load testing.
- Full property test suite.
- Six leaderboards (two ship, four are stubs).
- LLM-gateway gateway-side persistence work if the existing path
  doesn't already log `tools_offered` (separate PR if so).
