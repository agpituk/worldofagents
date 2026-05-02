// Composite + override tool containers, plus param_def.

import * as Blockly from "blockly/core";
import { VERB_SPECS } from "../verbSpec";

export function registerToolBlocks(): void {
  // tool_composite — Shape B in GRAMMAR.md §0.
  Blockly.Blocks["tool_composite"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput()
        .appendField("composite tool")
        .appendField(new Blockly.FieldTextInput("composite_name"), "NAME");
      this.appendDummyInput()
        .appendField("description")
        .appendField(new Blockly.FieldTextInput("Composite description for the LLM"), "DESCRIPTION");
      this.appendStatementInput("PARAMETERS").setCheck("ParamDef").appendField("parameters");
      this.appendStatementInput("STEPS").setCheck(["Action", "StepListItem"]).appendField("steps");
      this.setColour(280);
      this.setTooltip(
        "User-defined composite tool exposed to the LLM. The description " +
          "is what the model sees in its tool list.",
      );
    },
  };

  // tool_override — Shape A in GRAMMAR.md §0. Verb is text input (so
  // unknown verbs round-trip), but the tooltip hints at the clampable
  // params for whatever verb is currently set, refreshed on field change.
  Blockly.Blocks["tool_override"] = {
    init(this: Blockly.Block) {
      const block = this;
      const tipFor = (verb: string): string => {
        const spec = VERB_SPECS.find((v) => v.verb === verb);
        if (!spec) {
          return (
            `Override an existing primitive verb. ` +
            `Verb "${verb}" not in catalog — server validator will check.`
          );
        }
        if (spec.clampable.length === 0) {
          return (
            `Override ${spec.verb}. ` +
            `No clampable params; only description / when / after are useful.`
          );
        }
        return (
          `Override ${spec.verb}. Clampable params: ${spec.clampable.join(", ")}. ` +
          `Add clamp_param blocks under "clamp".`
        );
      };
      const verbField = new Blockly.FieldTextInput("verb", function (newValue) {
        // Refresh tooltip whenever the verb changes.
        block.setTooltip(tipFor(String(newValue)));
        return newValue;
      });
      this.appendDummyInput()
        .appendField("override")
        .appendField(verbField, "VERB");
      this.appendDummyInput()
        .appendField("description")
        .appendField(new Blockly.FieldTextInput(""), "DESCRIPTION");
      this.appendStatementInput("WHEN").setCheck("WhenSlot").appendField("when (optional)");
      this.appendStatementInput("CLAMP").setCheck("ClampSlot").appendField("clamp (optional)");
      this.appendStatementInput("AFTER").setCheck(["Action", "StepListItem"]).appendField("after");
      this.setColour(0);
      this.setTooltip(tipFor("verb"));
    },
  };

  // param_def — describes one composite parameter.
  Blockly.Blocks["param_def"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput()
        .appendField("param")
        .appendField(new Blockly.FieldTextInput("name"), "NAME")
        .appendField(":")
        .appendField(
          new Blockly.FieldDropdown([
            ["int", "int"], ["float", "float"], ["string", "string"], ["bool", "bool"],
            ["slug", "slug"], ["npc_slug", "npc_slug"], ["zone_slug", "zone_slug"],
            ["item_slug", "item_slug"], ["spell_slug", "spell_slug"], ["tile", "tile"],
          ]),
          "TYPE",
        )
        .appendField("required:")
        .appendField(
          new Blockly.FieldDropdown([
            ["yes", "true"],
            ["no", "false"],
          ]),
          "REQUIRED",
        )
        .appendField("default:")
        .appendField(new Blockly.FieldTextInput(""), "DEFAULT");
      this.setPreviousStatement(true, "ParamDef");
      this.setNextStatement(true, "ParamDef");
      this.setColour(310);
      this.setTooltip("Composite parameter declaration");
    },
  };
}
