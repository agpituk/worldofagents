// Blockly workspace JSON → manifest YAML.
//
// Counterpart to `yamlToBlocks`. Preserves the original manifest's
// `extras` (everything outside reflexes/abilities/tools) so the editor
// is non-destructive — a user editing only reflexes will not lose
// their bio, build, memory, models, etc.

import yaml from "js-yaml";
import { unparseExpr, ExprNode } from "./exprParser";
import {
  ManifestComposite,
  ManifestOverride,
  ManifestParameter,
  ManifestReflex,
  ManifestStep,
} from "./types";
import { BlockJson, WorkspaceJson } from "./yamlToBlocks";
import { VERB_BY_NAME } from "./verbSpec";

// Top-level key order preferred by the spec (BLOCK_EDITOR.md §5.2).
const TOP_LEVEL_ORDER = [
  "name", "author", "division", "bio", "build",
  "models", "model", "system", "reflexes", "abilities", "tools", "memory", "budget",
];

const TOOL_OVERRIDE_ORDER = ["name", "override", "description", "when", "clamp", "after"];
const TOOL_COMPOSITE_ORDER = ["name", "description", "parameters", "steps"];

export function blocksToYaml(
  workspace: WorkspaceJson,
  preservedExtras: Record<string, unknown> = {},
): string {
  const manifest = workspaceToManifest(workspace, preservedExtras);
  return yaml.dump(manifest, {
    noRefs: true,
    sortKeys: false,
    lineWidth: 100,
  });
}

export function workspaceToManifest(
  workspace: WorkspaceJson,
  preservedExtras: Record<string, unknown>,
): Record<string, unknown> {
  const reflexes: ManifestReflex[] = [];
  const abilities: Record<string, { steps: ManifestStep[] }> = {};
  const tools: Array<ManifestComposite | ManifestOverride> = [];

  for (const block of workspace.blocks?.blocks ?? []) {
    if (block.type === "reflex") {
      const rx = blockToReflex(block);
      if (rx) reflexes.push(rx);
    } else if (block.type === "ability") {
      const [name, spec] = blockToAbility(block);
      if (name) abilities[name] = spec;
    } else if (block.type === "tool_composite") {
      const c = blockToComposite(block);
      if (c) tools.push(c);
    } else if (block.type === "tool_override") {
      const o = blockToOverride(block);
      if (o) tools.push(o);
    }
  }

  // Reassemble manifest with preferred key order, dropping editor's
  // bookkeeping keys.
  const heroBody: Record<string, unknown> = {};
  for (const k of TOP_LEVEL_ORDER) {
    if (k === "reflexes") {
      if (reflexes.length > 0) heroBody.reflexes = reflexes;
    } else if (k === "abilities") {
      if (Object.keys(abilities).length > 0) heroBody.abilities = abilities;
    } else if (k === "tools") {
      if (tools.length > 0) heroBody.tools = tools;
    } else if (k in preservedExtras) {
      heroBody[k] = preservedExtras[k];
    }
  }
  // Append any extras not in TOP_LEVEL_ORDER (custom keys).
  for (const [k, v] of Object.entries(preservedExtras)) {
    if (k.startsWith("__")) continue;
    if (!(k in heroBody) && !TOP_LEVEL_ORDER.includes(k)) {
      heroBody[k] = v;
    }
  }

  const out: Record<string, unknown> = {};
  if (preservedExtras.__manifest_version !== undefined) {
    out.manifest_version = preservedExtras.__manifest_version;
  }
  if (preservedExtras.__hero_wrapped) {
    out.hero = heroBody;
  } else {
    Object.assign(out, heroBody);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Reflex / ability / tool extraction
// ---------------------------------------------------------------------------

function blockToReflex(block: BlockJson): ManifestReflex | null {
  const whenInput = block.inputs?.WHEN?.block;
  const thenInput = block.inputs?.THEN?.block;
  if (!whenInput) return null;
  const whenExpr = unparseExpr(blockToExpr(whenInput));
  const thenAction = thenInput ? blockToActionDict(thenInput) : { do: "wait" };
  return { when: whenExpr, then: thenAction };
}

function blockToAbility(block: BlockJson): [string, { steps: ManifestStep[] }] | [null, any] {
  const name = (block.fields?.NAME as string) || "";
  if (!name) return [null, null];
  const steps = inputToSteps(block.inputs?.STEPS);
  return [name, { steps }];
}

function blockToComposite(block: BlockJson): ManifestComposite | null {
  const name = (block.fields?.NAME as string) || "";
  if (!name) return null;
  const description = (block.fields?.DESCRIPTION as string) || "";
  const parameters = inputToParameters(block.inputs?.PARAMETERS);
  const steps = inputToSteps(block.inputs?.STEPS);
  const out: ManifestComposite = { name, description, steps };
  if (parameters.length > 0) out.parameters = parameters;
  // Reorder per TOOL_COMPOSITE_ORDER for canonical YAML.
  return reorderComposite(out);
}

function blockToOverride(block: BlockJson): ManifestOverride | null {
  const verb = (block.fields?.VERB as string) || "";
  if (!verb) return null;
  const description = (block.fields?.DESCRIPTION as string) || "";
  const out: ManifestOverride = { override: verb };
  if (description) out.description = description;

  const whenSlot = block.inputs?.WHEN?.block;
  if (whenSlot && whenSlot.type === "when_gate") {
    const cond = whenSlot.inputs?.COND?.block;
    if (cond) out.when = unparseExpr(blockToExpr(cond));
  }

  const clampSlot = block.inputs?.CLAMP?.block;
  if (clampSlot) {
    const clamps: Record<string, string> = {};
    let cursor: BlockJson | undefined = clampSlot;
    while (cursor) {
      const cName = (cursor.fields?.NAME as string) || "";
      const cExpr = cursor.inputs?.EXPR?.block;
      if (cName && cExpr) clamps[cName] = unparseExpr(blockToExpr(cExpr));
      cursor = cursor.next?.block;
    }
    if (Object.keys(clamps).length > 0) out.clamp = clamps;
  }

  const afterSteps = inputToSteps(block.inputs?.AFTER);
  if (afterSteps.length > 0) out.after = afterSteps;

  return reorderOverride(out);
}

function reorderComposite(c: ManifestComposite): ManifestComposite {
  const out: any = {};
  for (const k of TOOL_COMPOSITE_ORDER) {
    if (k in c) out[k] = (c as any)[k];
  }
  return out as ManifestComposite;
}

function reorderOverride(o: ManifestOverride): ManifestOverride {
  const out: any = {};
  for (const k of TOOL_OVERRIDE_ORDER) {
    if (k in o) out[k] = (o as any)[k];
  }
  return out as ManifestOverride;
}

function inputToSteps(input: { block?: BlockJson } | undefined): ManifestStep[] {
  const out: ManifestStep[] = [];
  let cursor = input?.block;
  while (cursor) {
    const step = blockToStep(cursor);
    if (step) out.push(step);
    cursor = cursor.next?.block;
  }
  return out;
}

function inputToParameters(input: { block?: BlockJson } | undefined): ManifestParameter[] {
  const out: ManifestParameter[] = [];
  let cursor = input?.block;
  while (cursor) {
    if (cursor.type === "param_def") {
      const name = (cursor.fields?.NAME as string) || "";
      const typ = (cursor.fields?.TYPE as string) || "string";
      const required = (cursor.fields?.REQUIRED as string) === "true";
      const def = (cursor.fields?.DEFAULT as string) || "";
      const param: ManifestParameter = {
        name,
        type: typ as ManifestParameter["type"],
        required,
      };
      if (!required && def !== "") param.default = coerceDefault(def, typ);
      out.push(param);
    }
    cursor = cursor.next?.block;
  }
  return out;
}

function coerceDefault(raw: string, typ: string): unknown {
  if (typ === "int") {
    const n = Number(raw);
    return Number.isFinite(n) ? Math.trunc(n) : raw;
  }
  if (typ === "float") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  if (typ === "bool") return raw === "true" || raw === "True";
  return raw;
}

function blockToStep(block: BlockJson): ManifestStep | null {
  if (block.type === "if_step_simple") {
    const cond = block.inputs?.COND?.block;
    const doBlock = block.inputs?.DO?.block;
    if (!cond || !doBlock) return null;
    const action = blockToActionDict(doBlock);
    return { if: unparseExpr(blockToExpr(cond)), do: action.do as string, args: stripDo(action) };
  }
  if (block.type === "if_step_full") {
    const cond = block.inputs?.COND?.block;
    if (!cond) return null;
    const thenBranch = inputToSteps(block.inputs?.THEN);
    const elseBranch = inputToSteps(block.inputs?.ELSE);
    const out: any = { if: unparseExpr(blockToExpr(cond)), then: thenBranch };
    if (elseBranch.length > 0) out.else = elseBranch;
    return out;
  }
  // Verb / composite / raw action
  const action = blockToActionDict(block);
  if (!action.do) return null;
  return { do: action.do as string, args: stripDo(action) };
}

function stripDo(action: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(action)) {
    if (k === "do") continue;
    out[k] = v;
  }
  return out;
}

function blockToActionDict(block: BlockJson): Record<string, unknown> {
  if (block.type === "do_composite") {
    return { do: (block.fields?.NAME as string) || "" };
  }
  if (block.type === "raw_action") {
    const verb = (block.fields?.DO as string) || "";
    const argsJson = (block.fields?.ARGS_JSON as string) || "{}";
    let args: Record<string, unknown> = {};
    try {
      args = JSON.parse(argsJson);
    } catch {
      // keep empty
    }
    return { do: verb, ...args };
  }
  if (block.type.startsWith("verb_")) {
    const verb = block.type.slice("verb_".length);
    const spec = VERB_BY_NAME[verb];
    if (!spec) return { do: verb };
    const out: Record<string, unknown> = { do: verb };
    for (const param of spec.params) {
      const inputBlock = block.inputs?.[param.name.toUpperCase()]?.block;
      if (!inputBlock) continue;
      out[param.name] = blockToArgValue(inputBlock);
    }
    return out;
  }
  return { do: "wait" };
}

function blockToArgValue(block: BlockJson): unknown {
  if (block.type === "int_literal" || block.type === "float_literal") {
    const v = block.fields?.VALUE;
    return typeof v === "number" ? v : Number(v);
  }
  if (block.type === "str_literal") {
    return (block.fields?.VALUE as string) ?? "";
  }
  if (block.type === "bool_literal") {
    return (block.fields?.VALUE as string) === "True";
  }
  if (block.type === "raw_expression") {
    const src = (block.fields?.SOURCE as string) ?? "";
    // Tile literal heuristic — `[x, y]`.
    const m = src.match(/^\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]\s*$/);
    if (m) return [Number(m[1]), Number(m[2])];
    // {{ ... }} interpolation — preserve verbatim string.
    if (src.includes("{{")) return src;
    // _expr fallback for non-string typed values
    return { _expr: src };
  }
  // Anything else — best-effort string render of the expression.
  try {
    return unparseExpr(blockToExpr(block));
  } catch {
    return "";
  }
}

// ---------------------------------------------------------------------------
// Block → ExprNode
// ---------------------------------------------------------------------------

const HELPER_PREFIX = "helper_";

export function blockToExpr(block: BlockJson): ExprNode {
  if (block.type === "int_literal" || block.type === "float_literal") {
    return { kind: "Const", value: Number(block.fields?.VALUE ?? 0) };
  }
  if (block.type === "str_literal") {
    return { kind: "Const", value: (block.fields?.VALUE as string) ?? "" };
  }
  if (block.type === "bool_literal") {
    return { kind: "Const", value: (block.fields?.VALUE as string) === "True" };
  }
  if (block.type === "var_ref") {
    return { kind: "Name", id: (block.fields?.NAME as string) ?? "" };
  }
  if (block.type === "args_ref") {
    return {
      kind: "Attribute",
      obj: { kind: "Name", id: "args" },
      attr: (block.fields?.NAME as string) ?? "",
    };
  }
  if (block.type === "requested_ref") {
    return { kind: "Name", id: "requested" };
  }
  if (block.type === "raw_expression") {
    return { kind: "Raw", source: (block.fields?.SOURCE as string) ?? "" };
  }
  if (block.type === "cmp") {
    return {
      kind: "Compare",
      left: blockToExpr(block.inputs?.LEFT?.block as BlockJson),
      ops: [(block.fields?.OP as any) ?? "=="],
      comparators: [blockToExpr(block.inputs?.RIGHT?.block as BlockJson)],
    };
  }
  if (block.type === "in_op") {
    return {
      kind: "Compare",
      left: blockToExpr(block.inputs?.ITEM?.block as BlockJson),
      ops: [(block.fields?.OP as any) ?? "in"],
      comparators: [blockToExpr(block.inputs?.LIST?.block as BlockJson)],
    };
  }
  if (block.type === "bool_and" || block.type === "bool_or") {
    return {
      kind: "BoolOp",
      op: block.type === "bool_and" ? "and" : "or",
      values: [
        blockToExpr(block.inputs?.LEFT?.block as BlockJson),
        blockToExpr(block.inputs?.RIGHT?.block as BlockJson),
      ],
    };
  }
  if (block.type === "bool_not") {
    return {
      kind: "UnaryOp",
      op: "not",
      operand: blockToExpr(block.inputs?.VALUE?.block as BlockJson),
    };
  }
  if (block.type === "arith") {
    return {
      kind: "BinOp",
      op: (block.fields?.OP as any) ?? "+",
      left: blockToExpr(block.inputs?.LEFT?.block as BlockJson),
      right: blockToExpr(block.inputs?.RIGHT?.block as BlockJson),
    };
  }
  if (block.type === "min_max") {
    const fn = (block.fields?.FN as string) ?? "min";
    const args: ExprNode[] = [];
    for (const k of ["ARG0", "ARG1", "ARG2"]) {
      const inner = block.inputs?.[k]?.block;
      if (inner) args.push(blockToExpr(inner));
    }
    return { kind: "Call", func: fn, args };
  }
  if (block.type.startsWith(HELPER_PREFIX)) {
    const fn = block.type.slice(HELPER_PREFIX.length);
    const args: ExprNode[] = [];
    const inner = block.inputs?.ARG0?.block;
    if (inner) args.push(blockToExpr(inner));
    return { kind: "Call", func: fn, args };
  }
  return { kind: "Raw", source: "None" };
}
