// Toolbox structure for the Blockly workspace.
//
// Categorized so the toolbox is discoverable. Action blocks are
// auto-listed by category from VERB_SPECS so adding a verb to the
// canonical spec is a one-line change.

import { REFLEX_HELPERS, VERB_SPECS } from "./verbSpec";
import { VerbCategory } from "./types";

const CATEGORY_LABELS: Record<VerbCategory, string> = {
  combat: "Combat",
  movement: "Movement",
  items: "Items",
  social: "Social",
  economy: "Economy",
  magic: "Magic",
  memory: "Memory",
  quest: "Quests",
  trade: "Trade",
  special: "Special",
};

const CATEGORY_COLORS: Record<VerbCategory, string> = {
  combat: "#cc4444",
  movement: "#4488cc",
  items: "#cc9944",
  social: "#cc44cc",
  economy: "#cc7733",
  magic: "#7744cc",
  memory: "#44aacc",
  quest: "#44cc44",
  trade: "#ccaa44",
  special: "#cc44aa",
};

type Block = { kind: "block"; type: string };
type Category = {
  kind: "category";
  name: string;
  colour?: string;
  contents: (Block | Category)[];
};
export type ToolboxDef = {
  kind: "categoryToolbox";
  contents: (Block | Category)[];
};

function block(type: string): Block {
  return { kind: "block", type };
}

function actionsByCategory(): Category[] {
  const grouped = new Map<VerbCategory, Block[]>();
  for (const v of VERB_SPECS) {
    if (!grouped.has(v.category)) grouped.set(v.category, []);
    grouped.get(v.category)!.push(block(`verb_${v.verb}`));
  }
  const out: Category[] = [];
  for (const [cat, blocks] of grouped) {
    out.push({
      kind: "category",
      name: CATEGORY_LABELS[cat],
      colour: CATEGORY_COLORS[cat],
      contents: blocks,
    });
  }
  return out;
}

export const TOOLBOX: ToolboxDef = {
  kind: "categoryToolbox",
  contents: [
    {
      kind: "category",
      name: "Reflexes",
      colour: "#aaaa44",
      contents: [block("reflex")],
    },
    {
      kind: "category",
      name: "Abilities",
      colour: "#cc8844",
      contents: [block("ability")],
    },
    {
      kind: "category",
      name: "Tools",
      colour: "#cc44cc",
      contents: [
        block("tool_composite"),
        block("tool_override"),
        block("param_def"),
        block("when_gate"),
        block("clamp_param"),
        block("do_composite"),
      ],
    },
    {
      kind: "category",
      name: "Conditions",
      colour: "#44aa44",
      contents: [
        block("cmp"),
        block("bool_and"),
        block("bool_or"),
        block("bool_not"),
        block("in_op"),
        block("args_ref"),
        block("requested_ref"),
        ...REFLEX_HELPERS.map((h) => block(`helper_${h.name}`)),
      ],
    },
    {
      kind: "category",
      name: "Values",
      colour: "#4488aa",
      contents: [
        block("int_literal"),
        block("float_literal"),
        block("str_literal"),
        block("bool_literal"),
        block("var_ref"),
        block("arith"),
        block("min_max"),
        block("raw_expression"),
      ],
    },
    {
      kind: "category",
      name: "Control",
      colour: "#aa44cc",
      contents: [block("if_step_simple"), block("if_step_full")],
    },
    ...actionsByCategory(),
  ],
};
