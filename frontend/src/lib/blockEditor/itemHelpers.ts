// Pure helpers for the master-detail block editor: deriving display
// labels, building stub items for "+ new", swapping a single item in
// or out of a `ParsedManifest` for the single-item Blockly canvas, and
// mapping validation paths back to selectable items.
//
// No React, no Blockly imports — keeps the orchestrator component
// small and lets these be unit-tested in isolation.

import type {
  ManifestAbility,
  ManifestComposite,
  ManifestOverride,
  ManifestReflex,
  ParsedManifest,
} from "./types";
import { workspaceToManifest } from "./blocksToYaml";
import { VERB_BY_NAME } from "./verbSpec";

// ---------------------------------------------------------------------------
// Selection / kind types — shared between the orchestrator and the row
// components. Co-located here so subcomponents don't all import from
// `BlockEditor.tsx`.
// ---------------------------------------------------------------------------

export type Tab = "reflexes" | "tools" | "abilities";

export type Selection =
  | { kind: "reflex"; index: number }
  | { kind: "tool"; index: number }
  | { kind: "ability"; name: string };

export type ValidationIssue = { severity: string; message: string; path?: string };

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

export function reflexLabel(rx: ManifestReflex): string {
  const w = (rx.when ?? "").trim();
  if (!w) return "(no condition)";
  return w.length > 48 ? w.slice(0, 47) + "…" : w;
}

export function toolLabel(tool: ManifestComposite | ManifestOverride): string {
  const name = (tool as any).name || "(unnamed)";
  if ("override" in tool && tool.override) return `${name} → ${tool.override}`;
  return name;
}

export function reflexVerb(rx: ManifestReflex): string {
  const v = (rx.then as any)?.do;
  return typeof v === "string" ? v : "?";
}

export function reflexVerbDescription(rx: ManifestReflex): string {
  const v = (rx.then as any)?.do;
  if (typeof v !== "string") return "";
  return VERB_BY_NAME[v]?.description ?? "";
}

// Trivially-true reflex condition. These are the catch-all / fallback
// reflexes — they always match, so they only fire when no earlier
// (higher-priority) rule did.
export function isCatchAll(rx: ManifestReflex): boolean {
  const w = (rx.when ?? "").trim().toLowerCase();
  return w === "true" || w === "1" || w === "";
}

// ---------------------------------------------------------------------------
// Stub item creation (+ new …)
// ---------------------------------------------------------------------------

export function uniqueName(base: string, taken: Set<string>): string {
  if (!taken.has(base)) return base;
  let i = 2;
  while (taken.has(`${base}_${i}`)) i++;
  return `${base}_${i}`;
}

export function newReflex(): ManifestReflex {
  return { when: "true", then: { do: "wait" } };
}

export function newTool(parsed: ParsedManifest): ManifestComposite {
  const taken = new Set(parsed.tools.map((t: any) => t.name).filter(Boolean));
  return {
    name: uniqueName("new_tool", taken),
    description: "",
    steps: [{ do: "wait" }],
  };
}

export function newAbility(parsed: ParsedManifest): { name: string; spec: ManifestAbility } {
  const taken = new Set(Object.keys(parsed.abilities));
  return { name: uniqueName("new_ability", taken), spec: { steps: [{ do: "wait" }] } };
}

// ---------------------------------------------------------------------------
// Single-item ↔ full manifest splicing
// ---------------------------------------------------------------------------

// Build a ParsedManifest containing only the selected item — fed to
// `manifestToWorkspace` so Blockly renders just that item.
export function singleItemManifest(parsed: ParsedManifest, sel: Selection): ParsedManifest | null {
  const empty: ParsedManifest = { reflexes: [], abilities: {}, tools: [], extras: {} };
  if (sel.kind === "reflex") {
    const rx = parsed.reflexes[sel.index];
    if (!rx) return null;
    return { ...empty, reflexes: [rx] };
  }
  if (sel.kind === "tool") {
    const t = parsed.tools[sel.index];
    if (!t) return null;
    return { ...empty, tools: [t] };
  }
  const a = parsed.abilities[sel.name];
  if (!a) return null;
  return { ...empty, abilities: { [sel.name]: a } };
}

// Splice the (one-item) workspace result back into the full parsed model.
export function spliceItem(
  prev: ParsedManifest,
  sel: Selection,
  partial: ReturnType<typeof workspaceToManifest>,
): ParsedManifest {
  // workspaceToManifest returns either a {hero: body} envelope or a
  // bare body, depending on extras. Since we passed `{}` for extras,
  // the result is the body itself.
  const body = (partial as any).hero ?? partial;
  if (sel.kind === "reflex") {
    const rxs = Array.isArray(body.reflexes) ? body.reflexes : [];
    if (rxs.length === 0) return prev;
    const reflexes = [...prev.reflexes];
    // Preserve `disabled` and any other extras on the original entry —
    // Blockly's serializer only knows {when, then}.
    const original = prev.reflexes[sel.index] || {};
    reflexes[sel.index] = { ...original, ...rxs[0] };
    return { ...prev, reflexes };
  }
  if (sel.kind === "tool") {
    const ts = Array.isArray(body.tools) ? body.tools : [];
    if (ts.length === 0) return prev;
    const tools = [...prev.tools];
    tools[sel.index] = ts[0];
    return { ...prev, tools };
  }
  const abs = body.abilities ?? {};
  // The user might have renamed the ability inside the block (its
  // NAME field is what becomes the key). Pick whatever single key
  // came back — that becomes the new key, replacing the old.
  const keys = Object.keys(abs);
  if (keys.length === 0) return prev;
  const newName = keys[0];
  const next: ParsedManifest = {
    ...prev,
    abilities: { ...prev.abilities },
  };
  delete next.abilities[sel.name];
  next.abilities[newName] = abs[newName];
  return next;
}

// ---------------------------------------------------------------------------
// Path / selection helpers (validation issues → master-list rows)
// ---------------------------------------------------------------------------

export function pathToItemKey(path: string): string | null {
  const r = path.match(/^reflexes\[(\d+)\]/);
  if (r) return `reflexes[${r[1]}]`;
  const t = path.match(/^tools\[(\d+)\]/);
  if (t) return `tools[${t[1]}]`;
  const a = path.match(/^abilities\.([a-zA-Z0-9_]+)/);
  if (a) return `abilities.${a[1]}`;
  return null;
}

export function issuePathMatchesSelection(path: string, sel: Selection): boolean {
  const key = pathToItemKey(path);
  if (!key) return false;
  if (sel.kind === "reflex") return key === `reflexes[${sel.index}]`;
  if (sel.kind === "tool") return key === `tools[${sel.index}]`;
  return key === `abilities.${sel.name}`;
}

export function describeSelection(parsed: ParsedManifest, sel: Selection): string {
  if (sel.kind === "reflex") {
    const rx = parsed.reflexes[sel.index];
    return rx ? `reflex #${sel.index + 1} — ${reflexLabel(rx)}` : `reflex #${sel.index + 1}`;
  }
  if (sel.kind === "tool") {
    const t = parsed.tools[sel.index];
    return t ? `tool — ${toolLabel(t)}` : "tool";
  }
  return `ability — ${sel.name}`;
}
