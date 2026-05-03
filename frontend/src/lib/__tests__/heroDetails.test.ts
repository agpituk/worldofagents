import { describe, expect, it } from "vitest";
import yaml from "js-yaml";
import {
  bioRequiresQuotedForm,
  parseHeroDetails,
  setBioInYaml,
  setScalarInYaml,
  getHeroDetailsBlockReason,
} from "../heroDetails";

const STARTER = `manifest_version: 1
hero:
  name: "Your Hero Name"
  author: "@your_handle"
  division: featherweight
  bio: |
    A short bio in the hero's own voice. The model uses this verbatim as
    persona context, so write it like you'd write a character sheet.
  build:
    str: 12
    dex: 12
    con: 12
    int: 12
    wis: 12
    cha: 12
`;

describe("parseHeroDetails", () => {
  it("strips the trailing newline js-yaml adds to | block scalars", () => {
    const d = parseHeroDetails(STARTER)!;
    expect(d.bio.endsWith("character sheet.")).toBe(true);
    expect(d.bio.endsWith("\n")).toBe(false);
  });

  it("returns null on empty / scalar / undefined documents", () => {
    expect(parseHeroDetails("")).toBeNull();
    expect(parseHeroDetails("just a string")).toBeNull();
  });
});

describe("setScalarInYaml", () => {
  it("quotes values with leading whitespace (YAML strips plain-scalar leading WS)", () => {
    const out = setScalarInYaml(STARTER, "name", " Padded");
    expect(yaml.load(out)).toMatchObject({ hero: { name: " Padded" } });
  });

  it("quotes values with trailing whitespace (the bug we fixed)", () => {
    const out = setScalarInYaml(STARTER, "name", "Trailing ");
    expect(yaml.load(out)).toMatchObject({ hero: { name: "Trailing " } });
  });
});

describe("bioRequiresQuotedForm", () => {
  it("forces quoted form for empty / whitespace-only / contains-blank-line content", () => {
    expect(bioRequiresQuotedForm("")).toBe(true);
    expect(bioRequiresQuotedForm(" ")).toBe(true);
    expect(bioRequiresQuotedForm("a\n \nb")).toBe(true); // middle whitespace-only line
  });

  it("allows literal-block form for normal multi-line content", () => {
    expect(bioRequiresQuotedForm("hello world")).toBe(false);
    expect(bioRequiresQuotedForm("p1\np2")).toBe(false);
    expect(bioRequiresQuotedForm("p1\n\np2")).toBe(false); // empty line OK
  });
});

describe("setBioInYaml", () => {
  // The component reads bio through parseHeroDetails (which strips
  // js-yaml's mandatory trailing newline on literal blocks). These
  // tests assert through the same lens — that's what users see.
  const roundTrip = (input: string, value: string) =>
    parseHeroDetails(setBioInYaml(input, value))?.bio;

  it("round-trips trailing-space content via parseHeroDetails", () => {
    expect(roundTrip(STARTER, "Hello ")).toBe("Hello ");
  });

  it("round-trips a single space (the original repro)", () => {
    expect(roundTrip(STARTER, " ")).toBe(" ");
  });

  it("preserves paragraph breaks (empty lines) inside the bio body", () => {
    expect(roundTrip(STARTER, "Para 1\n\nPara 2")).toBe("Para 1\n\nPara 2");
    // build: stayed in place — body extraction stopped at the sibling key.
    const out = setBioInYaml(STARTER, "Para 1\n\nPara 2");
    expect((yaml.load(out) as any).hero.build.str).toBe(12);
  });

  it("handles a YAML where bio is already a quoted single-line scalar", () => {
    const single = `hero:\n  name: x\n  author: "@me"\n  division: featherweight\n  bio: ""\n  build: { str: 12, dex: 12, con: 12, int: 12, wis: 12, cha: 12 }\n`;
    expect(roundTrip(single, "Hello world")).toBe("Hello world");
  });
});

describe("getHeroDetailsBlockReason", () => {
  it("blocks deploy when author is the @template placeholder", () => {
    const reason = getHeroDetailsBlockReason(STARTER);
    expect(reason).not.toBeNull();
    expect(reason).toMatch(/placeholder/);
  });

  it("blocks deploy when name is the placeholder", () => {
    const yamlWithGoodAuthor = STARTER.replace('"@your_handle"', '"@me"');
    const reason = getHeroDetailsBlockReason(yamlWithGoodAuthor);
    expect(reason).toMatch(/Your Hero Name/);
  });

  it("returns null when both are real values", () => {
    let valid = STARTER.replace('"@your_handle"', '"@me"');
    valid = valid.replace('"Your Hero Name"', '"Bromir"');
    expect(getHeroDetailsBlockReason(valid)).toBeNull();
  });
});
