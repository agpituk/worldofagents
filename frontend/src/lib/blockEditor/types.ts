// Type contracts shared across the block editor.
//
// The split: yamlToBlocks/blocksToYaml deal in `BlockTree` (a plain JSON
// shape derived from Blockly's serializer), while the Blockly runtime
// works with its native workspace state. We use Blockly's own
// JSON-serialization format for in-memory persistence; BlockTree wraps
// that so the parser/serializer aren't coupled to Blockly internals.

export type SlotType =
  | "Bool"
  | "Number"
  | "String"
  | "Slug"
  | "Tile"
  | "Action"
  | "StepListItem"
  | "ParamDef"
  | "ListString"
  | "Any";

export type ParamSpec = {
  name: string;
  type: "int" | "float" | "string" | "bool" | "slug" | "list_string" | "tile";
  optional?: boolean;
  description?: string;
};

export type VerbSpec = {
  verb: string;
  category: VerbCategory;
  description: string;
  params: ParamSpec[];
  // Names of params that the override grammar can `clamp:` per the
  // server-side clamp_table; populated by the build script.
  clampable: string[];
};

export type VerbCategory =
  | "combat"
  | "movement"
  | "items"
  | "social"
  | "economy"
  | "magic"
  | "memory"
  | "quest"
  | "trade"
  | "special";

// One reflex / step / tool entry in normalized form. All other shapes
// in this module derive from these.
export type ManifestReflex = {
  when: string;
  then: Record<string, unknown>;
};

export type ManifestStep =
  | { do: string; args?: Record<string, unknown> }
  | { if: string; do: string; args?: Record<string, unknown> }
  | { if: string; then: ManifestStep[]; else?: ManifestStep[] };

export type ManifestParameter = {
  name: string;
  type: ParamSpec["type"] | "npc_slug" | "zone_slug" | "item_slug" | "spell_slug";
  required?: boolean;
  default?: unknown;
};

export type ManifestComposite = {
  name: string;
  description: string;
  parameters?: ManifestParameter[];
  steps: ManifestStep[];
};

export type ManifestOverride = {
  name?: string;
  override: string;
  description?: string;
  when?: string;
  clamp?: Record<string, string>;
  after?: ManifestStep[];
};

export type ManifestAbility = {
  steps: ManifestStep[];
};

export type ParsedManifest = {
  reflexes: ManifestReflex[];
  abilities: Record<string, ManifestAbility>;
  tools: Array<ManifestComposite | ManifestOverride>;
  // Anything else round-trips verbatim under `extras`.
  extras: Record<string, unknown>;
};
