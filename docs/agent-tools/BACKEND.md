# Backend — Validator, Dispatcher, Tool Spec Assembly

**Phases**: 2 (composite tools + docstring overrides) and 3 (`when` /
`clamp` / `after` / `if`-step). All work consumes the contract in
[GRAMMAR.md](./GRAMMAR.md).

This doc is the implementation spec for backend changes. Frontend work
is in [BLOCK_EDITOR.md](./BLOCK_EDITOR.md). Inspector backend endpoints
are in [INSPECTOR.md](./INSPECTOR.md).

---

## 1. Manifest validator

### 1.1 Files to touch / create

- **Touch**: `world-api/app/domains/manifest_validate/router.py`
  - Extend `validate_manifest` to call into a new `tools_validator`
    after existing reflex/abilities checks.
- **Create**: `world-api/app/domains/manifest_validate/tools_validator.py`
  - Top-level `validate_tools(tools_list, context) -> list[ValidationError]`.
  - All rules in GRAMMAR.md §10.
- **Create**: `world-api/app/domains/manifest_validate/clamp_table.py`
  - Source-of-truth table for clampable parameters per verb (GRAMMAR.md
    §3.2). Imported by both validator and dispatcher.
- **Touch**: `world-api/app/domains/manifest_validate/router.py` again
  - Expose the table as `GET /admin/verb-catalog` for the frontend's
    block-spec generator (BLOCK_EDITOR.md §8). Read-only, no auth.

### 1.2 Validator structure

```python
# tools_validator.py

@dataclass
class ToolsValidationContext:
    valid_verbs: set[str]
    composite_names: set[str]   # populated as we walk tools[]
    sandbox_evaluator: Sandbox  # from reflex_sandbox.py
    clamp_table: dict[str, dict[str, ClampSpec]]

def validate_tools(tools: list[dict], ctx: ToolsValidationContext) -> list[ValidationError]:
    errors = []
    # Pass 1: name uniqueness, shape (override vs composite), basic schema
    # Pass 2: per-tool deep validation (expressions, clamps, steps)
    # Pass 3: cycle detection (DAG of composite -> composite refs)
    # Pass 4: expansion-depth budget (≤ 16 primitives)
    return errors
```

### 1.3 Expression validation

Reuse the sandbox's parse function:

```python
from arena_bot.reflex_sandbox import parse_safe, SandboxError

try:
    ast = parse_safe(expr_str, allowed_funcs=OVERRIDE_FUNC_WHITELIST)
except SandboxError as e:
    errors.append(ValidationError(
        path=f"tools[{i}].when",
        message=str(e),
    ))
```

`OVERRIDE_FUNC_WHITELIST` extends the reflex whitelist with `min`,
`max`, `clamp`, `floor`, `ceil`, `abs`, `len`, `requested`, `param`
(GRAMMAR.md §1.2).

### 1.4 Type checking expressions

For `when` and `if.condition`, the validator does a *best-effort* return-type
check. Strategy:

- If the AST root is a `BoolOp`, `Compare`, `bool_*` literal, or a known
  bool-returning helper from REFLEXES.md → accept.
- Otherwise emit `expression.type_warning` (non-blocking). Runtime
  evaluation will assert and gate the call false.

For `clamp.<param>`, the validator looks up the param's type in
`clamp_table` and applies a similar surface check on the AST root.

### 1.5 Cycle detection

```python
def build_call_graph(composites: list[CompositeTool]) -> dict[str, set[str]]:
    graph = {}
    for c in composites:
        refs = set()
        for step in walk_steps(c.steps):
            if step.do in {x.name for x in composites}:
                refs.add(step.do)
        graph[c.name] = refs
    return graph

def detect_cycles(graph) -> list[list[str]]:
    # Tarjan's SCC; any SCC of size > 1 OR self-loop is a cycle.
    ...
```

### 1.6 Expansion-depth budget

For each composite, compute `max_depth` by recursive descent (with the
DAG already proven acyclic). Reject if any composite's max expansion
exceeds 16 primitives. Branches are counted as the *max* of their two
sides (worst case).

### 1.7 Error format

Validation errors flow through the existing `ValidationError` shape:

```json
{
  "path": "tools[2].clamp.distance",
  "code": "expression.parse_error",
  "message": "unexpected token at column 14",
  "severity": "error"
}
```

Frontend uses `path` to highlight the offending block (BLOCK_EDITOR.md §9).

---

## 2. Tool spec assembly

### 2.1 Files to touch

- **Touch**: `bot-sdk-python/src/arena_bot/tools.py`
  - `build_tool_specs(hero)` becomes per-hero. Today it's a fixed
    `DEFAULT_TOOLS` projection (`tools.py:55-122`).
  - New: `build_tool_specs_for_hero(hero, manifest_tools) -> list[ToolSpec]`.

### 2.2 Algorithm

```python
def build_tool_specs_for_hero(hero, manifest_tools):
    # Start from defaults
    specs = {t.name: spec_from_function(t) for t in DEFAULT_TOOLS}

    # Apply overrides (Shape A)
    for tool in manifest_tools:
        if tool.kind == "override":
            if tool.description:
                specs[tool.override].description = tool.description
            # `when`/`clamp`/`after` are dispatcher concerns, not visible
            # in the LLM-facing spec — but the description should hint
            # at constraints. The dispatcher enforces, the spec advises.

    # Append composites (Shape B)
    for tool in manifest_tools:
        if tool.kind == "composite":
            specs[tool.name] = ToolSpec(
                name=tool.name,
                description=tool.description,
                parameters=schema_from_params(tool.parameters),
            )

    return list(specs.values())
```

### 2.3 LLM tool spec format

Continue to emit the OpenAI-format tool spec used today:

```python
{
  "type": "function",
  "function": {
    "name": "shoot_and_flee",
    "description": "Hit-and-run: ...",
    "parameters": {
      "type": "object",
      "properties": {
        "retreat_to": {"type": "string", "description": "Zone to retreat to."}
      },
      "required": []
    }
  }
}
```

Slug-typed parameters render as `string` in the JSON schema, with the
description noting the constraint. Server-side validation handles slug
membership at dispatch.

### 2.4 Caching

Tool specs are computed once per hero per manifest version. Cache key:
`(hero_id, manifest_version_hash)`. Invalidated on manifest update.

---

## 3. Dispatcher

### 3.1 Files to touch

- **Touch**: `bot-sdk-python/src/arena_bot/actions.py`
  - The current verb-dispatch path becomes the inner core. Wrap it with
    override middleware.
- **Touch**: `bot-sdk-python/src/arena_bot/hero_runtime.py`
  - Composite expansion lives here (next to `abilities` expansion at
    lines 41-58). Reuse the same expansion infrastructure where possible.

### 3.2 Control flow

```python
def dispatch_llm_tool_call(hero, name, args, trace):
    """Top-level entry when LLM picks a tool."""
    budget = ExpansionBudget(max_primitives=16, deadline_ms=50)
    return _dispatch(hero, name, args, trace, budget)

def _dispatch(hero, name, args, trace, budget):
    if name in COMPOSITE_NAMES_FOR(hero):
        return _expand_composite(hero, name, args, trace, budget)
    # Primitive
    override = OVERRIDE_FOR(hero, name)
    if override:
        return _dispatch_with_override(hero, name, override, args, trace, budget)
    return _dispatch_primitive(hero, name, args, trace, budget)

def _dispatch_with_override(hero, name, override, args, trace, budget):
    # 1. when?
    if override.when_expr:
        ok = sandbox_eval_bool(override.when_expr, hero_state(hero), args=args)
        if not ok:
            trace.emit("tool.gated", {"tool": name, "reason": "when_false"})
            return ToolResult(ok=False, reason="blocked_by_override")
    # 2. clamp?
    if override.clamp:
        args = _apply_clamps(name, override.clamp, args, hero, trace)
    # 3. server validate + execute
    result = _dispatch_primitive(hero, name, args, trace, budget)
    # 4. after?
    if result.ok and override.after:
        for step in override.after:
            budget.charge_one()
            _dispatch_step(hero, step, args, trace, budget)
    return result

def _expand_composite(hero, name, args, trace, budget):
    composite = COMPOSITE_FOR(hero, name)
    trace.emit("tool.expanded", {"tool": name, "args": args})
    for step in composite.steps:
        if not budget.has_capacity():
            trace.emit("tool.budget_exceeded", {"tool": name})
            return ToolResult(ok=False, reason="budget_exceeded")
        result = _dispatch_step(hero, step, args, trace, budget)
        if not result.ok:
            return result  # composite aborts on first failure
    return ToolResult(ok=True)

def _dispatch_step(hero, step, parent_args, trace, budget):
    if "if" in step:
        cond = sandbox_eval_bool(step["if"], hero_state(hero), args=parent_args)
        branch = step.get("then" if cond else "else", [])
        if "do" in step and "then" not in step:
            branch = [{"do": step["do"], "args": step.get("args", {})}] if cond else []
        for inner in branch:
            _dispatch_step(hero, inner, parent_args, trace, budget)
        return ToolResult(ok=True)
    # Simple primitive step
    interp_args = _interpolate(step.get("args", {}), hero_state(hero), parent_args)
    budget.charge_one()
    return _dispatch(hero, step["do"], interp_args, trace, budget)
```

### 3.3 Clamp application

```python
def _apply_clamps(verb, clamps, args, hero, trace):
    out = dict(args)
    for param, expr in clamps.items():
        requested = args.get(param)
        try:
            value = sandbox_eval_value(
                expr, hero_state(hero),
                requested=requested,
                param=lambda n: args.get(n),
            )
            value = _coerce_to_param_type(verb, param, value)
            if not _is_legal_value(verb, param, value, hero):
                trace.emit("tool.clamp.invalid", {"verb": verb, "param": param})
                continue  # keep `requested`
            out[param] = value
            trace.emit("tool.clamped", {
                "verb": verb, "param": param,
                "from": requested, "to": value,
            })
        except SandboxError as e:
            trace.emit("tool.clamp.error", {"verb": verb, "param": param, "error": str(e)})
    return out
```

### 3.4 Interpolation

`{{ expr }}` and `{ "_expr": "..." }` resolve through the same sandbox
evaluator (GRAMMAR.md §5.3). String interpolation produces strings; the
`_expr` form returns the native value.

```python
def _interpolate(args, hero_state, parent_args):
    return {k: _interpolate_value(v, hero_state, parent_args) for k, v in args.items()}

def _interpolate_value(v, hero_state, parent_args):
    if isinstance(v, dict) and set(v.keys()) == {"_expr"}:
        return sandbox_eval_value(v["_expr"], hero_state, args=parent_args)
    if isinstance(v, str) and "{{" in v:
        return _interpolate_string(v, hero_state, parent_args)
    if isinstance(v, list):
        return [_interpolate_value(x, hero_state, parent_args) for x in v]
    if isinstance(v, dict):
        return _interpolate(v, hero_state, parent_args)
    return v
```

### 3.5 Budget

```python
@dataclass
class ExpansionBudget:
    max_primitives: int
    deadline_ms: int
    primitives_used: int = 0
    started_at: float = 0.0

    def has_capacity(self):
        return (
            self.primitives_used < self.max_primitives
            and (now_ms() - self.started_at) < self.deadline_ms
        )

    def charge_one(self):
        self.primitives_used += 1
```

Budget overrun emits `tool.budget_exceeded` and the call returns
failure. The hero loses the tick.

---

## 4. Sandbox additions

### 4.1 Files to touch

- **Touch**: `bot-sdk-python/src/arena_bot/reflex_sandbox.py`
  - Add `min`, `max`, `clamp`, `floor`, `ceil`, `abs`, `len` to the
    function whitelist.
  - Add support for the `requested` and `param('name')` bindings — these
    are *parameters* to `sandbox_eval_value`, not function calls in the
    AST. Pass them as `extra_names` in the evaluator's namespace.

### 4.2 New API surface on the sandbox

```python
def sandbox_eval_bool(expr: str, hero_state: dict, args: dict | None = None) -> bool:
    ...

def sandbox_eval_value(
    expr: str,
    hero_state: dict,
    args: dict | None = None,
    requested: Any | None = None,
    param: Callable[[str], Any] | None = None,
) -> Any:
    ...
```

Both functions:
- Build the namespace from hero_state + args (under `args.<name>`) +
  `requested` and `param` (when provided).
- Reuse the existing AST parser.
- Apply the existing 200-call cap.

### 4.3 Test additions

- `bot-sdk-python/tests/test_sandbox_overrides.py` — every helper from
  GRAMMAR.md §1.2, every type-check rule.

---

## 5. Trace events

All events flow through the existing event stream
(`world-api/app/core/events.py` — extend if needed).

| Event | When | Payload |
|---|---|---|
| `tool.expanded` | Composite begins expansion | `tool`, `args` |
| `tool.gated` | `when:` returned false | `tool`, `reason: "when_false"` |
| `tool.clamped` | A clamp produced a different value | `verb`, `param`, `from`, `to` |
| `tool.clamp.invalid` | Clamp returned illegal value | `verb`, `param` |
| `tool.clamp.error` | Clamp expression raised | `verb`, `param`, `error` |
| `tool.after.step` | Each `after:` step fires | `verb`, `step`, `result` |
| `tool.after.step.failed` | An `after:` step server-rejected | `verb`, `step`, `error` |
| `tool.budget_exceeded` | Budget overrun | `tool`, `primitives_used`, `elapsed_ms` |
| `tool.expression.type_error` | Runtime type check failed | `expr`, `expected`, `got` |

The Inspector (INSPECTOR.md) consumes these to render per-tool stats
and the "why didn't my tool fire?" debugger.

Trace events for a single LLM call are grouped under a `correlation_id`
that matches the LLM tool-call ID. This grouping is critical for the
inspector's tree view.

---

## 6. Server validation interplay

Server validation is unchanged: existing per-verb checks
(`world-api/app/domains/actions/`) run on whatever args the dispatcher
passes them. Clamps reduce the args' space before validation; they do
not bypass validation.

If a clamp produces a value the server still rejects (e.g., a tile
that's not in perception this tick), the server emits its existing
rejection event and the dispatcher records `tool.failed`. From the
LLM's perspective, the tool call failed. From the user's perspective,
their clamp passed but the server still didn't like the value.

---

## 7. SDK ergonomics (Python)

### 7.1 Files to touch

- **Touch**: `bot-sdk-python/src/arena_bot/manifest.py`
  - Schema updates to round-trip the new `tools:` section.
- **Create**: `bot-sdk-python/src/arena_bot/user_tools.py`
  - Decorators for local iteration.

### 7.2 Decorator API

```python
from arena_bot.user_tools import user_tool, override, when, clamp, after

@user_tool(description="Hit-and-run: attack nearest, retreat to sanctuary.")
def shoot_and_flee(retreat_to: ZoneSlug = "hearthold"):
    yield attack_nearest_hostile()
    yield travel(to=retreat_to)

@override("move", description="Cautious move; never PvP, half-distance, look after.")
@when("not in_pvp_zone()")
@clamp(distance="min(requested, max_move_distance() // 2)")
@after(lambda: [look()])
def move_override():
    pass
```

The decorators are convenience: they generate the same canonical YAML
the user would write by hand. CLI:

```
arena-bot manifest dump my_hero.py > hero.yaml
arena-bot manifest validate hero.yaml
```

The same server validator runs on both paths — there is no second source
of truth.

### 7.3 Local dry-run

```
arena-bot tools simulate hero.yaml --tool shoot_and_flee --args '{"retreat_to":"hearthold"}'
```

Runs the dispatcher against a synthetic hero state and prints the trace
tree. Used for local iteration before deploy.

---

## 8. Test plan

### 8.1 Unit tests

- `tests/manifest_validate/test_tools_validator.py`
  - All rules in GRAMMAR.md §10
  - Cycle detection: direct, indirect, self
  - Expansion-depth budget at the boundary
  - Per-verb clampable params (table-driven)

- `tests/dispatcher/test_overrides.py`
  - `when:` blocks call → `tool.gated`
  - `when:` passes → primitive runs
  - `clamp:` reshapes numeric / slug / string params
  - `clamp:` returns illegal → falls back to `requested`
  - `after:` runs in order; aborts on failure
  - Recursive composite respects budget

- `tests/dispatcher/test_composites.py`
  - Single-level composite expands and runs
  - Nested composite respects depth budget
  - `if`-step branches; nested `if` rejected at validate time
  - Interpolation: string form, `_expr` form, list/dict recursion

- `tests/sandbox/test_override_helpers.py`
  - `min`, `max`, `clamp`, `floor`, `ceil`, `abs`, `len`
  - `requested` resolution
  - `param('name')` resolution
  - 200-call cap honored

### 8.2 Integration tests

- `tests/integration/test_tools_end_to_end.py`
  - Deploy a hero with all five worked examples from GRAMMAR.md §11
  - Force LLM tool choices via test fixtures
  - Assert trace events for each: `tool.expanded`, `tool.gated`,
    `tool.clamped`, `tool.after.step`
  - Verify world state matches expectations after each tool call

### 8.3 Property tests

- `tests/property/test_round_trip.py`
  - Generate random valid manifests; assert validator accepts
  - Generate random invalid manifests; assert validator rejects with
    expected error code

### 8.4 Fixtures

- `tests/fixtures/heroes/with_overrides/` — derived from
  `bot-sdk-python/examples/` plus the GRAMMAR.md examples.

---

## 9. Migration for existing heroes

Heroes deployed before Phase 2 have no `tools:` section. The validator
treats this as `tools: []`. Tool spec assembly returns `DEFAULT_TOOLS`
unchanged. No migration required.

If a future grammar change requires a `manifest_version` bump, the
existing migration framework at `world-api/app/core/memory.py` (lines
135-150) handles the transformation.

---

## 10. Performance considerations

### 10.1 Tool spec assembly

`build_tool_specs_for_hero` is called once per LLM call per hero.
Cached per `(hero_id, manifest_version_hash)`. With ~1000 active heroes
and 6s ticks, expect a few hundred cache lookups per second; cache hit
ratio should be > 99%.

### 10.2 Sandbox eval

Per-tick budget: 50ms wall-clock for *all* override evaluation in a
single LLM tool call. The sandbox is interpreted Python AST evaluation,
roughly 5-50µs per simple expression. A composite with 16 expanded
primitives, each with `when` + 2 `clamp` + 4 `after` steps, evaluates
~80 expressions = a few ms in the worst case. Budget gives headroom.

### 10.3 Trace volume

Each LLM tool call produces 1-50 trace events. With ~1000 heroes
ticking at 6s and ~10% LLM call rate per tick, expect ~1500 events/sec
peak. Existing event stream handles this; if not, batch + compress in
the inspector ingestion path (INSPECTOR.md).

---

## 11. Phase split

### Phase 2 deliverables

- Manifest schema accepts `tools:` (composites + docstring-only
  overrides; **no** `when`/`clamp`/`after`/`if`-step yet).
- Validator handles composites and docstring overrides.
- Tool spec assembly applies overrides + appends composites.
- Dispatcher expands composites (no override middleware yet).
- Tests for the above.

This is a complete, shippable feature — composite tools work end to end
without the override grammar.

### Phase 3 deliverables

- Validator handles `when`, `clamp`, `after`, `if`-step.
- Sandbox additions (helper functions, `requested`, `param`).
- Dispatcher applies override middleware.
- Trace events for gating, clamping, after-chains.
- Tests for the above.

After Phase 3, the full GRAMMAR.md is live server-side. Phase 4
(BLOCK_EDITOR.md) extends the UI to expose it; Phase 5 (INSPECTOR.md)
exposes the resulting traces.

---

## 12. Acceptance checklist

### Phase 2

- [ ] `tools:` section parses, validates, and round-trips through the
      manifest API.
- [ ] Docstring overrides change the description the LLM sees (verified
      via `/admin/hero/<id>/tool-spec` — new debug endpoint).
- [ ] Composite tools appear in the LLM tool list with their
      user-authored description and parameter schema.
- [ ] LLM choosing a composite expands its steps and executes them
      sequentially, respecting the 16-primitive budget.
- [ ] Trace tree for a composite call has the parent + child structure
      defined in §5.
- [ ] All examples in GRAMMAR.md §11.3 (docstring-only) and §11.2
      (composite) execute correctly in integration tests.

### Phase 3

- [ ] `when:` gates calls and emits `tool.gated`.
- [ ] `clamp:` reshapes args per the per-verb table; emits `tool.clamped`.
- [ ] Invalid clamp values fall back to `requested` with
      `tool.clamp.invalid`.
- [ ] `after:` steps run in order, abort on failure with
      `tool.after.step.failed`.
- [ ] `if`-step branches in composites work for both simple and full
      forms.
- [ ] Budget overruns emit `tool.budget_exceeded` and return failure.
- [ ] All examples in GRAMMAR.md §11.1 (cautious move), §11.4
      (composite calling composite), §11.5 (branching) execute
      correctly.
