// Control-flow + override-grammar blocks. Phase 4 of the rollout.

import * as Blockly from "blockly/core";

export function registerControlBlocks(): void {
  // if_step — full form (then/else)
  Blockly.Blocks["if_step_full"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("COND").setCheck(["Bool", "Any"]).appendField("if");
      this.appendStatementInput("THEN").setCheck(["Action", "StepListItem"]).appendField("then");
      this.appendStatementInput("ELSE").setCheck(["Action", "StepListItem"]).appendField("else");
      this.setPreviousStatement(true, ["Action", "StepListItem"]);
      this.setNextStatement(true, ["Action", "StepListItem"]);
      this.setColour(290);
      this.setTooltip("Conditional step: take 'then' if true, 'else' otherwise.");
    },
  };

  // if_step — simple form (single 'do' if true)
  Blockly.Blocks["if_step_simple"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("COND").setCheck(["Bool", "Any"]).appendField("if");
      this.appendStatementInput("DO").setCheck(["Action", "StepListItem"]).appendField("do");
      this.setPreviousStatement(true, ["Action", "StepListItem"]);
      this.setNextStatement(true, ["Action", "StepListItem"]);
      this.setColour(290);
      this.setTooltip("Run a step only if the condition is true.");
    },
  };

  // when_gate — slot inside tool_override; condition the dispatcher
  // evaluates before the primitive runs.
  Blockly.Blocks["when_gate"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("COND").setCheck(["Bool", "Any"]).appendField("when");
      this.setPreviousStatement(true, "WhenSlot");
      this.setNextStatement(true, "WhenSlot");
      this.setColour(0);
      this.setTooltip(
        "Boolean gate evaluated before the override's primitive runs. " +
          "False → call is blocked.",
      );
    },
  };

  // clamp_param — one entry in the override's clamp:{} map. Stackable.
  Blockly.Blocks["clamp_param"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput()
        .appendField("clamp")
        .appendField(new Blockly.FieldTextInput("param_name"), "NAME");
      this.appendValueInput("EXPR").setCheck(["Any", "Number", "String"]).appendField("=");
      this.setPreviousStatement(true, "ClampSlot");
      this.setNextStatement(true, "ClampSlot");
      this.setColour(20);
      this.setTooltip(
        "Per-parameter clamp expression. `requested` and `param('x')` " +
          "are bound for this expression.",
      );
    },
  };
}
