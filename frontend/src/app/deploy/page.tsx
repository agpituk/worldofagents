"use client";

// Hosted deploy page — paste a YAML manifest, register a hero, get a share
// URL and the runtime command. The actual bot-runner still runs locally
// (the `python -m arena_bot ...` command) — a managed runtime is on the
// roadmap but not in scope today. This page is the onboarding wall removal:
// no clone, no make dev, just paste-and-go.

import Link from "next/link";
import { useState } from "react";
import { api, WORLD_API_URL } from "@/lib/api";

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

export default function DeployPage() {
  const [manifest, setManifest] = useState(STARTER_MANIFEST);
  const [managed, setManaged] = useState(true); // default ON — paste-and-go
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

      <textarea
        value={manifest}
        onChange={(e) => setManifest(e.target.value)}
        spellCheck={false}
        className="w-full h-96 bg-bg-card border border-border px-3 py-2 font-mono text-xs resize-y"
      />

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
