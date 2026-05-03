"use client";

import { MemoryTrace } from "@/lib/api";

type Props = { trace: MemoryTrace };

export default function MemoryTracePanel({ trace }: Props) {
  const empty =
    trace.recall_tags.length === 0 &&
    !trace.system_summary &&
    trace.journal_relevant.length === 0;
  if (empty) return null;
  return (
    <details className="mt-6" open>
      <summary className="text-xs uppercase tracking-wider text-fg-muted cursor-pointer hover:text-amber">
        memory trace
        <span className="ml-2 text-fg-muted normal-case font-mono">
          via {trace.retriever_name}
        </span>
      </summary>
      <div className="mt-3 space-y-3 text-sm">
        {trace.system_summary && (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">always-on</div>
            <p className="text-fg/80 italic whitespace-pre-line text-xs leading-relaxed border-l-2 border-amber-dim/40 pl-3">
              {trace.system_summary}
            </p>
          </div>
        )}
        {trace.recall_tags.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">recall tags</div>
            <div className="flex flex-wrap gap-1">
              {trace.recall_tags.map((t) => (
                <span
                  key={t}
                  className="text-xs px-2 py-0.5 bg-amber-dim/10 border border-amber-dim/40 text-amber-dim"
                >
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}
        {trace.journal_relevant.length > 0 ? (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
              pulled this tick ({trace.journal_relevant.length})
            </div>
            <ol className="space-y-1.5">
              {trace.journal_relevant.map((m, i) => (
                <li key={i} className="border-l-2 border-blue-700 pl-3 text-xs">
                  <div className="text-fg-muted font-mono">
                    {m.tick_id != null ? `t${m.tick_id}` : "—"} · {m.kind}
                    {m.tags.length > 0 && (
                      <span className="ml-2">{m.tags.slice(0, 4).join(" · ")}</span>
                    )}
                  </div>
                  <div className="text-fg/85">{m.text}</div>
                </li>
              ))}
            </ol>
          </div>
        ) : trace.recall_tags.length > 0 ? (
          <p className="text-xs text-fg-muted italic">
            Tags declared, but the retriever found nothing matching yet.
          </p>
        ) : null}
        {trace.titles.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">titles earned</div>
            <div className="flex flex-wrap gap-1">
              {trace.titles.map((t) => (
                <span
                  key={t}
                  className="text-xs px-2 py-0.5 bg-amber/10 border border-amber/40 text-amber"
                >
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}
        {trace.discovered_recipes.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">recipes discovered</div>
            <ul className="text-xs space-y-0.5">
              {trace.discovered_recipes.map((r) => (
                <li key={r} className="text-amber-dim">
                  ✦ {r}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}
