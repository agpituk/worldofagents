"use client";

// Form inputs for the hero's identity fields (name, author, division,
// bio). All YAML parser/serializer logic lives in `lib/heroDetails.ts`
// — this component is render + event wiring only.

import { useMemo } from "react";
import {
  DIVISIONS,
  PLACEHOLDER_AUTHORS,
  PLACEHOLDER_BIOS,
  PLACEHOLDER_NAMES,
  parseHeroDetails,
  setBioInYaml,
  setScalarInYaml,
  type Division,
  type HeroDetails,
} from "@/lib/heroDetails";

// Re-export for callers (deploy/create page wires this into DeployActions).
export { getHeroDetailsBlockReason } from "@/lib/heroDetails";

type Props = {
  value: string;
  onChange: (next: string) => void;
};

export default function HeroDetailsPanel({ value, onChange }: Props) {
  const details = useMemo(() => parseHeroDetails(value), [value]);
  if (!details) {
    return (
      <div className="border border-border bg-bg-card p-4 text-xs text-fg-muted">
        hero details unavailable while YAML is invalid
      </div>
    );
  }

  function patch(key: keyof HeroDetails, v: string) {
    if (key === "bio") {
      onChange(setBioInYaml(value, v));
      return;
    }
    onChange(setScalarInYaml(value, key, v));
  }

  // Inline warnings for fields whose current value will be rejected by
  // the server (or that are obviously the template placeholder).
  const trimmedAuthor = details.author.trim();
  const authorIssue =
    trimmedAuthor === "" || trimmedAuthor === "@"
      ? "Set your @handle — the server requires it."
      : PLACEHOLDER_AUTHORS.has(trimmedAuthor)
      ? `'${trimmedAuthor}' is the template placeholder — replace with your handle.`
      : null;
  const trimmedName = details.name.trim();
  const nameIssue =
    trimmedName === ""
      ? "Give your hero a name."
      : PLACEHOLDER_NAMES.has(trimmedName)
      ? "Replace the placeholder name."
      : null;

  // Treat known starter values as effective placeholders: when the
  // user focuses a field whose value still matches the template, clear
  // it (or trim author down to "@") so they can type their own.
  function clearOnFocusIfPlaceholder(key: keyof HeroDetails) {
    return () => {
      if (key === "name" && PLACEHOLDER_NAMES.has(details!.name)) {
        patch("name", "");
      } else if (key === "author" && PLACEHOLDER_AUTHORS.has(details!.author)) {
        patch("author", "@");
      } else if (key === "bio" && PLACEHOLDER_BIOS.has(details!.bio)) {
        patch("bio", "");
      }
    };
  }

  return (
    <div className="border border-border bg-bg-card p-4 space-y-3">
      <h3 className="text-xs uppercase tracking-wider text-fg-muted">
        hero details
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <label className="text-xs text-fg-muted block">
          <div className="mb-1">name</div>
          <input
            type="text"
            value={details.name}
            onChange={(e) => patch("name", e.target.value)}
            onFocus={clearOnFocusIfPlaceholder("name")}
            placeholder="Your Hero Name"
            className={
              "w-full bg-bg border px-2 py-1 text-sm " +
              (nameIssue ? "border-rose-500" : "border-border")
            }
          />
          {nameIssue && (
            <div className="text-[10px] text-rose-300 mt-1">⚠ {nameIssue}</div>
          )}
        </label>
        <label className="text-xs text-fg-muted block">
          <div className="mb-1">author</div>
          <input
            type="text"
            value={details.author}
            onChange={(e) => patch("author", e.target.value)}
            onFocus={clearOnFocusIfPlaceholder("author")}
            placeholder="@your_handle"
            className={
              "w-full bg-bg border px-2 py-1 text-sm " +
              (authorIssue ? "border-rose-500" : "border-border")
            }
          />
          {authorIssue && (
            <div className="text-[10px] text-rose-300 mt-1">⚠ {authorIssue}</div>
          )}
        </label>
        <label className="text-xs text-fg-muted block">
          <div className="mb-1">division</div>
          <select
            value={details.division}
            onChange={(e) => patch("division", e.target.value)}
            className="w-full bg-bg border border-border px-2 py-1 text-sm"
          >
            {DIVISIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
            {!DIVISIONS.includes(details.division as Division) && (
              <option value={details.division}>{details.division}</option>
            )}
          </select>
          <div className="text-[10px] text-fg-muted/80 mt-1 leading-snug">
            Model/cost tier (like a weight class). The LLM gateway enforces it:
            <span className="block">
              <span className="text-amber-dim">featherweight</span> — small/cheap models only (default)
            </span>
            <span className="block">
              <span className="text-amber-dim">middleweight</span> — mainstream cloud, capped tokens/tick
            </span>
            <span className="block">
              <span className="text-amber-dim">heavyweight</span> — anything (e.g. Opus); limited slots
            </span>
          </div>
        </label>
      </div>
      <label className="text-xs text-fg-muted block">
        <div className="mb-1">
          bio{" "}
          <span className="text-[10px] opacity-70">
            — short character voice; the model reads it verbatim as persona context
          </span>
        </div>
        <textarea
          value={details.bio}
          onChange={(e) => patch("bio", e.target.value)}
          onFocus={clearOnFocusIfPlaceholder("bio")}
          placeholder="A short bio in the hero's own voice..."
          rows={5}
          className="w-full bg-bg border border-border px-2 py-1 text-sm font-mono"
        />
      </label>
    </div>
  );
}
