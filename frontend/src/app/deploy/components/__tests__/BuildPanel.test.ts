import { describe, expect, it } from "vitest";
import yaml from "js-yaml";
import { parseBuild, setStatInYaml } from "../BuildPanel";

const SAMPLE = `manifest_version: 1
hero:
  name: "Test Hero"
  author: "@you"
  division: featherweight
  bio: "x"
  build:
    str: 12
    dex: 12
    con: 14
    int: 12
    wis: 14
    cha: 8
    # Total must be <= 100
  reflexes:
    - when: "true"
      then: { do: invoke_llm }
`;

const STATS = ["str", "dex", "con", "int", "wis", "cha"] as const;

describe("BuildPanel pure helpers", () => {
  it("parseBuild reads all six stats from a hero-wrapped manifest", () => {
    const b = parseBuild(SAMPLE);
    expect(b).toEqual({ str: 12, dex: 12, con: 14, int: 12, wis: 14, cha: 8 });
  });

  it("parseBuild returns null when YAML is invalid", () => {
    expect(parseBuild("hero:\n  name: [unterminated")).toBeNull();
  });

  it("parseBuild returns null when build is absent", () => {
    const noBuild = `manifest_version: 1\nhero:\n  name: x\n`;
    expect(parseBuild(noBuild)).toBeNull();
  });

  it.each(STATS)("setStatInYaml round-trips through parseBuild for %s", (stat) => {
    const updated = setStatInYaml(SAMPLE, stat, 21);
    const re = parseBuild(updated);
    expect(re).not.toBeNull();
    expect(re![stat]).toBe(21);
    // Other stats unchanged.
    for (const other of STATS) {
      if (other === stat) continue;
      const original = parseBuild(SAMPLE)![other];
      expect(re![other]).toBe(original);
    }
  });

  it("setStatInYaml preserves trailing comment on the build block", () => {
    const updated = setStatInYaml(SAMPLE, "str", 18);
    expect(updated).toContain("# Total must be <= 100");
  });

  it("setStatInYaml is a no-op when the key isn't present", () => {
    const noBuild = `manifest_version: 1\nhero:\n  name: x\n`;
    expect(setStatInYaml(noBuild, "str", 18)).toBe(noBuild);
  });

  it("over-budget detection: sum > 100 is observable", () => {
    let yamlText = SAMPLE;
    yamlText = setStatInYaml(yamlText, "str", 25);
    yamlText = setStatInYaml(yamlText, "dex", 25);
    yamlText = setStatInYaml(yamlText, "con", 25);
    yamlText = setStatInYaml(yamlText, "int", 25);
    const b = parseBuild(yamlText)!;
    const total = b.str + b.dex + b.con + b.int + b.wis + b.cha;
    expect(total).toBeGreaterThan(100);
  });

  it("setStatInYaml output remains parseable YAML", () => {
    const updated = setStatInYaml(SAMPLE, "wis", 19);
    const doc = yaml.load(updated) as any;
    expect(doc.hero.build.wis).toBe(19);
  });
});
