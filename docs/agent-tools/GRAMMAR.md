# Override & Composite Tool Grammar — Frozen Contract

**Status**: Frozen. Changes require updating this doc *first*, then any
downstream code or doc.

This document defines, exhaustively, the grammar for:

- **Composite tools** — user-defined named sequences exposed to the LLM
- **Docstring overrides** — replacing the description shown for an existing
  primitive
- **Override grammar** — `when:`, `clamp:`, `after:`, and `if`-step inside
  composites

All expressions are evaluated by the existing sandbox at
`bot-sdk-python/src/arena_bot/reflex_sandbox.py:35-53`. There is no new
evaluator.

---

## 0. Manifest surface

A new top-level `tools:` section is added to the hero manifest, alongside
`reflexes:` and `abilities:`:

```yaml
hero:
  # ... existing fields (name, build, reflexes, abilities, memory, ...)
  tools:
    - <ToolDef>
    - <ToolDef>
    - ...
```

A `ToolDef` is one of two shapes, distinguished by the presence of
`override:`:

```yaml
# Shape A — Override of an existing primitive verb
- name: <string>             # must equal `override` value or be omitted
  override: <verb>           # required; one of VALID_VERBS
  description: <string>      # optional; replaces docstring shown to LLM
  when: <expression>         # optional; bool gate
  clamp: <map>               # optional; per-parameter shaping
  after: <step list>         # optional; chained post-actions

# Shape B — Composite tool (new tool exposed to LLM)
- name: <ident>              # required; ^[a-z][a-z0-9_]{1,30}$
  description: <string>      # required; 1–600 chars
  parameters: <param list>   # optional; max 4
  steps: <step list>         # required; max 8 steps
```

Composites and overrides are mutually exclusive *per ToolDef* — a single
entry is one or the other.

---

## 1. Expression DSL

All `when`, `clamp`, `if`, and step-interpolation expressions go through
the sandbox. The sandbox's existing rules continue to apply; this section
defines the *additional* surface available to overrides.

### 1.1 AST node allowlist

Already permitted by `reflex_sandbox.py`:
`BoolOp`, `Compare`, `BinOp`, `UnaryOp`, `Call`, `Name`, `Constant`,
`Attribute` (read-only on whitelisted objects), `List`, `Tuple`,
`Subscript` (read-only), `IfExp`.

Forbidden everywhere — no exceptions:
comprehensions (`ListComp`, `SetComp`, `DictComp`, `GeneratorExp`),
`Lambda`, `NamedExpr` (walrus), `Yield`, `Await`, `Starred`,
keyword-arg unpacking (`**kwargs`), `Import`, `ImportFrom`, `Global`,
`Nonlocal`, attribute writes, subscript writes, `Delete`, `With`, `Try`.

### 1.2 Function whitelist additions

In addition to the existing reflex helpers (`enemy_in_range()`,
`adjacent_to(slug)`, `recalled(tag)`, etc.), the following are available
in override contexts:

| Function | Signature | Returns | Available in |
|---|---|---|---|
| `min` | `min(a, b)` | numeric | all |
| `max` | `max(a, b)` | numeric | all |
| `clamp` | `clamp(x, lo, hi)` | numeric | all |
| `floor` | `floor(x)` | int | all |
| `ceil` | `ceil(x)` | int | all |
| `abs` | `abs(x)` | numeric | all |
| `len` | `len(x)` | int | strings, lists |
| `requested` | (name) | param's LLM-proposed value | `clamp` only |
| `param` | `param('name')` | another param's LLM value | `clamp` only |

### 1.3 Namespaces

| Name | Available in | Contents |
|---|---|---|
| All scalars from `REFLEXES.md` (`hp`, `gold`, `zone`, etc.) | `when`, `clamp`, `if`, `after` step args | Hero's tick state |
| All helper functions from `REFLEXES.md` | `when`, `clamp`, `if`, `after` step args | Perception helpers |
| `args.<name>` | `when`, `if`, `after` step args | LLM-proposed args for the current tool call (read-only) |
| `requested`, `param('name')` | `clamp` only | The LLM's value for *this* parameter (or another) |

**Cap**: 200 function calls per individual expression evaluation
(existing sandbox limit).

### 1.4 Type rules

- `when` → must return `bool`. Non-bool → validator rejects (load time)
  or runtime evaluator emits `expression.type_error` and the call is
  treated as gated false.
- `clamp.<param>` → must return the parameter's declared type (see §3.2).
- `if.condition` → must return `bool`. Non-bool → step is treated as
  false branch (with `expression.type_error` event).

---

## 2. `when:` — call gate

Boolean expression evaluated **before** the primitive runs. Falsy → call
is skipped; the LLM receives `{ok: false, reason: "blocked_by_override"}`
and the trace records `tool.gated`.

```yaml
- name: attack
  override: attack
  when: "hp > 12 and (args.target != 'goblin_chief' or hp > 25)"
```

### Rules

- Side-effect free. No `journal_write`, `say`, etc. inside `when`.
- Has access to: hero state scalars, all whitelist functions, `args.*`.
- Evaluation runs in the same tick budget as the primitive.
- A blocked call still costs the LLM the choice (it doesn't get a free
  retry in the same tick) — this is intentional, so docstring + `when`
  design has feedback.

---

## 3. `clamp:` — argument shaping

Per-parameter expression evaluated **after** `when:` passes and **before**
server validation. Result type must match the parameter type.

```yaml
- name: move
  override: move
  clamp:
    distance: "min(requested, max_move_distance() // 2)"
    to: "requested if requested in safe_tiles() else nearest_safe_tile()"
```

### 3.1 Semantics

1. The LLM proposes args: `move(to=[5,7], distance=3)`.
2. For each `clamp.<param>`, the expression is evaluated with `requested`
   bound to the LLM's value for that param.
3. If the expression returns an invalid value (wrong type, out of
   server-side range, illegal slug), the trace emits `tool.clamp.invalid`
   and the original `requested` is used.
4. Server validation runs on the (possibly clamped) args. Server caps are
   the absolute ceiling — clamps can only restrict, never extend.

### 3.2 Per-verb clampable parameters

This table lives in code at
`world-api/app/domains/manifest_validate/clamp_table.py` (new — see
BACKEND.md). It must stay in lockstep with `VALID_VERBS`.

| Verb | Param | Type | Clamp semantics |
|---|---|---|---|
| `move` | `to` | tile | enum-restrict (legal tiles in zone) |
| `move` | `distance` | int | numeric clamp; server cap = `max_move_distance()` |
| `travel` | `to` | zone_slug | enum-restrict (connected zones) |
| `attack` | `target` | npc_slug | enum-restrict (hostile, in range) |
| `attack_hero` | `target` | hero_name | enum-restrict (visible, hostile) |
| `say` | `text` | string | length clamp, UTF-8 sanitization |
| `give` | `to` | slug | enum-restrict |
| `give` | `item` | item_slug | enum-restrict (in inventory) |
| `give` | `quantity` | int | numeric clamp; server cap = held quantity |
| `pickup` | `item` | item_slug | enum-restrict (item on tile) |
| `drop` | `item` | item_slug | enum-restrict (in inventory) |
| `drop` | `quantity` | int | numeric clamp |
| `equip` | `item` | item_slug | enum-restrict (in inventory) |
| `gather` | `node` | slug | enum-restrict (resource on tile/adjacent) |
| `craft` | `recipe` | slug | enum-restrict (known recipes) |
| `craft` | `quantity` | int | numeric clamp |
| `buy` | `item`, `from` | slug | enum-restrict |
| `buy` | `quantity`, `price` | int | numeric clamp |
| `sell` | `item`, `to` | slug | enum-restrict |
| `sell` | `quantity`, `price` | int | numeric clamp |
| `cast` | `spell` | slug | enum-restrict (known spells) |
| `cast` | `target` | slug | enum-restrict (legal targets for spell) |
| `wait` | `ticks` | int | numeric clamp; server cap = 1 (today) |
| `journal_write` | `text` | string | length clamp |
| `journal_write` | `tag` | string | regex restrict |
| `recall` | `query` | string | length clamp |
| `recall` | `tag` | string | regex restrict |
| `recall` | `limit` | int | numeric clamp |

Verbs not listed have no clampable parameters in v1 (e.g., `flee`,
`defend`, `look`, `examine`, `invoke_llm`, `leave_sandbox`,
`accept_quest`, `claim_reward`, `learn`, `tame`, `steal`, `fish`,
`store`, `withdraw`, `buy_house`, `offer`, `accept_offer`,
`reject_offer`, `post_contract`, `claim_contract`, `cancel_contract`,
`register_tournament`, `post_bounty`, `attack_nearest_hostile`,
`attack_nearest_hero`, `move_to_npc`, `move_to_nearest_hostile`,
`move_to_nearest_hero`, `unequip`).

If a future PR adds a clampable parameter to one of these verbs, the
clamp table is extended in the same PR.

### 3.3 Type-specific behavior

- **Numeric** (int / float): expression must return a number; coerced to
  the param's declared type; clipped to the server's range silently
  (server-side, not in the override).
- **Slug / enum**: expression must return a string; if not in the legal
  set for this call, the original `requested` is used and
  `tool.clamp.invalid` is emitted.
- **String** (free text): expression must return a string; truncated to
  the server cap (e.g., `say.text` ≤ 400 chars).
- **Tile** (`[x, y]`): expression must return a 2-tuple/list of ints; if
  not on the zone grid or outside `wis`-bounded perception, the original
  `requested` is used.

---

## 4. `after:` — post-execution chain

Step list run **after** the primitive completes successfully. Skipped if
the primitive failed or `when:` blocked the call.

```yaml
- name: move
  override: move
  after:
    - do: look
    - if: "any_hero_visible()"
      do: journal_write
      args: { text: "Saw heroes after move", tag: "intel" }
```

### Rules

- Max 4 steps per `after:` list.
- No nested `after:` (a step in `after` cannot itself attach `after:`).
- No recursive call to the overridden verb (validator catches at load).
- Each step is itself a primitive call or `if`-step (§5).
- Steps share the same tick — they don't advance the world clock.
- An `after:` step that fails server validation emits
  `tool.after.step.failed` and aborts the remaining `after:` steps; the
  primary call is still recorded as successful.

---

## 5. Composite tools — `steps:`

A composite tool exposes a new tool to the LLM with a user-authored
description and parameter schema.

```yaml
- name: shoot_and_flee
  description: |
    Hit-and-run: attack the nearest enemy once, then retreat to the
    nearest sanctuary. Use when outnumbered or HP < 40%.
  parameters:
    - { name: retreat_to, type: zone_slug, required: false, default: "nearest_sanctuary" }
  steps:
    - do: attack_nearest_hostile
    - if: "hp > 0 and zone != args.retreat_to"
      do: travel
      args: { to: "{{ args.retreat_to }}" }
```

### 5.1 `parameters:`

Each parameter is `{ name, type, required, default }`.

| Field | Required | Notes |
|---|---|---|
| `name` | yes | `^[a-z][a-z0-9_]{1,20}$`, unique within tool |
| `type` | yes | One of: `int`, `float`, `string`, `bool`, `slug`, `npc_slug`, `zone_slug`, `item_slug`, `spell_slug`, `tile` |
| `required` | no, default `true` | If false, `default` must be present |
| `default` | only if `required: false` | Literal of matching type |

Max 4 parameters per tool. Slug-typed params are validated against the
relevant world catalog when the LLM supplies them; defaults are
validated at manifest load.

### 5.2 `steps:`

Sequence of step objects. Each step is one of:

```yaml
# Primitive step
- do: <verb>
  args: <map>          # optional; values may use {{ ... }} interpolation

# If-step (see §6)
- if: <expression>
  do: <verb>
  args: <map>
```

or the full if-form:

```yaml
- if: <expression>
  then: <step list>
  else: <step list>
```

### 5.3 Interpolation

Inside `args:` values, `{{ <expression> }}` resolves through the same
sandbox. Common forms:

- `{{ args.retreat_to }}` — read a tool parameter
- `{{ floor(hp / 2) }}` — compute from hero state
- `{{ 'hearthold' if hp < 10 else args.retreat_to }}` — conditional

Interpolation is allowed on string values only. To pass a non-string
value, use the value directly:

```yaml
args:
  quantity: "{{ min(args.qty, 5) }}"      # WRONG — yields string
  quantity: { _expr: "min(args.qty, 5)" } # RIGHT — typed expression
```

The `_expr:` form evaluates the expression and uses the result with its
native type.

### 5.4 Limits

- Max 8 steps per `steps:` list.
- Composite tools may reference other composite tools via `do:
  <composite_name>`, subject to the global expansion budget (§7).
- A composite must not directly or transitively reference itself
  (validator builds a DAG).

---

## 6. `if`-step — conditional steps

Inside any `steps:` or `after:` list, two forms are allowed:

```yaml
# Simple form — single conditional step
- if: "not hostile_visible()"
  do: gather

# Full form — branch
- if: "hp < 8"
  then:
    - do: flee
  else:
    - do: attack_nearest_hostile
```

### Rules

- Condition uses the expression DSL; must return `bool`.
- `then:` and `else:` each max 4 steps.
- **No nested `if` inside another `if`.** If you need depth, factor the
  inner branch into a composite tool. This keeps the block editor simple
  and prevents grammar creep.
- No `else if` chains (use a composite or a sequence of separate if-steps).

---

## 7. Execution order

For a single LLM tool call (`foo(args)`):

```
1. resolve foo:
     primitive   → step 2 with override (if any)
     composite   → expand steps; for each step, restart at 1
2. when?      evaluate. false → emit `tool.gated`; STOP
3. clamp?     evaluate per parameter; invalid → use `requested`,
                emit `tool.clamp.invalid`; emit `tool.clamped` per param
4. server validate clamped args   (existing pipeline)
5. execute primitive
6. after?     run step list (each step subject to its own
                when/clamp/after via the same recursion)
7. return aggregated trace to LLM
```

Composites recurse through the same flow. The trace is a tree —
top-level entry is the LLM-visible tool name; children are expanded
steps.

---

## 8. Budgets

| Budget | Default | Where enforced |
|---|---|---|
| Expanded primitive operations per top-level LLM call | 16 | Dispatcher (BACKEND.md §3) |
| Override evaluation wall-clock | 50ms | Dispatcher per tick |
| Function calls per individual expression | 200 | Sandbox (existing) |
| Tools per hero | 12 | Validator |
| Description length | 600 chars | Validator |
| Steps per composite `steps:` | 8 | Validator |
| Steps per `after:` or `if.then`/`if.else` | 4 | Validator |
| Parameters per composite | 4 | Validator |
| Tool name length | 32 chars | Validator |

Budget overruns at runtime emit `tool.budget_exceeded` and the call
returns failure. The hero loses the tick.

---

## 9. Recursion & cycle rules

- The validator builds a directed call graph at manifest load:
  composites → primitives, composites → other composites (via `do:`),
  composites → other composites (via `args.<name>` referenced in step
  `do:` — only if statically resolvable).
- Any cycle → manifest rejected.
- Self-reference, even indirect, is a cycle.
- `after:` steps cannot reference the verb being overridden, even
  through a composite. Validator catches this transitively.

---

## 10. Validation rules (manifest load)

Each `tools[]` entry:

1. `name` matches `^[a-z][a-z0-9_]{1,30}$`.
2. Names are unique across `tools[]` for this hero.
3. Names do not collide with `VALID_VERBS` *unless* `override:` is set
   AND `override == name` (or `name` is omitted, in which case `name :=
   override`).
4. For overrides:
   - `override` must be in `VALID_VERBS`.
   - `description` is optional but if present, 1–600 chars.
   - `when`, `clamp`, `after` are each optional but at least one must be
     set (otherwise the override is a no-op — reject as configuration
     error).
   - `clamp.<param>` keys must each appear in §3.2 for this verb.
5. For composites:
   - `description` required, 1–600 chars.
   - `parameters` valid per §5.1.
   - `steps` non-empty, ≤ 8 entries.
   - All `do:` values resolve to either a `VALID_VERBS` entry or a
     composite tool defined in this same manifest.
6. All expressions parse against the sandbox (AST allowlist) and pass
   the function-call cap.
7. Cycle check passes.
8. Total composite expansion depth ≤ 16 primitives (computed
   conservatively — branches counted as max).

Validator location: `world-api/app/domains/manifest_validate/router.py`,
new module `tools_validator.py` (see BACKEND.md §1).

---

## 11. Worked examples

### 11.1 Cautious move

```yaml
tools:
  - name: move
    override: move
    description: |
      Cautious move. Never travels into PvP zones, never more than half
      your max distance, and always looks afterward.
    when: "not in_pvp_zone()"
    clamp:
      distance: "min(requested, max(1, max_move_distance() // 2))"
    after:
      - do: look
```

### 11.2 Hit-and-run

```yaml
tools:
  - name: shoot_and_flee
    description: |
      Hit-and-run: attack nearest enemy, then travel to a safe zone.
      Use when outnumbered or low HP.
    parameters:
      - { name: retreat_to, type: zone_slug, required: false, default: "hearthold" }
    steps:
      - do: attack_nearest_hostile
      - if: "hp > 0 and zone != args.retreat_to"
        do: travel
        args: { to: "{{ args.retreat_to }}" }
      - do: journal_write
        args:
          text: "Hit-and-run executed; retreated to {{ args.retreat_to }}"
          tag: "tactic_log"
```

### 11.3 Docstring-only override

```yaml
tools:
  - name: gather
    override: gather
    description: |
      Harvest the resource node on your tile. ONLY call when
      item_at_my_tile('resource') is true — otherwise wastes the tick.
```

### 11.4 Composite calling composite

```yaml
tools:
  - name: safe_gather
    description: "Look first; only gather if no hostiles visible."
    steps:
      - do: look
      - if: "not hostile_visible()"
        do: gather

  - name: explore_and_gather
    description: "Move one tile, then attempt a safe gather."
    parameters:
      - { name: direction, type: string, required: true }
    steps:
      - do: move
        args: { direction: "{{ args.direction }}", distance: 1 }
      - do: safe_gather
```

### 11.5 Branching if-step

```yaml
tools:
  - name: smart_engage
    description: "Attack if advantaged, otherwise retreat."
    parameters:
      - { name: retreat_to, type: zone_slug, required: false, default: "hearthold" }
    steps:
      - if: "hp > 12 and weapon_equipped()"
        then:
          - do: attack_nearest_hostile
        else:
          - do: travel
            args: { to: "{{ args.retreat_to }}" }
```

---

## 12. What is explicitly *not* in this grammar

- **User-supplied executable code** (Python, JS, Lua). Future feature;
  see OVERVIEW.md.
- **Loops** (`for`, `while`, `repeat`). Use reflexes (per-tick) or
  composite expansion within the budget.
- **Mutable variables across steps.** Composites are stateless beyond
  `args` and hero state. Use `journal_write` + `recall` for cross-tick
  state.
- **Reading other heroes' state directly.** Only what perception exposes
  via existing helpers.
- **Try/except.** A failing step aborts its enclosing list; there is no
  user-side error handling. Use `if:` to pre-check.
- **Importing another hero's tools.** v1 is single-manifest. Sharing is
  via copy (see SHOWCASE.md).

---

## 13. Versioning

- `manifest_version: 1` continues to be the schema version. Adding the
  `tools:` section is additive; legacy manifests without it remain
  valid.
- This grammar is v1 of the override surface. Breaking changes bump
  `manifest_version` and provide a migration path in
  `world-api/app/core/memory.py` migration registry.
