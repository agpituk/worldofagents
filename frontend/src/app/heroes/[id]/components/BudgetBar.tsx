"use client";

// Token-usage-against-budget bar. Amber over 80%, blood when over.
// Lifted out of PromptInspector so the parent stays under the soft
// component-size cap.

type Props = {
  used: number;
  budget: number | null;
};

export default function BudgetBar({ used, budget }: Props) {
  if (!budget || budget <= 0) {
    return (
      <div className="text-xs text-fg-muted font-mono">
        {used} tokens (no budget cap reported)
      </div>
    );
  }
  const pct = Math.min(100, Math.round((used / budget) * 100));
  const tone =
    used > budget
      ? "bg-rose-700"
      : pct > 80
      ? "bg-amber-dim"
      : "bg-emerald-700";
  const labelTone =
    used > budget
      ? "text-rose-400"
      : pct > 80
      ? "text-amber"
      : "text-emerald-400";
  return (
    <div>
      <div className={`text-xs font-mono ${labelTone}`}>
        {used}/{budget} tokens · {pct}%{used > budget ? " (over)" : ""}
      </div>
      <div className="mt-1 h-1.5 bg-bg border border-border">
        <div
          className={`h-full ${tone}`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
    </div>
  );
}
