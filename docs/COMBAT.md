# Combat — Roll the d20

Combat is **d20-style under the hood**. Every attack is a d20 + modifiers
versus a target Armor Class. The same roll structure handles melee, ranged
spells, taming, stealing, and barter checks — only the modifiers and DCs
change.

## The basic attack roll

```
attack_roll  = d20()
attack_total = attack_roll + (str // 4) + weapon.attack_bonus + (melee_skill // 4)
hit          = attack_total >= target.ac   OR   attack_roll == 20  (crit)
miss         = attack_roll == 1            (fumble)
```

If you hit:

```
damage = roll(weapon.damage_dice) + (str // 4)
if crit: damage *= 2
```

So a **STR 16 hero with a +1 iron sword** (1d8) at melee skill 8 attacks
with `d20 + 4 + 1 + 2 = d20+7` and deals `1d8+4` on hit (`2d8+8` on crit).

## Armor Class (AC)

A hero's AC is built up from:

```
AC = 10 + (dex // 4) + armor.ac_bonus
   + 5 if defending this tick
```

Mob AC is fixed per NPC slug (rats are AC 12, embered cultists AC 14, the
wyrm AC 15). Heroes scale with DEX and armor.

### `defend` — the +5 AC tick

The `defend` action raises your AC by 5 for the rest of this tick (and only
this tick). It costs no resource. It's the right play when:
- You're at low HP and about to be attacked
- A target is mid-ranged-spell on you and you can't flee in time
- A reflex says `when: "hp <= 8 and enemy_in_range()" then: defend` is
  often a good first survival rule before `flee`.

## Damage dice cheat sheet

| Weapon | Dice | Notes |
|---|---|---|
| unarmed | `1d2` | what you start with |
| iron sword | `1d8` | basic crafted weapon |
| scaleforged blade | `2d6` | hidden-recipe craft (requires dragon scale) |

Spells fall into seven effect kinds. Direct damage / heal still rolls
the dice column; the rest dispatch through `effect_kind` and `payload`.

| Spell | Kind | Range | Mana | Effect |
|---|---|---|---|---|
| `firebolt` | damage | 4 | 5 | `1d6` fire to enemy |
| `frost_lance` | damage | 5 | 8 | `1d10` cold to enemy |
| `shock_arc` | damage | 1 | 4 | `1d8` lightning to adjacent enemy |
| `mend` | heal | 0 | 4 | heal self `1d6` |
| `regrowth` | apply_status | 3 | 6 | gives `regrowth` (heal `1d3` per tick × 8) |
| `purge_poison` | dispel | 3 | 6 | strips `bleed`/`blind`/`fear`/`slow`/`sleep` from target |
| `stoneskin` | apply_status | 0 | 7 | self `+4 AC` for 12 ticks |
| `bless` | apply_status | 3 | 5 | target `+1 to-hit` for 15 ticks |
| `blind` | apply_status | 3 | 6 | enemy `-3 to-hit` for 6 ticks |
| `fear` | apply_status | 3 | 6 | enemy `-2 to-hit` for 8 ticks |
| `blink` | move_self | 4 | 5 | teleport to a target tile |
| `gust` | move_target | 3 | 4 | push enemy 2 tiles |
| `summon_wisp` | summon_npc | 0 | 8 | spawn 1-HP scout NPC at your tile |
| `reveal` | reveal | 4 | 5 | strips `stealth` from anything in radius |

Damage dice come from the item's `props.damage_dice` JSON or the spell's
`damage_dice` column. Format is standard `<count>d<sides>` plus optional
`+N`. Effect handlers are wired in `world-api/app/core/actions.py` —
new effects mean new code, not just seed data.

## Status effects

A `Status` is a typed, time-limited modifier on a hero. Apply via spells,
mob bites, or item procs; expire on a tick hook (`tick_statuses`) when
`expires_at_tick` is reached. The runtime applies their payloads before
each action resolves.

| Slug | Source | Effect |
|---|---|---|
| `bless` | `cast bless` | `+1 to-hit` |
| `stoneskin` | `cast stoneskin` | `+4 AC` |
| `regrowth` | `cast regrowth` | heals `1d3` per tick |
| `bleed` | brigand crit, weapon affix | takes `1d3` damage per tick |
| `blind` | `cast blind` | `-3 to-hit` |
| `fear` | `cast fear` | `-2 to-hit` |
| `slow` | spell / item proc | `-1 priority` (acts later in tick) |
| `sleep` | spell | `-10 to-hit`, `-5 AC` (defenseless) |
| `stealth` | thief skill | invisible to perception |
| `tracking` | `cast reveal` mirror | cosmetic locator |

Read your current statuses from `_perception.my_statuses` —
`[{slug, expires_at_tick, payload}]`. A reflex like `when: "any(s['slug']
== 'bleed' for s in _perception.my_statuses)" then: { do: cast, spell:
purge_poison, target: "self" }` is the canonical *"clean myself before I
bleed out"* pattern.

## Affixes & item quality (Phase 7)

When a hero crafts a weapon or armor, the world rolls a *quality tier*
based on their skill, plus optional prefix/suffix affixes. The wyrm's
scaleforged blade always rolls two affixes; rare loot drops roll one.

**Quality tiers** (multiplier on damage / AC):

| Tier | Multiplier |
|---|---|
| `rough` | 0.8× |
| `fine` | 1.0× |
| `exceptional` | 1.25× |
| `masterwork` | 1.5× |

**Prefixes** (rolled on craft / drop):

| Affix | Effect |
|---|---|
| `flaming` | `+1d4` fire on hit |
| `frostbound` | `+1d4` cold on hit |
| `thirsty` | heals 2 HP per landed hit |
| `keen` | `+1` crit-range bonus |
| `reinforced` | `+1` AC (armor only) |
| `swift` | `+1` priority bonus |

**Suffixes:**

| Affix | Effect |
|---|---|
| `of_warding` | `+1` AC |
| `of_haste` | `+1` priority |
| `of_the_bear` | `+1` to-hit |
| `of_silver_blood` | `+1d6` vs undead |

Each crafted item also stamps `item.crafted_by_id` and
`item.crafted_by_name` — that's the crafter mark you see surfaced on
hero pages and item tooltips. *"Plate Hauberk crafted by Tova
(Grandmaster Smith)"* is the world telling everyone Tova is famous.

## PvP rules

- **Sanctuaries are no-PvP.** `attack_hero` and offensive `cast` are both
  rejected with `error: "PvP forbidden in sanctuary"`. Sanctuaries today:
  market_square, cracked_tankard, watchmans_bastion, codex_hall, embered_shrine.
- **Frontier zones are PvP-enabled.** Lantern Road, Hush Wood. Tournaments
  amplify this — kills there during a tournament window credit your entry.
- **Looting on PvP kill.** 50% of the victim's gold transfers to the killer.
  See `_resolve_attack_hero` in `world-api/app/core/actions.py` for the math.
- **Open bounties pay out.** Any open bounty on the victim's `target_hero_id`
  is automatically claimed by the killer (unless they posted it themselves —
  self-posted bounties refund instead). See [bounty board](../README.md#bounties).

## Mob phase

After every hero in a tick has acted, the **mob retaliation phase** runs:
each hostile NPC adjacent to a hero gets one free attack. This is why
"the rat hits me back when I don't kill it" — it's the core asymmetric
risk that makes engaging mobs a calculated bet.

The bestiary today (each archetype has distinct counter-play):

| Archetype | Signature | Counter |
|---|---|---|
| rat | swarm, low HP, low damage | AoE / cleave / kite |
| skeleton | high AC, slow | crushing damage, debuffs (`slow`/`fear`) |
| shade | spell-resistant, dodgy | melee, `reveal` to strip stealth |
| boar | charges, high HP | ranged kiting |
| brigand | uses items, drops gold | tame attempts, `blind`, ranged |
| embered cultist | casts spells back | silence, interrupt with `gust` |
| wisp | summoned scout, 1 HP | ignore — it's a perception probe |

Mob attacks use the same d20 formula:
```
roll = d20()
total = roll + mob.attack_bonus
hit   = total >= hero.ac   OR   roll == 20
damage = roll(mob.damage_dice)   (doubled on crit)
```

A hero who flees out of melee range *before* the hero phase ends avoids the
mob phase entirely. That's why `flee` is so often the best survival reflex.

## Non-combat checks (same roll structure)

| Action | Roll | Target |
|---|---|---|
| `tame` | `d20 + cha/4 + wis/4` | DC 12 |
| `steal` | `d20 + dex/4 + stealth_lvl/4` | DC 15 (NPC awareness) |
| `cast` heal | no roll, deterministic | range check only |
| `cast` damage | no attack roll | range check, then `damage = roll(spell.damage_dice) + skill_lvl/4` |

`steal` failure on nat-1 marks the merchant `aware_of_thief` and inflates
future buy/sell prices for that hero by 2× — there's a real cost to caught
thieves. `tame` failure is just a wasted action, no penalty.

## Skill XP

Combat actions grant skill XP:
- Successful `attack`: +1 melee XP, +5 on a kill
- Successful `cast`: +1 magic XP
- Successful `gather`: +1 of the node's `skill_required` (`mining`,
  `herbalism`, or `lumberjacking`)
- Successful `fish`: +1 fishing XP
- Successful `craft`: +2 of the recipe's `skill_required` (`smithing`,
  `tailoring`, `cooking`, `alchemy`, `carpentry`, `scribe`, or
  `tinkering`)

`skill_level = min(100, xp // 10)`. Skill levels feed back into rolls:
melee_lvl/4 adds to attack_total, magic_lvl/4 adds to spell damage,
gather_skill/4 raises gather yield, smithing/4 raises craft quality
(quality tiers above).

**Skill cap.** If the manifest sets `build.skill_cap`, the runtime stops
granting XP once `sum(hero.skills.values()) >= cap`. The verb still
resolves; the XP grant is just a no-op. `_perception.skill_points_remaining`
exposes the headroom so reflexes can plan around it.

## Faction reputation

Every hero has `faction_rep: {wardens, council, embered}` integers that
shift on action:
- Mob kills grant +1 council and the mob's `factions_aligned` deltas
- Quest claims grant the template's reward_faction_amount
- Faction tide events (every 7000 ticks) crown the leading faction

Thresholds at 10/25/50 trigger journal milestones and sometimes unlock
content (e.g. embered shrine training requires `embered >= 5`). Negative
rep can lock you out of a faction's NPCs.

## How to optimize as a player

- **Don't roll vs your ceiling.** A featherweight 1d2-fist hero attacking
  a wyrm (AC 15, 80 HP) just dies. Fight your tier; flee from the rest.
- **Stack passive bonuses early.** STR is a slow gain (each +4 = +1 to
  attack_total). Equipping a +1 attack-bonus weapon is faster.
- **Defend before the deathblow.** A reflex like `when: "hp <= 6 and
  enemy_in_range() and equipped.get('armor')" then: defend` before fleeing
  often saves the day.
- **Fumbles cost a tick.** Reflexes can't avoid them, but they're rare
  (5%). Don't write fumble-handling logic; the world surfaces them as a
  miss event for the spectator stream.

For the full implementation, see:
- `world-api/app/core/dice.py` — `d20()` and `roll(dice_str)`
- `world-api/app/core/actions.py` — `_resolve_attack`, `_resolve_attack_hero`, status modifiers
- `world-api/app/core/combat.py` — `run_mob_phase`
- `world-api/app/core/affixes.py` — quality + prefix/suffix tables
