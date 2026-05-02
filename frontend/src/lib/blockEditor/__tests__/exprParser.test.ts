import { describe, it, expect } from "vitest";
import { parseExpr, unparseExpr } from "../exprParser";

function roundtrip(src: string): string {
  return unparseExpr(parseExpr(src));
}

describe("exprParser", () => {
  it("parses simple comparisons", () => {
    expect(roundtrip("hp > 8")).toBe("hp > 8");
    expect(roundtrip("hp >= 8")).toBe("hp >= 8");
    expect(roundtrip("hp == 8")).toBe("hp == 8");
    expect(roundtrip("hp != 8")).toBe("hp != 8");
  });

  it("parses booleans", () => {
    expect(roundtrip("hp > 8 and gold > 0")).toBe("hp > 8 and gold > 0");
    expect(roundtrip("not hostile_visible()")).toBe("not hostile_visible()");
    expect(roundtrip("hp > 8 or hp < 2")).toBe("hp > 8 or hp < 2");
  });

  it("parses helper calls", () => {
    expect(roundtrip("adjacent_to('marek')")).toBe("adjacent_to('marek')");
    expect(roundtrip("hostile_visible()")).toBe("hostile_visible()");
  });

  it("parses arith with precedence", () => {
    expect(roundtrip("a + b * c")).toBe("a + b * c");
    expect(roundtrip("(a + b) * c")).toBe("(a + b) * c");
    expect(roundtrip("hp / 2")).toBe("hp / 2");
    expect(roundtrip("hp // 2")).toBe("hp // 2");
  });

  it("parses attribute access (args.X)", () => {
    expect(roundtrip("args.dest")).toBe("args.dest");
    expect(roundtrip("args.qty + 1")).toBe("args.qty + 1");
  });

  it("parses min/max/clamp", () => {
    expect(roundtrip("min(a, b)")).toBe("min(a, b)");
    expect(roundtrip("clamp(x, 0, 10)")).toBe("clamp(x, 0, 10)");
    expect(roundtrip("min(requested, max_move_distance() // 2)")).toBe(
      "min(requested, max_move_distance() // 2)",
    );
  });

  it("parses in / not in", () => {
    expect(roundtrip("'iron_sword' in inventory")).toBe("'iron_sword' in inventory");
    expect(roundtrip("'x' not in y")).toBe("'x' not in y");
  });

  it("parses ternary IfExp", () => {
    expect(roundtrip("a if cond else b")).toBe("a if cond else b");
  });

  it("falls back to Raw for unsupported syntax", () => {
    // Walrus is not supported — should land in Raw and round-trip the source.
    const raw = parseExpr("(x := 1)");
    expect(raw.kind).toBe("Raw");
  });

  it("preserves string quoting", () => {
    expect(roundtrip("'hello'")).toBe("'hello'");
    expect(roundtrip("\"hello\"")).toBe("'hello'"); // canonical → single quotes
  });
});
