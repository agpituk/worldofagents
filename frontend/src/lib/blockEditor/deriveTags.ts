// Auto-tag derivation for the master-detail item list. Tags come from
// VerbSpec.category — no schema change. The right pane's Blockly view
// is authoritative for editing; this is presentation only.

import type {
  ManifestAbility,
  ManifestComposite,
  ManifestOverride,
  ManifestReflex,
  ManifestStep,
} from "./types";
import { VERB_BY_NAME } from "./verbSpec";

function categoryOf(verb: unknown): string | null {
  if (typeof verb !== "string") return null;
  return VERB_BY_NAME[verb]?.category ?? null;
}

function categoriesInSteps(steps: ManifestStep[] | undefined): string[] {
  const out: string[] = [];
  if (!Array.isArray(steps)) return out;
  for (const s of steps) {
    if (typeof (s as any).do === "string") {
      const c = categoryOf((s as any).do);
      if (c) out.push(c);
    }
    if (Array.isArray((s as any).then)) out.push(...categoriesInSteps((s as any).then));
    if (Array.isArray((s as any).else)) out.push(...categoriesInSteps((s as any).else));
  }
  return out;
}

export function tagsForReflex(rx: ManifestReflex): string[] {
  const c = categoryOf((rx.then as any)?.do);
  return c ? [c] : [];
}

export function tagsForTool(tool: ManifestComposite | ManifestOverride): string[] {
  if ("override" in tool && tool.override) {
    const c = categoryOf(tool.override);
    return c ? [c] : [];
  }
  if ("steps" in tool) {
    return Array.from(new Set(categoriesInSteps(tool.steps)));
  }
  return [];
}

export function tagsForAbility(a: ManifestAbility): string[] {
  return Array.from(new Set(categoriesInSteps(a.steps)));
}
