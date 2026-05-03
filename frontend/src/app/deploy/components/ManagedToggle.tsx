"use client";

type Props = {
  managed: boolean;
  onChange: (next: boolean) => void;
};

export default function ManagedToggle({ managed, onChange }: Props) {
  return (
    <label className="flex items-start gap-3 border border-border bg-bg-card px-4 py-3 cursor-pointer hover:border-amber-dim">
      <input
        type="checkbox"
        checked={managed}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 accent-amber"
      />
      <div className="text-sm">
        <div className="text-amber">host this hero for me</div>
        <div className="text-xs text-fg-muted mt-1">
          Run the bot loop server-side — no local Python needed. The world-api
          executes your reflexes and calls the LLM gateway on your hero's
          behalf each tick. Uncheck to run the bot yourself with the SDK
          (you'll get the auth token and a one-line command on the next page).
        </div>
      </div>
    </label>
  );
}
