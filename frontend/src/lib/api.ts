// Thin REST client over the world-api. NEXT_PUBLIC_WORLD_API_URL is read at
// bundle time and used from the browser, so it must be a URL the user's
// browser can reach (typically http://localhost:47800 in dev).

export const WORLD_API_URL: string =
  process.env.NEXT_PUBLIC_WORLD_API_URL || "http://localhost:47800";

export type Zone = {
  slug: string;
  name: string;
  kind: "sanctuary" | "frontier" | "dungeon" | "arena";
  width: number;
  height: number;
  capacity_soft: number;
  description: string;
  connections?: string[];
};

export type Occupant = {
  id: string;
  name: string;
  pos: [number, number];
  hp: number;
  status: string;
  division: string;
  leading_faction: string | null;
  born_at_tick: number;
  ticks_alive: number;
  has_active_quest: boolean;
};

export type MerchantWare = {
  slug: string;
  name?: string;
  kind?: string;
  buy_price?: number;
  sell_price?: number;
  qty?: number | null;
  description?: string;
  props?: Record<string, any>;
};

export type ZoneNPC = {
  slug: string;
  name: string;
  kind: string;
  pos: [number, number];
  hostility: "peaceful" | "hostile" | "tamed";
  alive: boolean;
  hp: number;
  hp_max: number;
  merchant_stock?: MerchantWare[];
};

export type Recipe = {
  slug: string;
  name: string;
  output_slug: string;
  output_name: string;
  output_kind: string;
  inputs: { slug: string; count: number }[];
  skill_required: string;
  skill_min: number;
  workstation_kind: string;
};

export type ZoneBuilding = {
  slug: string;
  name: string;
  pos: [number, number];
  width: number;
  height: number;
  kind: string;
  owner_hero_id: string | null;
  gold_cost: number;
};

export type ZoneResource = {
  slug: string;
  name: string;
  kind: string;
  pos: [number, number];
  yield_item_slug: string;
  depleted_until_tick: number | null;
};

export type ZoneDetail = Zone & {
  occupants: Occupant[];
  npcs?: ZoneNPC[];
  buildings?: ZoneBuilding[];
  resource_nodes?: ZoneResource[];
};

export type Hero = {
  id: string;
  name: string;
  author: string;
  division: string;
  bio: string;
  hp: number;
  status: string;
  zone: string;
  pos: [number, number];
  build: Record<string, number>;
  skills?: Record<string, number>;
  skill_levels?: Record<string, number>;
  skill_titles?: Record<string, string>;
  top_title?: string | null;
  reputation?: { kills?: number; pvp_kills?: number; dead?: boolean };
  skill_cap?: number;
  skill_points_remaining?: number;
  equipped?: Record<string, string | null>;
  mana_current?: number;
  mana_max?: number;
  known_spells?: string[];
  faction_rep?: Record<string, number>;
  born_at_tick?: number;
  died_at_tick?: number | null;
  manifest?: Record<string, any>;
};

export type SkillLeaderboardRow = {
  id: string;
  name: string;
  author: string;
  division: string;
  status: string;
  xp: number;
  level: number;
  rank: string | null;
  top_title: string | null;
};

export type SkillLeaderboards = {
  top: number;
  boards: Record<string, SkillLeaderboardRow[]>;
};

export type LongevityRow = {
  id: string;
  name: string;
  author: string;
  division: string;
  zone: string;
  born_at_tick: number;
  died_at_tick: number | null;
  ticks_alive: number;
};

export type Longevity = {
  current_tick: number;
  alive: LongevityRow[];
  hall_of_fame: LongevityRow[];
};

export async function fetchJson<T>(
  path: string,
  opts: { ownerToken?: string | null } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.ownerToken) {
    // Header rather than query param so the auth_token is not logged
    // by browsers (history) or proxies (access logs / Referer).
    headers["X-Owner-Token"] = opts.ownerToken;
  }
  const r = await fetch(`${WORLD_API_URL}${path}`, {
    cache: "no-store",
    headers,
  });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${r.statusText}`);
  return r.json();
}

export type JournalEntry = {
  id: number;
  tick_id: number;
  kind: "player" | "milestone";
  text: string;
  tags: string[];
  created_at: string | null;
};

export type Quest = {
  id: string;
  template_slug: string;
  name: string;
  description: string;
  kind: string;
  target: string;
  count_done: number;
  count_required: number;
  status: "active" | "done" | "claimed";
  reward_gold: number;
  reward_faction: string | null;
  reward_faction_amount: number;
  offered_by: string;
};

export type Tournament = {
  slug: string;
  name: string;
  description: string;
  division: string;
  zone: string;
  status: "open" | "in_progress" | "closed";
  starts_at_tick: number;
  ends_at_tick: number;
  max_entries: number;
  prize_gold: number;
  prize_faction: string | null;
  prize_faction_amount: number;
  entries: number;
};

export type LeaderboardRow = {
  hero_id: string;
  name: string;
  kills: number;
  status: "registered" | "winner" | "finished";
};

export type TournamentDetail = Tournament & {
  leaderboard: LeaderboardRow[];
};

export const api = {
  listZones: () => fetchJson<Zone[]>("/zones"),
  getZone: (slug: string) => fetchJson<ZoneDetail>(`/zones/${slug}`),
  listHeroes: () => fetchJson<Hero[]>("/heroes"),
  getHero: (id: string) => fetchJson<Hero>(`/heroes/${id}`),
  getJournal: (id: string, limit = 100) =>
    fetchJson<JournalEntry[]>(`/heroes/${id}/journal?limit=${limit}`),
  getQuests: (id: string) => fetchJson<Quest[]>(`/heroes/${id}/quests`),
  listRecipes: () => fetchJson<Recipe[]>("/recipes"),
  listSpells: () => fetchJson<any[]>("/spells"),
  listTournaments: () => fetchJson<Tournament[]>("/tournaments"),
  getTournament: (slug: string) => fetchJson<TournamentDetail>(`/tournaments/${slug}`),
  longevity: (limit = 20) => fetchJson<Longevity>(`/heroes/longevity?limit=${limit}`),
  skillLeaderboards: (top = 10) =>
    fetchJson<SkillLeaderboards>(`/heroes/leaderboard/skills?top=${top}`),
  validateManifest: async (manifestYaml: string) => {
    const fd = new FormData();
    fd.append("manifest", new Blob([manifestYaml], { type: "application/x-yaml" }), "manifest.yaml");
    const r = await fetch(`${WORLD_API_URL}/manifest/validate`, { method: "POST", body: fd });
    if (!r.ok) throw new Error(`validate failed: ${r.status}`);
    return r.json() as Promise<{ valid: boolean; issues: any[]; summary: any }>;
  },
  simulateTick: async (manifestYaml: string) => {
    const fd = new FormData();
    fd.append("manifest", new Blob([manifestYaml], { type: "application/x-yaml" }), "manifest.yaml");
    const r = await fetch(`${WORLD_API_URL}/manifest/simulate-tick`, {
      method: "POST",
      body: fd,
    });
    if (!r.ok) throw new Error(`simulate failed: ${r.status}`);
    return r.json() as Promise<SimulateTickResult>;
  },
  listContracts: (
    status: "open" | "claimed" | "fulfilled" | "expired" | "all" = "open",
    kind?: string,
    zone?: string,
  ) => {
    const qp = new URLSearchParams({ status });
    if (kind) qp.set("kind", kind);
    if (zone) qp.set("zone", zone);
    return fetchJson<Contract[]>(`/contracts?${qp.toString()}`);
  },
  getHeroByName: (name: string) => fetchJson<Hero>(`/heroes/by-name/${encodeURIComponent(name)}`),
  getMemoryTrace: (id: string) => fetchJson<MemoryTrace>(`/heroes/${id}/memory-trace`),
  // Inspector — Phase 5 of agent-tools rollout.
  toolsSummary: (heroId: string) =>
    fetchJson<{ hero_id: string; tools: ToolSummary[] }>(
      `/api/heroes/${heroId}/tools/summary`,
    ),
  toolDetail: (heroId: string, toolName: string) =>
    fetchJson<ToolDetail>(`/api/heroes/${heroId}/tools/${toolName}`),
  tickLlmCall: (heroId: string, tick: number, ownerToken?: string | null) =>
    fetchJson<TickLlmCall>(
      `/api/heroes/${heroId}/ticks/${tick}/llm-call`,
      { ownerToken },
    ),
  latestLlmCall: (heroId: string, ownerToken?: string | null) =>
    fetchJson<LatestLlmCall>(
      `/api/heroes/${heroId}/llm-call/latest`,
      { ownerToken },
    ),
  listBounties: (status: "open" | "claimed" | "expired" | "all" = "open") =>
    fetchJson<Bounty[]>(`/bounties?status=${status}`),
  currentEvents: () => fetchJson<CurrentEvents>("/events/current"),
  listDiscoveries: () => fetchJson<Discovery[]>("/events/discoveries"),
  listHighlights: (limit = 30) => fetchJson<Highlight[]>(`/highlights?limit=${limit}`),
  getClip: (eventId: number, window = 15) =>
    fetchJson<Clip>(`/clip/${eventId}?window=${window}`),
  registerHero: async (
    manifestYaml: string,
    opts: { managed?: boolean } = {},
  ): Promise<{
    id: string;
    name: string;
    division: string;
    auth_token: string;
  }> => {
    // The /heroes/register endpoint takes multipart/form-data with a
    // `manifest` file field. Wrap the textarea string as a Blob so it
    // serialises like an upload. `managed` is a query param.
    const fd = new FormData();
    fd.append("manifest", new Blob([manifestYaml], { type: "application/x-yaml" }), "manifest.yaml");
    const url = `${WORLD_API_URL}/heroes/register?managed=${opts.managed ? "true" : "false"}`;
    const r = await fetch(url, { method: "POST", body: fd });
    if (!r.ok) {
      const text = await r.text().catch(() => `${r.status}`);
      throw new Error(text || `${r.status} ${r.statusText}`);
    }
    return await r.json();
  },
  // Showcase / tools meta surface (separate from the inspector's `toolDetail`)
  toolLeaderboard: (board: string) =>
    fetchJson<{ entries: any[]; honesty: string | null }>(
      `/api/tools/leaderboards?board=${board}`,
    ),
  toolMeta: (toolId: string) => fetchJson<any>(`/api/tools/${toolId}`),
  toolsGallery: (category?: string | null) =>
    fetchJson<any>(
      category ? `/api/tools-gallery?category=${category}` : `/api/tools-gallery`,
    ),
  compareHeroes: (heroesCsv: string) =>
    fetchJson<any>(`/api/compare?heroes=${encodeURIComponent(heroesCsv)}`),
  // Returns null when the hero is still alive (404), throws on other errors.
  heroDeath: async (id: string): Promise<any | null> => {
    const r = await fetch(`${WORLD_API_URL}/heroes/${id}/death`, { cache: "no-store" });
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  copyTool: async (
    toolId: string,
    byHero: string,
    ownerToken: string,
    rename?: string,
  ): Promise<{ appended?: boolean; rename_to?: string; [k: string]: any }> => {
    const url = new URL(`${WORLD_API_URL}/api/tools/${toolId}/copy`);
    url.searchParams.set("by_hero", byHero);
    if (rename) url.searchParams.set("rename", rename);
    const r = await fetch(url.toString(), {
      method: "POST",
      headers: { "X-Owner-Token": ownerToken },
    });
    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      throw new Error(detail?.detail ?? `HTTP ${r.status}`);
    }
    return r.json();
  },
  postSpectatorBounty: async (body: {
    target_name: string;
    gold: number;
    reason?: string;
    poster_name?: string;
    confirm_email?: string; // honeypot
  }) => {
    const r = await fetch(`${WORLD_API_URL}/bounties`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      // FastAPI surfaces structured details via { detail: ... }; pull a
      // user-friendly message + retry hint when present.
      let parsed: any = null;
      try { parsed = await r.json(); } catch {}
      if (r.status === 429 && parsed?.detail?.retry_after_seconds) {
        const err = new Error(parsed.detail.message || "rate limited");
        (err as any).retryAfter = parsed.detail.retry_after_seconds;
        throw err;
      }
      const msg =
        (typeof parsed?.detail === "string" && parsed.detail) ||
        parsed?.detail?.message ||
        `${r.status} ${r.statusText}`;
      throw new Error(msg);
    }
    return (await r.json()) as Bounty;
  },
};

export type Discovery = {
  recipe_slug: string;
  recipe_name: string;
  discoverer_hero_id: string;
  discoverer_name: string;
  tick_id: number;
  text: string;
};

export type Highlight = {
  event_id: number;
  tick_id: number;
  kind: string;
  zone: string | null;
  hero_id: string | null;
  score: number;
  headline: string;
  killer_kind?: string | null;
};

export type Clip = {
  pivot_event_id: number;
  pivot_tick: number;
  pivot_kind: string;
  headline: string;
  window: [number, number];
  events: {
    id: number;
    tick_id: number;
    kind: string;
    zone: string | null;
    hero_id: string | null;
    payload: any;
  }[];
  journal: {
    id: number;
    tick_id: number;
    hero_id: string;
    kind: string;
    text: string;
    tags: string[];
  }[];
};

export type WyrmStatus =
  | { active: false; next_spawn_at_tick: number; ticks_until_next: number }
  | {
      active: true;
      slug: string;
      name: string;
      zone: string;
      pos: [number, number];
      hp: number;
      hp_max: number;
      spawned_at_tick: number;
      expires_at_tick: number;
      ticks_remaining: number;
    };

export type TideStatus =
  | { active: false; reason: string }
  | {
      active: true;
      opened_at_tick: number;
      ends_at_tick: number;
      ticks_remaining: number;
      leading_faction: string | null;
      leading_deltas: Record<string, number>;
      contested_zone: string;
      last_winner: string | null;
    };

export type CurrentEvents = {
  current_tick: number;
  wyrm: WyrmStatus;
  tide: TideStatus;
};

export type MemoryTrace = {
  hero_id: string;
  name: string;
  recall_tags: string[];
  system_summary: string | null;
  discovered_recipes: string[];
  titles: string[];
  retriever_name: string;
  journal_relevant: {
    tick_id: number | null;
    kind: string;
    text: string;
    tags: string[];
  }[];
};

export type Bounty = {
  id: string;
  target_hero_id: string;
  target_name: string;
  poster_hero_id: string | null;
  poster_name: string;
  reason: string;
  gold: number;
  status: "open" | "claimed" | "expired";
  created_at_tick: number;
  claimed_by_hero_id: string | null;
  claimed_at_tick: number | null;
};

export type ContractKind =
  | "bounty"
  | "assassination"
  | "defense"
  | "delivery"
  | "escort"
  | "caravan";

export type Contract = {
  id: string;
  kind: ContractKind;
  poster_hero_id: string | null;
  poster_name: string;
  target_hero_id: string | null;
  target_ref: string | null;
  reward_gold: number;
  status: "open" | "claimed" | "fulfilled" | "expired";
  zone_scope: string | null;
  reason: string;
  terms: Record<string, any>;
  created_at_tick: number;
  expires_at_tick: number | null;
  claimed_by_hero_id: string | null;
  claimed_at_tick: number | null;
  fulfilled_at_tick: number | null;
};


// Inspector / Showcase types (Phase 5+6 of agent-tools rollout)
export type ToolSummary = {
  name: string;
  kind: "composite" | "override";
  calls: number;
  success: number;
  blocked_by_override: number;
  clamps_applied: number;
  budget_exceeded: number;
  after_chain_failures: number;
  expression_type_errors: number;
  last_called_tick: number | null;
  description: string;
};

export type ToolTraceEntry = { event: string; payload: Record<string, any> };

export type ToolDetail = {
  definition: Record<string, any>;
  recent_calls: Array<{
    tick: number;
    args: Record<string, any>;
    result: "ok" | "blocked" | "budget_exceeded";
    trace: ToolTraceEntry[];
  }>;
  stats: {
    calls: number;
    success: number;
    blocked_by_override: number;
    clamps_applied: number;
    budget_exceeded: number;
  };
};

export type TickLlmCall = {
  chosen_tool: string | null;
  chosen_args: Record<string, any> | null;
  tools_offered: Array<{ name: string; description: string }>;
  reasoning_trace: string;
  tool_mentions: string[];
  // Owner-only fields. Populated only when prompt_visible is true (the
  // request carried the right ?owner_token).
  prompt_visible: boolean;
  prompt_text: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  tokens_budget: number | null;
  latency_ms: number | null;
};

export type LatestLlmCall = TickLlmCall & { tick_id: number | null };



export type SimulateTickResult = {
  chosen_reflex_index: number | null;
  chosen_action: { do: string; [k: string]: any };
  when: string | null;
  tools_visible_to_llm: { name: string; description: string }[];
  composite_count: number;
  override_count: number;
};

