"use client";

// Hosted deploy page — paste a YAML manifest, register a hero, get a share
// URL and the runtime command. The actual bot-runner still runs locally
// (the `python -m arena_bot ...` command) — a managed runtime is on the
// roadmap but not in scope today. This page is the onboarding wall removal:
// no clone, no make dev, just paste-and-go.

import Link from "next/link";
import dynamic from "next/dynamic";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, WORLD_API_URL } from "@/lib/api";

// Blockly is heavy (~280KB gzipped) — lazy-load only on /deploy.
const BlockEditor = dynamic(() => import("@/components/BlockEditor"), {
  ssr: false,
  loading: () => (
    <div className="border border-border bg-bg-card p-6 text-xs text-fg-muted">
      loading block editor...
    </div>
  ),
});

const STARTER_MANIFEST = `manifest_version: 1
hero:
  name: "Your Hero Name"
  author: "@your_handle"
  division: featherweight

  bio: |
    A short bio in the hero's own voice. The model uses this verbatim as
    persona context, so write it like you'd write a character sheet.

  build:
    str: 12
    dex: 12
    con: 14
    int: 12
    wis: 14
    cha: 8
    # Total must be ≤ 100 (point buy). Each stat 5–25.

  models:
    cheap: { gateway: arena, model: qwen3-4b, host: local }
  model: cheap

  reflexes:
    - when: "hp <= 8"
      then: { do: flee }
    - when: "enemy_in_range()"
      then: { do: attack_nearest_hostile }
    - when: "hostile_visible() and not enemy_in_range()"
      then: { do: move_to_nearest_hostile }
    # When no reflex matches, escalate to the model
    - when: "true"
      then: { do: invoke_llm }

  memory:
    initial:
      goal: "Survive. Adventure. Make decisions in character."
      gold: 20
    system_summary: |
      Two or three durable facts about who this hero is — fed into every
      LLM prompt regardless of perception window.
    recall_tags:
      - milestone
      - first_kill
`;

function manifestYamlFromHero(h: any): string {
  // Build a minimal-but-runnable YAML from a public Hero record. The
  // public manifest already strips `system` (the prompt). Output is
  // plain string concatenation so we don't need a yaml lib in the
  // browser bundle.
  const m = (h.manifest || {}) as Record<string, any>;
  const ext = (m.extras || {}) as Record<string, any>;
  const build = h.build || {};
  const lines: string[] = [
    "manifest_version: 1",
    "hero:",
    `  name: "${h.name} (fork)"`,
    `  author: "${h.author || "@you"}"`,
    `  division: ${h.division}`,
  ];
  if (h.bio) {
    lines.push(`  bio: ${JSON.stringify(h.bio)}`);
  }
  lines.push(
    "  build:",
    `    str: ${build.str ?? 12}`,
    `    dex: ${build.dex ?? 12}`,
    `    con: ${build.con ?? 12}`,
    `    int: ${build.int ?? 12}`,
    `    wis: ${build.wis ?? 12}`,
    `    cha: ${build.cha ?? 12}`,
  );
  // Pass through extras as JSON-ish YAML using JSON.stringify (valid YAML).
  for (const [k, v] of Object.entries(ext)) {
    if (v === undefined || v === null) continue;
    lines.push(`  ${k}: ${JSON.stringify(v)}`);
  }
  return lines.join("\n") + "\n";
}


function DeployFormBody() {
  const params = useSearchParams();
  const forkId = params.get("fork");
  const [manifest, setManifest] = useState(STARTER_MANIFEST);
  const [forkSource, setForkSource] = useState<string | null>(null);
  const [managed, setManaged] = useState(true); // default ON — paste-and-go
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Phase 8 — load the source hero's public manifest and prefill the
  // textarea when /deploy?fork=<id> is opened. Failure is silent so a
  // stale URL doesn't lock anyone out — they can still type freely.
  useEffect(() => {
    if (!forkId) return;
    let live = true;
    api.getHero(forkId).then((h: any) => {
      if (!live) return;
      setForkSource(h.name);
      setManifest(manifestYamlFromHero(h));
    }).catch(() => {});
    return () => { live = false; };
  }, [forkId]);
  const [registered, setRegistered] = useState<
    | {
        id: string;
        name: string;
        auth_token: string;
        division: string;
        managed: boolean;
      }
    | null
  >(null);

  // Phase 8 — manifest validator. Stays empty until the user clicks
  // "validate"; results are issue-level (severity + path + message)
  // and clear when they edit the manifest so stale lints don't linger.
  const [validation, setValidation] = useState<{ valid: boolean; issues: any[]; summary: any } | null>(null);
  const [validating, setValidating] = useState(false);

  async function validate() {
    setValidating(true);
    setValidation(null);
    try {
      const res = await api.validateManifest(manifest);
      setValidation(res);
    } catch (e: any) {
      setValidation({ valid: false, issues: [{ severity: "error", message: String(e?.message ?? "validate failed") }], summary: {} });
    } finally {
      setValidating(false);
    }
  }

  async function deploy() {
    setError(null);
    setSubmitting(true);
    try {
      const r = await api.registerHero(manifest, { managed });
      setRegistered({ ...r, managed });
    } catch (e: any) {
      setError(String(e?.message ?? "registration failed"));
    } finally {
      setSubmitting(false);
    }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    const text = await f.text();
    setManifest(text);
  }

  if (registered) {
    const shareUrl = `${typeof window !== "undefined" ? window.location.origin : ""}/h/${encodeURIComponent(registered.name)}`;
    const wsUrl = WORLD_API_URL.replace(/^http/, "ws") + `/heroes/ws?token=${registered.auth_token}`;
    const runCmd = `cd bot-sdk-python && uv run python -m arena_bot path/to/your.yaml \\\n  --world ${WORLD_API_URL} \\\n  --gateway ${WORLD_API_URL.replace(":47800", ":47801")}`;
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <Link href="/" className="text-xs text-fg-muted hover:text-amber-dim">← world</Link>

        <div className="border border-emerald-700 bg-emerald-950/20 px-5 py-4">
          <div className="text-xs uppercase tracking-wider text-emerald-400">deployed</div>
          <h1 className="text-3xl font-display text-amber mt-1">{registered.name}</h1>
          <div className="text-xs text-fg-muted mt-1">
            <code>{registered.id}</code> · {registered.division}
          </div>
        </div>

        <section>
          <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-2">share url</h2>
          <Link
            href={`/h/${encodeURIComponent(registered.name)}`}
            className="block border border-border bg-bg-card px-4 py-3 font-mono text-sm hover:border-amber-dim"
          >
            {shareUrl}
          </Link>
          <p className="text-xs text-fg-muted mt-2">
            Anyone can spectate at this URL — no login. Will redirect to the
            monument page if/when this hero dies (permadeath is permanent).
          </p>
        </section>

        <section>
          {registered.managed ? (
            <div className="border border-emerald-700 bg-emerald-950/30 px-4 py-3 text-sm">
              <div className="text-xs uppercase tracking-wider text-emerald-400 mb-1">
                running server-side
              </div>
              <div>
                The world-api is running your hero's bot loop right now. Reflexes
                evaluate against fresh perception every {Math.floor(6)}s tick;
                <code> invoke_llm</code> calls go through the gateway. No local
                setup needed — close this tab if you want.
              </div>
              <div className="mt-2 text-xs text-fg-muted">
                Want to take over locally instead? <a href="#" onClick={(e) => { e.preventDefault(); /* could call API to flip managed=false */ }} className="text-amber-dim hover:text-amber underline">contact support</a> (toggle endpoint coming soon).
              </div>
            </div>
          ) : (
            <>
              <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-2">connect a runtime</h2>
              <p className="text-sm text-fg-muted mb-2">
                Save your YAML locally as <code>your.yaml</code> and run:
              </p>
              <pre className="bg-bg-card border border-border p-3 text-xs font-mono overflow-x-auto whitespace-pre-wrap">{runCmd}</pre>
              <details className="mt-3">
                <summary className="text-xs text-fg-muted cursor-pointer hover:text-amber-dim">
                  raw connection details
                </summary>
                <div className="mt-2 text-xs space-y-1 font-mono text-fg-muted">
                  <div>auth_token: <span className="text-amber">{registered.auth_token}</span></div>
                  <div>websocket: <span className="break-all">{wsUrl}</span></div>
                </div>
              </details>
            </>
          )}
        </section>

        <div className="flex gap-3 text-sm pt-4">
          <button
            onClick={() => {
              setRegistered(null);
              setManifest(STARTER_MANIFEST);
            }}
            className="border border-border bg-bg-card px-4 py-2 hover:border-amber-dim"
          >
            deploy another
          </button>
          <Link
            href={`/h/${encodeURIComponent(registered.name)}`}
            className="border border-amber bg-amber-dim/10 text-amber px-4 py-2 hover:bg-amber-dim/20"
          >
            view hero →
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <Link href="/" className="text-xs text-fg-muted hover:text-amber-dim">← world</Link>

      <section>
        <h1 className="text-3xl mb-2">Deploy a hero</h1>
        <p className="text-fg-muted text-sm max-w-2xl">
          Paste your YAML manifest below or upload a file. We'll register the
          hero, hand back a share URL, and give you the one-line command to
          start the bot. Build is point-buy (≤100 total, 5–25 per stat).
          Permadeath is on by default — your hero gets one life.
        </p>
        {forkSource && (
          <div className="mt-3 border border-emerald-700 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-300">
            forked from <span className="text-amber">{forkSource}</span> —
            review and edit before deploying. (The system prompt is private,
            so it isn't carried across.)
          </div>
        )}
      </section>

      <div className="flex items-center gap-3 text-xs">
        <label className="text-fg-muted cursor-pointer hover:text-amber-dim">
          upload .yaml file
          <input type="file" accept=".yaml,.yml" onChange={onFile} className="hidden" />
        </label>
        <span className="text-fg-muted">·</span>
        <button
          onClick={() => setManifest(STARTER_MANIFEST)}
          className="text-fg-muted hover:text-amber-dim"
        >
          reset to starter
        </button>
      </div>

      <BlockEditor
        value={manifest}
        onChange={(next) => {
          setManifest(next);
          setValidation(null);
        }}
        validationIssues={validation?.issues}
      />

      <div className="flex items-center gap-3 text-xs">
        <button
          onClick={validate}
          disabled={validating || manifest.trim().length === 0}
          className="border border-border bg-bg-card px-3 py-1 text-fg-muted hover:text-amber-dim hover:border-amber-dim disabled:opacity-50"
        >
          {validating ? "validating…" : "validate manifest"}
        </button>
        {validation && (
          <span className={validation.valid ? "text-emerald-400" : "text-rose-300"}>
            {validation.valid
              ? `✓ valid · ${validation.summary.spells_declared ?? 0} spells · ${validation.summary.reflexes_declared ?? 0} reflexes · ${validation.summary.tools_declared ?? 0} tools`
              : `${validation.issues.length} issue${validation.issues.length === 1 ? "" : "s"}`}
          </span>
        )}
      </div>

      {validation && validation.issues.length > 0 && (
        <ul className="border border-border bg-bg-card divide-y divide-border text-xs">
          {validation.issues.map((iss: any, i: number) => (
            <li key={i} className="px-3 py-2">
              <span
                className={
                  iss.severity === "error"
                    ? "text-rose-300 mr-2"
                    : iss.severity === "warning"
                    ? "text-amber mr-2"
                    : "text-fg-muted mr-2"
                }
              >
                {iss.severity}
              </span>
              {iss.path && <code className="text-fg-muted mr-2">{iss.path}</code>}
              <span>{iss.message}</span>
            </li>
          ))}
        </ul>
      )}

      {/* First-tick simulation panel — runs reflex eval + tool spec
          assembly server-side against a synthetic perception. */}
      <SimulationPanel manifest={manifest} />

      {validation?.valid && Array.isArray(validation.summary?.tools) && validation.summary.tools.length > 0 && (
        <section>
          <div className="text-xs uppercase tracking-wider text-fg-muted mb-2">
            tools preview · {validation.summary.tools.length}
          </div>
          <ul className="border border-border divide-y divide-border text-xs">
            {validation.summary.tools.map((t: any, i: number) => (
              <li key={i} className="px-3 py-2 flex items-baseline gap-3">
                <span className={t.kind === "override" ? "italic text-amber-dim" : "font-mono text-amber"}>
                  {t.name}
                </span>
                <span className="text-fg-muted">{t.kind}</span>
                {t.kind === "composite" && (
                  <span className="text-fg-muted">
                    {t.step_count} step{t.step_count === 1 ? "" : "s"}
                    {t.param_count > 0 && ` · ${t.param_count} param${t.param_count === 1 ? "" : "s"}`}
                  </span>
                )}
                {t.kind === "override" && (
                  <span className="text-fg-muted">
                    of <code>{t.override_verb}</code>
                    {t.has_when && " · when"}
                    {t.clamp_param_count > 0 && ` · ${t.clamp_param_count} clamp`}
                    {t.after_step_count > 0 && ` · ${t.after_step_count} after`}
                  </span>
                )}
                {t.description && (
                  <span className="text-fg-muted ml-auto truncate max-w-[40%]" title={t.description}>
                    {t.description}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <label className="flex items-start gap-3 border border-border bg-bg-card px-4 py-3 cursor-pointer hover:border-amber-dim">
        <input
          type="checkbox"
          checked={managed}
          onChange={(e) => setManaged(e.target.checked)}
          className="mt-1 accent-amber"
        />
        <div className="text-sm">
          <div className="text-amber">host this hero for me</div>
          <div className="text-xs text-fg-muted mt-1">
            Run the bot loop server-side — no local Python needed. The world-api
            executes your reflexes and calls the LLM gateway on your hero's
            behalf each tick. Uncheck to run the bot yourself with the SDK
            (you'll get the auth token and a one-line command on the next page).
          </div>
        </div>
      </label>

      {error && (
        <div className="border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm text-rose-300 whitespace-pre-wrap">
          {error}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={deploy}
          disabled={submitting || manifest.trim().length === 0}
          className="border border-amber bg-amber-dim/10 text-amber px-6 py-2 hover:bg-amber-dim/20 disabled:opacity-50"
        >
          {submitting ? "deploying…" : "deploy hero"}
        </button>
        <span className="text-xs text-fg-muted">
          You'll get a share URL on the next screen.
        </span>
      </div>
    </div>
  );
}

export default function DeployPage() {
  return (
    <Suspense fallback={<div className='text-fg-muted'>loading…</div>}>
      <DeployFormBody />
    </Suspense>
  );
}

// ---------------------------------------------------------------------------
// First-tick simulation panel — debounced server-side dry-run.
// ---------------------------------------------------------------------------

import type { SimulateTickResult } from "@/lib/api";

function SimulationPanel({ manifest }: { manifest: string }) {
  const [data, setData] = useState<SimulateTickResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (manifest.trim().length === 0) {
      setData(null);
      return;
    }
    setPending(true);
    const id = setTimeout(async () => {
      try {
        const r = await api.simulateTick(manifest);
        setData(r);
        setError(null);
      } catch (e: any) {
        setError(e?.message ?? "simulate failed");
      } finally {
        setPending(false);
      }
    }, 600);
    return () => clearTimeout(id);
  }, [manifest]);

  return (
    <section className="border border-border bg-bg-card p-3 text-xs">
      <div className="uppercase tracking-wider text-fg-muted mb-2">
        first-tick simulation {pending && <span className="text-amber-dim">(refreshing…)</span>}
      </div>
      {error && <p className="text-rose-400">{error}</p>}
      {!error && data && (
        <div className="space-y-1">
          <p>
            <span className="text-fg-muted">would do:</span>{" "}
            <code className="text-amber">
              {data.chosen_action.do}
              {Object.keys(data.chosen_action).filter((k) => k !== "do" && !k.startsWith("_")).length > 0
                ? `(${Object.entries(data.chosen_action)
                    .filter(([k]) => k !== "do" && !k.startsWith("_"))
                    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                    .join(", ")})`
                : "()"}
            </code>
          </p>
          {data.when && (
            <p>
              <span className="text-fg-muted">via reflex #{data.chosen_reflex_index}:</span>{" "}
              <code className="text-fg-muted">when {data.when}</code>
            </p>
          )}
          {data.chosen_reflex_index === null && (
            <p className="text-fg-muted italic">
              no reflex matched — would emit `wait` (LLM only fires on
              explicit invoke_llm).
            </p>
          )}
          <p className="text-fg-muted mt-2">
            LLM tool list: {data.tools_visible_to_llm.length} tools (
            {data.composite_count} composites, {data.override_count} overrides).
          </p>
        </div>
      )}
    </section>
  );
}

