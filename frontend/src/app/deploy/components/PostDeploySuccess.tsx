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
          onClick={onDeployAnother}
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
