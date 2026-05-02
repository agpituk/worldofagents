// Idempotent block-kind registration. Importing this once is enough.

import { registerAbilityBlocks } from "./abilities";
import { registerActionBlocks } from "./actions";
import { registerConditionBlocks } from "./conditions";
import { registerControlBlocks } from "./control";
import { registerReflexBlocks } from "./reflex";
import { registerToolBlocks } from "./tools";
import { registerValueBlocks } from "./values";

let registered = false;

export function registerAllBlocks(): void {
  if (registered) return;
  registered = true;
  registerValueBlocks();
  registerConditionBlocks();
  registerActionBlocks();
  registerControlBlocks();
  registerReflexBlocks();
  registerAbilityBlocks();
  registerToolBlocks();
}
