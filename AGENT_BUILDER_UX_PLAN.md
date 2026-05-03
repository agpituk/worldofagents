# Agent-Builder UX Plan — Lowering the On-Ramp, Closing the Diagnostic Loop

This plan covers three UX changes to `/deploy` and `/heroes/[id]` that
together turn the project from a "playground for agent-engineering
intuition" into something closer to a structured classroom for thinking
about agent control. None of them require new world mechanics, new
backend domains, or changes to permadeath. They re-shape what a player
sees when they build a hero and when they watch one fight.

The three items, in priority order:

1. **Point-buy stat widget** — replace YAML stat editing with a six-slider
   form panel.
2. **Class template picker** — give first-time visitors five starter
   builds backed by the existing example heroes.
3. **Prompt / token introspection panel** — surface what the LLM was
   sent, what it picked, and what it cost, per tick.

Items 1 and 2 reduce the cliff-face for new players. Item 3 closes the
"deploy → die → guess → re-deploy" loop into a real diagnostic loop. Do
1 → 2 → 3 in that order; each one stands alone, but the value compounds.

Each item below follows the house format: **Symptom**, **Evidence**,
**Fix**, **Done when**.

---

## P0 — On-ramp fixes

### P0-1. Point-buy stat widget on `/deploy`

**Symptom.** Stat allocation is the most mechanical, most rule-bound
part of hero creation, and it has no UI. Users edit six numbers in
YAML, the "≤100 total, each stat 5–25" rule is documented only as a
trailing comment in the starter template, and validation arrives late
(only after clicking "validate manifest" or on submit). New players
either copy the starter verbatim or get a server-side rejection on
their first real build.

**Evidence.**
- `frontend/src/app/deploy/components/manifestTemplates.ts` — `STARTER_MANIFEST`
  encodes the rule as a YAML comment (`# Total must be ≤ 100 (point
  buy). Each stat 5–25.`). That's the entire UI.
- `frontend/src/app/deploy/page.tsx` — Monaco + Blockly are the only
  surfaces; no form panel exists for `build:`.
- `world-api/app/domains/hero/schemas.py` — `Build` validator enforces
  per-stat bounds (5–25) and total ≤ 100. The constraint is
  authoritative server-side; the frontend just doesn't surface it until
  submit.

**Fix.**
1. Add a `BuildPanel.tsx` under
   `frontend/src/app/deploy/components/`. Six labelled rows
   (STR / DEX / CON / INT / WIS / CHA), each with:
   - a numeric input (5–25, clamped)
   - a slider bound to the same value
   - a one-line description of what the stat *does* in-world (pull
     these from `DESIGN.md §2.3` — INT = token budget per tick, WIS =
     perception radius + journal slice, etc.). Static copy, but it
     turns the widget into a teaching surface.
2. Above the rows, a "points remaining" indicator: `Σ stats / 100` with
   colour states — green when `< 100`, amber on `== 100`, blood when
   `> 100`. Disable "deploy" while over-budget; the server will reject
   anyway, but the inline signal is the point.
3. Wire bidirectional sync with the YAML pane and Blockly workspace, on
   the same model that already drives `BlockEditor`'s round-trip:
   panel edits → patch the `hero.build` node in the parsed YAML →
   re-emit to Monaco; YAML edits → re-read `hero.build` → re-render the
   panel. Keep `yaml.parse` failures soft — show "stats unavailable
   while YAML is invalid" rather than crashing the panel.
4. Mount `BuildPanel` above the editor split-pane on `/deploy`. On
   mobile (`<lg`), stack it; the panel is short enough to be usable on
   a phone, unlike the 600px Blockly grid.

**Non-goals.** No respec UI (permadeath stays). No "auto-balance"
button. No drag-to-redistribute between stats — explicit input per
stat is fine.

**Done when.** A user can land on `/deploy`, drag the STR slider from
12 to 18, see "points remaining" go from 100 → 94, and the YAML pane
update `str: 18` in real time. Editing `dex: 25` directly in the YAML
pane snaps the DEX slider to 25 and flips "points remaining" to
red/blood when the total goes over 100. A unit test asserts
panel-state ↔ YAML round-trip for each of the six stats.

---

### P0-2. Class template picker

**Symptom.** First-time visitors to `/deploy` see one starter manifest:
a generic, balanced build with a survive-and-attack reflex stub. The
five worked examples that *do* exist live in
`bot-sdk-python/examples/` and are invisible to anyone who hasn't
cloned the repo. The fork-from-existing-hero flow (`?fork=<id>`) is the
de facto onboarding path, but it requires browsing the home page,
identifying a hero you'd want to copy, and clicking through — three
steps too many for a player who has just landed.

**Evidence.**
- `frontend/src/app/deploy/page.tsx` — opens with a single
  `STARTER_MANIFEST` pre-loaded in both panes; no template selector.
- `frontend/src/app/deploy/components/manifestTemplates.ts` — exports
  exactly one constant.
- `bot-sdk-python/examples/` — five complete, distinct example
  manifests already exist:
  - `minimal_hero.yaml` — balanced beginner
  - `tova_smith.yaml` — crafter, low-LLM economy loop
  - `elara_wizard.yaml` — INT-heavy spellcaster
  - `quill_thief.yaml` — DEX-heavy stealth/theft
  - `lyra_hunter.yaml` — DEX-max PvP hunter, pure reflex
  These are the templates; they just aren't surfaced on the web.

**Fix.**
1. Add `frontend/src/app/deploy/components/TemplatePicker.tsx`. Render
   five cards in a horizontal row (wraps to two rows on mobile), each
   showing:
   - archetype name (Warrior / Crafter / Wizard / Thief / Hunter)
   - one-sentence pitch (e.g. "Quest + melee. Mostly free reflexes.")
   - the build's stat sparkline (six tiny bars)
   - estimated LLM intensity ("low / medium / high"), derived from
     whether the reflexes route to `invoke_llm` early or late
2. Move the five YAML files into the frontend build. Two reasonable
   options:
   - copy them to `frontend/src/app/deploy/templates/*.yaml` and
     import as raw text via `?raw` (simplest)
   - keep them in `bot-sdk-python/examples/` and add a small build-time
     script that copies them into a frontend-readable location
   Pick one; do not ship two sources of truth.
3. On card click: replace the manifest in the editor with the
   selected template's YAML. Use the same code path as the existing
   `?fork=<id>` flow. Show a subtle "Template: Wizard — edit freely"
   pill above the editor so the user knows what they started from.
4. On first visit (no `?fork`, no localStorage flag), open the
   template picker as a modal overlay, with a "skip — start from
   blank" link for returning users. Persist a `worldofagents:onboarded`
   flag in localStorage so we don't nag.
5. Update the five YAML files' `hero.author` to a clearly placeholder
   value (e.g. `"@template"`) so users have to set their own author
   before deploy succeeds. Server-side, reject manifests with
   `author == "@template"` so we don't leak placeholder authors into
   the leaderboard.

**Non-goals.** No "build wizard" multi-step form. No machine-generated
recommended builds. No locking templates behind a tutorial. The
picker is a launchpad, not a curriculum.

**Done when.** A logged-out visitor lands on `/deploy`, sees the modal
with five archetype cards, clicks "Wizard", and the editor populates
with `elara_wizard.yaml` — stats, bio, reflexes, memory all
pre-filled. Closing the modal and reopening `/deploy` skips the modal
on the second visit. A user who clicks "deploy" without changing
`author` from `"@template"` gets a server-side 422 with a clear
message.

---

## P1 — Diagnostic loop

### P1-1. Prompt / token introspection panel on `/heroes/[id]`

**Symptom.** The spectator surface shows what the hero *did* but not
what the model *saw* or *spent*. Players can watch their hero die,
read narrator flavour, and see which reflex fired — but they cannot
see the prompt slice that was actually sent to the LLM, the tools
that were offered, the tool the model chose, or the token cost. The
current learning loop is "deploy → die → guess → re-deploy"; without
this panel, the "guess" step never becomes "diagnose."

**Evidence.**
- `frontend/src/app/heroes/[id]/components/MemoryTracePanel.tsx` —
  shows `system_summary`, `recall_tags`, and journal entries
  retrieved this tick. Stops short of the actual prompt.
- `frontend/src/app/heroes/[id]/components/ActivityFeed.tsx` — shows
  reflex index fired and outcome; no prompt or token data.
- `frontend/src/components/inspector/ToolListPanel.tsx` — shows
  per-tool success rates aggregated; no per-tick tool-call detail.
- `world-api/app/core/gateway_token.py` — signed gateway tokens
  already carry a `tokens` claim. The data exists; it just isn't
  exposed.
- `llm-gateway/app/main.py` — the gateway sees prompt, response, and
  token counts on every call. Currently logged, not surfaced.

**Fix.**
1. Persist per-tick LLM call records in the world-api. New table
   `hero_llm_calls` keyed by `(hero_id, tick_id)` with columns:
   - `prompt_text` (the full system + user prompt slice)
   - `tools_offered` (JSON array of tool specs)
   - `tool_chosen` (name or null if the model returned plain text)
   - `tokens_in`, `tokens_out`, `tokens_budget`
   - `latency_ms`
   The gateway already has all of this; today it logs but doesn't
   write through to the world-api. Add a small POST hook from
   `llm-gateway/app/main.py` to a new world-api endpoint
   `POST /heroes/{id}/llm-calls` that the gateway calls after each
   completion.
2. Add `GET /heroes/{id}/ticks/{tick_id}/llm-call` that returns the
   record for a single tick (or 404 if the tick was reflex-only).
3. Add `frontend/src/app/heroes/[id]/components/PromptInspector.tsx`.
   Mounted in the existing right-rail of `/heroes/[id]`, below
   `MemoryTracePanel`. Collapsed by default; expands on click for
   the most recent LLM-tick. Shows:
   - **Budget bar**: `tokens_in + tokens_out` against `tokens_budget`,
     amber when `>80%`, blood when over.
   - **Prompt**: monospace block, scrollable, with a "copy" button.
   - **Tools offered**: chip list of tool names; hover shows the
     description string the model saw.
   - **Tool chosen**: highlighted chip, or a "no tool — plain text
     response" pill. Show the response text below either way.
   - **Latency**: small footnote.
4. In `ActivityFeed.tsx`, add a "view prompt" link on every tick row
   where `tool_chosen != null` — clicking jumps `PromptInspector` to
   that tick. The existing per-tick "debug this choice" route is the
   natural anchor; reuse it.
5. Privacy gate: only show `PromptInspector` to the hero's owner (and
   admins). Other spectators get a "prompt hidden — owner only"
   placeholder. Rationale: prompts may contain in-character secrets,
   strategy notes, or dev-time debugging copy that a player wouldn't
   want a rival to read. Enforce server-side in the new GET endpoint;
   the frontend gate is convenience.

**Non-goals.** No live token-budget gauge in the editor (separate
work). No prompt diff view across ticks (nice but P2). No
auto-summary of "why your hero died" — the panel exposes data,
players draw the conclusion.

**Done when.** A hero owner viewing `/heroes/{their-hero-id}` can
expand the prompt inspector, see the exact prompt their hero sent on
its most recent LLM tick, see which tools were offered, see which one
the model picked (if any), and see token use against budget. A
non-owner viewing the same page sees the placeholder. A reflex-only
tick (no LLM call) shows "no prompt — handled by reflex" rather than
empty fields. A unit test asserts the gateway → world-api write-back
fires exactly once per LLM call and records all six required fields.

---

## Sequencing

- **Item 1 (stat widget)** is the smallest and unblocks the most
  immediate pain. Land it first; ship independently.
- **Item 2 (template picker)** depends on item 1 only insofar as the
  template's `build:` should be editable in the new widget. If the
  widget isn't ready, the picker still works against YAML.
- **Item 3 (prompt inspector)** is independent of 1 and 2 on the
  frontend, but requires the gateway → world-api write-back, which is
  the bulk of the work. Land the schema + write-back first; the
  frontend panel can then be built and iterated quickly.

## Out of scope (intentionally)

- **Class system as in-world mechanic.** Templates are starter
  scaffolding, not gameplay-bound classes. The build-from-scratch
  expressivity stays.
- **Visual reflex builder beyond Blockly.** Blockly is shipped and
  works; not redesigning it here.
- **Memory configuration form.** Worth doing, but lower-leverage than
  the three above. Defer.
- **Mobile reflow of `BlockEditor`.** Real issue, separate fix.
- **Live token budget in the deploy editor.** Useful, but item 3
  delivers the same insight retrospectively at lower complexity.
- **Permadeath changes.** None; permadeath stays.
