// YAML manifest → Blockly workspace JSON.
//
// Pure: no Blockly runtime dependencies — produces JSON in Blockly's
// own serialization format which the workspace can load via
// `Blockly.serialization.workspaces.load`. Round-trip identity is
// asserted by `__tests__/roundtrip.test.ts`.

import yaml from "js-yaml";
import { parseExpr, ExprNode } from "./exprParser";
import {
  ManifestComposite,
  ManifestOverride,
  ManifestParameter,
  ManifestReflex,
  ManifestStep,
  ParsedManifest,
} from "./types";
import { VERB_BY_NAME, REFLEX_HELPERS } from "./verbSpec";

// Blockly serialization JSON shape.
export type BlockJson = {
  type: string;
  id?: string;
  x?: number;
  y?: number;
  fields?: Record<string, string | number | boolean>;
  inputs?: Record<string, { block?: BlockJson; shadow?: BlockJson }>;
  next?: { block: BlockJson };
};

export type WorkspaceJson = {
  blocks: { languageVersion: number; blocks: BlockJson[] };
};

// ---------------------------------------------------------------------------
// Manifest extraction
// ---------------------------------------------------------------------------

const MANIFEST_NESTED_KEYS = new Set([
  "reflexes", "abilities", "tools",
]);

export function parseManifest(yamlText: string): ParsedManifest {
  let doc: any;
  try {
    doc = yaml.load(yamlText);
  } catch {
    return { reflexes: [], abilities: {}, tools: [], extras: {} };
  }
  if (!doc || typeof doc !== "object") {
    return { reflexes: [], abilities: {}, tools: [], extras: {} };
  }
  const inner = (doc.hero && typeof doc.hero === "object") ? doc.hero : doc;

  const reflexes: ManifestReflex[] = Array.isArray(inner.reflexes) ? inner.reflexes : [];
  const abilities: Record<string, { steps: ManifestStep[] }> = {};
  if (inner.abilities && typeof inner.abilities === "object") {
    for (const [name, spec] of Object.entries(inner.abilities)) {
      if (spec && typeof spec === "object" && Array.isArray((spec as any).steps)) {
        abilities[name] = { steps: (spec as any).steps };
      }
    }
  }
  const tools: Array<ManifestComposite | ManifestOverride> = Array.isArray(inner.tools) ? inner.tools : [];

  const extras: Record<string, unknown> = {};
  // Preserve every non-editor key under hero so we can re-emit the
  // manifest verbatim except for the parts the editor manages.
  for (const [k, v] of Object.entries(inner)) {
    if (MANIFEST_NESTED_KEYS.has(k)) continue;
    extras[k] = v;
  }
  // Preserve the wrapping `hero:` if present.
  if (doc.hero) {
    extras.__hero_wrapped = true;
  }
  if (typeof doc.manifest_version !== "undefined") {
    extras.__manifest_version = doc.manifest_version;
  }
  return { reflexes, abilities, tools, extras };
}

// ---------------------------------------------------------------------------
// Manifest → blocks
// ---------------------------------------------------------------------------

export function manifestToWorkspace(parsed: ParsedManifest): WorkspaceJson {
  const blocks: BlockJson[] = [];
  let nextX = 20;
  let nextY = 20;
  const STEP_X = 380;
  const STEP_Y = 200;

  parsed.reflexes.forEach((rx, i) => {
    const block = reflexToBlock(rx);
    block.id = `reflex_${i}`;
    block.x = nextX;
    block.y = nextY;
    blocks.push(block);
    nextY += STEP_Y;
  });
  // After reflexes column, start abilities below in the same column.
  nextY += 40;
  for (const [name, spec] of Object.entries(parsed.abilities)) {
    const block = abilityToBlock(name, spec.steps);
    block.id = `ability_${name}`;
    block.x = nextX;
    block.y = nextY;
    blocks.push(block);
    nextY += STEP_Y;
  }
  // Tools in a second column.
  nextX += STEP_X;
  nextY = 20;
  parsed.tools.forEach((tool, i) => {
    const block = ("override" in tool && tool.override !== undefined)
      ? overrideToBlock(tool as ManifestOverride)
      : compositeToBlock(tool as ManifestComposite);
    // Stable id matches the YAML path the validator emits, so a server
    // error like "tools[2].clamp.distance" can be mapped back to the
    // tool block at id="tools_2".
    block.id = `tools_${i}`;
    block.x = nextX;
    block.y = nextY;
    blocks.push(block);
    nextY += STEP_Y;
  });

  return {
    blocks: { languageVersion: 0, blocks },
  };
}

// --- Reflexes ---

function reflexToBlock(rx: ManifestReflex): BlockJson {
  const cond = exprToValueBlock(parseExpr(rx.when));
  const thenBlock = thenToActionBlock(rx.then);
  return {
    type: "reflex",
    inputs: {
      WHEN: { block: cond },
      THEN: thenBlock ? { block: thenBlock } : {},
    },
  };
}

// `then:` in a reflex is the legacy single-action shape from
// `actions.py`; convert to a single action block. If it doesn't fit a
// known verb, fall back to `raw_action`.
function thenToActionBlock(then: Record<string, unknown>): BlockJson | null {
  if (!then || typeof then !== "object") return null;
  const verb = then.do;
  if (typeof verb !== "string") return null;
  const known = actionDictToBlock({ do: verb, args: extractArgsFromThen(then) });
  if (known) return known;
  // Unknown verb (e.g., attack_nearest_hostile, move_to_npc — convenience
  // verbs the world resolves but we haven't catalogued in VERB_SPECS).
  // Round-trip via raw_action.
  return rawActionBlock(then);
}

function extractArgsFromThen(then: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(then)) {
    if (k === "do") continue;
    out[k] = v;
  }
  return out;
}

// --- Abilities ---

function abilityToBlock(name: string, steps: ManifestStep[]): BlockJson {
  return {
    type: "ability",
    fields: { NAME: name },
    inputs: {
      STEPS: stepsToInput(steps),
    },
  };
}

// --- Tools ---

function compositeToBlock(c: ManifestComposite): BlockJson {
  return {
    type: "tool_composite",
    fields: { NAME: c.name, DESCRIPTION: c.description },
    inputs: {
      PARAMETERS: parametersToInput(c.parameters || []),
      STEPS: stepsToInput(c.steps),
    },
  };
}

function overrideToBlock(o: ManifestOverride): BlockJson {
  const inputs: BlockJson["inputs"] = {};
  if (o.when) {
    inputs.WHEN = {
      block: {
        type: "when_gate",
        inputs: {
          COND: { block: exprToValueBlock(parseExpr(o.when)) },
        },
      },
    };
  }
  if (o.clamp && Object.keys(o.clamp).length > 0) {
    inputs.CLAMP = clampToInput(o.clamp);
  }
  if (o.after && o.after.length > 0) {
    inputs.AFTER = stepsToInput(o.after);
  }
  return {
    type: "tool_override",
    fields: {
      VERB: o.override,
      DESCRIPTION: o.description || "",
    },
    inputs,
  };
}

function parametersToInput(params: ManifestParameter[]): { block?: BlockJson } {
  if (params.length === 0) return {};
  let head: BlockJson | undefined;
  let cursor: BlockJson | undefined;
  for (const p of params) {
    const block: BlockJson = {
      type: "param_def",
      fields: {
        NAME: p.name,
        TYPE: p.type,
        REQUIRED: (p.required !== false).toString(),
        DEFAULT: p.default == null ? "" : String(p.default),
      },
    };
    if (!head) {
      head = block;
      cursor = head;
    } else if (cursor) {
      cursor.next = { block };
      cursor = block;
    }
  }
  return head ? { block: head } : {};
}

function clampToInput(clamp: Record<string, string>): { block?: BlockJson } {
  const entries = Object.entries(clamp);
  if (entries.length === 0) return {};
  let head: BlockJson | undefined;
  let cursor: BlockJson | undefined;
  for (const [name, expr] of entries) {
    const block: BlockJson = {
      type: "clamp_param",
      fields: { NAME: name },
      inputs: {
        EXPR: { block: exprToValueBlock(parseExpr(expr)) },
      },
    };
    if (!head) {
      head = block;
      cursor = head;
    } else if (cursor) {
      cursor.next = { block };
      cursor = block;
    }
  }
  return head ? { block: head } : {};
}

// --- Steps ---

function stepsToInput(steps: ManifestStep[]): { block?: BlockJson } {
  if (!steps || steps.length === 0) return {};
  let head: BlockJson | undefined;
  let cursor: BlockJson | undefined;
  for (const step of steps) {
    const block = stepToBlock(step);
    if (!block) continue;
    if (!head) {
      head = block;
      cursor = head;
    } else if (cursor) {
      cursor.next = { block };
      cursor = block;
    }
  }
  return head ? { block: head } : {};
}

function stepToBlock(step: ManifestStep): BlockJson | null {
  if (typeof step !== "object" || step === null) return null;
  if ("if" in step && ("then" in step || "else" in step)) {
    const thenBranch = stepsToInput((step as any).then || []);
    const elseBranch = stepsToInput((step as any).else || []);
    return {
      type: "if_step_full",
      inputs: {
        COND: { block: exprToValueBlock(parseExpr((step as any).if)) },
        THEN: thenBranch,
        ELSE: elseBranch,
      },
    };
  }
  if ("if" in step && "do" in step) {
    return {
      type: "if_step_simple",
      inputs: {
        COND: { block: exprToValueBlock(parseExpr((step as any).if)) },
        DO: { block: actionDictToBlock(step as any) || rawActionBlock(step as any) },
      },
    };
  }
  if ("do" in step) {
    return actionDictToBlock(step as any) || rawActionBlock(step as any);
  }
  return null;
}

function actionDictToBlock(step: { do: string; args?: Record<string, unknown> }): BlockJson | null {
  const verb = step.do;
  const spec = VERB_BY_NAME[verb];
  if (!spec) return null;
  const inputs: BlockJson["inputs"] = {};
  const args = step.args || {};
  // Reflex `then:` shapes hold args at the top level too; be tolerant.
  for (const [k, v] of Object.entries(step)) {
    if (k === "do" || k === "args") continue;
    args[k] = v;
  }
  for (const param of spec.params) {
    if (!(param.name in args)) continue;
    inputs[param.name.toUpperCase()] = {
      block: argValueToBlock(args[param.name], param.type),
    };
  }
  return {
    type: `verb_${verb}`,
    inputs,
  };
}

function rawActionBlock(step: any): BlockJson {
  const verb = typeof step.do === "string" ? step.do : "wait";
  const args: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(step)) {
    if (k === "do" || k === "if" || k === "then" || k === "else") continue;
    args[k] = v;
  }
  return {
    type: "raw_action",
    fields: {
      DO: verb,
      ARGS_JSON: JSON.stringify(args),
    },
  };
}

function argValueToBlock(value: unknown, paramType: string): BlockJson {
  // Strings that look like interpolation expressions render as
  // raw_expression so the user can edit them; the parser would
  // mis-consume `{{ ... }}` as garbage.
  if (typeof value === "string" && value.includes("{{")) {
    return { type: "raw_expression", fields: { SOURCE: value } };
  }
  // Typed `_expr:` form.
  if (typeof value === "object" && value !== null && "_expr" in (value as object)) {
    const src = (value as any)._expr;
    return exprToValueBlock(parseExpr(src));
  }
  if (typeof value === "string") {
    return { type: "str_literal", fields: { VALUE: value } };
  }
  if (typeof value === "number") {
    if (Number.isInteger(value)) return { type: "int_literal", fields: { VALUE: value } };
    return { type: "float_literal", fields: { VALUE: value } };
  }
  if (typeof value === "boolean") {
    return { type: "bool_literal", fields: { VALUE: value ? "True" : "False" } };
  }
  if (Array.isArray(value)) {
    // Only [x, y] tile literals get a structured rendering — every
    // other list shape falls back to raw_expression.
    if (paramType === "tile" && value.length === 2 && value.every((n) => typeof n === "number")) {
      return {
        type: "raw_expression",
        fields: { SOURCE: `[${value[0]}, ${value[1]}]` },
      };
    }
    return { type: "raw_expression", fields: { SOURCE: JSON.stringify(value) } };
  }
  return {
    type: "raw_expression",
    fields: { SOURCE: JSON.stringify(value) },
  };
}

// ---------------------------------------------------------------------------
// Expression node → value block
// ---------------------------------------------------------------------------

const HELPER_NAMES = new Set(REFLEX_HELPERS.map((h) => h.name));
const OVERRIDE_HELPER_NAMES = new Set(["min", "max", "clamp", "floor", "ceil", "abs", "len"]);

export function exprToValueBlock(node: ExprNode): BlockJson {
  if (node.kind === "Raw") return { type: "raw_expression", fields: { SOURCE: node.source } };

  if (node.kind === "Const") {
    const v = node.value;
    if (v === null) return { type: "raw_expression", fields: { SOURCE: "None" } };
    if (typeof v === "boolean") {
      return { type: "bool_literal", fields: { VALUE: v ? "True" : "False" } };
    }
    if (typeof v === "string") {
      return { type: "str_literal", fields: { VALUE: v } };
    }
    if (Number.isInteger(v as number)) {
      return { type: "int_literal", fields: { VALUE: v as number } };
    }
    return { type: "float_literal", fields: { VALUE: v as number } };
  }

  if (node.kind === "Name") {
    if (node.id === "requested") return { type: "requested_ref" };
    return { type: "var_ref", fields: { NAME: node.id } };
  }

  if (node.kind === "Attribute") {
    if (node.obj.kind === "Name" && node.obj.id === "args") {
      return { type: "args_ref", fields: { NAME: node.attr } };
    }
    return { type: "raw_expression", fields: { SOURCE: unparseRaw(node) } };
  }

  if (node.kind === "Call") {
    if (HELPER_NAMES.has(node.func)) {
      const blockType = `helper_${node.func}`;
      const inputs: BlockJson["inputs"] = {};
      if (node.args.length > 0) {
        inputs.ARG0 = { block: exprToValueBlock(node.args[0]) };
      }
      return { type: blockType, inputs };
    }
    if (OVERRIDE_HELPER_NAMES.has(node.func)) {
      const inputs: BlockJson["inputs"] = {};
      node.args.forEach((a, i) => {
        inputs[`ARG${i}`] = { block: exprToValueBlock(a) };
      });
      return {
        type: "min_max",
        fields: { FN: node.func },
        inputs,
      };
    }
    if (node.func === "param" && node.args.length === 1) {
      const name = node.args[0];
      if (name.kind === "Const" && typeof name.value === "string") {
        return { type: "args_ref", fields: { NAME: name.value } };
      }
    }
    return { type: "raw_expression", fields: { SOURCE: unparseRaw(node) } };
  }

  if (node.kind === "BoolOp") {
    if (node.op === "and") return foldBinary("bool_and", node.values, "LEFT", "RIGHT");
    return foldBinary("bool_or", node.values, "LEFT", "RIGHT");
  }
  if (node.kind === "UnaryOp") {
    if (node.op === "not") {
      return {
        type: "bool_not",
        inputs: { VALUE: { block: exprToValueBlock(node.operand) } },
      };
    }
    return { type: "raw_expression", fields: { SOURCE: unparseRaw(node) } };
  }
  if (node.kind === "Compare") {
    if (node.ops.length === 1) {
      const op = node.ops[0];
      if (op === "in" || op === "not in") {
        return {
          type: "in_op",
          fields: { OP: op },
          inputs: {
            ITEM: { block: exprToValueBlock(node.left) },
            LIST: { block: exprToValueBlock(node.comparators[0]) },
          },
        };
      }
      if (["==", "!=", "<", "<=", ">", ">="].includes(op)) {
        return {
          type: "cmp",
          fields: { OP: op },
          inputs: {
            LEFT: { block: exprToValueBlock(node.left) },
            RIGHT: { block: exprToValueBlock(node.comparators[0]) },
          },
        };
      }
    }
    return { type: "raw_expression", fields: { SOURCE: unparseRaw(node) } };
  }
  if (node.kind === "BinOp") {
    return {
      type: "arith",
      fields: { OP: node.op },
      inputs: {
        LEFT: { block: exprToValueBlock(node.left) },
        RIGHT: { block: exprToValueBlock(node.right) },
      },
    };
  }
  // IfExp, Subscript, List — render as raw_expression (still saves
  // and validates server-side).
  return { type: "raw_expression", fields: { SOURCE: unparseRaw(node) } };
}

function foldBinary(blockType: string, values: ExprNode[], leftKey: string, rightKey: string): BlockJson {
  // Right-fold so `a and b and c` → cmp_and(a, cmp_and(b, c)).
  if (values.length === 1) return exprToValueBlock(values[0]);
  if (values.length === 2) {
    return {
      type: blockType,
      inputs: {
        [leftKey]: { block: exprToValueBlock(values[0]) },
        [rightKey]: { block: exprToValueBlock(values[1]) },
      },
    };
  }
  return {
    type: blockType,
    inputs: {
      [leftKey]: { block: exprToValueBlock(values[0]) },
      [rightKey]: { block: foldBinary(blockType, values.slice(1), leftKey, rightKey) },
    },
  };
}

// Just defer to the unparser for fallback strings.
import { unparseExpr } from "./exprParser";
function unparseRaw(node: ExprNode): string {
  return unparseExpr(node);
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

export function yamlToBlocks(yamlText: string): {
  workspace: WorkspaceJson;
  parsed: ParsedManifest;
} {
  const parsed = parseManifest(yamlText);
  const workspace = manifestToWorkspace(parsed);
  return { workspace, parsed };
}
