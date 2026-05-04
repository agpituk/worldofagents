"use client";

type Props = {
  manifest: string;
  submitting: boolean;
  error: string | null;
  onDeploy: () => void;
  disabledReason?: string | null;
};

export default function DeployActions({ manifest, submitting, error, onDeploy, disabledReason }: Props) {
  const blocked = !!disabledReason;
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
          disabled={submitting || manifest.trim().length === 0 || blocked}
          className="border border-amber bg-amber-dim/10 text-amber px-6 py-2 hover:bg-amber-dim/20 disabled:opacity-50"
        >
          {submitting ? "creating…" : "create hero"}
        </button>
        <span className="text-xs text-fg-muted">
          {blocked
            ? disabledReason
            : "You'll get a share URL and the one-line run command on the next screen."}
        </span>
      </div>
    </>
  );
}
