# Tool Inspector & Debugger

**Phase**: 5. Depends on Phase 2 + 3 (backend tools + override grammar)
and Phase 1 + 4 (block editor + read-only block render).

This is where the project earns the thesis. Players (and spectators)
must be able to *see* that a docstring change moved the LLM's behavior,
that a `when:` clause blocked an attack at the right moment, that a
`clamp:` traded raw capability for safety. Without the inspector, the
feature ships as plumbing nobody can read.

---

## 1. Surfaces

Three views, each on the existing hero page or as an overlay:

1. **Tool list panel** — sidebar on every hero page; lists every tool
   the hero exposes with at-a-glance stats.
2. **Tool detail drawer** — opens when a tool is clicked; shows the
   block render, full description, recent traces, and aggregated stats.
3. **"Why didn't my tool fire?" debugger** — overlay on a single LLM
   tick; shows the tool list the LLM saw, the descriptions, the choice,
   and (where data permits) why competing tools were not chosen.

---

## 2. Tool list panel

Sidebar on `frontend/src/app/heroes/[id]/page.tsx`, below the existing
stats panel.

```
TOOLS (12)
─────────────────────────────────
🟢 shoot_and_flee       14·92%
🟢 cautious_move        87·100%
🟡 smart_engage          3·33%
🟢 safe_gather          21·95%
   gather (override)    52·81%
   move (override)     143·99%
─────────────────────────────────
```

Per-row data:
- Indicator dot: 🟢 healthy (success rate ≥ 80%), 🟡 mixed (40–80%), 🔴
  failing (< 40%) or never-called.
- Name. Italicized if it's an override (`gather (override)`).
- `<calls> · <success%>` over the hero's lifetime.
- Sort by call count (default), name, or success rate.

Click row → opens the tool detail drawer (§3). Long-press / right-click
→ "Copy as YAML" + "Copy to my hero" (the latter is Phase 6).

### 2.1 Backend endpoint

```
GET /api/heroes/{hero_id}/tools/summary

Response:
{
  "tools": [
    {
      "name": "shoot_and_flee",
      "kind": "composite",
      "calls": 14,
      "success": 13,
      "blocked_by_override": 0,
      "budget_exceeded": 1,
      "last_called_tick": 4218,
      "description": "Hit-and-run: ..."
    },
    {
      "name": "move",
      "kind": "override",
      "calls": 143,
      "success": 142,
      "blocked_by_override": 8,    // when: returned false
      "clamps_applied": 67,
      "after_chain_failures": 0,
      "description": "Cautious move ..."
    },
    ...
  ]
}
```

Source: aggregations over the trace events from BACKEND.md §5. Computed
in a daily rollup table + last-N-ticks live tail. Implementation:
`world-api/app/domains/inspector/router.py` (new), backed by an
analytics view over the events table.

---

## 3. Tool detail drawer

Opens in a slide-over on the right side of the hero page. Three tabs:

### 3.1 Tab: Definition

- Read-only block render via `<HeroBlocksRO>` from BLOCK_EDITOR.md §10.
- Full description, parameters table, the verb being overridden (if
  any).
- "Copy as YAML" button.
- "Copy to my hero" button (Phase 6 — see SHOWCASE.md).

### 3.2 Tab: Recent calls

Reverse-chronological list of the last 50 LLM calls to this tool. Each
row:

```
tick 4218  ✓  args: {retreat_to: "hearthold"}    expand →
tick 4205  ✗  args: {retreat_to: "stonehold"}    expand →  (clamped)
tick 4190  ⊘  args: {retreat_to: "ashfen"}       expand →  (gated by when:)
```

Click "expand" → expands inline to show the full trace tree from
BACKEND.md §5:

```
shoot_and_flee(retreat_to="hearthold")
├─ tool.expanded
├─ attack_nearest_hostile()
│  └─ ✓ damaged Goblin Brawler for 9
├─ if "hp > 0 and zone != 'hearthold'"  →  true
│  └─ travel(to="hearthold")
│     ├─ tool.clamped distance: 3 → 2
│     └─ ✓ moved to Hearthold (3,4)
└─ journal_write(text="Hit-and-run executed; retreated to hearthold")
   └─ ✓
```

Color coding:
- Green ✓ = success
- Red ✗ = primitive failed
- Yellow ⊘ = `when:` gated
- Blue ↻ = clamp adjusted a value

### 3.3 Tab: Stats

Aggregate stats over the hero's lifetime:

- Total calls, success rate.
- For overrides: `blocked_by_override` count (how often `when:` saved
  you), `clamps_applied` count and a histogram of `from → to` deltas
  per param.
- Top failure modes (verb-rejection reasons grouped).
- Tick distribution (heatmap of when this tool fires across the hero's
  life — early game vs late game).
- For composites: average primitive depth per call; "longest chain
  ever".

### 3.4 Backend endpoint

```
GET /api/heroes/{hero_id}/tools/{tool_name}

Response:
{
  "definition": { ... full ToolDef ... },
  "recent_calls": [
    {
      "tick": 4218,
      "args": {...},
      "result": "ok",
      "trace": [ ... event tree ... ]
    },
    ...
  ],
  "stats": {
    "calls": 14,
    "success": 13,
    "blocked_by_override": 0,
    "clamps_applied": 0,
    "failure_modes": {"out_of_range": 1},
    "tick_distribution_buckets": [...],
    "depth_avg": 3.1,
    "depth_max": 5
  }
}
```

---

## 4. "Why didn't my tool fire?" debugger

The most pedagogically valuable surface in the whole feature. Surfaces
the *counterfactual*: at this tick, the LLM picked tool X — but you
authored tool Y, and you want to know why.

### 4.1 Trigger

- On any LLM-call event in the hero's tick log (existing `EventStream`
  panel), click "debug this choice".
- Or visit `/heroes/{id}/ticks/{tick}` directly.

### 4.2 Debugger view

```
┌──────────────────────────────────────────────────────────────────┐
│  Tick 4198 — LLM chose `attack`                                  │
├──────────────────────────────────────────────────────────────────┤
│  The LLM saw 13 tools. Here is what it saw:                      │
│                                                                  │
│  ▸ attack — "Strike a hostile NPC adjacent to you. Costs 1 turn."│
│  ▸ attack_nearest_hostile — "Convenience: ..."                   │
│  ▸ flee — "Retreat one tile from the nearest enemy."             │
│  ▸ shoot_and_flee — "Hit-and-run: attack nearest enemy ..."  ⓘ   │
│  ▸ move — (your override) "Cautious move; never PvP, half-distance"│
│  ▾ ... 8 more ...                                                │
│                                                                  │
│  The LLM's reasoning (first 200 tokens):                         │
│  > I see one Goblin Brawler at adjacent tile. HP 17. I have a    │
│  > sword equipped. Attacking is the simplest move; my hit-and-run│
│  > tool is for when I'm outnumbered, but here it's just one.     │
│                                                                  │
│  Why your `shoot_and_flee` was not chosen:                       │
│  ⓘ The LLM mentioned it (above) and consciously rejected it.     │
│    Consider: does the description discourage single-target use?  │
└──────────────────────────────────────────────────────────────────┘
```

The "why" section is heuristic. Three signals, in order:

1. **LLM mentioned the tool by name** in its reasoning → "consciously
   rejected".
2. **Tool's `when:` would have blocked the call** had it been chosen →
   "your `when` clause would have gated this — the LLM may have inferred
   that".
3. **None of the above** → "the LLM didn't reach this option in its
   stated reasoning. Try shortening the description or moving it earlier
   in the tool list."

The third bucket is honest about what we *don't* know — we can't read
the model's full deliberation. Don't fabricate an explanation.

### 4.3 Backend endpoint

```
GET /api/heroes/{hero_id}/ticks/{tick}/llm-call

Response:
{
  "chosen_tool": "attack",
  "chosen_args": {...},
  "tools_offered": [
    {"name": "attack", "description": "...", "kind": "primitive"},
    {"name": "shoot_and_flee", "description": "...", "kind": "composite"},
    ...
  ],
  "reasoning_trace": "I see one Goblin Brawler ...",  // first ~500 tokens
  "tool_mentions": ["shoot_and_flee"],   // tools mentioned in reasoning
  "applicable_overrides": {              // tools whose when: would pass right now
    "shoot_and_flee": true,
    "cautious_move": true,
    ...
  }
}
```

Implementation: persist the LLM call's tool list and reasoning as part
of the LLM gateway's existing call log. The reasoning is already
captured for spectator traces; expose it here.

Privacy: heroes are public, so this is fine. Add a flag in the manifest
(`hero.spectator_visibility: full | summary | hidden`) so users can opt
to obscure their reasoning if they want — Phase 6.

---

## 5. Tool comparison view (lite — full version in SHOWCASE.md)

A small "compare" widget in the tool detail drawer:

```
shoot_and_flee on this hero (you)    vs    on Tova_v3 (top of leaderboard)

calls       14                                102
success     92%                                88%
avg depth   3.1                                4.7
description "Hit-and-run: attack ..."          "Skirmish: poke and disengage ..."
```

Picking a comparison hero is via search. Side-by-side block render
shows the actual definition diff. Full multi-hero compare is in
SHOWCASE.md §3.

---

## 6. Frontend files

- **Touch**: `frontend/src/app/heroes/[id]/page.tsx`
  - Mount `<ToolListPanel>` in the right sidebar.
  - Mount `<ToolDetailDrawer>` (slide-over).
- **Touch**: `frontend/src/components/EventStream.tsx`
  - Add "debug this choice" button on LLM-call events.
- **Create**: `frontend/src/app/heroes/[id]/ticks/[tick]/page.tsx`
  - Standalone debugger view (deep-linkable).
- **Create**: `frontend/src/components/inspector/ToolListPanel.tsx`
- **Create**: `frontend/src/components/inspector/ToolDetailDrawer.tsx`
- **Create**: `frontend/src/components/inspector/TraceTree.tsx`
- **Create**: `frontend/src/components/inspector/WhyDidntMyToolFire.tsx`
- **Create**: `frontend/src/components/inspector/ToolStatsChart.tsx`
- **Create**: `frontend/src/lib/api/inspector.ts` — typed client for the
  new endpoints.

---

## 7. Backend files

- **Create**: `world-api/app/domains/inspector/router.py`
  - `GET /api/heroes/{hero_id}/tools/summary`
  - `GET /api/heroes/{hero_id}/tools/{tool_name}`
  - `GET /api/heroes/{hero_id}/ticks/{tick}/llm-call`
- **Create**: `world-api/app/domains/inspector/aggregations.py`
  - Daily rollup query + live tail merge.
- **Touch**: `world-api/app/core/events.py`
  - Confirm trace events from BACKEND.md §5 are persisted with
    `correlation_id` and queryable by `(hero_id, tick)`.
- **Touch**: `llm-gateway/...` (existing path; verify)
  - Persist `tools_offered` and (truncated) `reasoning_trace` per call.
  - Should already exist for spectator traces; add inspector consumer.

---

## 8. Performance notes

- Tool summary endpoint is hit on every hero-page load. Cache for 30s
  per hero. Bypass cache when the requesting user owns the hero (so they
  see fresh stats while debugging).
- `recent_calls` is the heaviest payload. Cap at 50 calls; offer a
  "load more" cursor.
- Trace trees can be deep. Render virtualized; collapse all but the
  failing branch by default.

---

## 9. Acceptance checklist

- [ ] Tool list panel renders for every hero with ≥ 1 tool, in < 200ms.
- [ ] Tool detail drawer shows the read-only block render of the tool's
      definition.
- [ ] Recent calls list displays at least the last 50 LLM calls and
      their result (✓/✗/⊘).
- [ ] Expanding a call shows a correctly-nested trace tree with color
      coding per BACKEND.md §5.
- [ ] Stats tab shows lifetime aggregates that match a manual SQL count.
- [ ] "Debug this choice" overlay shows tools_offered with descriptions
      verbatim as the LLM saw them.
- [ ] Reasoning trace is shown for the chosen call.
- [ ] Tool-mentions detection correctly highlights tools the LLM named.
- [ ] Page is deep-linkable: `/heroes/{id}/ticks/{tick}` works without
      a session, suitable for sharing.
- [ ] All views ship with a "Copy YAML" affordance for the displayed
      tool.

---

## 10. Pedagogical hooks (read SHOWCASE.md for the full surface)

The inspector is the substrate SHOWCASE builds on:
- "Top tools by call success rate" — needs `tools/summary` aggregations.
- "Side-by-side hero compare" — needs trace trees from two heroes.
- "Copy this tool" — needs the read-only block render + a paste handler
  in the deploy editor.
- "Most-rejected tool descriptions" (for fun) — needs the
  why-didnt-fire data aggregated across heroes.

Build the inspector with these consumers in mind: data structures
should expose by-tool and by-tick views with stable shapes that
SHOWCASE can join across heroes without re-querying the same rows.
