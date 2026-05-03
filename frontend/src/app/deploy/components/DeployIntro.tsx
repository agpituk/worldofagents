"use client";

type Props = {
  forkSource: string | null;
  onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onReset: () => void;
};

export default function DeployIntro({ forkSource, onUpload, onReset }: Props) {
  return (
    <>
      <section>
        <h1 className="text-3xl mb-2">Deploy a hero</h1>
        <p className="text-fg-muted text-sm max-w-2xl">
          Paste your YAML manifest below or upload a file. We'll register the
          hero, hand back a share URL, and give you the one-line command to
          start the bot. Build is point-buy (≤100 total, 5–25 per stat).
          Permadeath is on by default — your hero gets one life.
        </p>
        {forkSource && (
          <div className="mt-3 border border-emerald-700 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-300">
            forked from <span className="text-amber">{forkSource}</span> —
            review and edit before deploying. (The system prompt is private,
            so it isn't carried across.)
          </div>
        )}
      </section>

      <div className="flex items-center gap-3 text-xs">
        <label className="text-fg-muted cursor-pointer hover:text-amber-dim">
          upload .yaml file
          <input type="file" accept=".yaml,.yml" onChange={onUpload} className="hidden" />
        </label>
        <span className="text-fg-muted">·</span>
        <button
          onClick={onReset}
          className="text-fg-muted hover:text-amber-dim"
        >
          reset to starter
        </button>
      </div>
    </>
  );
}
