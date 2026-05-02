// Composite + override tool containers, plus param_def.

import * as Blockly from "blockly/core";

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

  // tool_override — Shape A in GRAMMAR.md §0. The verb being overridden
  // is a free-text field for v1; a future improvement hooks into the
  // verb spec to render a dropdown.
  Blockly.Blocks["tool_override"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput()
        .appendField("override")
        .appendField(new Blockly.FieldTextInput("verb"), "VERB");
      this.appendDummyInput()
        .appendField("description")
        .appendField(new Blockly.FieldTextInput(""), "DESCRIPTION");
      this.appendStatementInput("WHEN").setCheck("WhenSlot").appendField("when (optional)");
      this.appendStatementInput("CLAMP").setCheck("ClampSlot").appendField("clamp (optional)");
      this.appendStatementInput("AFTER").setCheck(["Action", "StepListItem"]).appendField("after");
      this.setColour(0);
      this.setTooltip(
        "Override the description and/or behavior of an existing primitive verb. " +
          "When/clamp/after are optional but at least one must be set.",
      );
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
