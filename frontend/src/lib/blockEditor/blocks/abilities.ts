// Ability container — `abilities: { name: { steps: [...] } }`.
//
// Abilities are shorthand for multi-step plans the reflex layer can
// emit via `{do: <ability_name>}`. The runtime queues the steps and
// dispatches one primitive per tick.

import * as Blockly from "blockly/core";

export function registerAbilityBlocks(): void {
  Blockly.Blocks["ability"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput()
        .appendField("ability")
        .appendField(new Blockly.FieldTextInput("ability_name"), "NAME");
      this.appendStatementInput("STEPS").setCheck(["Action", "StepListItem"]).appendField("steps");
      this.setColour(40);
      this.setTooltip(
        "Multi-step ability. A reflex emits {do: <name>} and the runtime " +
          "queues these steps (one primitive per tick).",
      );
    },
  };
}
