// Action blocks — one per VERB_SPECS entry. Generated from the
// canonical verb spec so we don't hand-maintain 44 block definitions.
//
// Each verb's params get typed slots:
//   slug      → Slug
//   string    → String
//   int/float → Number
//   bool      → Bool
//   tile      → Tile  (a list of two ints)
//   list_string → ListString
//
// "Statement"-style: action blocks are stackable steps (previous/next
// connections). The top-level reflex container provides one slot for
// a single action. Composite/ability `steps:` lists accept stacks.

import * as Blockly from "blockly/core";
import { ParamSpec, VerbSpec } from "../types";
import { VERB_SPECS } from "../verbSpec";

const TYPE_TO_CHECK: Record<ParamSpec["type"], string[]> = {
  int: ["Number", "Any"],
  float: ["Number", "Any"],
  string: ["String", "Slug", "Any"],
  bool: ["Bool", "Any"],
  slug: ["Slug", "String", "Any"],
  list_string: ["ListString", "Any"],
  tile: ["Tile", "Any"],
};

export function registerActionBlocks(): void {
  for (const v of VERB_SPECS) {
    Blockly.Blocks[`verb_${v.verb}`] = { init: makeBlockInit(v) };
  }

  // do_composite — live dropdown of composite tool names defined in the
  // current workspace. Falls back to a free-text input if no composites
  // exist (so the block is always placeable from the toolbox).
  Blockly.Blocks["do_composite"] = {
    init(this: Blockly.Block) {
      const block = this;
      const generateOptions = (): [string, string][] => {
        const ws = block.workspace;
        if (!ws) return [["composite_name", "composite_name"]];
        const composites: [string, string][] = [];
        for (const b of ws.getAllBlocks(false)) {
          if (b.type === "tool_composite" && b.id !== block.id) {
            const name = b.getFieldValue("NAME");
            if (typeof name === "string" && name) {
              composites.push([name, name]);
            }
          }
        }
        if (composites.length === 0) return [["(no composites yet)", ""]];
        return composites;
      };
      this.appendDummyInput()
        .appendField("do composite")
        .appendField(new Blockly.FieldDropdown(generateOptions), "NAME");
      this.setPreviousStatement(true, ["Action", "StepListItem"]);
      this.setNextStatement(true, ["Action", "StepListItem"]);
      this.setColour(40);
      this.setTooltip(
        "Call another composite tool defined in this manifest. " +
          "Dropdown updates live as you add/rename composites.",
      );
    },
  };

  // raw_action — fallback for action shapes the verb spec doesn't
  // know about. Stores the do-name + a JSON args blob; round-trips
  // verbatim. Keeps the editor tolerant of manifests that include
  // verbs we haven't catalogued yet.
  Blockly.Blocks["raw_action"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput()
        .appendField("raw")
        .appendField(new Blockly.FieldTextInput("do_name"), "DO");
      this.appendDummyInput()
        .appendField("args (JSON)")
        .appendField(new Blockly.FieldTextInput("{}"), "ARGS_JSON");
      this.setPreviousStatement(true, ["Action", "StepListItem"]);
      this.setNextStatement(true, ["Action", "StepListItem"]);
      this.setColour(0);
      this.setTooltip("Raw action with JSON args (fallback for unknown verbs)");
    },
  };
}

function makeBlockInit(v: VerbSpec) {
  return function (this: Blockly.Block) {
    this.appendDummyInput().appendField(v.verb);
    for (const p of v.params) {
      const input = this.appendValueInput(p.name.toUpperCase()).setCheck(TYPE_TO_CHECK[p.type]);
      input.appendField(p.name + (p.optional ? "?" : "") + ":");
    }
    this.setPreviousStatement(true, ["Action", "StepListItem"]);
    this.setNextStatement(true, ["Action", "StepListItem"]);
    this.setInputsInline(true);
    this.setColour(colorForCategory(v.category));
    this.setTooltip(v.description);
  };
}

function colorForCategory(c: VerbSpec["category"]): number {
  switch (c) {
    case "combat":   return 0;
    case "movement": return 200;
    case "items":    return 60;
    case "social":   return 280;
    case "economy":  return 30;
    case "magic":    return 260;
    case "memory":   return 180;
    case "quest":    return 100;
    case "trade":    return 20;
    case "special":  return 320;
  }
}
