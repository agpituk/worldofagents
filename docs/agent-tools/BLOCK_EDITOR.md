# Block Editor — Frontend Spec

**Phases**: 1 (reflex blocks for existing grammar) and 4 (extends to
abilities, composites, overrides). YAML remains the source of truth.

This doc is the implementation spec for the visual builder users see at
`/deploy` and (read-only) on hero pages.

---

## 1. Goals

1. **Onboard non-YAML-fluent users** without dumbing down the model. A
   YAML editor stays alongside the blocks; both are authoritative-equal,
   both editable, both round-trip losslessly.
2. **Inspect other heroes' tools visually.** Every block kind has a
   read-only render mode that ships on hero pages.
3. **Surface the trade-offs.** Block parameters, type slots, and the
   live "first-tick simulation" panel make tool design tangible.

Non-goals:
- Replacing YAML.
- Full Turing-completeness in blocks. The grammar in
  [GRAMMAR.md](./GRAMMAR.md) is the cap.

---

## 2. Library choice

Use **Blockly** (`blockly@^11`) for the underlying block engine. Reasons:
- Handles serialization, type-slot validation, drag-and-drop, a11y,
  workspace management for free.
- We write only the block definitions and the YAML ↔ Blockly XML
  transformer.
- Mature read-only rendering mode for spectator views.

Alternative considered: hand-rolled DnD (`dnd-kit` + `zustand`). Faster
to start but slow to harden. Skip unless Blockly proves a deal-breaker.

Bundle impact: ~280KB gzipped. Acceptable; lazy-load only on `/deploy`
and hero pages.

---

## 3. Block kinds

All blocks have:
- A canonical YAML serialization (lossless both ways).
- A read-only rendering used in spectator views.
- A type-slot schema enforced by Blockly (an action slot only accepts
  action blocks; a condition slot only accepts boolean expressions; etc.).

### 3.1 Top-level container blocks

| Block | YAML maps to | Phase |
|---|---|---|
| `reflex` | `reflexes[]` entry | 1 |
| `ability` | `abilities[]` entry | 4 |
| `tool_composite` | `tools[]` entry, Shape B | 4 |
| `tool_override` | `tools[]` entry, Shape A | 4 |

### 3.2 Action / step blocks

One block per `VALID_VERBS` entry (44 today). Each block has typed slots
for that verb's parameters.

Special action block:
- `do_composite` — slot accepts a dropdown of composite tools defined in
  the same workspace; renders as a function call with arg slots.

### 3.3 Condition (boolean expression) blocks

| Block | Form | Phase |
|---|---|---|
| `cmp` | `<value> <op> <value>` (op ∈ `==`, `!=`, `<`, `<=`, `>`, `>=`) | 1 |
| `bool_and`, `bool_or` | n-ary | 1 |
| `bool_not` | unary | 1 |
| `in_op` | `<value> in <list>` | 1 |
| `helper_call` | one block per helper function from `REFLEXES.md` | 1 |
| `args_ref` | `args.<name>` (only valid in tool/composite contexts) | 4 |
| `requested_ref` | `requested` (only valid in `clamp` slots) | 4 |

### 3.4 Numeric / string / value blocks

| Block | Use |
|---|---|
| `int_literal`, `float_literal`, `str_literal`, `bool_literal` | Constants |
| `var_ref` | Hero state scalars (dropdown from REFLEXES.md scalars) |
| `arith` | `+`, `-`, `*`, `/`, `//`, `%` |
| `min_max` | `min(a, b)`, `max(a, b)`, `clamp(x, lo, hi)` (Phase 4) |

### 3.5 Override / control-flow blocks (Phase 4)

| Block | YAML key | Notes |
|---|---|---|
| `when_gate` | `when:` | Slot in `tool_override`; accepts a condition |
| `clamp_param` | `clamp.<param>:` | Slot per clampable param of overridden verb |
| `after_chain` | `after:` | Slot list of action blocks |
| `if_step` | `if:` step | Two flavors: simple (`if + do`) and full (`if + then + else`) |

### 3.6 Composite tool blocks (Phase 4)

`tool_composite` exposes:
- Name slot
- Description slot (multiline string)
- Parameters slot (list of `param_def` blocks)
- Steps slot (list of action / if-step blocks)

`param_def` is `{name, type, required, default?}` rendered as a tidy row.

---

## 4. Type system in Blockly

Slot type constants used to gate which block accepts which:

```
'Bool'         — condition slots
'Number'       — int/float-typed value slots
'String'       — text slots
'Slug'         — slug-typed slots (npc/zone/item/spell)
'Tile'         — [x, y] coords
'List<T>'      — typed list slots
'Action'       — any action block (top-level then/step)
'StepListItem' — action OR if_step
'ParamDef'     — only the param_def block fits
```

Blockly's `setCheck()` enforces these on connection.

Helper functions and verb arg slots advertise the right type
constraints. Example: the `move` action block's `distance` slot accepts
`Number`; its `to` slot accepts `Tile`.

---

## 5. YAML round-trip

Two functions in `frontend/src/lib/blockEditor/`:

```ts
yamlToBlocks(yaml: string): BlocklyXml
blocksToYaml(xml: BlocklyXml): string
```

Both are pure and deterministic.

### 5.1 Round-trip invariants

- `blocksToYaml(yamlToBlocks(y))` ≡ `y` for any *valid* manifest YAML
  (structurally equal — comments and key order may shift to canonical).
- `yamlToBlocks(blocksToYaml(x))` ≡ `x` for any block tree the editor
  can produce.
- Invalid YAML is rendered with a placeholder block (`unparseable_yaml`)
  that shows the raw text and prevents save until resolved. The editor
  must never silently drop user content.

### 5.2 Canonical YAML

The serializer always:
- Uses two-space indent.
- Quotes strings only when necessary.
- Preserves multiline blocks as `|` for descriptions and `bio`.
- Emits keys in this order at top level: `name`, `author`, `division`,
  `bio`, `build`, `models`, `model`, `reflexes`, `abilities`, `tools`,
  `memory`.
- Inside a `tools[]` override entry: `name`, `override`, `description`,
  `when`, `clamp`, `after`.
- Inside a `tools[]` composite entry: `name`, `description`,
  `parameters`, `steps`.

### 5.3 Expression strings

`when:`, `if.condition`, `clamp.<param>` are stored as Python expression
strings in YAML. The block editor parses them with a small expression
parser (in `frontend/src/lib/blockEditor/exprParser.ts`) that mirrors
the sandbox AST allowlist from
`bot-sdk-python/src/arena_bot/reflex_sandbox.py:35-53`.

If a user pastes YAML with an expression the block parser cannot
represent (e.g., a nested ternary), the editor shows a `raw_expression`
block displaying the source text verbatim. Save is allowed; the
expression remains canonical YAML.

---

## 6. UI layout

### 6.1 `/deploy` page (Phase 1 + 4)

```
┌─────────────────────────────────────────────────────────────┐
│ Header: Hero name, division, build summary                  │
├──────────────────────────────────┬──────────────────────────┤
│                                  │                          │
│   Block workspace (Blockly)      │   YAML editor (Monaco)   │
│                                  │                          │
│   - Toolbox on left              │   - Syntax highlighting  │
│   - Workspace center             │   - Lint errors gutter   │
│                                  │   - Both views write     │
│                                  │     to the same source   │
│                                  │     of truth via         │
│                                  │     debounced sync       │
├──────────────────────────────────┴──────────────────────────┤
│  Live preview panel                                         │
│  - Inferred archetype                                       │
│  - First-tick simulation (server-side dry run)              │
│  - Validator errors (real-time)                             │
└─────────────────────────────────────────────────────────────┘
```

Sync semantics:
- Both views debounce 250ms before propagating.
- Last-edited view wins on conflict.
- An "out of sync" banner appears if the parser or serializer fails.

### 6.2 Toolbox structure

Categorized for discoverability:

- **Reflexes** (Phase 1) — the `reflex` container + condition + action
- **Abilities** (Phase 4) — `ability` container + step blocks
- **Tools** (Phase 4) — `tool_composite`, `tool_override`
- **Conditions** — comparisons, booleans, helpers
- **Actions** — folded by category (combat, movement, items, social,
  economy, memory, special)
- **Values** — literals, arithmetic, hero-state vars
- **Control** — `if_step` (Phase 4)

### 6.3 Read-only mode (hero pages, Phase 1+)

`<HeroBlocksRO yaml={hero.manifest.tools_yaml} />` renders any block
container with editing disabled, drag handles hidden, and a "Copy as
YAML" button. Shipped on hero pages from Phase 1 (for reflexes) and
extended in Phase 4 to tools/abilities.

---

## 7. Files to create

### Phase 1

- `frontend/src/lib/blockEditor/index.ts` — public API
- `frontend/src/lib/blockEditor/yamlToBlocks.ts`
- `frontend/src/lib/blockEditor/blocksToYaml.ts`
- `frontend/src/lib/blockEditor/exprParser.ts`
- `frontend/src/lib/blockEditor/blocks/reflex.ts` — container
- `frontend/src/lib/blockEditor/blocks/conditions.ts`
- `frontend/src/lib/blockEditor/blocks/actions.ts` — generated from a
  canonical verb spec (see §8)
- `frontend/src/lib/blockEditor/blocks/values.ts`
- `frontend/src/lib/blockEditor/toolbox.ts`
- `frontend/src/lib/blockEditor/types.ts`
- `frontend/src/components/BlockEditor.tsx` — split-pane workspace
- `frontend/src/components/HeroBlocksRO.tsx` — read-only render
- `frontend/src/app/deploy/page.tsx` — extend to host BlockEditor
- `frontend/src/app/heroes/[id]/page.tsx` — embed HeroBlocksRO

### Phase 4 additions

- `frontend/src/lib/blockEditor/blocks/abilities.ts`
- `frontend/src/lib/blockEditor/blocks/tools.ts` — composite + override
- `frontend/src/lib/blockEditor/blocks/control.ts` — `if_step`,
  `when_gate`, `clamp_param`, `after_chain`

### Test fixtures (both phases)

- `frontend/src/lib/blockEditor/__tests__/roundtrip.test.ts` — every
  worked example from GRAMMAR.md §11 round-trips losslessly
- `frontend/src/lib/blockEditor/__tests__/exprParser.test.ts`
- `frontend/src/lib/blockEditor/__fixtures__/manifests/` — copy of
  `bot-sdk-python/examples/*.yaml` plus the GRAMMAR.md examples

---

## 8. Verb spec source of truth

Action blocks should *not* be hand-written one by one. Generate them
from a canonical spec:

`frontend/src/lib/blockEditor/verbSpec.ts` exports an array of
`VerbSpec` objects:

```ts
type VerbSpec = {
  verb: string;             // 'move'
  category: VerbCategory;   // 'movement'
  description: string;      // shown in toolbox
  params: ParamSpec[];      // typed slots
  clampable: string[];      // names of clampable params
};
```

This file is generated from the server's `VALID_VERBS` registry. A
build-time script
(`frontend/scripts/generate-verb-spec.ts`) hits a new
`world-api/admin/verb-catalog` endpoint (read-only, no auth required for
the public verb shape) and writes `verbSpec.ts`. Re-run on backend
schema changes.

This is the single point of update when verbs are added.

---

## 9. Validation in the editor

Two layers:

1. **Local (Blockly)**: type-slot mismatches prevent connection. Missing
   required parameter slots show a red ring.
2. **Server (real-time)**: on every debounced YAML change, POST to
   `world-api/manifest/validate` (already exists; extend to handle
   `tools:` section per GRAMMAR.md §10). Errors render in the YAML
   editor's gutter and as red badges on the offending blocks.

The block layer must communicate server errors back to specific blocks.
Achieved via stable block IDs in the YAML serializer:

```yaml
# Blocks emit YAML with line-anchored comments only in the editor's
# in-memory copy. The submitted manifest is comment-free. Mapping is
# kept in editor state, not in YAML.
```

The editor maintains a `BlockId → YAMLPath` map and translates server
errors with `path: "tools[2].clamp.distance"` into a highlight on the
corresponding block.

---

## 10. Read-only inspector mode (Phase 1+)

Used on hero pages, copy-this-tool dialogs (SHOWCASE.md), and the
debugger overlay (INSPECTOR.md). API:

```tsx
<HeroBlocksRO
  yaml={string}
  highlight?: { path: string; tone: 'success' | 'warn' | 'error' }[]
/>
```

Renders each top-level block with a "Copy YAML" + "Copy as code in my
editor" pair of buttons. Used heavily in SHOWCASE.

---

## 11. First-tick simulation panel (Phase 1, expanded Phase 4)

Below the editor, a panel shows: "If you deployed this hero now in
Hearthold, here's what would happen on tick 0."

Phase 1: reflex evaluation only (deterministic; no LLM call). Server
endpoint: `world-api/manifest/simulate-tick` (new). Returns:
- Which reflex fired (if any)
- The action it produced
- The result the world would compute
- Errors if any

Phase 4: extends to show:
- The tool list the LLM would receive (with applied docstrings)
- Which composite tools are available
- A "what tool would the LLM probably pick first" suggestion (cheap
  heuristic, *not* an LLM call — just shows tools whose `when:` would
  pass right now)

---

## 12. Acceptance criteria

### Phase 1

- [ ] Pasting any of `bot-sdk-python/examples/*.yaml` into the YAML pane
      produces a non-empty block workspace.
- [ ] Editing a reflex via blocks updates the YAML pane within 300ms.
- [ ] Editing the YAML pane updates the block workspace within 300ms.
- [ ] Round-trip identity: `blocksToYaml(yamlToBlocks(y)) ≡ y` for all
      example manifests (assertion in CI).
- [ ] Invalid YAML shows a recoverable error state; no data loss on the
      block side.
- [ ] Hero pages render reflexes as read-only blocks; spectator can copy
      individual reflex YAML to clipboard.
- [ ] First-tick simulation panel shows a sensible result for every
      example hero in their default starting tile.

### Phase 4 (additive)

- [ ] All worked examples in GRAMMAR.md §11 round-trip losslessly.
- [ ] `tool_override` block correctly enables/disables `clamp` slots
      based on the chosen verb's clampable params (§3.2 of GRAMMAR.md).
- [ ] `if_step` block supports both simple and full forms; toggling
      between them preserves user content where possible.
- [ ] `do_composite` block updates its dropdown live as the user adds
      composite tools.
- [ ] Server validation errors highlight specific blocks via stable IDs.

---

## 13. Open questions for the implementer

These are not blockers but should be revisited during implementation:

1. **Mobile**: Blockly's mobile DnD is workable but not great. Consider
   a read-only mode with a "switch to YAML" CTA on small screens.
2. **Dark mode**: Blockly themes are configurable but require a custom
   palette. Match the existing site's tokens.
3. **Undo / redo**: Blockly has its own stack. The YAML editor (Monaco)
   has its own. They should interoperate: an undo from either pane
   reverts the *unified* state by one step. Consider a wrapper that
   coalesces both stacks.
4. **Sharing partial blocks**: Phase 6 (SHOWCASE) wants users to share
   individual tools. Block IDs should be stable enough that sharing a
   single tool's YAML inserts correctly into another hero's workspace
   without ID collisions.
