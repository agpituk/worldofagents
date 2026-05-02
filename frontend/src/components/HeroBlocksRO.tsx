"use client";

// Read-only block render. Used on hero pages, copy-this-tool dialogs,
// and the inspector. Renders the same Blockly workspace but disables
// editing affordances — the user can scroll/zoom but not modify.

import { useEffect, useRef, useState } from "react";
import * as Blockly from "blockly/core";
import "blockly/blocks";
import { registerAllBlocks, yamlToBlocks } from "@/lib/blockEditor";

type Props = {
  yaml: string;
  height?: number;
};

export default function HeroBlocksRO({ yaml: yamlText, height = 360 }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const wsRef = useRef<Blockly.WorkspaceSvg | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!ref.current) return;
    registerAllBlocks();
    wsRef.current = Blockly.inject(ref.current, {
      toolbox: undefined,
      readOnly: true,
      scrollbars: true,
      zoom: { controls: true, wheel: false, startScale: 0.85 },
      grid: { spacing: 20, length: 3, colour: "#222" },
    });
    return () => {
      wsRef.current?.dispose();
      wsRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!wsRef.current) return;
    try {
      const { workspace } = yamlToBlocks(yamlText);
      Blockly.serialization.workspaces.load(workspace as any, wsRef.current);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? "load failed");
    }
  }, [yamlText]);

  return (
    <div className="border border-border">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-bg-card text-xs">
        <span className="uppercase tracking-wider text-fg-muted">blocks (read-only)</span>
        <button
          type="button"
          className="text-fg-muted hover:text-amber-dim"
          onClick={() => {
            navigator.clipboard.writeText(yamlText);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? "copied!" : "copy YAML"}
        </button>
      </div>
      {error && (
        <div className="bg-rose-950 text-rose-200 text-xs px-3 py-2">
          {error}
        </div>
      )}
      <div ref={ref} style={{ height }} className="bg-bg-card" />
    </div>
  );
}
