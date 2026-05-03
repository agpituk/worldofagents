// ParsedManifest → YAML. Mirrors the reassembly logic at the tail of
// `workspaceToManifest` (blocksToYaml.ts) so the master-detail editor
// can serialize state changes (drag-reorder, +new, delete, disabled
// toggle) without a round-trip through Blockly.

import yaml from "js-yaml";
import type { ParsedManifest } from "./types";

const TOP_LEVEL_ORDER = [
  "name", "author", "division", "bio", "build",
  "models", "model", "system", "reflexes", "abilities", "tools", "memory", "budget",
];

export function parsedToYaml(parsed: ParsedManifest): string {
  const heroBody: Record<string, unknown> = {};
  for (const k of TOP_LEVEL_ORDER) {
    if (k === "reflexes") {
      if (parsed.reflexes.length > 0) heroBody.reflexes = parsed.reflexes;
    } else if (k === "abilities") {
      if (Object.keys(parsed.abilities).length > 0) heroBody.abilities = parsed.abilities;
    } else if (k === "tools") {
      if (parsed.tools.length > 0) heroBody.tools = parsed.tools;
    } else if (k in parsed.extras) {
      heroBody[k] = parsed.extras[k];
    }
  }
  for (const [k, v] of Object.entries(parsed.extras)) {
    if (k.startsWith("__")) continue;
    if (!(k in heroBody) && !TOP_LEVEL_ORDER.includes(k)) {
      heroBody[k] = v;
    }
  }
  const out: Record<string, unknown> = {};
  if (parsed.extras.__manifest_version !== undefined) {
    out.manifest_version = parsed.extras.__manifest_version;
  }
  if (parsed.extras.__hero_wrapped) {
    out.hero = heroBody;
  } else {
    Object.assign(out, heroBody);
  }
  return yaml.dump(out, { noRefs: true, sortKeys: false, lineWidth: 100 });
}
