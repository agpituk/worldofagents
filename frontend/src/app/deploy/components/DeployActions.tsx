"use client";

type Props = {
  manifest: string;
  submitting: boolean;
  error: string | null;
  onDeploy: () => void;
};

export default function DeployActions({ manifest, submitting, error, onDeploy }: Props) {
  return (
    <>
      {error && (
        <div className="border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm text-rose-300 whitespace-pre-wrap">
          {error}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={onDeploy}
          disabled={submitting || manifest.trim().length === 0}
          className="border border-amber bg-amber-dim/10 text-amber px-6 py-2 hover:bg-amber-dim/20 disabled:opacity-50"
        >
          {submitting ? "deploying…" : "deploy hero"}
        </button>
        <span className="text-xs text-fg-muted">
          You'll get a share URL on the next screen.
        </span>
      </div>
    </>
  );
}
