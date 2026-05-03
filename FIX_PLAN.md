# Fix Plan — Closing the Gap Between DESIGN.md and the Code

> **Historical document.** The 16-commit branch this plan drove has
> landed; remaining work moved to `REMAINING_WORK.md`. Commit `006b2dd`
> (arch-review cleanup) split `world-api/app/core/actions.py` into
> `world-api/app/core/actions/{combat,contracts,dispatcher,equipment,
> gathering,inventory,magic,movement,perception,quests,sandbox,social,
> statuses,titles,trade}.py` plus `_helpers.py` and `_result.py`. Line
> numbers below (`actions.py:NNNN`) are frozen against the pre-split
> monolith — grep by symbol when chasing references.

This plan is the output of a code-level review of the prototype. It is not
a roadmap of new features; it is a list of places where the implementation
does not currently honour what `DESIGN.md` and `README.md` promise, plus
the operational warts that will bite as soon as more than ~20 heroes are
active.

Items are grouped by priority. Each item lists the **symptom**, the
**files/lines** involved, the **fix**, and a **done-when** check so the PR
that closes it has an unambiguous bar.

---

## P0 — Pitch-breaking gaps

These are places where the headline design promise is false in code. They
should land before any further content work, because every additional
feature compounds on top of them.

### P0-1. Make INT and WIS actually shape the LLM environment

**Symptom.** `DESIGN.md §2.3` calls this the "genius mechanic": INT is the
tokens-per-thinking-tick budget, WIS is memory KV size + perception
radius. In code, both stats are decorative.

**Evidence.**
- `world-api/app/core/models.py:57-58` — fields exist on `Hero`.
- `world-api/app/core/tick.py:115` — mana regen is hard-coded `1/tick`,
  not INT-scaled.
- `world-api/app/core/gateway_token.py:27` — the signed token carries a
  `tokens` claim, but no caller reads it back to enforce a per-tick
  budget.
- `world-api/app/core/actions.py:2130, 2152` — journal slices are flat
  constants (5 relevant, 12 recent). WIS is not consulted.

**Fix.**
1. Add a single `hero_budgets.py` module that derives, from a `Hero`:
   - `max_tokens_per_tick = base + int_ * k_int`
   - `mana_regen_per_tick = 1 + max(0, (int_ - 10) // 4)`
   - `journal_recent_limit = base + wis * k_wis`
   - `journal_relevant_k = base + wis * k_wis_k`
   - `look_radius = base + wis // 4` (this one already exists in
     `_look_radius`; move it here so the formulas live together).
2. Pass `max_tokens_per_tick` into the gateway token issuance path so the
   signed claim reflects the hero's INT.
3. In `llm-gateway/app/main.py`, **enforce** the `tokens` claim — reject
   requests whose `max_tokens` exceeds the signed value. This is the
   piece that turns the existing signing infrastructure from theatre into
   a real metering boundary.
4. In `actions.py:perception_for`, replace the hard-coded `12` and `5`
   with the WIS-derived limits.

**Done when.** A hero with INT 5 cannot request more tokens per tick than
a hero with INT 25, verified by a unit test that signs two tokens and
asserts the gateway rejects the over-budget one. A hero with WIS 25 sees
strictly more journal entries in `perception_for` than one with WIS 5,
verified by a perception snapshot test.

---

### P0-2. Trim perception to a bounded payload

**Symptom.** `perception_for` (`actions.py:2183-2211`) serialises the full
inventory, every visible NPC, every visible hero, and every memory tag
into the LLM payload every tick. There is no top-K, no token budgeting.
A wizard with WIS 25 sees the same blob as a barbarian with WIS 5,
contradicting both P0-1 and the "build = information environment" pitch.

**Fix.**
1. Introduce `perception_budget(hero) -> PerceptionBudget` with caps:
   `max_inventory_items`, `max_visible_npcs`, `max_visible_heroes`,
   `max_memory_tags`, `max_journal_chars`.
2. Sort each list by a relevance score before truncating:
   - inventory: equipped first, then by recent use (need a
     `last_used_tick` column on inventory rows).
   - NPCs: by distance, then hostility.
   - heroes: by distance, then by whether they are in active combat with
     this hero.
   - memory tags: by `recall_tags` overlap with current zone/quest.
3. After trimming, run a token estimator (`len(json) // 4` is fine for v1)
   and log a metric `perception_tokens_estimated`. If the estimate
   exceeds the signed token budget × some headroom, drop further.

**Done when.** A synthetic test that places one hero in a zone with 100
NPCs and 100 inventory items produces a perception JSON whose length is
deterministic and bounded by the WIS-derived caps.

---

### P0-3. Make LLM parse failures visible to the player

**Symptom.** `bot-sdk-python/src/arena_bot/client.py:77-101` regex-extracts
the first JSON object it finds in the LLM output. Trailing prose is
ignored; a second JSON object is silently dropped; an unknown verb
becomes a soft "wasted tick" (`actions.py:1442`). The spectator UI shows
nothing — this directly undercuts the "watch them think" half of the
product thesis.

**Fix.**
1. Replace the regex extractor with a strict JSON parser plus a
   single-retry fallback that asks the model "return only valid JSON
   matching this schema" with the original output appended.
2. On final failure, emit a `ParseFailure` event into the per-hero event
   stream with `{raw_output, error, schema}`.
3. On the hero page (`frontend/`), render parse failures inline next to
   ticks so a player can see "your model emitted invalid JSON 14 times
   this hour." This turns failures into pedagogy, which is the one thing
   this game can do that no other game can.

**Done when.** A hero whose model emits `not json` shows a visible
`ParseFailure` row on its public page; the underlying tick is recorded
as a no-op with a structured reason.

---

## P1 — Operational fragility

These do not change the pitch but determine whether the prototype
survives modest load or a malicious manifest.

### P1-1. Sandbox reflex evaluation against runaway expressions

**Symptom.** `bot-sdk-python/src/arena_bot/reflexes.py:288-310` runs
`eval(expr, {"__builtins__": {}}, ctx)`. The empty builtins block
attribute walks to `os` etc., but there is no wall-clock cap. A reflex
of `when: "[0 for _ in range(10**9)]"` will pin a CPU. Combined with the
single-threaded tick (`tick.py:101`), one bad manifest stalls the entire
world. The deploy form takes pasted YAML; this is a guaranteed incident.

**Fix.**
1. Run each reflex eval in a worker thread with a 50ms wall-clock
   timeout. On timeout, log a `ReflexTimeout` event, skip the reflex,
   and surface it on the hero page (P0-3 piggybacks on this).
2. Pre-compile expressions with `compile(..., mode="eval")` once at
   manifest load and reject any AST node not on an allowlist
   (`Expression`, `BoolOp`, `BinOp`, `UnaryOp`, `Compare`, `Call`,
   `Attribute`, `Subscript`, `Name`, `Constant`, `List`, `Tuple`, `Dict`,
   `Set`, `IfExp`, `Lambda` — no `comprehensions`, no `Yield`).
3. Cap calls per evaluation: wrap helpers (`adjacent_to`, `hostile_visible`,
   etc.) in a counter that aborts after N invocations.

**Done when.** A manifest with a runaway reflex deploys, the offending
reflex is disabled with a visible error on the hero page, and the rest
of the world ticks normally.

---

### P1-2. Async-ify the tick loop

**Symptom.** `tick.py` resolves heroes serially in DEX order
(`tick.py:135-159`). DB reads, retriever calls, and LLM-driven managed
heroes are awaited inline. `actions.py:2129` runs the journal scoring
synchronously. One slow `CqExchangeRetriever` HTTP hop blocks every other
hero's resolution.

**Fix.**
1. Resolve hero actions in two passes:
   - **Read pass (parallel):** build perception for every alive hero
     concurrently with `asyncio.gather`. No writes.
   - **Write pass (serial):** apply actions in DEX order against the now
     in-memory snapshots. This preserves combat determinism while
     parallelising the slow part (retriever, perception assembly).
2. Move all retriever calls behind an `async` interface. The SQL retriever
   uses `asyncpg`; the cq retrievers wrap `httpx.AsyncClient`.
3. Add a per-handler watchdog: any single hero whose write-pass takes
   >500ms gets its action skipped and logged.

**Done when.** A load test with 100 heroes and a deliberately slow
retriever (200ms) completes a tick in <1s instead of 20s.

---

### P1-3. Lock trades against TOCTOU

**Symptom.** `actions.py:407-478` validates inventory and gold at
accept-time, then writes — without a row lock. Concurrent accepts on
shared assets can hand out ghost items. Any visible duplication bug
destroys spectator trust faster than any other category.

**Fix.**
1. Wrap the trade-accept handler in a serialisable transaction.
2. Use `SELECT ... FOR UPDATE` on both heroes' rows and on the offer row.
3. Re-check all preconditions inside the lock; abort with a structured
   error on failure.
4. Apply the same pattern to: `give`, `pickup` (on shared zone items),
   `buy`/`sell` (NPC inventory), `store`/`withdraw`.

**Done when.** A property-based test that fires 1000 concurrent accepts
on a single offer ends with exactly one success and zero ghost items in
the inventory tables.

---

### P1-4. Reject actions from dead or stale heroes

**Symptom.** The dispatcher (`actions.py:1438`) does not check
`hero.status` before resolving a verb. The tick loop filters alive heroes
(`tick.py:134`), but managed bots can submit actions over WebSocket
between the death write and the next tick.

**Fix.**
1. First line of the dispatcher: `if hero.status != "alive": return
   {"ok": False, "reason": "dead"}`.
2. Also reject if the hero's `last_action_tick == current_tick` — one
   action per hero per tick, period.

**Done when.** A test that kills a hero, then submits an action via the
managed runner, returns a `dead` rejection rather than mutating state.

---

## P2 — Codebase hygiene

These are not pitch- or stability-critical but will keep biting.

### P2-1. Collapse the dual bot runtime

**Symptom.** `world-api/app/managed/runner.py` and
`bot-sdk-python/src/arena_bot/runner.py` both implement reflex eval →
composite expansion → LLM call → action submit. Two implementations.
Inevitable behavioural drift between locally-run and hosted heroes is
also a fairness problem on leaderboards.

**Fix.**
1. Extract the loop into a `hero_runtime` package that both consume.
   Keep transport (WebSocket vs in-process) as the only difference.
2. Add a parity test: feed the same manifest and the same canned
   perception sequence into both runtimes and assert byte-identical
   action streams.

**Done when.** The parity test exists and passes. Either runner.py file
is now a thin transport shim under 50 lines.

---

### P2-2. Re-evaluate composites between primitive steps

**Symptom.** `runner.py:70-81` expands a composite into a queue of
primitive actions and dispatches them one per tick without
re-evaluation. If an enemy appears on step 2 of a 5-step gather plan,
the hero finishes the plan. This is a gameplay quality issue *and*
teaches the wrong lesson about how plans should compose with reactive
policies.

**Fix.**
1. After each primitive step, re-run reflexes against fresh perception.
   If any reflex fires, abandon the composite and act on the reflex.
2. Add an explicit `composite_interrupted` event so spectators can see
   "the hero broke off gathering when the rat appeared."

**Done when.** A test where a hero is mid-composite and an enemy is
spawned shows the composite abandoned and a combat reflex firing.

---

### P2-3. Schema-version the hero memory blob

**Symptom.** `models.py:73` stores `hero.memory` as schemaless JSON.
Mutations are ad-hoc (`mem = dict(hero.memory); mem[k] = v; hero.memory =
mem`) throughout `actions.py`. The first key-shape change breaks
in-flight heroes silently.

**Fix.**
1. Add `memory_schema_version: int` to the Hero row.
2. Define a `MemoryV1 = TypedDict(...)` and route all reads/writes
   through `get_memory(hero) -> MemoryV1` and `update_memory(hero, **kw)`
   helpers.
3. Add a forward-migration table keyed on version.

**Done when.** All `hero.memory` accesses in `actions.py` go through
the helper. Grep for `hero.memory =` in `app/` returns only the helper.

---

### P2-4. Cap journal growth

**Symptom.** `actions.py:74-89` writes journal entries with no rate
limit and no archival policy. Retrieval is capped at 200 (`actions.py:
2152`) so query performance is bounded, but the table grows forever.

**Fix.**
1. Add a per-hero rate limit (e.g. ≤ 4 `journal_write` per tick).
2. Add a periodic archival job that moves entries older than 10k ticks
   into a cold table, keeping only those tagged with `recall_tags` hot.

**Done when.** Disk usage for a hero's journal stays bounded under a
write-spam workload test.

---

### P2-5. Stricter action schema validation

**Symptom.** Even after P0-3 catches malformed JSON, the dispatcher
accepts any dict with a `do` key. Unknown verbs return a soft "unknown
verb" string downstream. `target`, `spell`, `qty` are not type-checked.

**Fix.**
1. Define a Pydantic model per verb (`MoveAction`, `AttackAction`, ...).
2. Dispatcher selects the model by verb, validates, and only then runs
   the handler. Validation errors flow into the `ParseFailure` stream
   from P0-3.

**Done when.** Submitting `{"do":"attack","target":42}` (where
`target` should be a slug) yields a structured validation error visible
on the hero page.

---

## P3 — Nice-to-have, after P0/P1

- `P3-1` Audit log on memory mutations (which action changed which key,
  with before/after).
- `P3-2` Add hooks for NPC autonomous behaviours so NPCs can act
  without a hero stimulus (currently `tick.py:161-212` only reacts).
- `P3-3` Per-tick perception/action correlation IDs so a bot can prove
  "I saw X, then did Y" rather than inferring it.
- `P3-4` Test coverage for the cq retrievers — `retriever.py:99-208`
  has fall-through behaviour but no tests; a misconfigured cq silently
  serves SQL results.

---

## Sequencing

A reasonable PR train:

1. **PR 1 — Pitch fixes (P0-1, P0-2, P0-3).** Ships the three things
   the README/DESIGN already promise. Visible to players immediately.
2. **PR 2 — Loop safety (P1-1, P1-4, P2-5).** Cheap, high-impact, makes
   the deploy form safe to leave open.
3. **PR 3 — Concurrency and data integrity (P1-2, P1-3, P2-3).** The
   "survives 100 heroes" PR.
4. **PR 4 — Hygiene (P2-1, P2-2, P2-4).** Pays down debt before more
   content lands.
5. **PR 5+ — P3 items as opportunity allows.**

Each PR ships with the `Done when` check from its items as automated
tests. No item is closed by inspection alone.
