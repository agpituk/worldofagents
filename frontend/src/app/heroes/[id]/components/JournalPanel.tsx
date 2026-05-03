"use client";

import { JournalEntry } from "@/lib/api";

type Props = { entries: JournalEntry[] };

export default function JournalPanel({ entries }: Props) {
  if (entries.length === 0) return null;
  return (
    <details className="mt-6" open>
      <summary className="text-xs uppercase tracking-wider text-fg-muted cursor-pointer hover:text-amber">
        journal ({entries.length})
      </summary>
      <ol className="mt-2 space-y-2 max-h-[40vh] overflow-y-auto pr-2">
        {entries.map((j) => (
          <li
            key={j.id}
            className={`text-sm leading-relaxed border-l-2 pl-3 ${
              j.kind === "milestone" ? "border-amber-dim" : "border-blue-700"
            }`}
          >
            <div className="text-xs text-amber-dim font-mono mb-0.5">
              t{j.tick_id} · {j.kind}
              {j.tags.length > 0 && (
                <span className="text-fg-muted ml-2">{j.tags.join(" · ")}</span>
              )}
            </div>
            <div className={j.kind === "player" ? "italic text-fg" : "text-fg/85"}>
              {j.text}
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}
