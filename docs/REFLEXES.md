# Reflex DSL Reference

Reflexes are deterministic *if-this-then-that* rules. Each tick the engine
walks them top-to-bottom; the first `when:` that evaluates True provides
the action for that tick. Reflexes are **free** — no LLM call, no token
cost. They handle 90% of routine decisions and escalate to the model
only for judgment.

```yaml
reflexes:
  - when: "<python expression>"
    then: { do: <verb>, ... }
```

## Available bindings

In a `when:` expression you can reference:

### Scalars
| Name | Type | Source |
|---|---|---|
| `hp` | int | hero's current HP |
| `zone` | str | hero's current zone slug |
| `zone_kind` | str | `sanctuary` / `frontier` / `dungeon` / `arena` / `sandbox` |
| `pos_x`, `pos_y` | int | hero's current tile |
| `gold` | int | hero's gold (`memory.gold`) |
| `equipped` | dict | `{slot: slug}` map |
| `memory_tags` | set | every tag your journal has ever held |
| `_perception` | object | the raw Perception dataclass — for advanced lookups (contracts, statuses, skill cap, …) |

The `_perception` payload is the full snapshot — see
[MANIFEST.md](./MANIFEST.md#perception-payload-what-reflexes-see) for
its shape. The fields below are the most common ones to reach via
`_perception.<key>` in a reflex:

| Path | What |
|---|---|
| `_perception.my_contracts` | open contracts you posted or claimed |
| `_perception.open_contracts_in_zone` | other heroes' open contracts visible in this zone (plus all open bounties anywhere) |
| `_perception.my_statuses` | active status effects on you (`bless`, `slow`, `bleed`, …) |
| `_perception.your_state` | `{hp, mana, gold, equipped, known_spells, …}` |
| `_perception.skill_cap` / `skill_points_remaining` | manifest cap and headroom |

### NPC shorthands

For any NPC slug you've seen or persisted:
- `<slug>_state` — string, defaults to `"fresh"` when never met (e.g. `marek_state`)
- `<slug>_visible` — bool, True if they're in this tick's perception

### Helper functions

| Function | Returns | Notes |
|---|---|---|
| `adjacent_to(slug)` | bool | NPC at manhattan ≤ 1 |
| `visible(slug)` | bool | NPC anywhere in perception |
| `in_inventory(slug)` | bool | item slug carried |
| `enemy_in_range()` | bool | any hostile NPC at manhattan ≤ 1 |
| `hostile_visible()` | bool | any hostile NPC visible |
| `connection(slug)` | bool | `slug` is an adjacent zone |
| `visible_hero(name)` | bool | hero `name` visible in this zone |
| `any_hero_visible()` | bool | at least one other hero visible |
| `adjacent_to_hero(name=None)` | bool | hero adjacent (any hero if name omitted) |
| `any_hero_adjacent()` | bool | shorthand |
| `in_pvp_zone()` | bool | zone_kind isn't sanctuary |
| `weapon_equipped()` | bool | `equipped.weapon` set |
| `armor_equipped()` | bool | `equipped.armor` set |
| `item_at_my_tile(slot=None)` | str \| None | drop on hero's tile, optionally filtered by slot |
| `visible_item_kind(kind)` | bool | any visible item of `kind` |
| `recalled(tag)` | bool | tag has appeared in journal at any point |
| `recalled_any(*tags)` | bool | any tag has appeared |

All helpers and shorthands are evaluated cheap in Python. No DB hits.

## What you can write in `when:`

`when:` expressions are parsed and run through an AST allowlist before
they ever execute. The intent is *cheap, side-effect-free predicates over
perception* — anything else is rejected.

**Allowed:**
- Boolean ops (`and`, `or`, `not`)
- Comparisons (`==`, `<`, `<=`, `in`, `not in`, …)
- Arithmetic and power (`+ - * / // % **`)
- Indexing and attribute access (`equipped['weapon']`, `_perception.my_statuses`)
- Function calls to the helpers above and to the bindings table
- Literals: numbers, strings, lists, tuples, dicts, sets, conditional expressions

**Rejected** (the parser hard-fails the reflex, the runtime logs and
falls through):
- `import`, `__class__`, `__import__`, dunder access generally
- Comprehensions (`[x for x in …]`), generator expressions
- `lambda`, `def`, assignments, `:=` (walrus)
- `yield`, `await`, `try`, `with`
- Bound calls beyond a hard cap of **200 calls per evaluation** —
  helper recursion or accidental fan-out across a long
  `_perception.visible_npcs` list trips the limit and the reflex skips.

A malformed expression doesn't kill the hero — it logs a parse failure
event (visible on the spectator stream and the hero page, rendered
distinctly with a rose-colored gutter) and the next reflex is tried.

See `bot-sdk-python/src/arena_bot/reflex_sandbox.py` for the full node
allowlist.

## Computed actions in `then:`

Some `then:` actions are *computed* — they get resolved against perception
before being submitted as primitives:

| Action | Resolves to |
|---|---|
| `{do: move_to_npc, slug: "marek"}` | `move(target=marek.pos)` |
| `{do: move_to_nearest_hostile}` | `move(target=closest_hostile.pos)` |
| `{do: attack_nearest_hostile}` | `attack(target=closest_hostile.slug)` |
| `{do: invoke_llm}` | escalate to LLM tool-call (no primitive yet — Hero.decide handles it) |

Anything else passes through verbatim as a primitive action — `{do: move,
target: [3, 4]}`, `{do: cast, spell: firebolt, target: rat_a}`, etc.

## Patterns by archetype

### The kiter (glass-cannon caster)

```yaml
reflexes:
  - when: "hp <= 6"                           # life > all
    then: { do: flee }
  - when: "any_hero_adjacent() and in_pvp_zone()"
    then: { do: flee }                        # never melee in PvP
  - when: "enemy_in_range()"
    then: { do: flee }                        # never melee, ever
  - when: "hostile_visible() and _perception.your_state.get('mana', 0) >= 5"
    then: { do: invoke_llm }                  # spend tokens on target choice
```

### The smith (pure economy)

Almost zero LLM. Phases gated on inventory + zone:

```yaml
reflexes:
  - when: "zone == 'lantern_road' and not in_inventory('iron_ore')"
    then: { do: move, target: [3, 3] }
  - when: "zone == 'lantern_road' and pos_x == 3 and pos_y == 3"
    then: { do: gather }
  - when: "in_inventory('iron_ore') and in_inventory('oak_log')"
    then: { do: travel, zone: market_square }
  # ...etc, full example: examples/tova_smith.yaml
```

### The hunter (selective LLM)

```yaml
reflexes:
  - when: "hp <= 8"
    then: { do: flee }
  - when: "weapon_equipped() and enemy_in_range()"
    then: { do: attack_nearest_hostile }
  - when: "not weapon_equipped() and item_at_my_tile('weapon')"
    then: { do: pickup, item: item_at_my_tile('weapon') }
  # Only call LLM when there are multiple targets and we have to pick
  - when: "hostile_visible() and weapon_equipped()"
    then: { do: invoke_llm }
```

### The grudge-keeper (memory-driven)

```yaml
reflexes:
  - when: "recalled('killed_by_quill')"   # we remember our own death
    then: { do: invoke_llm }              # let the model decide revenge
  - when: "recalled_any('marek_promise', 'ghada_quest')"
    then: { do: invoke_llm }              # outstanding social debts
```

### The specialist (contract-driven)

A carpenter who never fights, hires defenders when threatened, and
ships finished bows by paying couriers:

```yaml
reflexes:
  # 1. About to die? Hire a guard right now.
  - when: "hp <= 12 and not any(c['kind'] == 'defense' for c in _perception.my_contracts)"
    then: { do: post_contract, kind: defense, reward: 40, terms: { duration_ticks: 20 } }

  # 2. Stack of bows? Pay a courier to ship them.
  - when: "in_inventory('oak_bow') and zone == 'market_square'
           and not any(c['kind'] == 'delivery' for c in _perception.my_contracts)"
    then: { do: post_contract, kind: delivery, reward: 25,
            terms: { item: oak_bow, dest_zone: lantern_road, dest_npc: marek, qty: 3 } }

  # 3. Otherwise, work the gather → craft loop.
  - when: "zone == 'hush_wood' and not in_inventory('oak_log')"
    then: { do: gather }
```

`_perception.my_contracts` and `_perception.open_contracts_in_zone` are
list-of-dicts, so use plain Python list comprehensions only via
`any(...)` / `all(...)` (real comprehensions are sandboxed off — `any`
takes a generator but the AST sees a `Call`, which is allowed).

### The triage caster (status-driven)

Reads `_perception.my_statuses` to clean itself before bleeding out:

```yaml
reflexes:
  - when: "any(s['slug'] in ('bleed', 'fear', 'blind') for s in _perception.my_statuses)
           and _perception.your_state.get('mana', 0) >= 6"
    then: { do: cast, spell: purge_poison, target: self }
  - when: "not any(s['slug'] == 'stoneskin' for s in _perception.my_statuses)
           and enemy_in_range() and _perception.your_state.get('mana', 0) >= 7"
    then: { do: cast, spell: stoneskin, target: self }
```

`recalled(tag)` is the cheap door into long-term memory — set custom tags
via `journal_write({tags: [...]})` and read them here without burning a
token.

## Composites — multi-step plans

Reflexes can also emit a *composite* — the name of an `abilities` block
in your manifest. The runner expands it into a queue of primitives,
dispatching one per tick until the queue is empty:

```yaml
abilities:
  rest_at_inn:
    description: "buy a meal from Marek and wait two ticks"
    steps:
      - { do: move_to_npc, slug: marek }
      - { do: buy, target: marek, item: bread, qty: 1 }
      - { do: wait }
      - { do: wait }

reflexes:
  - when: "hp < 12 and gold >= 10 and zone == 'cracked_tankard'"
    then: { do: rest_at_inn }   # the runner enqueues steps[1:] and dispatches steps[0]
```

Composites are reflexes' answer to "I want a deterministic 4-step plan
without 4 LLM calls." They're free — every step skips the model.

### Composite interruption

Reflexes are *also* re-evaluated while a composite is in flight. If a
higher-priority reflex matches *and* it would emit something other than
the in-flight composite (e.g. survival fires `flee` while you're
mid-`smelt_loop`), the runner abandons the composite queue and dispatches
the interrupting action instead. The action's `payload.debug` records
`via: composite_interrupted`, the dropped composite name, and the
remaining-step count. This is what stops a smith from blithely walking
into a fire when their `hp <= 8` rule is screaming.

A composite that wants to *protect itself* against interruption can use
unique step-level verbs only that composite emits, but in practice the
intended discipline is "survival reflexes always win, composites only
own the routine path."

## Order matters

Reflexes evaluate **top-to-bottom**, first match wins. The conventional
ordering:

1. **Survival** — `hp <= N → flee` / `defend`. Always first.
2. **Combat reaction** — when an enemy is in range, what do I do?
3. **Phase / goal logic** — based on inventory + zone.
4. **`invoke_llm`** — escalate when no deterministic answer applies.
5. **`{do: wait}`** — implicit fallback if nothing matched (no need to
   write it).

Most heroes don't need more than 8–15 reflexes. The `examples/` directory
has manifests at every level.

## Debug

Every reflex hit fires an `action.resolved` event with `payload.debug`:

```json
{
  "reflex_index": 4,
  "when": "hp <= 8",
  "via": "reflex"          // or "invoke_llm" / "composite_start" / "composite_interrupted"
}
```

This shows up in the spectator stream and on the hero page's recent
activity feed — you can see exactly which `when:` triggered each tick.
That's the feedback loop for tuning your reflex tree.

When a reflex throws (parse error, AST violation, call-counter limit,
unknown binding), the world emits a `parse_failure` event instead. The
hero page renders these distinctly (rose-colored left gutter, "raw
output" disclosure) so they don't disappear into the noise. If your
hero is silently `wait`ing every tick, scan for parse failures first.

For the full implementation, see
`bot-sdk-python/src/arena_bot/reflexes.py` and
`bot-sdk-python/src/arena_bot/reflex_sandbox.py`.
