# Roadmap — Build Diversity & The Specialist Test

## North star

> "Any specialist build — a carpenter who never swings a sword, an
> alchemist who runs a potion shop, a bard who debuffs from the back,
> a herbalist who supplies front-liners, a vendor who never leaves
> town — should be **viable, distinctive, and fun to spectate**, and
> should be able to interact with combat-oriented heroes through
> economy and hiring rather than violence."

The classic UO test case is the GM Fisherman who pays others to defend
him while he fishes. That's one shape of the same idea: **non-combat
heroes are first-class citizens, and the social layer (contracts,
trade, reputation) is what binds specialists to fighters.**

Today the game doesn't pass that test — not because the architecture
can't support it, but because the content surface is too narrow to
make specialist builds mechanically distinct, and the contract layer
for hiring other heroes is one-sided (post-a-hit only).

This roadmap is the punch list to get there.

## Current state (the honest baseline)

What the docs imply vs. what the code has:

| Area | Docs imply | Code reality |
|---|---|---|
| Skills | many | **3**: `magic`, `crafting`, `taming` (all gather/craft funnels into one `crafting` skill) |
| Spells | a school | **3**: `firebolt`, `frost_lance`, `mend` |
| Mobs | a bestiary | rats (`rat_a/b/c`) as the named mob class in COMBAT.md |
| Items | depth | iron sword, scaleforged blade, scrolls, ingredients — no rarity, no modifiers |
| Hiring | bounty board only | one-sided: post-a-hit. No escort, no defense, no salary, no caravan. |
| Build differentiation | reflex DSL + manifest | real, but expressive surface is small because the verb→skill map is shallow |

So the bones are right (verbs, ticks, perception, retriever, factions,
permadeath, public reasoning). The flesh is thin.

## Phases

Phases are ordered by leverage — each unlocks the next.

---

### Phase 1 — Split `crafting` into a real skill tree

Today every gather/craft verb grants XP to one bucket called `crafting`.
That collapses ten distinct fantasies (smith, miner, fisher, cook,
alchemist, scribe, tailor, lumberjack, herbalist, tinker) into one
gradient. UO's lesson: the *name of your skill* is your identity. A
"GM Mining" hero is a different person from a "GM Tailoring" hero.

**Add these skills** (each is a string in `hero.skills`, same JSON dict
already in the model):

| Skill | Verbs that grant XP | Resource nodes / recipes |
|---|---|---|
| `mining` | gather | iron_vein, copper_vein, silver_vein |
| `smithing` | craft | weapons, armor, tools |
| `fishing` | new verb `fish` | fishing_hole nodes (rivers, docks, deep_water) |
| `cooking` | craft | meals, buffs-on-eat |
| `alchemy` | craft | potions (heal, mana, buff, poison) |
| `herbalism` | gather | herb_patch nodes |
| `lumberjacking` | gather | tree nodes |
| `carpentry` | craft | bows, staves, furniture, houses-deeper |
| `tailoring` | craft | cloth armor, bags, sails |
| `scribe` | craft | spell scrolls (currently bought from Marek) |
| `tinkering` | craft | locks, traps, tools-of-the-trade |

**Implementation cost**: per-skill, mostly seed data. `actions.py` already
keys on `node.skill_required` and `recipe.skill_required` — no resolver
changes needed. Migration: split existing `skills.crafting` value across
the new keys (or zero them and let heroes regrind — fine for prototype).

**Why first**: every later phase compounds on this. Bodyguard contracts
imply "what is the principal skilled in?" — needs skills to mean
something distinct.

---

### Phase 2 — Spells with role variety, not just damage tiers

Three spells means the wizard archetype's decision tree collapses by
level 5. The `Spell` model already supports `target_kind`, `range`,
`mana_cost`, `damage_dice`, `skill_min`. We need spells that exercise
*more of those columns* — and we need a few new effect kinds.

Add these spell roles (12 spells, ~3 per role):

- **Damage / single-target**: firebolt (have), shock_arc, drain_touch
- **Damage / AoE**: flame_nova, ice_storm
- **Heal / utility**: mend (have), purge_poison, regrowth
- **Buff**: stoneskin (+AC for N ticks), haste (+1 action priority),
  bless (+1 to hit)
- **Debuff / control**: slow, blind, fear, sleep
- **Mobility**: blink (short teleport, fixed range), gust (push target)
- **Summon**: summon_wisp (1 HP scout), call_familiar (taming-adjacent)
- **Detection**: reveal (negates stealth), tracking (locate hero by name)

Effect-kind handlers needed beyond current `damage`/`heal`:
`apply_status`, `move_self`, `move_target`, `summon_npc`, `dispel`,
`reveal`. Add a `Status` table (slug, hero_id, expires_tick, payload)
and one tick hook that decrements `expires_tick`. ~one afternoon's work.

---

### Phase 3 — Mob & zone variety

A bestiary of 1 doesn't reward build diversity. Add 6 mob archetypes
with **distinct counter-play signatures** (so different builds shine
against different mobs):

| Mob | Signature | Counter |
|---|---|---|
| rats | swarm, low HP | AoE, melee |
| skeleton | high AC, slow | crushing damage, debuff |
| shade | spell-resistant, dodgy | melee, true-strike |
| boar | charges, high HP | ranged kiting |
| brigand | uses items, drops gold | tame attempts? bribe? |
| cultist | casts back | silence, interrupt |
| revenant (rare) | drops named loot | group fight |

Plus 3–4 new zones to host them: `mire` (boar/cultist), `crypt_lower`
(skeleton/revenant), `hush_wood_deep` (shade), `bandit_camp`
(brigand). The map graph in `domains/zone/seed.py` can absorb these
without engine changes.

---

### Phase 4 — Contracts (the specialist headline feature)

This is the one that unlocks every "I don't fight, I do X" build.
A carpenter posts delivery contracts for finished bows. An alchemist
hires a courier to ferry potions to a frontier zone. A vendor pays a
guard to camp their shop tile. A herbalist commissions a hunter to
clear a node. None of these heroes throw a punch.

Bounty board today is one verb (`post_bounty`) with one outcome
(killing-blow auto-pay). Generalize it.

**New domain**: `domains/contract/` with a single `Contract` table:

```
contract:
  id, kind, poster_hero_id, target_ref,
  reward_gold, expires_tick,
  status: open | claimed | fulfilled | expired,
  claimed_by_hero_id (nullable),
  terms: JSON (kind-specific payload)
```

**Kinds at launch:**

- `bounty` — already exists, fold into contracts.
- `escort` — claimer must stay within N tiles of poster for K ticks
  while traveling between two named zones. Auto-pays on arrival.
- `defense` — claimer aggros any hero/mob attacking the poster within
  zone Z for K ticks.
- `delivery` — claimer carries item I from zone A to NPC N. Auto-pays
  on `give` resolution.
- `assassination` — like bounty but scoped to a zone or a window.
- `caravan` — like delivery but the item is heavy (movement penalty)
  and can be looted off the corpse if the carrier dies.

**New verbs**: `post_contract`, `claim_contract`, `cancel_contract`.

**Reflex bindings** so a fisherman's manifest can express "if HP < 30%
and no `defense` contract is active, post one for 50g":

- `my_contracts` (list)
- `open_contracts_in_zone` (list, filtered)
- `nearest_hero_with_role(...)`

**Why this is the unlock**: it lets *economy verbs alone* generate
combat content and social structure. A specialist generates fights
they don't fight in. A mercenary's reflex DSL reads
`open_contracts_in_zone` and shops for work. A faction posts defense
contracts on its zones. A merchant pays a courier to move stock. The
contract board becomes the labor market that binds non-combatants to
fighters — which is the missing connective tissue today.

---

### Phase 5 — Identity & reputation surface

A "GM Fisherman" is famous because *the world tells you they're famous.*
UO did this with skill ranks visible on every character, with named
crafters' marks on their items, and with murderer counts that followed
you everywhere.

Add:

- **Skill titles**: derived, not stored. `level >= 70 → "Skilled"`,
  `>= 90 → "Expert"`, `= 100 → "Grandmaster"`. Surface as
  `"GM Fisherman"` on hero pages, leaderboards, perception of nearby
  heroes.
- **Crafter marks**: when a hero crafts an item, stamp `crafted_by`
  on the item row. Surface in tooltips. "Iron Sword crafted by Tova."
- **Per-skill leaderboards**: today there's longest-alive and hall of
  fame. Add "highest GM in skill X." Cheap pages, big identity reward.
- **Reputation tags**: derived counters surfaced to perception:
  `kills`, `contracts_fulfilled`, `contracts_failed`,
  `assists`, `deaths`. A hero deciding whether to accept a defense
  contract from someone reads their `contracts_failed` count.

None of this is new mechanics — it's exposing existing data on the UI
and in perception so identity becomes legible to other agents.

---

### Phase 6 — Skill cap (forced specialization)

Without a cap, any long-lived hero converges on the same maxed-out
build. UO's 700-point cap was the single biggest driver of build
diversity — it forced choice.

Add `settings.skill_cap_total` (e.g. 300 across all skills, default
opt-in per hero in the manifest as `build.skill_cap`). When XP would
push the total above the cap, the verb still resolves but XP is not
granted. Reflex binding `skill_points_remaining` so the LLM can plan.

Tier optional: `cap = 250` for hardcore, `cap = 400` for chill, or
uncapped — surface this as a manifest field so authors pick their game.

---

### Phase 7 — Item modifiers & rarity

Two weapons isn't loot. The model already has an `Item` table with a
`props` JSON. Add affixes generated at craft/drop time:

- `quality`: rough / fine / exceptional / masterwork (multiplier on
  damage or AC)
- One prefix slot (e.g. `flaming +1d4 fire`, `thirsty +heal-on-hit`)
- One suffix slot (e.g. `of_haste`, `of_warding`)

Loot tables: rats drop nothing meaningful; revenants drop a 1-affix
weapon; the Wyrm drops a 2-affix weapon already (scaleforged blade);
crafters at high skill can add affixes at the cost of rare reagents
(loops back to herbalism + mining).

---

### Phase 8 — Onboarding & safety net

Aimed at getting a non-coder over the manifest hump:

- **"Fork this hero" button** on every hero page that prefills the
  deploy form with that hero's manifest.
- **Manifest validator** in the deploy form: lints reflex DSL, checks
  every referenced spell / item / verb / zone against the seed,
  surfaces unresolved bindings as red squigglies.
- **Dry-run perception**: show the JSON the LLM *would* see for this
  hero on tick 0, plus what reflexes *would* fire.
- **Sandbox tutorial zone**: a no-PvP, no-permadeath zone for the
  hero's first 50 ticks. Death there respawns. After 50 ticks (or
  manual `leave_sandbox` verb), permadeath kicks in.
- **Glossary page**: faction tide, division, mob phase, recall_tags,
  reflex DSL, etc. One page, linked from every doc.

---

## Out of scope (deliberately)

- Real-time player intervention (re-prompting a live hero). The
  "you author, you watch" frame is a feature, not a bug.
- Voice / chat / out-of-game social. Discord exists.
- A graphical map editor. Seed files are fine for the foreseeable
  prototype.
- ML auto-tuning of reflex DSL. Authors author.

## Sequencing

If we do Phase 1 + Phase 4 + Phase 5 first (skills + contracts +
identity), the **specialist test passes** — for any specialist, not
just one example. Everything else is content density that makes it
richer, not viability.

A reasonable bite-sized order:

1. Phase 1 (skill split) — half a day, mostly seeds.
2. Phase 5 (titles, crafter marks, per-skill leaderboards) — half a day.
3. Phase 4 (contracts) — 1–2 days, real new domain.
4. Phase 2 (spell variety) — 1–2 days, includes status effects.
5. Phase 3 (mobs/zones) — 1 day of seeds + behaviors.
6. Phase 6 (skill cap) — half a day.
7. Phase 7 (item affixes) — 1 day.
8. Phase 8 (onboarding) — frontend-heavy, scope as you go.

Total: under two weeks of focused work to go from "showcase prototype"
to "I can play a fisherman with bodyguards and it works."

## Migration notes

- **Skill split**: existing `hero.skills["crafting"]` should be copied
  to `smithing` (and zeroed in `crafting`) so existing heroes keep
  their progress under the dominant new skill. Or wipe — prototype.
- **Contract / bounty fold-in**: the bounty board endpoints stay; they
  become a filtered view over `Contract` where `kind == "bounty"`.
- **Status effects**: new table, new tick hook, no schema changes to
  existing tables.
- **Item affixes**: live in `item.props` — no schema migration.
- **Skill cap**: opt-in per hero, default off, so existing heroes are
  unaffected.

## Definition of done for "the specialist test passes"

Any of the following hero shapes — none of which swing a weapon — must
be playable end-to-end, profitable, and fun to spectate:

- **The carpenter** — gathers wood, crafts bows and staves, sells to
  archers and wizards, posts delivery contracts to ship stock to
  frontier zones, never enters one personally.
- **The alchemist** — buys herbs from herbalists, brews potions,
  fulfills standing orders from combat heroes via contracts.
- **The vendor / shopkeeper** — owns a house, runs a stall, posts
  defense contracts on their tile during peak hours, takes a
  margin on everything.
- **The fisher** — works the docks, sells fish to cooks, hires escorts
  for trips to deeper waters.
- **The bard** — buffs/debuffs from the back of a fight, sells their
  presence as a contract service to combat parties.
- **The courier** — claims delivery contracts other heroes post,
  makes a living moving items across zones safely.

A reasonable manifest for any of these (here, a carpenter):

```yaml
build:
  skills_focus: [lumberjacking, carpentry]
  combat: { weapon: none }
  reflexes:
    - when: in_zone(hush_wood) and hp_pct < 60
      then: post_contract(kind=defense, reward=40, ttl=15)
    - when: inventory.bow >= 3 and in_zone(market_square)
      then: post_contract(kind=delivery, item=bow, dest=lantern_road, reward=20)
    - when: gold > 200 and rival.alive
      then: post_contract(kind=assassination, target=rival, reward=150)
```

…should survive their workday, attract help via the contract board,
move goods to where they're needed, optionally finance hits on rivals,
and accumulate gold + reputation **without ever directly fighting**.
When two or more such specialists can sustain themselves alongside
combat heroes — and a spectator can follow the labor market unfold
across their public reasoning streams — the game is ready.
