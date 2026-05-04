"use client";

import {
  isCatchAll,
  reflexLabel,
  reflexVerb,
  reflexVerbDescription,
  tagsForReflex,
  type Selection,
} from "@/lib/blockEditor";
import type { ManifestReflex } from "@/lib/blockEditor";
import TagChips from "./TagChips";
import ErrorBadge from "./ErrorBadge";

type Props = {
  reflexes: ManifestReflex[];
  selection: Selection | null;
  dragIndex: number | null;
  overIndex: number | null;
  errorsByPath: Record<string, number>;
  onSelect: (i: number) => void;
  onToggleDisabled: (i: number) => void;
  onDragStart: (i: number) => (e: React.DragEvent) => void;
  onDragOver: (i: number) => (e: React.DragEvent) => void;
  onDrop: (i: number) => (e: React.DragEvent) => void;
};

export default function ReflexList({
  reflexes, selection, dragIndex, overIndex, errorsByPath,
  onSelect, onToggleDisabled, onDragStart, onDragOver, onDrop,
}: Props) {
  if (reflexes.length === 0) {
    return <div className="px-3 py-6 text-xs text-fg-muted">no reflexes yet — click + new reflex</div>;
  }
  return (
    <ul className="text-sm">
      {reflexes.map((rx, i) => {
        const sel = selection?.kind === "reflex" && selection.index === i;
        const tags = tagsForReflex(rx);
        const disabled = (rx as any).disabled === true;
        const errs = errorsByPath[`reflexes[${i}]`] ?? 0;
        const catchAll = isCatchAll(rx);
        // A catch-all that isn't last shadows everything below it —
        // those rules can never fire. Worth flagging.
        const shadowing = catchAll && i < reflexes.length - 1;
        const verbDesc = reflexVerbDescription(rx);
        return (
          <li
            key={i}
            draggable
            onDragStart={onDragStart(i)}
            onDragOver={onDragOver(i)}
            onDrop={onDrop(i)}
            onClick={() => onSelect(i)}
            className={
              "px-3 py-2 border-b border-border cursor-pointer flex items-center gap-2 " +
              (sel ? "bg-amber-dim/10 " : "hover:bg-amber-dim/5 ") +
              (disabled ? "opacity-50 " : "") +
              (catchAll ? "bg-sky-950/20 " : "") +
              (overIndex === i && dragIndex !== null && dragIndex !== i ? "border-t-2 border-t-amber " : "") +
              (dragIndex === i ? "opacity-30 " : "")
            }
          >
            <span className="text-fg-muted text-xs cursor-grab" title="drag to reorder">⋮⋮</span>
            <span className="text-xs text-amber-dim w-6">#{i + 1}</span>
            <span className="flex-1 min-w-0">
              {catchAll ? (
                <div className="truncate text-sky-300">
                  🛟 fallback <span className="text-fg-muted">(when: {(rx.when ?? "true").trim() || "true"})</span>
                </div>
              ) : (
                <div className="truncate">{reflexLabel(rx)}</div>
              )}
              <div className="text-[11px] text-fg-muted truncate">→ {reflexVerb(rx)}</div>
              {(catchAll || verbDesc) && (
                <div className="text-[10px] text-fg-muted/80 italic truncate">
                  {catchAll ? "fires only if no earlier rule matched" : verbDesc}
                </div>
              )}
              {shadowing && (
                <div className="text-[10px] text-rose-300 truncate">
                  ⚠ shadows rules below — drag to bottom
                </div>
              )}
            </span>
            <TagChips tags={tags} />
            <ErrorBadge count={errs} />
            <button
              onClick={(e) => { e.stopPropagation(); onToggleDisabled(i); }}
              className="text-xs text-fg-muted hover:text-amber-dim"
              title={disabled ? "enable reflex" : "disable reflex"}
            >
              {disabled ? "○" : "●"}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
