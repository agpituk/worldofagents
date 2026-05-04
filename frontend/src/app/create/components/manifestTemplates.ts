// Shared manifest constants/helpers for the deploy page.

export const STARTER_MANIFEST = `manifest_version: 1
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
    con: 14
    int: 12
    wis: 14
    cha: 8
    # Total must be ≤ 100 (point buy). Each stat 5–25.

  models:
    cheap: { gateway: arena, model: qwen3-4b, host: local }
  model: cheap

  reflexes:
    - when: "hp <= 8"
      then: { do: flee }
    - when: "enemy_in_range()"
      then: { do: attack_nearest_hostile }
    - when: "hostile_visible() and not enemy_in_range()"
      then: { do: move_to_nearest_hostile }
    # When no reflex matches, escalate to the model
    - when: "True"
      then: { do: invoke_llm }

  memory:
    initial:
      goal: "Survive. Adventure. Make decisions in character."
      gold: 20
    system_summary: |
      Two or three durable facts about who this hero is — fed into every
      LLM prompt regardless of perception window.
    recall_tags:
      - milestone
      - first_kill
`;

export function manifestYamlFromHero(h: any): string {
  // Build a minimal-but-runnable YAML from a public Hero record. The
  // public manifest already strips `system` (the prompt). Output is
  // plain string concatenation so we don't need a yaml lib in the
  // browser bundle.
  const m = (h.manifest || {}) as Record<string, any>;
  const ext = (m.extras || {}) as Record<string, any>;
  const build = h.build || {};
  const lines: string[] = [
    "manifest_version: 1",
    "hero:",
    `  name: "${h.name} (fork)"`,
    `  author: "${h.author || "@you"}"`,
    `  division: ${h.division}`,
  ];
  if (h.bio) {
    lines.push(`  bio: ${JSON.stringify(h.bio)}`);
  }
  lines.push(
    "  build:",
    `    str: ${build.str ?? 12}`,
    `    dex: ${build.dex ?? 12}`,
    `    con: ${build.con ?? 12}`,
    `    int: ${build.int ?? 12}`,
    `    wis: ${build.wis ?? 12}`,
    `    cha: ${build.cha ?? 12}`,
  );
  // Pass through extras as JSON-ish YAML using JSON.stringify (valid YAML).
  for (const [k, v] of Object.entries(ext)) {
    if (v === undefined || v === null) continue;
    lines.push(`  ${k}: ${JSON.stringify(v)}`);
  }
  return lines.join("\n") + "\n";
}
