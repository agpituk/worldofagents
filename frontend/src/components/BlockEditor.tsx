"use client";

// Split-pane block editor — Blockly workspace on the left, raw YAML on
// the right. Both views are authoritative-equal: edit either, debounced
// sync to the other. Last-edited side wins on conflict; an "out of
// sync" banner appears if the parser or serializer fails.

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import * as Blockly from "blockly/core";
import "blockly/blocks";
import "blockly/javascript";
import {
  blocksToYaml,
  registerAllBlocks,
  TOOLBOX,
  yamlToBlocks,
} from "@/lib/blockEditor";
import type { ParsedManifest } from "@/lib/blockEditor";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

type Props = {
  value: string;
  onChange: (next: string) => void;
};

export default function BlockEditor({ value, onChange }: Props) {
  const wsRef = useRef<HTMLDivElement | null>(null);
  const workspace = useRef<Blockly.WorkspaceSvg | null>(null);
  const extras = useRef<ParsedManifest["extras"]>({});
  const lastWriter = useRef<"yaml" | "blocks">("yaml");
  const ignoreNext = useRef(false);
  const [error, setError] = useState<string | null>(null);

  // ---- Initialize Blockly workspace once ----
  useEffect(() => {
    if (!wsRef.current || workspace.current) return;
    registerAllBlocks();
    workspace.current = Blockly.inject(wsRef.current, {
      toolbox: TOOLBOX as any,
      trashcan: true,
      grid: { spacing: 20, length: 3, colour: "#222", snap: true },
      zoom: { controls: true, wheel: true, startScale: 0.9 },
    });

    // Initial load.
    try {
      const { workspace: ws, parsed } = yamlToBlocks(value);
      extras.current = parsed.extras;
      ignoreNext.current = true;
      Blockly.serialization.workspaces.load(ws as any, workspace.current);
    } catch (e: any) {
      setError(e?.message ?? "initial load failed");
    }

    // On change → serialize back to YAML.
    workspace.current.addChangeListener((event) => {
      if (event.isUiEvent) return;
      if (ignoreNext.current) {
        ignoreNext.current = false;
        return;
      }
      lastWriter.current = "blocks";
      try {
        const ws = Blockly.serialization.workspaces.save(workspace.current!);
        const yamlText = blocksToYaml(ws as any, extras.current);
        setError(null);
        onChange(yamlText);
      } catch (e: any) {
        setError(e?.message ?? "serialize failed");
      }
    });

    return () => {
      workspace.current?.dispose();
      workspace.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- YAML → workspace (debounced) ----
  const yamlChanged = useCallback(
    (next: string) => {
      lastWriter.current = "yaml";
      onChange(next);
      if (!workspace.current) return;
      try {
        const { workspace: ws, parsed } = yamlToBlocks(next);
        extras.current = parsed.extras;
        ignoreNext.current = true;
        Blockly.serialization.workspaces.load(ws as any, workspace.current);
        setError(null);
      } catch (e: any) {
        setError(e?.message ?? "parse failed");
      }
    },
    [onChange],
  );

  // External value change (e.g., reset to starter). Skip if blocks just wrote.
  useEffect(() => {
    if (!workspace.current) return;
    if (lastWriter.current === "blocks") return;
    try {
      const { workspace: ws, parsed } = yamlToBlocks(value);
      extras.current = parsed.extras;
      ignoreNext.current = true;
      Blockly.serialization.workspaces.load(ws as any, workspace.current);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? "parse failed");
    }
  }, [value]);

  return (
    <div className="border border-border">
      {error && (
        <div className="bg-rose-950 text-rose-200 text-xs px-3 py-2 border-b border-rose-800">
          out of sync: {error}
        </div>
      )}
      <div className="grid grid-cols-2 gap-0">
        <div ref={wsRef} className="h-[600px] bg-bg-card" />
        <div className="h-[600px]">
          <MonacoEditor
            language="yaml"
            theme="vs-dark"
            value={value}
            onChange={(v) => yamlChanged(v ?? "")}
            options={{
              minimap: { enabled: false },
              fontSize: 12,
              lineNumbers: "on",
              wordWrap: "on",
              scrollBeyondLastLine: false,
            }}
          />
        </div>
      </div>
    </div>
  );
}
