"use client";

import type { Tab } from "@/lib/blockEditor";

type Props = {
  current: Tab;
  t: Tab;
  count: number;
  onClick: () => void;
  children: React.ReactNode;
};

export default function TabButton({ current, t, count, onClick, children }: Props) {
  const active = current === t;
  return (
    <button
      onClick={onClick}
      className={
        "px-3 py-1 border " +
        (active
          ? "border-amber text-amber"
          : "border-transparent text-fg-muted hover:text-amber-dim")
      }
    >
      {children} <span className="text-xs opacity-70">({count})</span>
    </button>
  );
}
