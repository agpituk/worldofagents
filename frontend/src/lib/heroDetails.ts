// Hero-detail YAML helpers — pure parser/serializer for the deploy
// form's identity fields (name, author, division, bio). Edits use
// surgical line-level replaces so existing comments and formatting
// survive — same approach as `BuildPanel`'s stat edits.
//
// Lives in `lib/` (not next to the React component) so it can be unit
// tested without React, and so other panels can reuse the helpers.

import yaml from "js-yaml";

export const DIVISIONS = ["featherweight", "middleweight", "heavyweight"] as const;
export type Division = (typeof DIVISIONS)[number];

export type HeroDetails = {
  name: string;
  author: string;
  division: Division | string;
  bio: string;
};

// Starter-template values that act as guidance text rather than real
// content — clear them on focus so the user can type their own.
// Author keeps the leading "@" sigil so handles are easy to type.
export const PLACEHOLDER_NAMES: ReadonlySet<string> = new Set(["Your Hero Name"]);
export const PLACEHOLDER_AUTHORS: ReadonlySet<string> = new Set(["@your_handle", "@template"]);
export const PLACEHOLDER_BIOS: ReadonlySet<string> = new Set([
  "A short bio in the hero's own voice. The model uses this verbatim as\npersona context, so write it like you'd write a character sheet.",
]);

export function parseHeroDetails(yamlText: string): HeroDetails | null {
  try {
    const doc: any = yaml.load(yamlText);
    if (!doc || typeof doc !== "object") return null;
    const inner = doc.hero && typeof doc.hero === "object" ? doc.hero : doc;
    // js-yaml keeps exactly one trailing newline on `|` block scalars by
    // default — strip it so the textarea doesn't park the cursor on a
    // blank line after every keystroke.
    const rawBio = typeof inner.bio === "string" ? inner.bio : "";
    return {
      name: typeof inner.name === "string" ? inner.name : "",
      author: typeof inner.author === "string" ? inner.author : "",
      division: typeof inner.division === "string" ? inner.division : "featherweight",
      bio: rawBio.replace(/\n+$/, ""),
    };
  } catch {
    return null;
  }
}

// A scalar value needs YAML quoting if it starts/ends with whitespace
// (plain scalars get trimmed per YAML spec), starts with a special
// token, or contains `: ` / ` #`. Conservative: when in doubt, quote.
function needsQuoting(v: string): boolean {
  if (v === "") return true;
  if (/^\s|\s$/.test(v)) return true;
  if (/^['":\-?,\[\]{}#&*!|>%@`]/.test(v)) return true;
  if (/[:#]\s/.test(v)) return true;
  return false;
}

function quote(v: string): string {
  return needsQuoting(v) ? JSON.stringify(v) : v;
}

export function setScalarInYaml(yamlText: string, key: string, value: string): string {
  const re = new RegExp(`^([ \\t]*)${key}[ \\t]*:[ \\t]*.*$`, "m");
  if (!re.test(yamlText)) return yamlText;
  return yamlText.replace(re, `$1${key}: ${quote(value)}`);
}

// js-yaml's literal-block parser drops content on lines that are
// *only* whitespace (a body line of "     " round-trips to ""). So if
// the bio is empty or contains any whitespace-only line, the literal
// `|` form is lossy — we have to render it as a double-quoted scalar
// instead. JSON.stringify produces valid YAML double-quoted output
// (the \n escape is interpreted by YAML the same way as JSON).
export function bioRequiresQuotedForm(value: string): boolean {
  if (value === "") return true;
  return value.split("\n").some((l) => l.length > 0 && l.trim() === "");
}

// Bio is typically a `bio: |` literal block. Replace the whole block
// (header line + every following line that's empty or indented past
// the header — empty lines are paragraph breaks inside the bio body).
// Falls back to single-line replace if the original was a quoted scalar.
export function setBioInYaml(yamlText: string, value: string): string {
  const useQuoted = bioRequiresQuotedForm(value);
  const headerRe = /^([ \t]*)bio[ \t]*:[ \t]*\|[^\n]*\n/m;
  const header = headerRe.exec(yamlText);
  if (header && header.index !== undefined) {
    const indent = header[1];
    const headerEnd = header.index + header[0].length;
    // Walk forward consuming body lines: empty/whitespace-only OR
    // indented strictly deeper than the header.
    let cursor = headerEnd;
    while (cursor < yamlText.length) {
      const nl = yamlText.indexOf("\n", cursor);
      const lineEnd = nl === -1 ? yamlText.length : nl + 1;
      const line = yamlText.slice(cursor, lineEnd);
      const stripped = line.replace(/\n$/, "");
      if (stripped.trim() === "") {
        cursor = lineEnd; // empty line — part of the body
        continue;
      }
      let ws = 0;
      while (ws < stripped.length && (stripped[ws] === " " || stripped[ws] === "\t")) ws++;
      if (ws <= indent.length) break; // sibling key at the same depth
      cursor = lineEnd;
    }
    if (useQuoted) {
      return yamlText.slice(0, header.index) + `${indent}bio: ${JSON.stringify(value)}\n` + yamlText.slice(cursor);
    }
    const child = indent + "  ";
    const lines = value.split("\n").map((l) => (l ? child + l : "")).join("\n");
    return yamlText.slice(0, header.index) + `${indent}bio: |\n${lines}\n` + yamlText.slice(cursor);
  }
  const lineRe = /^([ \t]*)bio[ \t]*:[ \t]*.*$/m;
  if (lineRe.test(yamlText)) {
    if (!useQuoted && value.includes("\n")) {
      return yamlText.replace(lineRe, (_m, indent) => {
        const child = indent + "  ";
        const lines = value.split("\n").map((l) => (l ? child + l : "")).join("\n");
        return `${indent}bio: |\n${lines}`;
      });
    }
    // Always emit double-quoted form for the single-line bio replace.
    // Bio is freeform user text, and YAML plain (unquoted) scalars
    // strip leading/trailing whitespace per spec — typing `"foo "` and
    // round-tripping would lose the trailing space.
    return yamlText.replace(lineRe, `$1bio: ${JSON.stringify(value)}`);
  }
  return yamlText;
}

// Returns null when hero-detail fields look ready to submit, otherwise
// a short message explaining why the server will reject (or what the
// user obviously hasn't filled in). Used by the create page so the
// "create hero" button can disable itself before the round-trip.
export function getHeroDetailsBlockReason(yamlText: string): string | null {
  const d = parseHeroDetails(yamlText);
  if (!d) return null; // YAML invalid — let other panels surface it
  const author = d.author.trim();
  if (author === "" || author === "@") return "set your @handle in author";
  if (PLACEHOLDER_AUTHORS.has(author)) {
    return `replace the author placeholder ('${author}') with your handle`;
  }
  const name = d.name.trim();
  if (name === "") return "give your hero a name";
  if (PLACEHOLDER_NAMES.has(name)) return "replace 'Your Hero Name' with a real name";
  return null;
}
