"use client";

import { tagsForAbility, type Selection } from "@/lib/blockEditor";
import type { ManifestAbility } from "@/lib/blockEditor";
import TagChips from "./TagChips";
import ErrorBadge from "./ErrorBadge";

type Props = {
  abilities: Record<string, ManifestAbility>;
  selection: Selection | null;
  errorsByPath: Record<string, number>;
  onSelect: (name: string) => void;
};

export default function AbilityList({ abilities, selection, errorsByPath, onSelect }: Props) {
  const names = Object.keys(abilities);
  if (names.length === 0) {
    return <div className="px-3 py-6 text-xs text-fg-muted">no abilities yet — click + new ability</div>;
  }
  return (
    <ul className="text-sm">
      {names.map((name) => {
        const a = abilities[name];
        const sel = selection?.kind === "ability" && selection.name === name;
        const tags = tagsForAbility(a);
        const errs = errorsByPath[`abilities.${name}`] ?? 0;
        return (
          <li
            key={name}
            onClick={() => onSelect(name)}
            className={
              "px-3 py-2 border-b border-border cursor-pointer flex items-center gap-2 " +
              (sel ? "bg-amber-dim/10" : "hover:bg-amber-dim/5")
            }
          >
            <span className="flex-1 min-w-0">
              <div className="truncate">{name}</div>
              <div className="text-[11px] text-fg-muted">{a.steps.length} step(s)</div>
            </span>
            <TagChips tags={tags} />
            <ErrorBadge count={errs} />
          </li>
        );
      })}
    </ul>
  );
}
