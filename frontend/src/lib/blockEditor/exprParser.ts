// Tiny Python expression parser → block tree.
//
// Mirrors the sandbox AST allowlist at
// `bot-sdk-python/src/arena_bot/reflex_sandbox.py:35-53`.
// Anything outside the allowlist is rendered as a `raw_expression`
// block so the user sees the source text and can still save — the
// editor never silently drops content.
//
// The block-tree shape produced here is consumed by `yamlToBlocks` to
// build Blockly XML. Round-trip identity is enforced by a vitest
// suite: `parse(unparse(t)) === t` for every shape we emit, and
// `unparse(parse(s)) === s` for the canonical-string forms below.

export type ExprNode =
  | { kind: "Const"; value: string | number | boolean | null }
  | { kind: "Name"; id: string }
  | { kind: "Attribute"; obj: ExprNode; attr: string }
  | { kind: "BinOp"; op: BinOp; left: ExprNode; right: ExprNode }
  | { kind: "BoolOp"; op: "and" | "or"; values: ExprNode[] }
  | { kind: "UnaryOp"; op: "not" | "-" | "+"; operand: ExprNode }
  | { kind: "Compare"; left: ExprNode; ops: CmpOp[]; comparators: ExprNode[] }
  | { kind: "Call"; func: string; args: ExprNode[] }
  | { kind: "List"; elts: ExprNode[] }
  | { kind: "Subscript"; obj: ExprNode; index: ExprNode }
  | { kind: "IfExp"; test: ExprNode; body: ExprNode; orelse: ExprNode }
  | { kind: "Raw"; source: string };

export type BinOp =
  | "+" | "-" | "*" | "/" | "//" | "%" | "**";

export type CmpOp =
  | "==" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not in" | "is" | "is not";

// ---------- Tokenizer ----------

type Token =
  | { kind: "num"; value: number; raw: string }
  | { kind: "str"; value: string }
  | { kind: "ident"; value: string }
  | { kind: "kw"; value: string } // keywords: and, or, not, in, is, True, False, None, if, else
  | { kind: "op"; value: string }
  | { kind: "punc"; value: "(" | ")" | "[" | "]" | "," | "." }
  | { kind: "eof" };

const KEYWORDS = new Set([
  "and", "or", "not", "in", "is", "True", "False", "None", "if", "else",
]);

function tokenize(src: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  const len = src.length;

  while (i < len) {
    const c = src[i];
    if (c === " " || c === "\t" || c === "\n" || c === "\r") {
      i++;
      continue;
    }
    if (c === "(" || c === ")" || c === "[" || c === "]" || c === "," || c === ".") {
      tokens.push({ kind: "punc", value: c });
      i++;
      continue;
    }
    // Multichar ops first
    const two = src.slice(i, i + 2);
    const three = src.slice(i, i + 3);
    if (three === "//=" || three === "**=" || three === "==." || three === "!==" /* unused but safe */) {
      // No assignments allowed; bail to single-op and let parser reject.
    }
    if (two === "**" || two === "//" || two === "==" || two === "!=" || two === ">=" || two === "<=") {
      tokens.push({ kind: "op", value: two });
      i += 2;
      continue;
    }
    if (
      c === "+" || c === "-" || c === "*" || c === "/" || c === "%" ||
      c === ">" || c === "<"
    ) {
      tokens.push({ kind: "op", value: c });
      i++;
      continue;
    }
    if (c === '"' || c === "'") {
      const quote = c;
      let j = i + 1;
      let value = "";
      while (j < len && src[j] !== quote) {
        if (src[j] === "\\" && j + 1 < len) {
          const n = src[j + 1];
          if (n === "n") value += "\n";
          else if (n === "t") value += "\t";
          else if (n === "r") value += "\r";
          else value += n;
          j += 2;
        } else {
          value += src[j];
          j++;
        }
      }
      if (j >= len) throw new Error("unterminated string literal");
      tokens.push({ kind: "str", value });
      i = j + 1;
      continue;
    }
    if (/[0-9]/.test(c)) {
      let j = i;
      while (j < len && /[0-9]/.test(src[j])) j++;
      if (src[j] === ".") {
        j++;
        while (j < len && /[0-9]/.test(src[j])) j++;
      }
      const raw = src.slice(i, j);
      tokens.push({ kind: "num", value: Number(raw), raw });
      i = j;
      continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      let j = i;
      while (j < len && /[A-Za-z0-9_]/.test(src[j])) j++;
      const word = src.slice(i, j);
      if (KEYWORDS.has(word)) {
        tokens.push({ kind: "kw", value: word });
      } else {
        tokens.push({ kind: "ident", value: word });
      }
      i = j;
      continue;
    }
    throw new Error(`unexpected character '${c}' at index ${i}`);
  }

  tokens.push({ kind: "eof" });
  return tokens;
}

// ---------- Parser ----------
//
// Grammar (Python-like, subset):
//   expr     := ifexpr
//   ifexpr   := orExpr ("if" orExpr "else" expr)?
//   orExpr   := andExpr ("or" andExpr)*
//   andExpr  := notExpr ("and" notExpr)*
//   notExpr  := "not" notExpr | cmp
//   cmp      := arith (cmpOp arith)*
//   arith    := term (("+" | "-") term)*
//   term     := factor (("*" | "/" | "//" | "%") factor)*
//   factor   := unary | factor "**" unary    (right assoc)
//   unary    := ("-" | "+") unary | trailer
//   trailer  := atom ("(" args ")" | "." ident | "[" expr "]")*
//   atom     := NUM | STR | True | False | None | ident | "(" expr ")" | "[" listElts "]"

export function parseExpr(src: string): ExprNode {
  try {
    const tokens = tokenize(src);
    const parser = new Parser(tokens, src);
    const node = parser.parseExpr();
    parser.expectEof();
    return node;
  } catch {
    return { kind: "Raw", source: src };
  }
}

class Parser {
  i = 0;
  constructor(public tokens: Token[], public src: string) {}

  peek(off = 0): Token {
    return this.tokens[this.i + off];
  }
  consume(): Token {
    return this.tokens[this.i++];
  }
  matchKw(s: string): boolean {
    const t = this.peek();
    if (t.kind === "kw" && t.value === s) {
      this.i++;
      return true;
    }
    return false;
  }
  matchOp(s: string): boolean {
    const t = this.peek();
    if (t.kind === "op" && t.value === s) {
      this.i++;
      return true;
    }
    return false;
  }
  matchPunc(s: string): boolean {
    const t = this.peek();
    if (t.kind === "punc" && t.value === s) {
      this.i++;
      return true;
    }
    return false;
  }
  expectPunc(s: string): void {
    if (!this.matchPunc(s)) {
      const t = this.peek();
      throw new Error(`expected '${s}', got ${describe(t)}`);
    }
  }
  expectEof(): void {
    if (this.peek().kind !== "eof") {
      throw new Error(`unexpected trailing token ${describe(this.peek())}`);
    }
  }

  parseExpr(): ExprNode {
    return this.parseIfExp();
  }

  parseIfExp(): ExprNode {
    const body = this.parseOr();
    if (this.matchKw("if")) {
      const test = this.parseOr();
      if (!this.matchKw("else")) throw new Error("expected 'else' in conditional expression");
      const orelse = this.parseExpr();
      return { kind: "IfExp", test, body, orelse };
    }
    return body;
  }

  parseOr(): ExprNode {
    let left = this.parseAnd();
    const values: ExprNode[] = [left];
    while (this.matchKw("or")) {
      values.push(this.parseAnd());
    }
    if (values.length === 1) return left;
    return { kind: "BoolOp", op: "or", values };
  }
  parseAnd(): ExprNode {
    let left = this.parseNot();
    const values: ExprNode[] = [left];
    while (this.matchKw("and")) {
      values.push(this.parseNot());
    }
    if (values.length === 1) return left;
    return { kind: "BoolOp", op: "and", values };
  }
  parseNot(): ExprNode {
    if (this.matchKw("not")) {
      const operand = this.parseNot();
      return { kind: "UnaryOp", op: "not", operand };
    }
    return this.parseCmp();
  }
  parseCmp(): ExprNode {
    const left = this.parseArith();
    const ops: CmpOp[] = [];
    const comps: ExprNode[] = [];
    while (true) {
      const t = this.peek();
      let op: CmpOp | null = null;
      if (t.kind === "op") {
        if (["==", "!=", "<", "<=", ">", ">="].includes(t.value)) {
          op = t.value as CmpOp;
          this.i++;
        }
      } else if (t.kind === "kw") {
        if (t.value === "in") {
          op = "in";
          this.i++;
        } else if (t.value === "not") {
          // not in
          if (this.peek(1).kind === "kw" && (this.peek(1) as any).value === "in") {
            this.i += 2;
            op = "not in";
          }
        } else if (t.value === "is") {
          this.i++;
          if (this.peek().kind === "kw" && (this.peek() as any).value === "not") {
            this.i++;
            op = "is not";
          } else {
            op = "is";
          }
        }
      }
      if (op === null) break;
      ops.push(op);
      comps.push(this.parseArith());
    }
    if (ops.length === 0) return left;
    return { kind: "Compare", left, ops, comparators: comps };
  }
  parseArith(): ExprNode {
    let left = this.parseTerm();
    while (true) {
      const t = this.peek();
      if (t.kind === "op" && (t.value === "+" || t.value === "-")) {
        this.i++;
        const right = this.parseTerm();
        left = { kind: "BinOp", op: t.value as BinOp, left, right };
      } else break;
    }
    return left;
  }
  parseTerm(): ExprNode {
    let left = this.parseUnary();
    while (true) {
      const t = this.peek();
      if (t.kind === "op" && (t.value === "*" || t.value === "/" || t.value === "//" || t.value === "%")) {
        this.i++;
        const right = this.parseUnary();
        left = { kind: "BinOp", op: t.value as BinOp, left, right };
      } else break;
    }
    return left;
  }
  parseUnary(): ExprNode {
    const t = this.peek();
    if (t.kind === "op" && (t.value === "-" || t.value === "+")) {
      this.i++;
      const operand = this.parseUnary();
      return { kind: "UnaryOp", op: t.value as "-" | "+", operand };
    }
    return this.parsePow();
  }
  parsePow(): ExprNode {
    const left = this.parseTrailer();
    if (this.matchOp("**")) {
      const right = this.parseUnary();
      return { kind: "BinOp", op: "**", left, right };
    }
    return left;
  }
  parseTrailer(): ExprNode {
    let node = this.parseAtom();
    while (true) {
      const t = this.peek();
      if (t.kind === "punc" && t.value === "(") {
        this.i++;
        const args = this.parseArgList();
        this.expectPunc(")");
        if (node.kind !== "Name") throw new Error("only direct function calls supported");
        node = { kind: "Call", func: node.id, args };
      } else if (t.kind === "punc" && t.value === ".") {
        this.i++;
        const next = this.consume();
        if (next.kind !== "ident") throw new Error("expected ident after '.'");
        node = { kind: "Attribute", obj: node, attr: next.value };
      } else if (t.kind === "punc" && t.value === "[") {
        this.i++;
        const index = this.parseExpr();
        this.expectPunc("]");
        node = { kind: "Subscript", obj: node, index };
      } else break;
    }
    return node;
  }
  parseArgList(): ExprNode[] {
    const out: ExprNode[] = [];
    if (this.peek().kind === "punc" && (this.peek() as any).value === ")") return out;
    out.push(this.parseExpr());
    while (this.matchPunc(",")) {
      if (this.peek().kind === "punc" && (this.peek() as any).value === ")") break;
      out.push(this.parseExpr());
    }
    return out;
  }
  parseAtom(): ExprNode {
    const t = this.consume();
    if (t.kind === "num") return { kind: "Const", value: t.value };
    if (t.kind === "str") return { kind: "Const", value: t.value };
    if (t.kind === "kw") {
      if (t.value === "True") return { kind: "Const", value: true };
      if (t.value === "False") return { kind: "Const", value: false };
      if (t.value === "None") return { kind: "Const", value: null };
      throw new Error(`unexpected keyword '${t.value}' in atom position`);
    }
    if (t.kind === "ident") return { kind: "Name", id: t.value };
    if (t.kind === "punc" && t.value === "(") {
      const e = this.parseExpr();
      this.expectPunc(")");
      return e;
    }
    if (t.kind === "punc" && t.value === "[") {
      const elts: ExprNode[] = [];
      if (!(this.peek().kind === "punc" && (this.peek() as any).value === "]")) {
        elts.push(this.parseExpr());
        while (this.matchPunc(",")) {
          if (this.peek().kind === "punc" && (this.peek() as any).value === "]") break;
          elts.push(this.parseExpr());
        }
      }
      this.expectPunc("]");
      return { kind: "List", elts };
    }
    throw new Error(`unexpected token ${describe(t)}`);
  }
}

function describe(t: Token): string {
  if (t.kind === "eof") return "<eof>";
  if (t.kind === "num") return `number ${t.raw}`;
  if (t.kind === "str") return `string`;
  return `${t.kind} '${(t as any).value}'`;
}

// ---------- Unparser (canonical form) ----------

const PREC: Record<string, number> = {
  IfExp: 1, Or: 2, And: 3, Not: 4, Compare: 5,
  Add: 6, Sub: 6, Mult: 7, Div: 7, FloorDiv: 7, Mod: 7,
  UAdd: 8, USub: 8, Pow: 9, Atom: 10,
};

export function unparseExpr(node: ExprNode): string {
  return _u(node, 0);
}

function _u(node: ExprNode, parentPrec: number): string {
  if (node.kind === "Raw") return node.source;
  if (node.kind === "Const") {
    if (node.value === null) return "None";
    if (typeof node.value === "boolean") return node.value ? "True" : "False";
    if (typeof node.value === "string") return JSON.stringify(node.value).replace(/^"|"$/g, "'");
    return String(node.value);
  }
  if (node.kind === "Name") return node.id;
  if (node.kind === "Attribute") return `${_u(node.obj, PREC.Atom)}.${node.attr}`;
  if (node.kind === "Subscript") return `${_u(node.obj, PREC.Atom)}[${_u(node.index, 0)}]`;
  if (node.kind === "Call") {
    return `${node.func}(${node.args.map((a) => _u(a, 0)).join(", ")})`;
  }
  if (node.kind === "List") {
    return `[${node.elts.map((a) => _u(a, 0)).join(", ")}]`;
  }
  if (node.kind === "UnaryOp") {
    if (node.op === "not") return wrap(parentPrec, PREC.Not, `not ${_u(node.operand, PREC.Not)}`);
    return wrap(parentPrec, PREC.USub, `${node.op}${_u(node.operand, PREC.USub)}`);
  }
  if (node.kind === "BoolOp") {
    const sep = ` ${node.op} `;
    const prec = node.op === "or" ? PREC.Or : PREC.And;
    const inner = node.values.map((v) => _u(v, prec)).join(sep);
    return wrap(parentPrec, prec, inner);
  }
  if (node.kind === "Compare") {
    const parts: string[] = [_u(node.left, PREC.Compare)];
    for (let i = 0; i < node.ops.length; i++) {
      parts.push(node.ops[i]);
      parts.push(_u(node.comparators[i], PREC.Compare));
    }
    return wrap(parentPrec, PREC.Compare, parts.join(" "));
  }
  if (node.kind === "BinOp") {
    const opPrec = node.op === "**" ? PREC.Pow : node.op === "+" || node.op === "-" ? PREC.Add : PREC.Mult;
    return wrap(parentPrec, opPrec, `${_u(node.left, opPrec)} ${node.op} ${_u(node.right, opPrec)}`);
  }
  if (node.kind === "IfExp") {
    return wrap(
      parentPrec, PREC.IfExp,
      `${_u(node.body, PREC.IfExp)} if ${_u(node.test, PREC.IfExp)} else ${_u(node.orelse, PREC.IfExp)}`,
    );
  }
  return "?";
}

function wrap(parentPrec: number, myPrec: number, text: string): string {
  return parentPrec > myPrec ? `(${text})` : text;
}
