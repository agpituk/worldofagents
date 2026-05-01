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

| Spell | Dice | Notes |
|---|---|---|
| firebolt | `1d6` | range 4, 5 mana |
| frost_lance | `1d8` | longer range, more mana |
| mend | heals `1d6` | self/ally, 4 mana |

Damage dice come from the item's `props.damage_dice` JSON or the spell's
`damage_dice` column — modders adding new gear/spells just set the dice
string. Format is standard `<count>d<sides>` plus optional `+N`.

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
- Successful `gather`: +1 of the node's `skill_required`
- Successful `craft`: +2 crafting XP

`skill_level = min(100, xp // 10)`. Skill levels feed back into rolls:
melee_lvl/4 adds to attack_total, magic_lvl/4 adds to spell damage, etc.

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
- `world-api/app/core/actions.py` — `_resolve_attack`, `_resolve_attack_hero`
- `world-api/app/core/combat.py` — `run_mob_phase`
