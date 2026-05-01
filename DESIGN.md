# World of Agents — Design Document

> Canonical design notes for World of Agents (working title). Everything here was agreed in design conversation; treat this as source-of-truth context for resuming work.

## 1. Vision

**A persistent MMO world where every player ships an LLM-driven hero and watches them live a life on the prompts they wrote.** Screeps-but-prompts. Players don't pilot moment-to-moment — they author a hero (manifest, build, prompt) and spectate. The LLM's reasoning is public and is the entertainment.

The pitch in one line: *"You write a prompt, your hero lives a life on it, and you watch them think their way through the world. The thoughts are public, the deaths are monuments, and the highlight reel writes itself."*

**Why it goes viral:**
- David-vs-Goliath story (a Raspberry Pi llamafile beating Opus is real and headline-worthy)
- LLM reasoning is inherently shareable — see AI Town
- Permadeath + public death pages create monuments worth tweeting
- The game is secretly a portfolio piece for agent engineering — a hot skill people want to learn

**Forced gateway:** every LLM call routes through *our* gateway, which under the hood uses cq / any-llm / llamafile. This is the metering layer, the moat, and the trust anchor.

---

## 2. Game Design

### 2.1 Player & hero model

- **One named hero per player.** Individual, not colony. Heroes have a name, a bio, a portrait, a Twitter-shareable URL.
- **Permadeath.** When a hero dies, the death is public and permanent. Player can immediately spawn a new hero.
- **On respawn**: same build template offered for free (you've already paid the design cost). New hero name and bio.

### 2.2 Divisions (weight classes)

| Division | Constraint | Vibe |
|---|---|---|
| **Featherweight** | Local-only models (llamafile/ollama), <500ms response | Pi at home, scrappy underdog |
| **Middleweight** | Cloud allowed, capped tokens-per-tick | Mainstream player |
| **Heavyweight** | Anything goes, hard cost cap, **earned/limited slots** (~200 active) | Aspirational. Earned via featherweight performance, weekly draft, etc. |

The gateway enforces division at request time — featherweight can't request opus.

### 2.3 Build system (point-buy)

100 points to distribute across 6 stats. Min 5, max 25 per stat. **Permanent for that hero's life. No respec.**

| Stat | Effect |
|---|---|
| **STR** | Melee damage, carry capacity |
| **DEX** | Move speed in ticks, dodge, ranged accuracy, **initiative** |
| **CON** | Max HP (HP = 20 + CON), stamina regen |
| **INT** | **Tokens-per-thinking-tick budget** (the LLM's thinking room) |
| **WIS** | **Memory KV size + perception radius** (what the LLM sees & remembers) |
| **CHA** | `say()` persuasion modifier, trade prices |

**Genius mechanic**: INT/WIS/CHA directly shape the LLM's information environment. A wizard build (high INT/WIS) literally has more thinking room and bigger memory; a barbarian build (high STR/CON, low INT) reflexes its way through fights with a tiny model. **Build choice and model choice interact** — featherweight gravitates physical, heavyweight cerebral.

### 2.4 Tools — primitives + composites

**Two tiers.** The world only ever resolves primitives. Composites are player-side macros that expand to primitives.

#### Primitive verbs (immutable, ~20)

```
movement   move(target)  face(direction)  follow(entity)
perception look(radius)  examine(entity)  listen()
combat     attack(target)  defend()  cast(spell, target)  flee()
social     say(msg)  whisper(target, msg)  emote(action)
items      pickup(item)  drop(item)  use(item)  equip(item)  give(target, item)
trade      offer(target, items, price)  accept(id)  reject(id)
state      rest()  wait()  remember(key, val)  forget(key)
```

Verbs are universal but their **effectiveness** depends on items and acquired knowledge. `cast(fireball)` is legal for any hero, but with no fireball learned the world resolves it as wasted tick.

**Primitive set evolves at season cadence** (every ~3 months) via community vote. No mid-season changes.

#### Composites (player-defined macros)

```yaml
abilities:
  charge_attack:                    # deterministic — fixed sequence, free
    description: "Close distance and strike in one tick"
    decompose:
      - move(target.position - 1)
      - attack(target)

  scout_room:                       # prompted — sub-agent picks primitives, costs tokens
    description: "Survey surroundings and note anything important"
    model: cheap
    system: "You are scouting. Use look/examine, then remember() findings."
    allows: [look, examine, remember]
    budget: 200_tokens
```

- **Composites are shareable, traded, sold** → a recipe marketplace, a community layer
- **In-game earned abilities** (acquired via training/scrolls/quests) — v2 progression hook
- Banned: arbitrary code execution, network calls, side effects outside the world

### 2.5 Combat (d20-style, tick-based)

- **Tick = 6 seconds = 1 combat round.**
- Two regimes:
  - **Out of combat** — agents in different contexts resolve in parallel; presentation ordered by initiative
  - **In combat** — strict serialized initiative; LLM call happens at agent's turn against current world state. No "I planned X but they moved" frustration.
- **Combat trigger**: an `attack` declared on another agent in range puts both into initiative.
- **Initiative** ordered by DEX (ties: INT, then random).

#### Math

```
attack roll  = d20 + (STR or DEX)/4 + weapon.attack_bonus
target AC    = 10 + DEX/4 + armor.bonus
hit if attack_roll ≥ AC
damage       = weapon.dice + STR/4
nat 20       = crit (double damage)
nat 1        = fumble (lose next tick / drop weapon)
HP start     = 20 + CON
death        = HP ≤ 0
```

Spells use INT for attack roll, deal type-specific damage, cost mana (also INT-scaled).

#### Action submission as priority list

Agents emit a ranked list; world picks the first valid one at execution time:

```json
{
  "actions": [
    {"do": "attack", "target": "orc",  "if": "orc.in_melee_range"},
    {"do": "move",   "target": "orc",  "if": "orc.visible"},
    {"do": "defend"}
  ]
}
```

Rewards smart contingency thinking. Production-agent lesson: always have a fallback.

#### Drama hooks
- **Death speech** — dying agent's last LLM call is broadcast publicly
- **Crit narration** — narrator-LLM auto-generates flavor text for crits/kills
- **Witnesses** — agents in the zone "see" the fight; can write to memory, narrate, seek revenge

### 2.6 World map

- **~50 zones at launch**, graph-connected (not a strict grid). Some zones have 2 exits, some 5.
- Each zone is a 10×10 grid or a small set of named "spots."
- A zone has: name, theme, danger level, soft agent-capacity, resource nodes, NPCs.

#### Zone types

| Type | PvP | Cap soft / hard | Purpose |
|---|---|---|---|
| **Sanctuary** (cities, taverns) | off | 40 / ∞ via instances | Merchants, trainers, social hubs |
| **Frontier** (wilderness) | on | 15 / 25, max 2-3 instances | Mobs, resources, mid-danger |
| **Dungeon** | on | 6 / 10, hard or party-instanced | Themed dives, high reward |
| **Arena** (tournaments) | structured | bracket-defined | Scheduled tournaments per division |

#### Movement
- `move(direction or coord)` within zone, ~1 tile per tick (DEX-modified)
- `travel(zone)` between adjacent zones, ~1 tick per hop
- **Persistence**: zones evolve. Raided villages stay raided. Resources regrow on cycles. NPC moods accumulate.

### 2.7 Idle / AFK

- **Inn mode** (manual or auto-after-50-ticks-idle) — hero parks at a sanctuary, doesn't count toward zone cap, can't be attacked.
- **Frontier idle = vulnerable** — hero stays put but can be attacked, robbed. Adds real risk to leaving them mid-wilderness. Source of overnight drama.

### 2.8 Lore & setting

**Post-collapse low fantasy where the LLM mechanic IS the magic system.**

A generation ago, the **Sundering** broke the world's *structured thought* — the formal discipline that held magic, contracts, language, and complex craft together. Most people now think only in fragments. **Heroes (you) are anomalies — minds that can hold long, structured thought.** That literally *is* your prompt + token budget. NPCs are wary, awed, or jealous.

- Cheap models = local awakened folk
- Frontier models = something more (and the Wardens want to know what)
- Token budgets = "thought stamina"
- Memory composites = "recovered disciplines"

### 2.9 Threshold (the starting city)

Three terraced rings at the edge of the **Sundered Mile**:

- **Upper Vault** — administration, guarded, the Codex Hall
- **Market Tier** — where everyone meets
- **Underspill** — slums, smugglers, the Cisterns

#### Three factions in soft tension

| Faction | Want | Pay heroes for | Vibe |
|---|---|---|---|
| **Codex Wardens** | Pre-Sundering knowledge recovered | Recovered texts, intact composites, witnessed phenomena | Lawful, methodical, secretive |
| **Free Council** | Roads safe, city profitable | Bounties, escort, market security | Pragmatic, transactional, gossipy |
| **The Embered** | A new beginning post-Sundering | Service in heretical rituals | Generous, unsettling, possibly correct |

#### Locations within Threshold

| Location | Type | Function |
|---|---|---|
| **Market Square** | Sanctuary | Merchants, public quest board |
| **The Cracked Tankard** | Sanctuary | Tavern, gossip, side-quest hookups |
| **Watchman's Bastion** | Sanctuary | Guard hires, bounty board, banking |
| **Codex Hall** | Sanctuary | Library, composite trainer (memory/perception) |
| **The Embered Shrine** | Sanctuary, sketchy | Heretical composite trainer (high-power, side effects) |
| **The Old Cisterns** | Frontier / tutorial dungeon | First solo content for new heroes |

#### Adjacent zones
- **The Lantern Road** — mid-danger frontier, route to other towns
- **Hush Wood** — forest, herbs, low-mid mobs
- **The Sundered Mile** — high-danger ruins, multi-zone endgame area

#### NPCs (six)

- **Marek Ashfoot** — Innkeeper of the Cracked Tankard. Ex-mercenary, knows everyone. Hook: his daughter went into the Sundered Mile six months ago.
- **Magistra Vela** — Codex Warden, Hall of Threshold. Pays for recovered texts. Hook: interested in *you* — what model are you running?
- **Captain Old Ghada Stoneknuckle** — Watchman's Bastion. Teaches combat composites (charge, riposte, shield-wall). Hook: bandits on the Lantern Road have gotten bolder.
- **Brother Jossen** — Embered, Underspill shrine. Teaches dangerous composites with costs (cooldown, hp drain, stat penalty). Hook: believes you're "approaching the threshold."
- **Quill** — fence near the Cisterns at night. Off-books items, illegal scrolls. Hook: has a buyer for anything from the Sundered Mile.
- **The Cracked One** — unhoused oracle, Market Square. Speaks in fragments that occasionally describe your future. Hook: drops endgame breadcrumbs.

#### First-hour onboarding

1. Spawn in Market Square. The Cracked One mutters their hero's name.
2. Marek at the Tankard offers a delivery quest (sealed package to Ghada). Tutorial: `move`, `travel`, `say`, `give`.
3. Ghada offers a bounty: rats in the Old Cisterns. Tutorial: `attack`, `examine`, `pickup`.
4. Returning, Vela approaches them in the Square. Quiet evaluation. Real first job.
5. By hour two, all three factions have noticed them. The player chooses a thread.

---

## 3. UX Design

### 3.1 The spectator-author player

The player is **not piloting**. They're a spectator-author. They wrote the prompt; they watch consequences. Three modes:

| Mode | Activity | % of time |
|---|---|---|
| Spectator | Watching their hero think and act | 70% |
| Author | Editing manifest, tuning prompts | 25% |
| Social | Browsing other heroes, leaderboards, market | 5% |

**The LLM's reasoning IS the entertainment.** Don't hide thoughts. Make them the centerpiece. AI Town went viral on exactly this.

### 3.2 The Live Hero View (the main play screen)

Three panes:

```
┌──────────────────┬─────────────────────────────┬──────────────────┐
│  ZONE MAP        │  THOUGHT STREAM (live)      │  STATUS          │
│                  │                             │  HP: 24/38       │
│   . . o . .      │  [tick 1247] perceives:     │  Gold: 142       │
│   . B . . .      │    orc (hp~12), 3 tiles E   │  Zone: Hush Wood │
│   . . . . .      │    Bromir thinks:           │                  │
│   . . . S .      │    "Wounded. Can finish."   │  INVENTORY       │
│   . . . . .      │    → attack(orc)            │  • Iron sword    │
│                  │                             │  • Health potion │
│  B = Bromir      │  [tick 1248] resolution:    │                  │
│  o = orc         │    HIT — 9 damage           │  ACTIVE QUEST    │
│  S = sapling     │    orc dies                 │  Marek's package │
└──────────────────┴─────────────────────────────┴──────────────────┘
```

### 3.3 Hero profile (the viral artifact)

Public URL `arena.gg/h/<hero-slug>`:

- Portrait + bio + live status
- Stat sheet, division, model in use
- Career: kills, quests, deaths, fame
- Recent thoughts wall (curated quotable moments)
- **Death speech** (if dead) — pinned forever as epitaph
- Manifest preview (system prompt hidden by default with toggle; thoughts public; build & reflexes public)

### 3.4 Engagement loops

| Loop | Cadence | What |
|---|---|---|
| Tight | minutes | Watch dumb decision → edit one prompt line → redeploy → watch again. Sub-30s redeploy required. |
| Medium | per session | "What's happened since I logged off?" Read highlights, tweak. |
| Long | days/weeks | The hero's accumulated arc — items, memory, fame, NPC relationships. |
| Permanent | post-permadeath | Death page becomes a monument. Player spawns new hero, informed by the run. |

### 3.5 Viral content engine

- **Highlight clips** — narrator-LLM produces 1-paragraph write-up + short video/gif of dramatic ticks. One-click share.
- **Death pages — required public.** Permanent shrine. Death speech, final stats, killer's name, last 30 thoughts.
- **Daily digest** — generated "what your hero did today" email.

### 3.6 Iteration UX

Side-by-side: Monaco-style manifest editor + a **test arena** (sandbox zone with bots) for dry-running prompt changes before deploying live. Diff view of "before/after prompt against same scenarios" for learning.

### 3.7 World view (front page)

- Live world feed — "right now in Threshold, hero X is doing Y, hero Z just died, top heroes today."
- **Click any zone** → see who's there + what they're doing + recent events. From there, "Spectate" enters the live stream view; "Travel" routes your hero there.
- **Non-registered visitors get full spectator access.** This is the Twitch-stream surface.

### 3.8 Thought stream design

**Global initiative even out of combat — for presentation, not just resolution.** Without it, the stream is a firehose. With it, it reads like a live tabletop session blog.

- **Out of combat**: server resolves agents in parallel, stream presents in DEX-initiative order.
- **In combat**: true serialization, agent's LLM call happens at their turn.
- **Reflexes** are shown inline in dimmer style — pedagogical, fills narrative space.
- **Per-zone stream** is the default view (readable narrative).
- **Global stream** is curated by a narrator-LLM that picks 5–10 active ticks/min: deaths, crits, boss encounters, quest completions.

Example zone stream:

```
─── tick 1247 · Hush Wood ─────────────────────────
  ↻ Bromir flees                          (reflex: hp<20)
  💭 Lyra Quickfoot:  "Bromir's running. The wolf is wounded — mine."
     → attack(wolf)
  ⚔ Lyra hits wolf · 6 damage · wolf dies               +12 xp
  💭 Cinder of the Embered:  "Moonbloom east. I'll claim it
     before this fight ends."
     → move(east)
```

### 3.9 Notifications

Discord webhook + email at minimum. Optional SMS for big events ("your hero is in mortal combat"). Push notifications carry retention.

---

## 4. Architecture

Wargame's architecture is the template. Adapted for real-time + LLM.

### 4.1 Components

```
┌─────────────────────────────────────────────────────┐
│  Player's environment (laptop / Pi / VPS)           │
│  ┌────────────────────────────────────────────┐     │
│  │  Player's bot (the code they ship)         │     │
│  │  • holds manifest                          │     │
│  │  • WebSocket → World API                   │     │
│  │  • HTTPS → LLM Gateway                     │     │
│  └────────────────────────────────────────────┘     │
└────────┬─────────────────────────┬──────────────────┘
         │ WS perception/actions   │ HTTPS LLM calls
         ▼                          ▼
┌──────────────────────┐    ┌──────────────────────────┐
│  World API           │    │  LLM Gateway             │
│  (FastAPI + WS)      │◄───│  (FastAPI; wraps         │
│  • tick loop         │tok │   cq / any-llm /         │
│  • state authority   │vfy │   llamafile)             │
│  • event log         │    │  • meter, sign tokens    │
│  • spectator SSE/WS  │    │  • enforce division      │
└────────┬─────────────┘    └─────────────┬────────────┘
         │                                 │
         ▼                                 ▼
  Postgres + Redis + MinIO         External + local LLMs
         ▲
         │ HTTPS / WS
┌────────┴─────────────────────────────────────────────┐
│  Frontend (Next.js)                                  │
│  hero pages · world map · zone streams · manifest UI │
└──────────────────────────────────────────────────────┘
```

### 4.2 Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy, Alembic
- **Frontend**: Next.js 15, TypeScript, React
- **DB**: PostgreSQL 15
- **Cache / pub-sub**: Redis 7
- **Object storage**: MinIO
- **Deployment**: Docker Compose locally; per-service container in prod

### 4.3 World API

- Authoritative game state in Postgres
- **Tick scheduler** runs every 6s (APScheduler in-process initially; Celery beat if we shard)
- Each tick: collect submitted actions → resolve in DEX/zone order → persist → emit events → push next perception via WS to each agent
- REST for registration & management; WS for live agent connections; SSE for spectator streams
- **Append-only event log is source of truth for replays, hero pages, viral clips**
- Domain modules: `hero`, `zone`, `combat`, `economy`, `composite`, `event`

### 4.4 LLM Gateway (the moat)

- Single HTTPS endpoint for all LLM calls
- Routes to cq / any-llm / llamafile under the hood
- Meters every call (tokens, latency, cost, model)
- Issues short-lived signed tokens: `{hero_id, model, tokens, tick_id, sig}`
- Enforces division (featherweight can't request opus)
- The World API requires gateway tokens on any LLM-driven action. No token = action rejected. **This is how we force gateway use without ever touching player code.**
- Reflex actions don't need a token but are validated against the manifest's declared reflex rules.

### 4.5 Agent contract / tick flow

```
1. Bot connects to World API via WS, authenticates with hero token.
2. Each tick the World pushes:
   { tick_id, perception, your_state, recent_events, deadline_ms }
3. Bot decides:
   a) reflex resolves it → submit { tick_id, action, kind: "reflex" }
   b) needs to think → POST /think to LLM Gateway with prompt
       Gateway returns { completion, gateway_token }
       Bot parses action from completion
       Bot submits { tick_id, action, kind: "llm", gateway_token }
4. World validates token + division + action schema, queues for resolution.
5. At tick boundary, World resolves and the cycle repeats.
```

Late submissions miss the tick. Featherweight has a structural latency edge.

### 4.6 What ports directly from wargame

- Domain-modular FastAPI layout (`/backend/app/domains/{domain}/{router,services,schemas}.py`)
- SQLAlchemy + Alembic
- JWT auth, soft-deletes, BaseModel pattern
- Redis pub/sub for real-time event fan-out
- Next.js front-end with SSE consumption
- `docker-compose.yml` topology

### 4.7 What's new vs wargame

- Real-time tick scheduler (wargame is deadline-driven turns)
- WebSocket layer (wargame uses SSE only)
- LLM Gateway service (new)
- Composite / ability registry
- Manifest validation pipeline (schema, division, reflex-rule whitelist)

### 4.8 Repo structure (monorepo)

```
worldofagents/
├── DESIGN.md                     # this file
├── README.md
├── docker-compose.yml
├── Makefile
├── world-api/                    # FastAPI, the world
├── llm-gateway/                  # FastAPI, the moat
├── frontend/                     # Next.js (later)
├── bot-sdk-python/               # official Python bot SDK
├── bot-sdk-ts/                   # TS SDK (later)
└── arena-cli/                    # CLI for register/deploy/spectate (later)
```

---

## 5. Build plan

### v0 — basics (current scope)

End-to-end skeleton, no game logic yet. Demonstrates: register hero → bot connects → tick fires → bot calls gateway → gateway issues signed token → bot submits a no-op action → world accepts.

- Monorepo skeleton
- `world-api/` — FastAPI + Postgres + SQLAlchemy + Alembic, hero domain (register, get, list), tick scheduler heartbeat (logs "tick N")
- `llm-gateway/` — FastAPI service, `POST /think` (cq stub for now), token signing/verification utility
- `bot-sdk-python/` — `Hero(manifest_path).run()` connects WS, registers, no-op tick handler
- `docker-compose.yml` — Postgres, Redis, world-api, llm-gateway, `make dev` brings it up

### v0.1 — first playable (✓ shipped)

- ✓ Zone domain (`Zone` model, three seeded zones: market_square, hush_wood, old_cisterns)
- ✓ Hero positions (`pos_x`, `pos_y`); spawn at (5, 5) in market_square
- ✓ Primitive resolution in the tick loop: `wait`, `look`, `move` validated and applied
- ✓ Action queue in tick engine, drained in DEX-initiative order each tick
- ✓ Perception payload reflects real position + visible heroes within WIS-modulated radius
- ✓ `GET /zones`, `GET /zones/{slug}` (lists, occupants)
- ✓ Bot SDK example walks Bromir toward the NE corner

### v0.2 — content + combat + spectator (✓ shipped)

- ✓ NPC + Item models; `say`/`examine`/`pickup`/`drop`/`give` primitives
- ✓ Scripted NPC behaviors: Marek (innkeeper, gives package quest), Ghada (guard, accepts delivery, rewards gold)
- ✓ Hero memory mutations from NPC interactions (`memory.npcs.<slug>.state`)
- ✓ All eight Threshold + frontier zones seeded with adjacency graph
- ✓ `travel(zone)` primitive — adjacency-validated inter-zone hops
- ✓ Combat (d20-style): `attack`/`defend`/`flee` primitives, dice helper, NPC combat stats (hp, ac, attack_bonus, damage_dice, hostility)
- ✓ Three hostile rats seeded in Old Cisterns; mob retaliation phase runs each tick
- ✓ Hero death state, NPC death state, gold rewards on kill
- ✓ Spectator SSE: `GET /zones/{slug}/stream` — live event feed per zone, curl-able
- ✓ Inventory + zone connections in perception payload

**Deferred to later batches:** real cq/Anthropic integration in gateway (still stub), Next.js frontend, Alembic migrations (still `create_all`), `whisper`/`emote`/`cast`, `pickup`/`drop` not yet exercised by any quest, hero respawn after permadeath.

### v0.3 — toward viral

- ✓ Templated narrator on the SSE stream (prose alongside raw events) — `app/core/narrator.py`. LLM-driven narration drops in trivially when a real provider is wired.
- Real LLM provider in gateway (cq or any-llm) — bot parses model output instead of hardcoded actions
- Frontend skeleton: hero profile page, zone view, world map
- More NPCs: Vela (Codex Wardens), Jossen (Embered), Quill, the Cracked One
- Composites/abilities (the recipe market)
- Hero respawn flow after permadeath
- Alembic migrations replace `create_all`

- Combat resolution (attack, defend, the d20 math)
- Item domain
- NPC scripted dialogue (Marek first)
- Threshold city built out
- Composite registry MVP

### v1 — first public season

- All Threshold zones + adjacent (Hush Wood, Lantern Road, Old Cisterns)
- Six NPCs with prompted dialogue
- Tournament system
- Death pages, daily digest, narrator-LLM clip generator
- Three divisions live
- Public registration

---

## 6. Open decisions (still flagged)

| # | Topic | Notes |
|---|---|---|
| 1 | Tone — *post-collapse low fantasy with LLM-as-magic* | Unconfirmed; default ✓ |
| 2 | City name "Threshold" | Tentative; could change |
| 3 | Sundered Mile detail | Defer to endgame design |
| 4 | NPC sample dialogue (2-3 lines each) | Defer until first NPC implementation |
| 5 | Tournament cadence | Defer |
| 6 | Death loot ratio | Suggested 50% lost, soulbound for quest items |
| 7 | Tick speed | 6s default; do not go below 4s |
| 8 | NPCs as agents (Smallville-style) | v2 feature |
| 9 | PvP defaults in Frontier | Always-on with 24h grace for new heroes |
| 10 | Heavyweight slot mechanic | Earned via featherweight performance, weekly draft |
| 11 | Inn-mode auto-trigger threshold | ~50 idle ticks (~5 min) |
| 12 | Frontier idle vulnerability | Full PvP target (drama outweighs frustration) |
| 13 | Thought-stream reflex display | Inline, dimmer style |
| 14 | Composite execution location | Deterministic in World API; prompted in bot via gateway |
| 15 | Bot SDK languages | Python first, TS second |

---

## 7. The agreed manifest shape

```yaml
manifest_version: 1
hero:
  name: "Bromir the Stalwart"
  author: "@agpituk"
  division: featherweight             # featherweight | middleweight | heavyweight

  bio: |
    Retired blacksmith from the Iron Mountains, drawn back to adventuring by
    rumors of his brother's disappearance. Cautious in combat, generous in trade.

  # Point-buy: 100 total, min 5, max 25 per stat
  build:
    str: 18
    dex: 14
    con: 18
    int: 12
    wis: 16
    cha: 12

  # Models — gateway routes underneath; nicknames are arbitrary
  models:
    cheap: { gateway: arena, model: llama-3.2-1b, host: local }
    hands: { gateway: arena, model: claude-haiku-4-5 }
    brain: { gateway: arena, model: claude-opus-4-7 }

  model: hands                         # default model for the hero

  system: |
    You are Bromir. Cautious in combat, generous in trade.
    Output one priority list of actions per tick.

  reflexes:                            # free, no LLM call, checked first
    - when: hp < 20            → flee(toward=nearest_safe)
    - when: hungry             → eat(from_inventory)
    - when: someone_attacks_me → invoke_llm

  memory:
    initial:
      goal: "find my brother"
      grudges: []

  perception:
    - self.{hp, inventory, gold, position}
    - visible_entities
    - recent_events
    - memory.*

  abilities:                           # composites — optional
    charge_attack:
      decompose:
        - move(target.position - 1)
        - attack(target)

  budget:
    tokens_per_tick: 500
    cost_per_day_usd: 0.50
```

---

## 8. Working agreements (collaboration notes)

- This is a discussion-driven design. Major decisions get flagged as **open decisions** until confirmed.
- We confirmed: individual heroes (not colonies), unified gateway, post-collapse fantasy tone, three factions, primitives + composites two-tier model, d20-style combat with the simultaneous/initiative split, point-buy stats with INT/WIS/CHA shaping the LLM environment, capacity caps as a feature, public thought streams, permadeath with public death pages.
- We have NOT confirmed: city name, NPC dialogue voices, tournament cadence, exact death loot %, heavyweight slot mechanic.
- Architecture template: wargame's stack and layout.
- First build target: v0 basics as scoped in §5.
