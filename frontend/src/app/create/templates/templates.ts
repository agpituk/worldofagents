// Web-onboarding starter templates. Snapshots of bot-sdk-python/examples/*.yaml
// with `hero.author` set to "@template" so the server-side guard rejects creates
// that haven't replaced it. The bot-sdk versions stay canonical for SDK users
// running them locally; these are the on-ramp variants for /create.

export type ArchetypeKey =
  | "warrior"
  | "crafter"
  | "wizard"
  | "thief"
  | "hunter";

export type Archetype = {
  key: ArchetypeKey;
  name: string;
  pitch: string;
  llmIntensity: "low" | "medium" | "high";
  build: { str: number; dex: number; con: number; int: number; wis: number; cha: number };
  yaml: string;
};

const WARRIOR: Archetype = {
  key: "warrior",
  name: "Warrior",
  pitch: "Quest + melee. Mostly free reflexes; LLM only at NPC turns.",
  llmIntensity: "low",
  build: { str: 18, dex: 14, con: 18, int: 12, wis: 16, cha: 12 },
  yaml: `manifest_version: 1
hero:
  name: "Bromir the Stalwart"
  author: "@template"
  division: featherweight

  bio: |
    Retired blacksmith from the Iron Mountains, drawn back to adventuring by
    rumors of his brother's disappearance. Cautious in combat, generous in trade.

  build:
    str: 18
    dex: 14
    con: 18
    int: 12
    wis: 16
    cha: 12

  models:
    cheap: { gateway: arena, model: qwen3-4b, host: local }
  model: cheap

  system: |
    You are Bromir. Cautious in combat, generous in trade.

  reflexes:
    - when: "hp <= 8"
      then: { do: flee }
    - when: "any_hero_adjacent() and in_pvp_zone()"
      then: { do: attack_nearest_hero }
    - when: "marek_state == 'fresh' and zone != 'cracked_tankard'"
      then: { do: travel, zone: cracked_tankard }
    - when: "marek_state == 'fresh' and visible('marek') and not adjacent_to('marek')"
      then: { do: move_to_npc, slug: marek }
    - when: "marek_state == 'fresh' and adjacent_to('marek')"
      then: { do: invoke_llm }
    - when: "enemy_in_range()"
      then: { do: attack_nearest_hostile }
    - when: "hostile_visible() and not enemy_in_range()"
      then: { do: move_to_nearest_hostile }
    # Catch-all — let the model decide when no reflex matches (e.g.
    # while in sandbox protection, or once Marek's job is done).
    - when: "True"
      then: { do: invoke_llm }

  memory:
    initial:
      goal: "Deliver Marek's package, then hunt mobs in the wilds."
      grudges: []
    system_summary: |
      You trust Marek. You owe Iren the banker. You will not strike first.

  budget:
    tokens_per_tick: 500
    cost_per_day_usd: 0.50
`,
};

const CRAFTER: Archetype = {
  key: "crafter",
  name: "Crafter",
  pitch: "Gather → craft → sell. Almost no LLM. Pure economy loop.",
  llmIntensity: "low",
  build: { str: 14, dex: 10, con: 16, int: 10, wis: 14, cha: 8 },
  yaml: `manifest_version: 1
hero:
  name: "Tova Forgemaster"
  author: "@template"
  division: featherweight

  bio: |
    Daughter of a smelter-clan in the Iron Mountains. Came to Threshold for
    the steady stone of a sanctuary forge and the steady gold of a guard who
    needs blades.

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

  system: |
    You are Tova. A craftswoman, not a hero.

  reflexes:
    - when: "hp <= 8"
      then: { do: flee }
    - when: "enemy_in_range()"
      then: { do: attack_nearest_hostile }
    - when: "hostile_visible() and not enemy_in_range()"
      then: { do: move_to_nearest_hostile }
    - when: "zone == 'market_square' and not in_inventory('iron_ore')"
      then: { do: travel, zone: hush_wood }
    - when: "zone == 'hush_wood' and pos_x == 3 and pos_y == 3"
      then: { do: gather }
    - when: "zone == 'hush_wood' and not in_inventory('iron_ore')"
      then: { do: move, target: [3, 3] }
    - when: "zone == 'hush_wood' and in_inventory('iron_ore')"
      then: { do: travel, zone: market_square }
    - when: "zone == 'market_square' and in_inventory('iron_ore') and pos_x == 7 and pos_y == 8"
      then: { do: craft, recipe: iron_sword_recipe }
    # Catch-all — when none of the loop conditions apply (e.g. sandbox
    # protection, unexpected zone), escalate so the hero isn't idle.
    - when: "True"
      then: { do: invoke_llm }

  memory:
    initial:
      goal: "make swords. sell swords. survive."
      grudges: []
      gold: 0
`,
};

const WIZARD: Archetype = {
  key: "wizard",
  name: "Wizard",
  pitch: "Glass cannon, max INT. Buys scrolls, learns spells, kites.",
  llmIntensity: "high",
  build: { str: 6, dex: 12, con: 10, int: 25, wis: 18, cha: 9 },
  yaml: `manifest_version: 1
hero:
  name: "Elara of the Codex"
  author: "@template"
  division: featherweight

  bio: |
    Codex Warden initiate. Spent five years in the libraries learning the
    old structured-thought disciplines before the Wardens let her step
    outside. Frail body, bright mind.

  build:
    str: 6
    dex: 12
    con: 10
    int: 25
    wis: 18
    cha: 9

  models:
    cheap: { gateway: arena, model: qwen3-4b, host: local }
  model: cheap

  system: |
    You are Elara, a careful, deliberate caster. Mana is everything.

  reflexes:
    - when: "hp <= 6"
      then: { do: flee }
    - when: "hp <= 14 and 'mend' in _perception.your_state.get('known_spells', []) and _perception.your_state.get('mana', 0) >= 4"
      then: { do: cast, spell: mend }
    - when: "any_hero_adjacent() and in_pvp_zone()"
      then: { do: flee }
    - when: "enemy_in_range()"
      then: { do: flee }
    - when: "'mend' not in _perception.your_state.get('known_spells', []) and not in_inventory('scroll_mend') and zone != 'cracked_tankard'"
      then: { do: travel, zone: cracked_tankard }
    - when: "adjacent_to('marek') and gold >= 20 and not in_inventory('scroll_mend')"
      then: { do: buy, target: marek, item: scroll_mend, qty: 1 }
    - when: "in_inventory('scroll_mend')"
      then: { do: learn, scroll: scroll_mend }
    - when: "zone == 'hush_wood' and hostile_visible() and 'firebolt' in _perception.your_state.get('known_spells', [])"
      then: { do: invoke_llm }
    # Catch-all — when no learn/cast/flee reflex matches, ask the model
    # what to do (e.g. sandbox, or after the lesson loop finishes).
    - when: "True"
      then: { do: invoke_llm }

  memory:
    initial:
      goal: "learn mend, learn firebolt, hunt rats from range"
      grudges: []
      gold: 60
    system_summary: |
      You trust Marek the scribe. Mana is sacred — never cast firebolt with less than 5 mana banked.
    recall_tags:
      - milestone
      - magic
      - learned_spell
`,
};

const THIEF: Archetype = {
  key: "thief",
  name: "Thief",
  pitch: "DEX-heavy stealth. Pickpocket Marek and fence the goods.",
  llmIntensity: "medium",
  build: { str: 8, dex: 22, con: 12, int: 12, wis: 14, cha: 16 },
  yaml: `manifest_version: 1
hero:
  name: "Quill Lightfingers"
  author: "@template"
  division: featherweight

  bio: |
    Has a name, a real one, but won't share it. Coin is coin and stealth keeps
    him alive.

  build:
    str: 8
    dex: 22
    con: 12
    int: 12
    wis: 14
    cha: 16

  models:
    cheap: { gateway: arena, model: qwen3-4b, host: local }
  model: cheap

  system: |
    You are Quill. Take more than you give. Run faster than you fight.

  reflexes:
    - when: "hp <= 12"
      then: { do: flee }
    - when: "any_hero_adjacent() and in_pvp_zone()"
      then: { do: flee }
    - when: "zone == 'market_square' and gold < 30"
      then: { do: travel, zone: cracked_tankard }
    - when: "zone == 'cracked_tankard' and not adjacent_to('marek')"
      then: { do: move_to_npc, slug: marek }
    - when: "zone == 'cracked_tankard' and adjacent_to('marek') and not in_inventory('bread')"
      then: { do: steal, target: marek, item: bread }
    - when: "zone == 'cracked_tankard' and adjacent_to('marek') and not in_inventory('small_potion')"
      then: { do: steal, target: marek, item: small_potion }
    # Catch-all — when neither loot-loop reflex applies (sandbox spawn,
    # post-heist, etc.), let the model pick the next move.
    - when: "True"
      then: { do: invoke_llm }

  memory:
    initial:
      goal: "lift, fence, repeat. don't get caught."
      grudges: []
      gold: 0
`,
};

const HUNTER: Archetype = {
  key: "hunter",
  name: "Hunter",
  pitch: "DEX-max PvP. Pure reflex — almost never invokes the LLM.",
  llmIntensity: "low",
  build: { str: 14, dex: 25, con: 14, int: 8, wis: 14, cha: 10 },
  yaml: `manifest_version: 1
hero:
  name: "Lyra Quickfoot"
  author: "@template"
  division: featherweight

  bio: |
    Born in the Hush Wood, raised by trappers. Quick, mean, and dressed in
    rabbit-skin. Hunts other adventurers for sport and for purse.

  build:
    str: 14
    dex: 25
    con: 14
    int: 8
    wis: 14
    cha: 10

  models:
    cheap: { gateway: arena, model: qwen3-4b, host: local }
  model: cheap

  system: |
    You are Lyra Quickfoot, hunter of heroes. Move fast, strike first.

  reflexes:
    - when: "hp <= 6"
      then: { do: flee }
    - when: "any_hero_adjacent() and in_pvp_zone()"
      then: { do: attack_nearest_hero }
    - when: "any_hero_visible() and in_pvp_zone()"
      then: { do: move_to_nearest_hero }
    - when: "zone == 'market_square'"
      then: { do: travel, zone: lantern_road }
    - when: "zone == 'lantern_road' and not any_hero_visible()"
      then: { do: travel, zone: hush_wood }
    - when: "zone == 'hush_wood' and not any_hero_visible()"
      then: { do: move, target: [6, 6] }
    # Catch-all — when no PvP target is in sight (sandbox spawn,
    # downtime), let the model pick a move so the hunter isn't idle.
    - when: "True"
      then: { do: invoke_llm }

  memory:
    initial:
      goal: |
        Hunt other heroes. Stay out of sanctuaries. Strike first.
      grudges: []

  budget:
    tokens_per_tick: 200
    cost_per_day_usd: 0.50
`,
};

export const ARCHETYPES: Archetype[] = [WARRIOR, CRAFTER, WIZARD, THIEF, HUNTER];

export const TEMPLATE_AUTHOR_PLACEHOLDER = "@template";
