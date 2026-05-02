# Showcase Layer — Leaderboards, Copy, Compare

**Phase**: 6. Depends on Phases 2, 3, 5 (backend tools, override grammar,
inspector).

This is the layer that turns the feature into a credible demonstration of
the thesis. The inspector lets one player see how *their* tools work;
the showcase lets the community see how *everyone's* tools work, copy
what's good, and learn by side-by-side comparison.

---

## 1. Goals

1. Make tools first-class artifacts: shareable, attributable,
   inspectable.
2. Surface what works. Players should learn from leaderboards which
   tool patterns produce outcomes.
3. Enable cross-pollination. Copying a great tool into your hero takes
   one click.

Non-goals:
- Real-time PvP tool battles. The world already provides PvP; the
  showcase is for the meta-layer.
- Marketplace / monetization. Tools are public goods.

---

## 2. Tool leaderboards

A new top-level page at `/tools` and a panel on the existing home page.

### 2.1 Boards

| Board | Sort key | Time window | Notes |
|---|---|---|---|
| **Most copied** | times-copied desc | 7d / 30d / all-time | Drives discovery |
| **Highest survival lift** | (avg lifespan with tool − without) | 30d | Causal-ish; see §2.4 |
| **Most-called composites** | total LLM calls desc | 7d | What the meta is doing |
| **Best success rate (≥ 50 calls)** | success_rate desc, calls tiebreak | 30d | Encourages quality |
| **"David tools"** | featherweight tools used to beat heavyweights | 30d | Underdog drama |
| **Best-named** | description-mention rate ÷ call rate | 30d | "LLM picks it because the description is good" — see INSPECTOR.md §4 |

Each board shows ~10 entries with: tool name, author hero, brief
description, the metric value, and a "view" button → tool detail page.

### 2.2 Tool detail page

`/tools/{tool_id}` (where `tool_id` is `<hero_id>:<tool_name>`):

```
shoot_and_flee
by Tova_v3 · used by 47 heroes · forked 12×

Description:
  Hit-and-run: attack the nearest enemy once, then retreat to the
  nearest sanctuary. Use when outnumbered or HP < 40%.

Block render:
  [...read-only blocks via HeroBlocksRO from BLOCK_EDITOR.md §10...]

Stats across all heroes using this tool (last 30d):
  Calls:           14,283
  Success rate:    91%
  Avg depth:       3.2
  Median lifespan increase: +12 ticks vs heroes without it (see §2.4)

Top users:
  - Tova_v3        (author)        102 calls
  - HollowKnight    forked         88 calls
  - The_Postman     forked         71 calls
  ...

[Copy this tool to my hero]   [Fork & edit]   [Inspect a recent call]
```

The "Copy" button opens a modal that asks which of the user's heroes to
add the tool to (or "create new hero with this tool"). On confirm, the
tool is appended to that hero's `tools:` section. If a name collision
exists, the user is prompted to rename.

The "Fork & edit" button is the same but immediately opens the deploy
editor with the tool pre-inserted, so the user can tweak before saving.

### 2.3 Tool identity & versioning

Two heroes can have a `shoot_and_flee` tool that differ in details. We
treat tools as **content-addressed**: the canonical `tool_id` is a hash
of the canonical YAML. Re-uses across heroes are detected by hash
match, not by name. The leaderboards aggregate over `tool_id`.

A "fork" is a `tool_id` whose `parent_tool_id` is set in the manifest
metadata block:

```yaml
tools:
  - name: shoot_and_flee
    description: "..."
    steps: [...]
    _meta:
      parent_tool_id: "abc123..."  # auto-set by the Copy/Fork UX
```

`_meta` is opaque to the validator and dispatcher; only the showcase
reads it. Validator rejects unknown top-level keys, so meta is nested
under `_meta` to avoid forward-compatibility breakage.

### 2.4 Survival-lift methodology (be honest about the stats)

The "median lifespan increase" stat is suggestive, not causal. We
compute:

```
heroes_with_tool   = all heroes whose manifest contained this tool_id
                     for at least 50% of their lifetime
heroes_without     = all heroes without this tool_id, matched on
                     division and starting zone
median_lifespan(A) − median_lifespan(B) → "lift"
```

Display the value with a tooltip: *"Suggestive only — heroes who pick
this tool may differ in other ways."*

Don't claim causation. Players will respect honesty more than fake
precision.

---

## 3. Side-by-side compare

`/compare?heroes=alice,bob` — pick two (or more, up to 4) heroes, see
their tool layers next to each other.

### 3.1 Layout

```
┌─────────────────────┬─────────────────────┬─────────────────────┐
│  Tova_v3            │  HollowKnight       │  ColdAshes          │
│  ─────────────────  │  ─────────────────  │  ─────────────────  │
│  STR 14 DEX 10      │  STR 16 DEX 12      │  STR 8  DEX 18      │
│  Lifespan: 12d (alive)│ 8d (alive)         │  4d (dead)          │
│                     │                     │                     │
│  Tools:             │  Tools:             │  Tools:             │
│  · shoot_and_flee   │  · charge_in        │  · long_recall      │
│  · cautious_move    │  · attack (override)│  · poison_strike    │
│  · safe_gather      │  · ...              │  · ...              │
│                     │                     │                     │
│  [block render]     │  [block render]     │  [block render]     │
└─────────────────────┴─────────────────────┴─────────────────────┘

Common tools (shared by ≥ 2):
  shoot_and_flee  (Tova_v3, HollowKnight)
```

### 3.2 Diff view for a shared tool

If two heroes share a tool by name but their `tool_id` differs (one
forked + edited), show a side-by-side block diff. Implementation:
two `HeroBlocksRO` panels with synchronized scroll + a thin diff bar
highlighting changed slots.

### 3.3 Lifespan / KPI overlay

Below the tool comparison, a small chart showing each hero's lifespan
over time, deaths annotated. If a tool was added to a hero mid-life,
mark the addition on the chart.

---

## 4. Tool gallery

`/tools/gallery` — a curated discovery surface, separate from the
leaderboards. Curation is community + light editorial:

- **Featured** — hand-picked by maintainers (manual flag in DB)
- **New & noteworthy** — tools published in last 7d with ≥ 5 copies
- **By category** — grouped by inferred role (combat / movement /
  economy / social / hybrid). Inference: simple keyword match on
  description + steps for v1; can be smarter later.

Each tile is a tool card with name, author, one-line description, copy
count, and a quick block preview.

---

## 5. Per-tool comments / discussion (defer to v2)

Tempting but a moderation burden. v1 ships with a "share link" button
on each tool detail page; community discussion happens on Discord /
Twitter. Add comments only if there's clear demand and a moderation
plan.

---

## 6. Privacy

Heroes are public; manifests are public; tools are public. The only
opt-out is the spectator-visibility setting from INSPECTOR.md §4.3,
which controls reasoning-trace exposure but not the tool definitions
themselves.

A user can mark a *hero* as "tools-private" (`hero.tool_visibility:
private`) — their tool definitions don't appear in the showcase, but
calls/results remain visible. Use case: someone testing a new strategy
who doesn't want immediate copying. Validator enforces — opt-in only,
default public.

---

## 7. Backend

### 7.1 New endpoints

```
GET  /api/tools/leaderboards?board=most_copied&window=30d
GET  /api/tools/{tool_id}                          # detail
GET  /api/tools/{tool_id}/users                    # who uses it
GET  /api/tools/{tool_id}/recent_calls             # samples across all heroes
GET  /api/tools/gallery?category=combat            # gallery feed
GET  /api/compare?heroes=a,b,c                     # comparison payload
POST /api/tools/{tool_id}/copy                     # records a copy event
```

### 7.2 Tables (suggested schema)

```sql
-- canonical, content-addressed registry
CREATE TABLE tool_definitions (
  tool_id        TEXT PRIMARY KEY,         -- sha256 of canonical YAML
  canonical_yaml TEXT NOT NULL,
  name           TEXT NOT NULL,
  kind           TEXT NOT NULL,            -- 'composite' | 'override'
  parent_tool_id TEXT,                     -- fork lineage, nullable
  first_seen_at  TIMESTAMPTZ NOT NULL,
  first_seen_hero TEXT NOT NULL
);

-- which heroes currently use which tool
CREATE TABLE hero_tools (
  hero_id    TEXT NOT NULL,
  tool_id    TEXT NOT NULL,
  added_tick INT NOT NULL,
  PRIMARY KEY (hero_id, tool_id)
);

-- copy events (one-click "Copy to my hero")
CREATE TABLE tool_copies (
  copy_id      BIGSERIAL PRIMARY KEY,
  source_tool_id  TEXT NOT NULL,
  copied_by_hero  TEXT NOT NULL,
  copied_at    TIMESTAMPTZ NOT NULL
);
```

Daily rollups feed the leaderboards. The `most_copied` board sorts
`tool_copies` by source_tool_id within the time window.

### 7.3 Files

- `world-api/app/domains/showcase/router.py`
- `world-api/app/domains/showcase/leaderboards.py`
- `world-api/app/domains/showcase/copy.py`
- `world-api/app/domains/showcase/aggregations.py`
- DB migration file under `world-api/alembic/versions/...`

---

## 8. Frontend

- **Create**: `frontend/src/app/tools/page.tsx` — leaderboards
- **Create**: `frontend/src/app/tools/[toolId]/page.tsx` — tool detail
- **Create**: `frontend/src/app/tools/gallery/page.tsx`
- **Create**: `frontend/src/app/compare/page.tsx`
- **Create**: `frontend/src/components/showcase/Leaderboard.tsx`
- **Create**: `frontend/src/components/showcase/ToolCard.tsx`
- **Create**: `frontend/src/components/showcase/CopyToolModal.tsx`
- **Create**: `frontend/src/components/showcase/CompareGrid.tsx`
- **Create**: `frontend/src/components/showcase/ToolDiffPanel.tsx`
- **Touch**: `frontend/src/app/page.tsx` — add a "Top tools this week"
  panel to the home page.
- **Touch**: `frontend/src/components/inspector/ToolDetailDrawer.tsx` —
  add a "Open in tools showcase" link.
- **Touch**: `frontend/src/app/deploy/page.tsx` — handle paste-from-copy
  flow (a tool YAML inserted via the modal lands as a new block in the
  workspace, scrolled into view).

---

## 9. Acceptance checklist

- [ ] `/tools` page renders all six leaderboards from §2.1.
- [ ] Each board sorts correctly and respects the time-window selector.
- [ ] Tool detail page shows definition, stats, top users, and a copy
      button.
- [ ] Copy flow inserts the tool into the user's chosen hero with no
      name collisions (or prompts on collision).
- [ ] Fork flow opens the editor with the tool pre-inserted and meta
      `parent_tool_id` set.
- [ ] `/compare` renders 2–4 heroes side by side with their tool lists,
      block renders, and a shared-tools section.
- [ ] Shared tools with different `tool_id`s show a diff view.
- [ ] Gallery page renders with category filters.
- [ ] Survival-lift stat is shown with the honesty tooltip.
- [ ] `hero.tool_visibility: private` removes the hero's tools from all
      showcase boards but leaves them visible on the hero's own page.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Top boards become a monoculture (everyone copies the same 3 tools) | Add a "diverse picks" board that surfaces tools used by < 5 heroes with high success rates. Rotate featured weekly. |
| Survival-lift gets misread as causal | Explicit honesty tooltip; don't put the number in headlines without context. |
| A buggy popular tool propagates failures | Surface "recent regression" — if a popular tool's success rate drops by > 20% week-over-week, flag on its detail page. |
| Spam tools (joke names, useless steps) | Soft demotion: tools never copied + never called are hidden from gallery after 30d. No hard removal — they're still on the author's hero page. |
| Author leaves; their popular tools become unmaintained | Tools are content-addressed; the author leaving doesn't break anyone. Forks continue to work. Encourage forking in the UX. |

---

## 11. Pedagogical lens — what each surface teaches

| Surface | What it makes visible |
|---|---|
| Most-copied board | "These docstrings are working." |
| Survival-lift board | "Tools have measurable consequences." |
| Best-named board | "Description quality drives LLM choice." |
| Side-by-side compare | "Same primitives, different decompositions, different outcomes." |
| Why-didn't-fire (INSPECTOR) | "Your description was inferior to a peer's. Here's both." |
| Copy + fork lineage | "Iteration matters. The community improves a tool over weeks." |

These are the answers to "why does this game matter beyond entertainment?"
The showcase is where the project's argument lives.
