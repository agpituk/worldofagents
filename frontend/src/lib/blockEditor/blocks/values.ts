// Value blocks — literals, hero-state refs, arithmetic, math helpers.
//
// Slot types follow `types.ts` SlotType. The Blockly shapes here use
// String/Number/Bool checks so they slot into condition / action arg
// inputs without surprises.

import * as Blockly from "blockly/core";
import { HERO_SCALARS, OVERRIDE_HELPERS } from "../verbSpec";

export function registerValueBlocks(): void {
  Blockly.Blocks["int_literal"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput().appendField(new Blockly.FieldNumber(0, -1e6, 1e6, 1), "VALUE");
      this.setOutput(true, ["Number", "Any"]);
      this.setColour(210);
      this.setTooltip("Integer literal");
    },
  };

  Blockly.Blocks["float_literal"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput().appendField(new Blockly.FieldNumber(0), "VALUE");
      this.setOutput(true, ["Number", "Any"]);
      this.setColour(210);
      this.setTooltip("Number literal");
    },
  };

  Blockly.Blocks["str_literal"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput()
        .appendField('"')
        .appendField(new Blockly.FieldTextInput(""), "VALUE")
        .appendField('"');
      this.setOutput(true, ["String", "Slug", "Any"]);
      this.setColour(160);
      this.setTooltip("String literal");
    },
  };

  Blockly.Blocks["bool_literal"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput().appendField(
        new Blockly.FieldDropdown([
          ["true", "True"],
          ["false", "False"],
        ]),
        "VALUE",
      );
      this.setOutput(true, ["Bool", "Any"]);
      this.setColour(120);
      this.setTooltip("Boolean literal");
    },
  };

  Blockly.Blocks["var_ref"] = {
    init(this: Blockly.Block) {
      const choices: [string, string][] = HERO_SCALARS.map((s) => [s, s]);
      this.appendDummyInput().appendField(new Blockly.FieldDropdown(choices), "NAME");
      this.setOutput(true, ["Number", "String", "Any"]);
      this.setColour(180);
      this.setTooltip("Hero state scalar from build_context()");
    },
  };

  Blockly.Blocks["arith"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("LEFT").setCheck(["Number", "Any"]);
      this.appendDummyInput().appendField(
        new Blockly.FieldDropdown([
          ["+", "+"], ["−", "-"], ["×", "*"], ["÷", "/"],
          ["// (floor)", "//"], ["% (mod)", "%"], ["**", "**"],
        ]),
        "OP",
      );
      this.appendValueInput("RIGHT").setCheck(["Number", "Any"]);
      this.setOutput(true, ["Number", "Any"]);
      this.setInputsInline(true);
      this.setColour(230);
      this.setTooltip("Arithmetic operation");
    },
  };

  Blockly.Blocks["min_max"] = {
    init(this: Blockly.Block) {
      const choices: [string, string][] = OVERRIDE_HELPERS.map((h) => [h.name, h.name]);
      this.appendDummyInput().appendField(new Blockly.FieldDropdown(choices), "FN");
      this.appendValueInput("ARG0").setCheck(["Number", "Any"]);
      this.appendValueInput("ARG1").setCheck(["Number", "Any"]);
      this.appendValueInput("ARG2").setCheck(["Number", "Any"]);
      this.setOutput(true, ["Number", "Any"]);
      this.setInputsInline(true);
      this.setColour(230);
      this.setTooltip("min(a,b) / max(a,b) / clamp(x,lo,hi) / floor / ceil / abs / len");
    },
  };

  Blockly.Blocks["raw_expression"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput()
        .appendField("raw expr")
        .appendField(new Blockly.FieldTextInput(""), "SOURCE");
      this.setOutput(true, ["Any", "Bool", "Number", "String"]);
      this.setColour(0);
      this.setTooltip(
        "Fallback for expressions the parser can't represent as blocks. " +
          "Stored verbatim; the server still validates it.",
      );
    },
  };
}
