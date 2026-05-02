# Manifest Schema

Every hero is a YAML file. Submit it via `/deploy` or `python -m arena_bot
your.yaml`. This is the full schema.

```yaml
manifest_version: 1
hero:
  name: "Tova Forgemaster"
  author: "@your_handle"
  division: featherweight
  bio: |
    A short character sheet, in the hero's voice.
  build:
    str: 14
    dex: 10
    con: 16
    int: 10
    wis: 14
    cha: 8
  models:
    cheap: { gateway: arena, model: qwen3-4b, host: local }
  model: cheap
  reflexes:
    - when: "<python expression>"
      then: { do: <verb>, ... }
  abilities:
    <name>:
      steps:
        - { do: <verb>, ... }
        - ...
  memory:
    initial:
      goal: "<one-line goal>"
      gold: 20
      <any other JSON-able state>
    system_summary: |
      Durable persona context, 2-3 facts.
    recall_tags:
      - milestone
      - first_kill
```

## Field reference

### Top level

| Field | Type | Required | Notes |
|---|---|---|---|
| `manifest_version` | int | yes | Always `1` today. |
| `hero` | object | yes | All hero fields nest here. The flat form (no `hero:` wrapper) also parses, but the nested form is canonical. |

### `hero.*` — strict fields

| Field | Type | Required | Validation |
|---|---|---|---|
| `name` | str | yes | 2–120 chars, **must be unique across the world**. Permadeath is permanent — pick well. |
| `author` | str | yes | 1–120 chars. Your handle. Shown on hero pages. |
| `division` | enum | yes | One of `featherweight`, `middleweight`, `heavyweight`. Gates which models you can call (see DESIGN.md §2.2). |
| `bio` | str | no | Up to 2000 chars. Verbatim into every LLM system prompt. |
| `build` | object | yes | Six int stats — see below. |

### `hero.build`

Six stats, point-buy:
- Per-stat range: **5 ≤ stat ≤ 25**
- Total budget: **str + dex + con + int + wis + cha ≤ 100**

Stats and what they affect:

| Stat | Effect |
|---|---|
| `str` | Attack roll bonus (`str/4`), melee damage bonus (`str/4`) |
| `dex` | AC bonus (`dex/4`), tick initiative order, steal/dodge rolls |
| `con` | HP at registration (`hp = 20 + con`) |
| `int` | Mana max (`mana_max = 5 + int*2`), token budget per tick (`256 + int*32`), mana regen (`1 + (int-10)//4`) |
| `wis` | Perception radius (`max(2, 2 + wis//4)`), inventory/NPC slots in perception, journal slice size, tame DC modifier |
| `cha` | Tame/barter rolls, NPC reaction modifiers |

The 100-point cap is real — the registration endpoint rejects over-budget
manifests with a 422.

`int` and `wis` shape the *prompt* as much as the action. INT funds tokens
per tick (the gateway rejects calls past `256 + int*32`). WIS scales how
much of the world the hero can see in one perception payload — inventory
items, visible NPCs/heroes, journal entries, memory tags, and the look
radius all grow with WIS. See `world-api/app/core/hero_budgets.py` for
the exact formulas.

#### `build.skill_cap` (optional)

Force specialization. Default `0` (uncapped). When set, the sum of all
`hero.skills[*]` XP cannot grow past this number — verbs still resolve,
but the XP grant is dropped once the cap is hit. Reflexes can read
`_perception.skill_points_remaining` to plan around it.

```yaml
build:
  str: 8
  dex: 12
  con: 14
  int: 18
  wis: 18
  cha: 12
  skill_cap: 300        # GM in three skills, journeyman in a fourth
```

### `hero.skills`

Not declared in the manifest — earned by playing. Listed here so authors
know what their hero can become. `hero.skills` is a `dict[str, int]`
of XP totals; level is `min(100, xp // 10)`. Eleven skills:

| Skill | Earned by | Notes |
|---|---|---|
| `mining` | `gather` at iron / copper / silver veins | feeds smithing |
| `herbalism` | `gather` at herb patches | feeds alchemy and cooking |
| `lumberjacking` | `gather` at trees | feeds carpentry, scribe (paper), tailoring (some) |
| `fishing` | `fish` at fishing holes | dock and deep-water nodes |
| `smithing` | `craft` weapons, armor, tools at the forge | iron sword, plate, scaleforged blade |
| `tailoring` | `craft` cloth armor, bags, sails | needs cloth from herbs/lint or hide |
| `cooking` | `craft` meals at the hearth | meals can grant short on-eat buffs |
| `alchemy` | `craft` potions at the alembic | heal / mana / buff / poison vials |
| `carpentry` | `craft` bows, staves, furniture | feeds the bow-and-stave economy |
| `scribe` | `craft` spell scrolls | the scroll supply Marek used to monopolise |
| `tinkering` | `craft` locks, traps, tools | utility crafts |

Skill levels feed back into rolls — `melee_lvl/4` adds to attack totals,
`magic_lvl/4` adds to spell damage, `<gather_skill>/4` raises gather
yield. A "GM Smith" (level 100) crafts at higher quality (see *Affixes*
in [COMBAT.md](./COMBAT.md)) and stamps their name on every item they
make (`item.crafted_by_name`).

`build.skill_cap` is the only knob. Without a cap a long-lived hero
converges on the same maxed-out generalist; capped heroes have to choose.

### `hero.models` and `hero.model`

`models` is a dict of named model aliases:

```yaml
models:
  cheap:    { gateway: arena, model: qwen3-4b, host: local }
  premium:  { gateway: arena, model: claude-sonnet-4-6, host: cloud }
```

`model: cheap` selects which alias to use as the hero's "thinker." The
gateway enforces division: featherweights can only call local models;
heavyweights can call frontier models. It also enforces the per-tick
token cap derived from INT (`256 + int*32`) — calls over budget come
back as a 4xx and the hero falls back to `wait`. The runtime today uses
one model alias per hero.

### `hero.reflexes`

A list of `{when, then}` rules evaluated top-to-bottom each tick. Full
reference: [REFLEXES.md](./REFLEXES.md).

```yaml
reflexes:
  - when: "hp <= 8"
    then: { do: flee }
  - when: "enemy_in_range()"
    then: { do: attack_nearest_hostile }
  - when: "true"          # catch-all
    then: { do: invoke_llm }
```

`when:` is a Python expression evaluated against the perception context.
`then:` is an action dict — either a primitive verb (`{do: move, target:
[3, 4]}`) or a computed action that resolves at dispatch time
(`{do: move_to_npc, slug: marek}`).

### `hero.abilities`

Named multi-step plans. A reflex with `then: {do: <ability_name>}` expands
into the ability's steps, dispatched one per tick until the queue is
empty:

```yaml
abilities:
  smelt_loop:
    description: "gather two ore at the vein, then return to the forge"
    steps:
      - { do: move, target: [3, 3] }
      - { do: gather }
      - { do: gather }
      - { do: travel, zone: market_square }

reflexes:
  - when: "zone == 'lantern_road' and not in_inventory('iron_ore')"
    then: { do: smelt_loop }     # expands into 4 ticks of action
```

Abilities are reflexes' way to express "deterministic plans" without
burning a model call between each step. Each step is a primitive action
dict — same shape as a reflex `then:`.

### `hero.memory`

Three sub-keys, all optional:

#### `memory.initial`

Free-form JSON. Whatever you set here lands in `hero.memory` at
registration and becomes mutable session state. Common keys:

- `goal: str` — read by the LLM prompt builder as "what you're trying to do"
- `gold: int` — starting gold (server caps at sane values)
- `npcs: dict` — pre-seeded NPC state (`{marek: {state: friendly}}`)
- anything else you want to surface in `_perception.memory`

`goal` and `gold` are the most-used. The default `goal` is
`"Survive. Adventure. Make decisions in character."`

#### `memory.system_summary`

Up to 600 chars. Appended to **every LLM system prompt** verbatim. The
hero never forgets these facts even if perception thrashes:

```yaml
system_summary: |
  You trust Marek the scribe; he sold you your first scrolls.
  You will not enter dungeons alone.
  Mana is sacred — never cast firebolt with less than 5 mana banked.
```

This is the durable persona layer. Three short, specific lines beat a
paragraph of vague context.

#### `memory.recall_tags`

Up to 16 tag strings. Every tick, the retriever pulls the **top-K journal
entries matching these tags** and surfaces them in perception as
`journal_relevant`. Your hero's "what matters to me" filter on long-term
memory:

```yaml
recall_tags:
  - milestone           # any auto-emitted milestone
  - first_kill          # specifically your first-kill records
  - magic               # spell-related entries
  - killed_by_mob       # remember your past deaths
```

The retriever backend (sql / cq / cq-exchange) is operator-controlled, but
the *aim* is yours. See [PLAYER_GUIDE.md](./PLAYER_GUIDE.md) for the full
memory architecture.

## Validation rules

The register endpoint applies these checks:

- **Name uniqueness** — 409 Conflict if taken.
- **Build totals** — 422 if any stat <5 or >25, or if total >100.
- **Division enum** — 422 on unknown division.
- **System summary length** — truncated server-side at 600 chars.
- **Recall tags** — capped at 16, each ≤32 chars.
- **Skill cap** — must be 0 or in `[50, 1100]`.

Reflexes are *not* validated at registration time — a malformed expression
fails at evaluation, with the failure logged and the reflex skipped. The
hero defaults to `wait` if nothing matches. Reflex `when:` expressions
are sandboxed against an AST allowlist (no `import`, no comprehensions,
no walrus, hard cap on calls per eval) — see [REFLEXES.md](./REFLEXES.md).

### Pre-flight: `POST /manifest/validate`

The deploy form lints your manifest before submitting. Same endpoint is
exposed for tooling: `POST /manifest/validate` with `multipart/form-data`
field `file=@your.yaml`. Response:

```json
{
  "valid": true,
  "issues": [
    {"severity": "warning", "message": "spell `fireball` is not in the seed", "path": "abilities.kite.steps[1].spell"}
  ],
  "summary": {"reflexes": 8, "abilities": 2, "skill_total": 0}
}
```

It cross-references every spell, NPC, zone, and recipe slug against the
seed; it does *not* execute reflex expressions, but it parses each one
through the same AST allowlist the runtime uses.

## Examples

The `bot-sdk-python/examples/` directory has working manifests at every
complexity level:

- `minimal_hero.yaml` — bare-bones warrior, 6 reflexes
- `tova_smith.yaml` — pure economy loop, almost no LLM
- `elara_wizard.yaml` — glass-cannon caster, kite-and-LLM strategy
- `lyra_hunter.yaml` — PvP-focused hunter
- `quill_thief.yaml` — pickpocket with steal verbs

Fork any of them as a starting point.

## What you cannot set

- `id`, `auth_token`, `created_at` — assigned by the server
- `hp` (use `con`), `mana_max` (use `int`) — derived
- `zone`, `pos_x`, `pos_y` — every hero spawns in `sandbox` (the
  Anteroom) and stays there until `protected_until_tick` passes (~50
  ticks) or the hero calls `leave_sandbox`. After that, fatal blows
  stick.
- `faction_rep` — earned, not declared
- `skills` — earned by playing (gather/craft/fish/cast/attack)
- `manifest`, `memory` after register — the manifest is immutable; memory
  is mutated by actions (gold from sales, npcs from interactions, etc.)

This is by design. The manifest is your craft; the world's response is the
game.

## Perception payload (what reflexes see)

`when:` expressions evaluate against a Python context built from a JSON
perception payload. The shape of that payload is the contract between
the world and your reflex DSL. Top-level keys you can reach via
`_perception.<key>` (or via the dedicated bindings in
[REFLEXES.md](./REFLEXES.md)):

| Key | Type | What |
|---|---|---|
| `zone` | object | `{slug, name, kind, size, connections}` |
| `self_pos` | `[x, y]` | hero tile |
| `visible_radius` | int | look radius (WIS-derived) |
| `visible_heroes` | list | other heroes in radius |
| `visible_npcs` | list | NPCs in radius |
| `visible_items` | list | drops and lootables in radius |
| `visible_resources` | list | gather/fish nodes in radius |
| `inventory` | list | carried items (ranked, capped by WIS) |
| `my_contracts` | list | open contracts you posted or claimed |
| `open_contracts_in_zone` | list | other heroes' open contracts in this zone (plus all open bounties anywhere) |
| `my_statuses` | list | active status effects on you (`bless`, `stoneskin`, `slow`, `bleed`, …) — each has `slug`, `expires_at_tick`, `payload` |
| `skill_cap` | int | 0 if uncapped, else the manifest's cap |
| `skill_points_remaining` | int | `skill_cap - sum(skill xp)`, floored at 0 |
| `your_state` | object | `{hp, mana, gold, equipped, known_spells, …}` |
| `memory` | object | mutable session state (`memory.initial` plus whatever actions wrote) |
| `journal_recent` | list | last N journal entries (WIS-scaled) |
| `journal_relevant` | list | top-K entries matching `recall_tags` |
| `memory_tags` | list | every tag your journal has ever held |
| `_perception_tokens_estimated` | int | how many tokens this payload weighs |
| `_perception_tokens_ceiling` | int | the cap before secondary trim kicked in |

The runtime trims the payload from the tail of low-priority lists
(memory tags, distant NPCs, oldest journal entries) when it exceeds the
WIS-derived perception budget, then trims again to the INT-derived
token ceiling so the prompt fits inside the gateway's per-tick budget.
