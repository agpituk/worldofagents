"use client";

import TemplatePicker from "./TemplatePicker";
import type { Archetype } from "../templates/templates";

type Props = {
  open: boolean;
  onPick: (archetype: Archetype) => void;
  onSkip: () => void;
};

export default function TemplateModal({ open, onPick, onSkip }: Props) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Pick a starter archetype"
    >
      <div className="max-w-5xl w-full border border-border bg-bg p-6">
        <div className="flex items-baseline justify-between mb-4">
          <div>
            <h2 className="text-xl font-display text-amber">Pick a starter</h2>
            <p className="text-xs text-fg-muted mt-1">
              Five archetypes that map to the SDK's worked examples. Each loads
              a complete manifest you can edit. Set <code>author</code> to your
              own handle before deploying.
            </p>
          </div>
          <button
            onClick={onSkip}
            className="text-xs text-fg-muted hover:text-fg border border-border px-3 py-1"
          >
            skip — start from blank
          </button>
        </div>
        <TemplatePicker onSelect={onPick} />
      </div>
    </div>
  );
}
