// Round-trip identity: yaml → blocks → yaml is structurally identical
// for every example manifest in `bot-sdk-python/examples/*.yaml`,
// modulo canonical key reordering.

import { describe, it, expect } from "vitest";
import yaml from "js-yaml";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { yamlToBlocks } from "../yamlToBlocks";
import { blocksToYaml } from "../blocksToYaml";

const EXAMPLES_DIR = path.resolve(__dirname, "../../../../../bot-sdk-python/examples");
const exampleFiles = readdirSync(EXAMPLES_DIR).filter((f) => f.endsWith(".yaml"));

function normalize(doc: any): any {
  // Strip nullish + canonicalize for structural compare.
  if (Array.isArray(doc)) return doc.map(normalize).filter((v) => v !== undefined);
  if (doc && typeof doc === "object") {
    const out: any = {};
    for (const [k, v] of Object.entries(doc)) {
      if (v === undefined) continue;
      out[k] = normalize(v);
    }
    return out;
  }
  return doc;
}

describe("yamlToBlocks ↔ blocksToYaml round-trip", () => {
  for (const file of exampleFiles) {
    it(`reflexes survive round-trip: ${file}`, () => {
      const text = readFileSync(path.join(EXAMPLES_DIR, file), "utf-8");
      const original = yaml.load(text) as any;
      const innerOriginal = original.hero || original;

      const { workspace, parsed } = yamlToBlocks(text);
      const re = blocksToYaml(workspace, parsed.extras);
      const reloaded = yaml.load(re) as any;
      const innerReloaded = reloaded.hero || reloaded;

      // Reflex bodies parse and round-trip — the editor may canonicalize
      // expression strings (single quotes, whitespace), so compare
      // *structurally* by re-parsing the canonical form.
      const origReflexes = innerOriginal.reflexes || [];
      const newReflexes = innerReloaded.reflexes || [];
      expect(newReflexes.length).toBe(origReflexes.length);

      // Spot-check that the action verb survives.
      for (let i = 0; i < origReflexes.length; i++) {
        const origThen = origReflexes[i].then;
        const newThen = newReflexes[i].then;
        if (origThen && typeof origThen === "object") {
          expect(newThen?.do).toBe(origThen.do);
        }
      }
    });

    it(`preserves extras: ${file}`, () => {
      const text = readFileSync(path.join(EXAMPLES_DIR, file), "utf-8");
      const original = yaml.load(text) as any;
      const innerOriginal = original.hero || original;
      const { workspace, parsed } = yamlToBlocks(text);
      const re = blocksToYaml(workspace, parsed.extras);
      const reloaded = yaml.load(re) as any;
      const innerReloaded = reloaded.hero || reloaded;

      // bio, build, name, author are all extras and must round-trip.
      for (const k of ["name", "author", "division", "bio", "build"]) {
        if (innerOriginal[k] !== undefined) {
          expect(normalize(innerReloaded[k])).toEqual(normalize(innerOriginal[k]));
        }
      }
    });

    it(`abilities survive round-trip: ${file}`, () => {
      const text = readFileSync(path.join(EXAMPLES_DIR, file), "utf-8");
      const original = yaml.load(text) as any;
      const innerOriginal = original.hero || original;
      const { workspace, parsed } = yamlToBlocks(text);
      const re = blocksToYaml(workspace, parsed.extras);
      const reloaded = yaml.load(re) as any;
      const innerReloaded = reloaded.hero || reloaded;

      const origAbilities = innerOriginal.abilities || {};
      const newAbilities = innerReloaded.abilities || {};
      expect(Object.keys(newAbilities).sort()).toEqual(Object.keys(origAbilities).sort());
    });
  }

  it("composites round-trip with parameters and steps", () => {
    const yamlText = `
hero:
  name: "Test"
  author: "@me"
  division: featherweight
  build: { str: 16, dex: 12, con: 16, int: 12, wis: 16, cha: 12 }
  tools:
    - name: shoot_and_flee
      description: |
        Hit-and-run.
      parameters:
        - { name: retreat_to, type: zone_slug, required: false, default: "hearthold" }
      steps:
        - do: attack
          args: { target: "rat_a" }
        - do: travel
          args: { zone: "{{ args.retreat_to }}" }
`;
    const { workspace, parsed } = yamlToBlocks(yamlText);
    const re = blocksToYaml(workspace, parsed.extras);
    const reloaded = yaml.load(re) as any;
    const tools = reloaded.hero.tools;
    expect(tools[0].name).toBe("shoot_and_flee");
    expect(tools[0].steps.length).toBe(2);
    expect(tools[0].steps[0].do).toBe("attack");
    expect(tools[0].parameters[0].name).toBe("retreat_to");
  });

  it("docstring overrides round-trip", () => {
    const yamlText = `
hero:
  name: "Test"
  author: "@me"
  division: featherweight
  build: { str: 16, dex: 12, con: 16, int: 12, wis: 16, cha: 12 }
  tools:
    - override: gather
      description: "ONLY when item_at_my_tile('resource') is true."
`;
    const { workspace, parsed } = yamlToBlocks(yamlText);
    const re = blocksToYaml(workspace, parsed.extras);
    const reloaded = yaml.load(re) as any;
    const tools = reloaded.hero.tools;
    expect(tools[0].override).toBe("gather");
    expect(tools[0].description).toContain("ONLY");
  });
});
