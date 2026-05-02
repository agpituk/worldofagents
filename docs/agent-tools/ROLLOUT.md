# Rollout — Phased Delivery Plan

**Audience**: lead, planning, anyone scoping the next sprint.

This doc sequences the seven phases of the agent-tools feature group,
identifies dependencies, calls out the shippable deliverable per phase,
and flags risk. Each phase has a corresponding spec doc in this
directory.

---

## 1. Phase summary

| Phase | Title | Spec doc | Shippable on its own? |
|---|---|---|---|
| 0 | Grammar freeze | [GRAMMAR.md](./GRAMMAR.md) | N/A — gate |
| 1 | Block editor for existing reflex grammar | [BLOCK_EDITOR.md](./BLOCK_EDITOR.md) §3.1, §3.3, §3.4 | Yes — visible UI win |
| 2 | Backend: composites + docstring overrides | [BACKEND.md](./BACKEND.md) §1–§3, §11 (Phase 2 deliverables) | Yes — feature works via YAML |
| 3 | Backend: `when` / `clamp` / `after` / `if`-step | [BACKEND.md](./BACKEND.md) §4, §11 (Phase 3 deliverables) | Yes — full GRAMMAR live |
| 4 | Block editor extends to abilities + tools | [BLOCK_EDITOR.md](./BLOCK_EDITOR.md) §3.5, §3.6 | Yes — full UI parity |
| 5 | Tool inspector + debugger | [INSPECTOR.md](./INSPECTOR.md) | Yes — pedagogical payoff |
| 6 | Showcase layer | [SHOWCASE.md](./SHOWCASE.md) | Yes — community/network effects |

---

## 2. Dependency graph

```
                     ┌────────────┐
                     │  Phase 0   │
                     │  Grammar   │
                     └─────┬──────┘
                ┌──────────┴──────────┐
                │                     │
          ┌─────▼─────┐         ┌─────▼─────┐
          │  Phase 1  │         │  Phase 2  │
          │  Blocks   │         │  Backend  │
          │  (existing)         │  composites│
          └─────┬─────┘         └─────┬─────┘
                │                     │
                │              ┌──────▼──────┐
                │              │  Phase 3    │
                │              │  Override   │
                │              │  grammar    │
                │              └──────┬──────┘
                │                     │
                └──────────┬──────────┘
                           │
                     ┌─────▼─────┐
                     │  Phase 4  │
                     │  Blocks   │
                     │  (full)   │
                     └─────┬─────┘
                           │
                     ┌─────▼─────┐
                     │  Phase 5  │
                     │ Inspector │
                     └─────┬─────┘
                           │
                     ┌─────▼─────┐
                     │  Phase 6  │
                     │ Showcase  │
                     └───────────┘
```

Phases 1 and 2 are **parallelizable** once Phase 0 freezes — different
codebases (frontend vs backend) and Phase 1 only consumes the *existing*
reflex grammar, not the new tools surface.

Phase 4 needs both 1 and 3 (it extends the editor to cover the new
backend grammar).

Phase 5 needs 3 (for the trace events) and 4 (for `HeroBlocksRO`
extended to render tools).

Phase 6 needs 5 (the inspector data feeds showcase aggregations).

---

## 3. Phase details

### Phase 0 — Grammar freeze

**Goal**: Lock GRAMMAR.md as the contract. Get reviewers to agree it's
the schema we're building.

**Deliverables**:
- [ ] GRAMMAR.md reviewed and signed off.
- [ ] Per-verb clamp table reviewed for completeness.
- [ ] One example manifest hand-written for each grammar feature
      (overrides, composites, `when`, `clamp`, `after`, `if`-step) and
      added as fixtures.

**Owners**: lead + 1 backend + 1 frontend reviewer.

**Risk**: Low. Document-only.

**Exit criteria**: GRAMMAR.md merged to `main`.

---

### Phase 1 — Block editor for existing reflex grammar

**Goal**: Visible UI win. Round-trippable block editor for reflexes
only, no backend changes.

**Deliverables** (per BLOCK_EDITOR.md §7 Phase 1, §12 Phase 1):
- [ ] Blockly integrated, lazy-loaded on `/deploy`.
- [ ] Block kinds: reflex container, condition (cmp/and/or/not/in/helpers),
      action (one per VALID_VERB), value blocks.
- [ ] `yamlToBlocks` / `blocksToYaml` round-trip with CI assertion on
      all `bot-sdk-python/examples/*.yaml`.
- [ ] Split-pane on `/deploy`: Blockly + Monaco YAML editor with
      bidirectional sync.
- [ ] Read-only block render on hero pages for the reflexes section.
- [ ] First-tick simulation panel (reflex-only path).
- [ ] Frontend validator (real-time call to existing `/manifest/validate`).
- [ ] Verb-spec generator script (`scripts/generate-verb-spec.ts`).

**Owners**: 1–2 frontend.

**Risk**: Medium. Blockly + YAML round-trip is fiddly. Round-trip CI
assertion is the safety net.

**Exit criteria**:
- All Phase 1 acceptance items in BLOCK_EDITOR.md §12 pass.
- Existing manifests deploy unchanged through the new UI.
- A new user can author a reflex without seeing YAML.

---

### Phase 2 — Backend: composites + docstring overrides

**Goal**: Tools work end to end via YAML. No override grammar yet.

**Deliverables** (per BACKEND.md §11 Phase 2):
- [ ] `tools:` section parses, validates, persists.
- [ ] Validator handles composites (Shape B) and docstring-only
      overrides (Shape A with only `description`).
- [ ] Per-hero tool-spec assembly applies overrides + appends composites.
- [ ] Dispatcher expands composites with the 16-primitive budget.
- [ ] Trace events: `tool.expanded`, `tool.budget_exceeded`.
- [ ] Test suite per BACKEND.md §8.
- [ ] SDK: `@user_tool` decorator in `bot-sdk-python/src/arena_bot/user_tools.py`.
- [ ] CLI: `arena-bot manifest dump`, `arena-bot tools simulate`.

**Owners**: 1–2 backend.

**Risk**: Medium. Composite-of-composite expansion + budget accounting
needs careful testing. Cycle detection at validate time is the safety
net.

**Exit criteria**:
- All Phase 2 acceptance items in BACKEND.md §12 pass.
- A user can deploy a hero with a composite tool via YAML and see the
  LLM call it.

---

### Phase 3 — Backend: override grammar

**Goal**: Full GRAMMAR live server-side. `when` / `clamp` / `after` /
`if`-step all work.

**Deliverables** (per BACKEND.md §11 Phase 3):
- [ ] Sandbox additions: `min`, `max`, `clamp`, `floor`, `ceil`, `abs`,
      `len`, `requested`, `param('name')`.
- [ ] Validator handles `when`, `clamp`, `after`, `if`-step.
- [ ] Per-verb clamp table lives in code (`clamp_table.py`); accessible
      via `/admin/verb-catalog`.
- [ ] Dispatcher: override middleware (when → clamp → exec → after).
- [ ] `if`-step handling inside composites.
- [ ] Interpolation: `{{ ... }}` and `_expr:` forms.
- [ ] Trace events: `tool.gated`, `tool.clamped`, `tool.clamp.invalid`,
      `tool.clamp.error`, `tool.after.step`,
      `tool.after.step.failed`, `tool.expression.type_error`.
- [ ] Tests per BACKEND.md §8 (Phase 3 cases).

**Owners**: 1–2 backend (can be the same team as Phase 2; sequential).

**Risk**: Medium-high. The clamp + interpolation interplay has edge
cases. Property tests on round-trip + dispatcher trace shape are the
safety net.

**Exit criteria**:
- All Phase 3 acceptance items in BACKEND.md §12 pass.
- All worked examples in GRAMMAR.md §11 deploy and execute correctly.

---

### Phase 4 — Block editor full grammar

**Goal**: Block editor reaches grammar parity with YAML.

**Deliverables** (per BLOCK_EDITOR.md §7 Phase 4 additions, §12 Phase 4):
- [ ] Block kinds: ability container, tool_composite, tool_override,
      when_gate, clamp_param, after_chain, if_step (simple + full),
      args_ref, requested_ref, param_def, do_composite, min_max
      (clamp/min/max).
- [ ] `tool_override` dynamically enables/disables clamp slots based on
      the chosen verb.
- [ ] Server-error → block-highlight mapping via stable block IDs.
- [ ] First-tick simulation panel extended to show tool list (with
      applied descriptions) and "what tool would the LLM probably pick".
- [ ] Read-only renders for tools/abilities on hero pages.

**Owners**: 1–2 frontend (can overlap with Phase 5 frontend work).

**Risk**: Medium. The override block's dynamic clamp slots and the
nested step lists in composites are the main complexity.

**Exit criteria**:
- All Phase 4 acceptance items in BLOCK_EDITOR.md §12 pass.
- Every example in GRAMMAR.md §11 round-trips losslessly through the
  block editor.

---

### Phase 5 — Tool inspector + debugger

**Goal**: Make the tool design lever legible. Stats, traces,
why-didn't-fire.

**Deliverables** (per INSPECTOR.md §9):
- [ ] `<ToolListPanel>` on hero pages.
- [ ] `<ToolDetailDrawer>` with three tabs (Definition / Recent calls /
      Stats).
- [ ] `<TraceTree>` component with color coding and virtualization.
- [ ] `<WhyDidntMyToolFire>` debugger overlay + standalone deep-link
      page (`/heroes/[id]/ticks/[tick]`).
- [ ] Backend endpoints: `tools/summary`, `tools/{tool_name}`,
      `ticks/{tick}/llm-call`.
- [ ] LLM gateway persistence of `tools_offered` + `reasoning_trace`.
- [ ] Daily aggregation rollup table.

**Owners**: 1 backend + 1–2 frontend.

**Risk**: Medium. Trace volume could stress the events table; address
with rollups + 30s endpoint cache.

**Exit criteria**:
- All INSPECTOR.md §9 acceptance items pass.
- A spectator visiting any hero page can: see all tools with stats,
  expand a tool to inspect a recent call, and replay the LLM's choice
  on any specific tick.

---

### Phase 6 — Showcase layer

**Goal**: Community-scale leaderboards, copy-this-tool, side-by-side
compare. The argument layer.

**Deliverables** (per SHOWCASE.md §9):
- [ ] `/tools` leaderboard page with all six boards (§2.1).
- [ ] `/tools/{tool_id}` detail page.
- [ ] `/tools/gallery` discovery page.
- [ ] `/compare` multi-hero compare with tool diff.
- [ ] Copy + fork flows landing in the deploy editor.
- [ ] DB schema: `tool_definitions`, `hero_tools`, `tool_copies`.
- [ ] Daily rollups for leaderboards.
- [ ] Survival-lift stat with honesty tooltip.
- [ ] `hero.tool_visibility` opt-out.

**Owners**: 1 backend + 1–2 frontend + 1 designer for board UX.

**Risk**: Medium-low (technically straightforward) but the *content*
risks matter — see SHOWCASE.md §10.

**Exit criteria**:
- All SHOWCASE.md §9 acceptance items pass.
- The home page surfaces a "top tools this week" panel and drives
  meaningful traffic to `/tools`.

---

## 4. Suggested calendar (rough order-of-magnitude)

Numbers assume one full-time backend and one full-time frontend, plus a
tech lead for Phase 0 and design support. Adjust to your team.

| Phase | Wall-clock estimate | Notes |
|---|---|---|
| 0 | 0.5–1 week | Document-only; review-bound |
| 1 | 2–3 weeks | First visible win; ships at week ~3 |
| 2 | 2 weeks | Parallel with Phase 1 |
| 3 | 2 weeks | Sequential after Phase 2 |
| 4 | 2 weeks | Parallel with Phase 5 backend |
| 5 | 2–3 weeks | Frontend-heavy + LLM-gateway tweaks |
| 6 | 3 weeks | Most "feature surface" of any phase |

End-to-end: ~13–16 weeks for one team. Heavy parallelization could cut
4 weeks if you're staffed for it.

---

## 5. Risk register

| Risk | Phase | Likelihood | Mitigation |
|---|---|---|---|
| Grammar shifts after Phase 0 | All downstream | Medium | Strict gate: any change requires GRAMMAR.md edit + downstream impact note before code changes. |
| Blockly + YAML round-trip drift | 1, 4 | Medium | CI round-trip assertion on every example manifest. Block grammar is also documented. |
| Composite cycle / budget bug | 2, 3 | Medium | Cycle detection at validate time + property tests on dispatcher. Conservative depth budget. |
| Sandbox eval CPU spike under load | 3 | Low | 200-call cap (existing) + 50ms wall-clock per tick (new). Reflex sandbox is already production-tested at scale. |
| Trace event volume overwhelms events table | 5 | Medium | Per-event correlation_id + daily rollup. Sample debug-grade traces only on the latest N ticks per hero. |
| Leaderboard monoculture | 6 | Medium-high | Diverse-picks board + soft demotion of stale tools (SHOWCASE.md §10). |
| Survival-lift misread as causal | 6 | High | Explicit honesty tooltip; never headline the stat without context. |
| LLM gateway can't expose `tools_offered` | 5 | Low | Spike early in Phase 3 to confirm the gateway logs the right fields. If not, scope a small gateway PR before Phase 5. |

---

## 6. Cross-cutting concerns

These touch multiple phases and need a single owner across the project:

| Concern | Owner | Notes |
|---|---|---|
| Trace event schema | Backend lead | Defined in BACKEND.md §5; consumed by INSPECTOR + SHOWCASE. Don't change without coordinating. |
| Per-verb clamp table | Backend lead | `world-api/.../clamp_table.py`; read by validator (Phase 3), dispatcher (Phase 3), block editor's verb-spec generator (Phase 4). |
| Stable block IDs | Frontend lead | Needed for server-error → block-highlight (Phase 4) and copy-this-tool dedupe (Phase 6). Decide convention in Phase 1. |
| Spectator-visibility flag | Backend + Frontend | `hero.spectator_visibility` (INSPECTOR.md §4.3) and `hero.tool_visibility` (SHOWCASE.md §6) live in the same manifest; design them coherently. |
| LLM gateway persistence | LLM gateway maintainer | Phases 5 + 6 both depend on the gateway logging `tools_offered` and `reasoning_trace`. Spike in Phase 3. |

---

## 7. Done definition (whole feature group)

The feature group is "shipped" when:

- [ ] All seven phases pass their acceptance checklists.
- [ ] At least one hero on the live leaderboard uses a composite tool.
- [ ] At least 10 unique tools have been copied across heroes.
- [ ] A new player can deploy a hero with a custom tool inside 5
      minutes via the block editor (measured in usability test).
- [ ] The tool inspector receives ≥ 100 unique-spectator views per week.
- [ ] A "tool design = agent design" demo video can be recorded
      end-to-end using only the live UI (no slides).

Last item is the real bar. If we can record the demo, the project's
argument lands.

---

## 8. What to build first

If you have *one week* and need to demonstrate momentum:

1. Phase 0 (Grammar freeze) — ½ day of focused review.
2. Phase 1 reflex block editor (start; ship in 2 weeks).
3. Phase 2 backend composite + docstring (start; ship in 2 weeks).

Both Phase 1 and Phase 2 ship visible/functional value at the end of
sprint 1, and they're independent.

Phases 3 → 6 ladder from there; the path is well-defined and each is
its own clear sprint.
