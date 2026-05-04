"use client";

import Link from "next/link";
import { WORLD_API_URL } from "@/lib/api";

export type RegisteredHero = {
  id: string;
  name: string;
  auth_token: string;
  division: string;
  managed: boolean;
};

type Props = {
  registered: RegisteredHero;
  onDeployAnother: () => void;
};

export default function PostDeploySuccess({ registered, onDeployAnother }: Props) {
  const shareUrl = `${typeof window !== "undefined" ? window.location.origin : ""}/h/${encodeURIComponent(registered.name)}`;
  const wsUrl = WORLD_API_URL.replace(/^http/, "ws") + `/heroes/ws?token=${registered.auth_token}`;
  const manifestUrl = `${WORLD_API_URL}/heroes/${registered.id}/manifest.yaml`;
  const gatewayUrl = WORLD_API_URL.replace(":47800", ":47801");
  // Slug-ify the hero name so the local filename is shell-safe even
  // when the name has spaces or punctuation ("Bromir the Stalwart" →
  // "bromir_the_stalwart"). Wrap in quotes too — belt + suspenders.
  const slug =
    registered.name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") ||
    "hero";
  const filename = `${slug}.yaml`;
  // One-shot: download the saved manifest into the local dir, then run.
  // The user doesn't have to copy/paste YAML out of the editor.
  // Run from the repo root. `uv run --project bot-sdk-python` resolves
  // the SDK's venv without a `cd`, so the manifest path stays simple
  // (no "../") and the command works whether the user pasted it from
  // the worktree root or anywhere else inside it.
  //
  // The `--token` flag is what makes the create-via-web → run-locally
  // handoff work. Without it, the SDK tries to re-register the hero,
  // hits 409 Conflict on the unique-name constraint, and aborts.
  const runCmd = `curl -fsSL "${manifestUrl}" -o "${filename}" \\\n  && uv run --project bot-sdk-python python -m arena_bot "${filename}" \\\n  --token ${registered.auth_token} \\\n  --world ${WORLD_API_URL} \\\n  --gateway ${gatewayUrl}`;
  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <Link href="/" className="text-xs text-fg-muted hover:text-amber-dim">← world</Link>

      <div className="border border-emerald-700 bg-emerald-950/20 px-5 py-4">
        <div className="text-xs uppercase tracking-wider text-emerald-400">created</div>
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
          The hero will idle until you start the bot loop below.
        </p>
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-2">run your hero</h2>
        <p className="text-sm text-fg-muted mb-2">
          From your <code>worldofagents</code> repo root, paste this — it
          downloads your manifest and starts the bot loop in one shot:
        </p>
        <pre className="bg-bg-card border border-border p-3 text-xs font-mono overflow-x-auto whitespace-pre-wrap">{runCmd}</pre>
        <p className="text-xs text-fg-muted mt-2">
          The bot loop reads perception from the world-api each tick and
          calls your configured LLM via the gateway. You bring your own
          provider (local llamafile, Anthropic, OpenAI, …).
        </p>
        <details className="mt-3">
          <summary className="text-xs text-fg-muted cursor-pointer hover:text-amber-dim">
            raw connection details
          </summary>
          <div className="mt-2 text-xs space-y-1 font-mono text-fg-muted">
            <div>
              manifest: <a href={manifestUrl} className="text-amber-dim hover:text-amber underline break-all">{manifestUrl}</a>
            </div>
            <div>auth_token: <span className="text-amber">{registered.auth_token}</span></div>
            <div>websocket: <span className="break-all">{wsUrl}</span></div>
          </div>
        </details>
      </section>

      <div className="flex gap-3 text-sm pt-4">
        <button
          onClick={onDeployAnother}
          className="border border-border bg-bg-card px-4 py-2 hover:border-amber-dim"
        >
          create another
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
