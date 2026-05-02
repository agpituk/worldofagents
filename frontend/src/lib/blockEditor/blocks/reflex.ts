// Top-level reflex container. One slot for the `when:` boolean
// expression and one slot for the action block (`then:`).
//
// The reflex doesn't stack — each reflex is its own top-level block on
// the workspace. The block-tree → YAML serializer collects every
// reflex container into the manifest's `reflexes:` array in the order
// they appear top-to-bottom on the workspace.

import * as Blockly from "blockly/core";

export function registerReflexBlocks(): void {
  Blockly.Blocks["reflex"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("WHEN").setCheck(["Bool", "Any"]).appendField("reflex when");
      this.appendStatementInput("THEN").setCheck(["Action", "StepListItem"]).appendField("then");
      this.setColour(60);
      this.setTooltip(
        "Reflex: evaluated every tick. First reflex whose `when` is true " +
          "fires its action. Free — no LLM call.",
      );
    },
  };
}
