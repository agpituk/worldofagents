"use client";

import { tagsForTool, toolLabel, type Selection } from "@/lib/blockEditor";
import type { ManifestComposite, ManifestOverride } from "@/lib/blockEditor";
import TagChips from "./TagChips";
import ErrorBadge from "./ErrorBadge";

type Props = {
  tools: Array<ManifestComposite | ManifestOverride>;
  selection: Selection | null;
  errorsByPath: Record<string, number>;
  onSelect: (i: number) => void;
};

export default function ToolList({ tools, selection, errorsByPath, onSelect }: Props) {
  if (tools.length === 0) {
    return <div className="px-3 py-6 text-xs text-fg-muted">no tools yet — click + new tool</div>;
  }
  return (
    <ul className="text-sm">
      {tools.map((t, i) => {
        const sel = selection?.kind === "tool" && selection.index === i;
        const tags = tagsForTool(t);
        const errs = errorsByPath[`tools[${i}]`] ?? 0;
        const isOverride = "override" in t && !!t.override;
        return (
          <li
            key={i}
            onClick={() => onSelect(i)}
            className={
              "px-3 py-2 border-b border-border cursor-pointer flex items-center gap-2 " +
              (sel ? "bg-amber-dim/10" : "hover:bg-amber-dim/5")
            }
          >
            <span className="flex-1 min-w-0">
              <div className="truncate">{toolLabel(t)}</div>
              <div className="text-[11px] text-fg-muted">
                {isOverride ? "override" : "composite"}
              </div>
            </span>
            <TagChips tags={tags} />
            <ErrorBadge count={errs} />
          </li>
        );
      })}
    </ul>
  );
}
