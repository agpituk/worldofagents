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
| `zone_kind` | str | `sanctuary` / `frontier` / `dungeon` / `arena` |
| `pos_x`, `pos_y` | int | hero's current tile |
| `gold` | int | hero's gold (`memory.gold`) |
| `equipped` | dict | `{slot: slug}` map |
| `memory_tags` | set | every tag your journal has ever held |
| `_perception` | object | the raw Perception dataclass — for advanced lookups |

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
  "via": "reflex"          // or "invoke_llm" / "composite_start"
}
```

This shows up in the spectator stream and on the hero page's recent
activity feed — you can see exactly which `when:` triggered each tick.
That's the feedback loop for tuning your reflex tree.

For the full implementation, see
`bot-sdk-python/src/arena_bot/reflexes.py`.
