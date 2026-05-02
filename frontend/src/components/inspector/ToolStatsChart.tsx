"use client";

// Tick-distribution heatmap of when a tool fires across the hero's life.
// No charting library — bins the recent_calls into N buckets and renders
// CSS-only bars. Fast, no extra deps.

type Call = { tick: number; result: "ok" | "blocked" | "budget_exceeded" };

type Props = {
  calls: Call[];
  buckets?: number;
  title?: string;
};

export default function ToolStatsChart({
  calls,
  buckets = 12,
  title = "Calls over time",
}: Props) {
  if (calls.length === 0) {
    return (
      <div className="text-xs text-zinc-500">
        No calls yet — chart will populate once the LLM picks this tool.
      </div>
    );
  }

  const ticks = calls.map((c) => c.tick);
  const min = Math.min(...ticks);
  const max = Math.max(...ticks);
  const span = Math.max(1, max - min);
  const binSize = span / buckets;

  const buckets_ok = new Array(buckets).fill(0);
  const buckets_other = new Array(buckets).fill(0);
  for (const c of calls) {
    let idx = Math.floor((c.tick - min) / binSize);
    if (idx >= buckets) idx = buckets - 1;
    if (idx < 0) idx = 0;
    if (c.result === "ok") buckets_ok[idx]++;
    else buckets_other[idx]++;
  }
  const max_height = Math.max(
    ...buckets_ok.map((v, i) => v + buckets_other[i]),
    1,
  );

  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-zinc-400 mb-2">
        {title}
      </div>
      <div className="flex gap-[2px] items-end h-16">
        {buckets_ok.map((ok_n, i) => {
          const other_n = buckets_other[i];
          const total = ok_n + other_n;
          const totalH = (total / max_height) * 100;
          const okH = total > 0 ? (ok_n / total) * totalH : 0;
          return (
            <div
              key={i}
              title={`tick ${Math.round(min + i * binSize)} — ok ${ok_n}, other ${other_n}`}
              className="flex-1 min-w-[6px] flex flex-col-reverse"
              style={{ height: "100%" }}
            >
              <div
                style={{ height: `${okH}%` }}
                className="bg-emerald-500"
              />
              <div
                style={{ height: `${totalH - okH}%` }}
                className="bg-amber-500"
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] text-zinc-500 mt-1">
        <span>tick {min}</span>
        <span>tick {max}</span>
      </div>
    </div>
  );
}
