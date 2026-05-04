"use client";

export default function TagChips({ tags }: { tags: string[] }) {
  if (tags.length === 0) return null;
  return (
    <span className="flex gap-1">
      {tags.map((t) => (
        <span key={t} className="text-[10px] px-1.5 py-0.5 border border-border text-fg-muted">
          {t}
        </span>
      ))}
    </span>
  );
}
