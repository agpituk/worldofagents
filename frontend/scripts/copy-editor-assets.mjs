#!/usr/bin/env node
// Copy Monaco's AMD loader bundle and Blockly's media assets into
// public/ so they're served same-origin. The CSP in next.config.ts
// blocks the upstream CDN URLs (cdn.jsdelivr.net for Monaco,
// blockly-demo.appspot.com for Blockly sprites/sounds).
//
// Runs as `predev` and `prebuild`. Inside the docker dev container,
// /app/public is bind-mounted to the host, so the copies appear on
// the host filesystem too (gitignored).
import { cpSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const copies = [
  { from: "node_modules/monaco-editor/min/vs", to: "public/monaco/vs" },
  { from: "node_modules/blockly/media", to: "public/blockly/media" },
];

for (const { from, to } of copies) {
  const src = resolve(root, from);
  const dst = resolve(root, to);
  if (!existsSync(src)) {
    console.error(`[copy-editor-assets] missing ${from} — run npm install first`);
    process.exit(1);
  }
  cpSync(src, dst, { recursive: true, force: true });
  console.log(`[copy-editor-assets] ${from} -> ${to}`);
}
