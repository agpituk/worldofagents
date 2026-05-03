"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ownerTokenFor } from "@/lib/heroOwnership";

type Hero = { id: string; name: string; alive: boolean };

type Props = {
  toolId: string;
  toolName: string;
  onClose: () => void;
};

export default function CopyToolModal({ toolId, toolName, onClose }: Props) {
  const [heroes, setHeroes] = useState<Hero[]>([]);
  const [selectedHero, setSelectedHero] = useState<string>("");
  const [renameTo, setRenameTo] = useState<string>("");
  const [collision, setCollision] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    api.listHeroes()
      .then((rows) =>
        setHeroes(
          rows
            .filter((h) => h.status === "alive")
            .map((h) => ({ id: h.id, name: h.name, alive: true })),
        ),
      )
      .catch((e) => setError(e?.message ?? "load heroes failed"));
  }, []);

  async function submit() {
    if (!selectedHero) return;
    const token = ownerTokenFor(selectedHero);
    if (!token) {
      setError(
        "You don't own this hero on this browser. Copy is only allowed for heroes you registered here.",
      );
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const body = await api.copyTool(toolId, selectedHero, token, renameTo || undefined);
      if (body.appended) {
        setSuccess(
          `Added "${renameTo || toolName}" to ${
            heroes.find((h) => h.id === selectedHero)?.name ?? "hero"
          }.`,
        );
        setCollision(null);
      } else if (body.rename_to) {
        setCollision(body.rename_to);
        setRenameTo(`${body.rename_to}_v2`);
      }
    } catch (e: any) {
      setError(e?.message ?? "copy failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-zinc-900 border border-zinc-700 rounded p-5 w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-zinc-100">
          Copy <code className="text-emerald-300">{toolName}</code>
        </h2>
        <p className="text-xs text-zinc-400 mt-1">
          The tool will be appended to the chosen hero's manifest with a
          fork-lineage stamp linking back to this source.
        </p>

        <label className="block mt-4 text-xs text-zinc-300">
          Add to hero
          <select
            value={selectedHero}
            onChange={(e) => {
              setSelectedHero(e.target.value);
              setCollision(null);
              setRenameTo("");
            }}
            className="mt-1 w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1 text-zinc-200"
          >
            <option value="">Select a hero...</option>
            {heroes.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
        </label>

        {collision && (
          <div className="mt-4 px-3 py-2 border border-amber-800 bg-amber-950/30 text-xs text-amber-200">
            Hero already has a tool named <code>{collision}</code>. Pick a new name:
            <input
              value={renameTo}
              onChange={(e) => setRenameTo(e.target.value)}
              className="mt-1 w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1 text-zinc-200 font-mono"
            />
          </div>
        )}

        {error && (
          <p className="mt-3 text-xs text-rose-300">Error: {error}</p>
        )}
        {success && (
          <p className="mt-3 text-xs text-emerald-300">{success}</p>
        )}

        <div className="flex gap-2 mt-5 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1 text-sm text-zinc-300 hover:text-white"
          >
            close
          </button>
          {!success && (
            <button
              type="button"
              onClick={submit}
              disabled={!selectedHero || submitting}
              className="px-3 py-1 text-sm border border-emerald-700 bg-emerald-950/30 text-emerald-200 rounded hover:bg-emerald-900/40 disabled:opacity-50"
            >
              {submitting ? "copying..." : collision ? "retry with rename" : "copy"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
