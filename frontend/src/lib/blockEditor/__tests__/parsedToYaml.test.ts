import { describe, expect, it } from "vitest";
import { parsedToYaml } from "../parsedToYaml";
import { parseManifest } from "../yamlToBlocks";

describe("parsedToYaml", () => {
  it("round-trips a minimal manifest through parse → emit → parse", () => {
    const input = `manifest_version: 1
hero:
  name: "Test"
  author: "@me"
  division: featherweight
  build:
    str: 12
    dex: 12
    con: 12
    int: 12
    wis: 12
    cha: 12
  reflexes:
    - when: "True"
      then: { do: invoke_llm }
`;
    const parsed = parseManifest(input);
    const dumped = parsedToYaml(parsed);
    const reparsed = parseManifest(dumped);
    expect(reparsed.reflexes).toEqual(parsed.reflexes);
    // The hero envelope is preserved.
    expect(reparsed.extras.__hero_wrapped).toBe(true);
    expect(reparsed.extras.__manifest_version).toBe(1);
  });

  it("preserves extras keys outside reflexes/abilities/tools", () => {
    const input = `hero:
  name: "X"
  author: "@me"
  division: featherweight
  build: { str: 12, dex: 12, con: 12, int: 12, wis: 12, cha: 12 }
  bio: "hello"
  memory:
    initial:
      goal: "do things"
`;
    const parsed = parseManifest(input);
    const dumped = parsedToYaml(parsed);
    const reparsed = parseManifest(dumped);
    expect((reparsed.extras as any).bio).toBe("hello");
    expect((reparsed.extras as any).memory.initial.goal).toBe("do things");
  });

  it("emits empty reflexes array as omitted (no `reflexes:` key)", () => {
    const parsed = {
      reflexes: [],
      abilities: {},
      tools: [],
      extras: { name: "X", author: "@me", division: "featherweight", build: {} },
    };
    const dumped = parsedToYaml(parsed);
    expect(dumped).not.toContain("reflexes:");
  });
});
