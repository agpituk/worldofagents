import { describe, expect, it } from "vitest";
import { tagsForAbility, tagsForReflex, tagsForTool } from "../deriveTags";

describe("tagsForReflex", () => {
  it("returns the verb's category", () => {
    expect(tagsForReflex({ when: "true", then: { do: "attack" } })).toEqual(["combat"]);
    expect(tagsForReflex({ when: "true", then: { do: "move" } })).toEqual(["movement"]);
  });

  it("returns empty for unknown verbs", () => {
    expect(tagsForReflex({ when: "true", then: { do: "unknown_verb" } })).toEqual([]);
  });

  it("returns empty when then.do is missing", () => {
    expect(tagsForReflex({ when: "true", then: {} as any })).toEqual([]);
  });
});

describe("tagsForTool", () => {
  it("returns the override target verb's category", () => {
    expect(
      tagsForTool({ name: "atk", override: "attack" } as any),
    ).toEqual(["combat"]);
  });

  it("walks composite steps and dedupes categories", () => {
    expect(
      tagsForTool({
        name: "scout_and_strike",
        steps: [
          { do: "move", args: { target: [1, 1] } },
          { do: "look" },
          { do: "attack", args: { target: "rat" } },
        ],
      } as any),
    ).toEqual(expect.arrayContaining(["movement", "special", "combat"]));
  });

  it("recurses into if/then/else", () => {
    const tool = {
      name: "branchy",
      steps: [
        { if: "hp < 5", then: [{ do: "flee" }], else: [{ do: "attack", args: { target: "rat" } }] },
      ],
    };
    const tags = tagsForTool(tool as any);
    expect(tags).toEqual(expect.arrayContaining(["combat"]));
  });
});

describe("tagsForAbility", () => {
  it("walks step verbs", () => {
    expect(
      tagsForAbility({
        steps: [
          { do: "cast", args: { spell: "mend" } },
          { do: "wait" },
        ],
      }),
    ).toEqual(expect.arrayContaining(["magic", "special"]));
  });
});
