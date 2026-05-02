# Agent Tools — Overview

This directory specifies a feature group that turns *World of Agents* into a
showcase for the thesis **tool design is agent design**. It adds two
extensibility primitives to the manifest, a visual block editor over the
existing reflex DSL, and a tool-inspector layer that makes the
tool-design-as-lever lesson legible to spectators.

**Audience for this doc set**: engineers (human or agent) implementing the
feature in phases. Each doc is self-contained — read OVERVIEW first, then
the doc for the phase you're building.

---

## Thesis

In agent engineering, the tools you expose to a model and the way you
describe them are the dominant determinant of behavior — bigger than
prompt phrasing, bigger than which model you pick within a tier. World of
Agents is uniquely positioned to demonstrate this because:

- Heroes are public, comparable, and run on the same primitives.
- Permadeath + leaderboards make tool-design choices accountable.
- The reasoning trace is already first-class in the spectator UI.

Today, every hero shares the same fixed tool list (`DEFAULT_TOOLS` in
`bot-sdk-python/src/arena_bot/actions.py:684-697`). This feature group
opens *the description and composition layer* to users while keeping the
verb whitelist server-bound for fairness and security.

---

## What we are adding

### 1. Docstring overrides
Same primitive verb (`attack`, `gather`, `flee`), different description
shown to the LLM. Teaches: *the words you choose change the agent.*

### 2. Composite tools
User-named sequences of primitives, with an author-written docstring and
optional parameters, exposed to the LLM as new tools. `shoot_and_flee` is
a tool the LLM sees in its tool list. Teaches: *the right decomposition
makes hard problems trivial.*

### 3. Override grammar (`when` / `clamp` / `after` / `if`-step)
A small grammar — reusing the existing reflex sandbox — that lets users
gate, shape, and chain primitive calls without supplying executable code.
Teaches: *constraints are design.* Example: `move` that only travels half
your max distance and always `look`s after.

### 4. Block editor
A visual builder for reflexes, abilities, composites, and overrides that
round-trips with the canonical YAML manifest. Both views editable; YAML
is the source of truth.

### 5. Tool inspector + debugger
Per-hero panel showing every tool's call count, success rate, blocked
count, and expanded traces. Includes a "why didn't my tool fire?" view
that surfaces the descriptions the LLM saw at the point of choice.

### 6. Showcase layer
Tool leaderboards, copy-this-tool, side-by-side hero compare. The layer
that turns the feature into a portfolio-grade demonstration.

---

## What we are *not* adding (yet)

- **User-supplied executable code** (Python / JS / Lua). Needs WASM-style
  sandboxing, deterministic replay, CPU/memory budgets, fairness story.
  Future feature; the override grammar is shaped so this can layer in
  later without changing the user-facing schema.
- **New primitive verbs.** The `VALID_VERBS` whitelist in
  `world-api/app/domains/manifest_validate/router.py:38-48` remains the
  canonical capability surface. New verbs ship via repo PR as today.
- **Cross-hero memory or shared tools.** Each hero owns its tool layer.
- **Loops in step lists.** Reflexes already loop per tick; the per-tool
  step budget caps recursion.

---

## Doc map

| Doc | Phase | Audience |
|---|---|---|
| [OVERVIEW.md](./OVERVIEW.md) | — | Everyone — start here |
| [GRAMMAR.md](./GRAMMAR.md) | Phase 0 (must freeze first) | Backend + frontend |
| [BLOCK_EDITOR.md](./BLOCK_EDITOR.md) | Phases 1, 4 | Frontend |
| [BACKEND.md](./BACKEND.md) | Phases 2, 3 | Backend |
| [INSPECTOR.md](./INSPECTOR.md) | Phase 5 | Frontend + backend |
| [SHOWCASE.md](./SHOWCASE.md) | Phase 6 | Full stack |
| [ROLLOUT.md](./ROLLOUT.md) | All phases | Lead, planning |

GRAMMAR.md is the **frozen contract**. Every other doc consumes it. If a
phase needs a grammar change, that change lands in GRAMMAR.md *first* and
all downstream docs update accordingly.

---

## Touched surfaces (high-level)

| Layer | Files (representative — see per-phase docs for full lists) |
|---|---|
| Manifest schema | `world-api/app/domains/manifest_validate/router.py` |
| Reflex sandbox | `bot-sdk-python/src/arena_bot/reflex_sandbox.py` |
| Reflex evaluation | `bot-sdk-python/src/arena_bot/reflexes.py` |
| Tool spec assembly | `bot-sdk-python/src/arena_bot/tools.py` |
| Verb dispatch | `bot-sdk-python/src/arena_bot/actions.py` |
| Hero runtime / abilities | `bot-sdk-python/src/arena_bot/hero_runtime.py` |
| Memory + traces | `world-api/app/core/memory.py`, event stream |
| Deploy UI | `frontend/src/app/deploy/page.tsx` |
| Hero pages | `frontend/src/app/heroes/[id]/page.tsx` |

---

## Ground rules for implementers

1. **Read GRAMMAR.md before writing any code.** It is the contract.
2. **Never introduce a new evaluator.** All expressions go through the
   sandbox in `reflex_sandbox.py`. Add functions to its whitelist; do not
   build a parallel path.
3. **YAML is the source of truth.** The block editor must round-trip
   losslessly. Any block that can't serialize to canonical YAML doesn't
   ship.
4. **Server validation is the ceiling.** Clamps only restrict; they never
   extend capability past `VALID_VERBS` server-side checks.
5. **Trace everything.** Every override action emits a structured event
   so the inspector and the spectator UI can render what happened.
6. **Don't shadow built-ins silently.** A user tool that reuses a
   primitive verb name *must* declare `override:` explicitly.
