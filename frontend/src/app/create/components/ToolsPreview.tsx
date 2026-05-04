"use client";

type Props = {
  tools: any[];
};

export default function ToolsPreview({ tools }: Props) {
  if (tools.length === 0) return null;
  return (
    <section>
      <div className="text-xs uppercase tracking-wider text-fg-muted mb-2">
        tools preview · {tools.length}
      </div>
      <ul className="border border-border divide-y divide-border text-xs">
        {tools.map((t: any, i: number) => (
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
  );
}
