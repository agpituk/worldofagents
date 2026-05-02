// Boolean / comparison / helper blocks for the expression DSL.

import * as Blockly from "blockly/core";
import { REFLEX_HELPERS } from "../verbSpec";

export function registerConditionBlocks(): void {
  Blockly.Blocks["cmp"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("LEFT").setCheck(["Number", "String", "Bool", "Any"]);
      this.appendDummyInput().appendField(
        new Blockly.FieldDropdown([
          ["==", "=="], ["≠", "!="], ["<", "<"], ["≤", "<="], [">", ">"], ["≥", ">="],
        ]),
        "OP",
      );
      this.appendValueInput("RIGHT").setCheck(["Number", "String", "Bool", "Any"]);
      this.setOutput(true, ["Bool", "Any"]);
      this.setInputsInline(true);
      this.setColour(120);
      this.setTooltip("Comparison");
    },
  };

  Blockly.Blocks["bool_and"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("LEFT").setCheck(["Bool", "Any"]);
      this.appendDummyInput().appendField("and");
      this.appendValueInput("RIGHT").setCheck(["Bool", "Any"]);
      this.setOutput(true, ["Bool", "Any"]);
      this.setInputsInline(true);
      this.setColour(120);
    },
  };

  Blockly.Blocks["bool_or"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("LEFT").setCheck(["Bool", "Any"]);
      this.appendDummyInput().appendField("or");
      this.appendValueInput("RIGHT").setCheck(["Bool", "Any"]);
      this.setOutput(true, ["Bool", "Any"]);
      this.setInputsInline(true);
      this.setColour(120);
    },
  };

  Blockly.Blocks["bool_not"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput().appendField("not");
      this.appendValueInput("VALUE").setCheck(["Bool", "Any"]);
      this.setOutput(true, ["Bool", "Any"]);
      this.setInputsInline(true);
      this.setColour(120);
    },
  };

  Blockly.Blocks["in_op"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("ITEM").setCheck(["Any"]);
      this.appendDummyInput().appendField(
        new Blockly.FieldDropdown([
          ["in", "in"],
          ["not in", "not in"],
        ]),
        "OP",
      );
      this.appendValueInput("LIST").setCheck(["Any"]);
      this.setOutput(true, ["Bool", "Any"]);
      this.setInputsInline(true);
      this.setColour(120);
    },
  };

  Blockly.Blocks["args_ref"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput()
        .appendField("args.")
        .appendField(new Blockly.FieldTextInput("name"), "NAME");
      this.setOutput(true, ["Any", "String", "Number", "Bool"]);
      this.setColour(290);
      this.setTooltip("Read a tool parameter by name (composite/override only)");
    },
  };

  Blockly.Blocks["requested_ref"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput().appendField("requested");
      this.setOutput(true, ["Any", "String", "Number"]);
      this.setColour(290);
      this.setTooltip("The LLM's proposed value for this clamp parameter");
    },
  };

  // One helper_call_<name> block per reflex helper. Arity 0 / 1 only.
  for (const helper of REFLEX_HELPERS) {
    const blockType = `helper_${helper.name}`;
    Blockly.Blocks[blockType] = {
      init(this: Blockly.Block) {
        if (helper.arity === 0) {
          this.appendDummyInput().appendField(`${helper.name}()`);
        } else {
          this.appendDummyInput().appendField(`${helper.name}(`);
          this.appendValueInput("ARG0").setCheck(["Any", "String", "Slug"]);
          this.appendDummyInput().appendField(")");
        }
        this.setOutput(true, ["Bool", "Any"]);
        this.setInputsInline(true);
        this.setColour(140);
        this.setTooltip(helper.description);
      },
    };
  }
}
