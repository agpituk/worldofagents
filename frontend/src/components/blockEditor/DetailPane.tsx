"use client";

// Detail pane: action bar (editing X — duplicate / delete) + the
// optional fallback-reflex banner + the Blockly canvas mount.
// Receives the canvas div ref from the orchestrator so Blockly's
// long-lived workspace stays attached across renders.

import { forwardRef } from "react";
import { describeSelection, isCatchAll } from "@/lib/blockEditor";
import type { ParsedManifest, Selection } from "@/lib/blockEditor";

type Props = {
  parsed: ParsedManifest;
  selection: Selection | null;
  onDuplicate: () => void;
  onDelete: () => void;
};

const DetailPane = forwardRef<HTMLDivElement, Props>(function DetailPane(
  { parsed, selection, onDuplicate, onDelete },
  ref,
) {
  const selectedReflex =
    selection?.kind === "reflex" ? parsed.reflexes[selection.index] : null;
  const showFallbackBanner =
    selectedReflex !== null && selectedReflex !== undefined && isCatchAll(selectedReflex);
  const fallbackHandsToLlm =
    selectedReflex && (selectedReflex.then as any)?.do === "invoke_llm";

  return (
    <div className="flex flex-col">
      <div className="px-3 py-2 border-b border-border text-xs flex items-center gap-3">
        {selection ? (
          <>
            <span className="text-fg-muted">editing</span>
            <span className="text-amber">{describeSelection(parsed, selection)}</span>
            <div className="ml-auto flex items-center gap-3">
              <button onClick={onDuplicate} className="text-fg-muted hover:text-amber-dim">
                duplicate
              </button>
              <button onClick={onDelete} className="text-rose-300 hover:text-rose-200">
                delete
              </button>
            </div>
          </>
        ) : (
          <span className="text-fg-muted">
            select an item on the left, or click <span className="text-amber-dim">+ new</span> above
          </span>
        )}
      </div>
      {showFallbackBanner && (
        <div className="px-3 py-2 border-b border-border bg-sky-950/30 text-xs text-sky-200">
          🛟 <span className="font-semibold">Fallback reflex.</span>{" "}
          <span className="text-sky-200/80">
            <code className="text-sky-300">when: true</code> always matches, so this rule fires only when every earlier reflex didn't.
            {fallbackHandsToLlm && " It hands control to the LLM, which picks the next action with full perception + tools."}
          </span>
        </div>
      )}
      <div ref={ref} className="h-[60vh] bg-bg-card" />
    </div>
  );
});

export default DetailPane;
