"use client";

export default function ErrorBadge({ count }: { count: number }) {
  if (!count) return null;
  return (
    <span
      className="text-[10px] px-1.5 py-0.5 bg-rose-900 text-rose-200"
      title={`${count} validation error(s)`}
    >
      ✕ {count}
    </span>
  );
}
