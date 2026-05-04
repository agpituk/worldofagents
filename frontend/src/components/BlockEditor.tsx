"use client";

// Master-detail block editor (orchestrator).
//
// Left pane (master): collapsible list of items grouped by kind
// (reflexes / tools / abilities). Each row shows an auto-derived label,
// tag chips from VerbSpec.category, and per-row actions (delete,
// duplicate, toggle-disabled). Reflexes are draggable — order is
// priority (first match wins).
//
// Right pane (detail): one Blockly workspace bound to the SELECTED
// item only. Switching items saves the current canvas back into the
// parsed manifest before loading the next.
//
// Bottom pane: Monaco YAML editor over the whole manifest. The single
// source of truth is `parsed: ParsedManifest` — both panes write into
// it and we re-emit YAML up via `onChange`.
//
// Pure helpers (label derivation, splice, path matching) live in
// `lib/blockEditor/itemHelpers.ts`. Master-list row components live
// under `components/blockEditor/`. This file is state machine + render
// glue only.

import dynamic from "next/dynamic";
import { loader } from "@monaco-editor/react";
import { useEffect, useMemo, useRef, useState } from "react";
import * as Blockly from "blockly/core";
import "blockly/blocks";
import "blockly/javascript";
// English message catalog. Without it Blockly.Msg.* lookups return
// undefined and the context-menu renderer (xdisplayText) crashes when
// the user right-clicks or trackpad-taps the workspace.
import "blockly/msg/en";
import {
  manifestToWorkspace,
  parseManifest,
  parsedToYaml,
  pathToItemKey,
  registerAllBlocks,
  singleItemManifest,
  spliceItem,
  TOOLBOX,
  useBlockEditorActions,
  workspaceToManifest,
  issuePathMatchesSelection,
} from "@/lib/blockEditor";
import type {
  ParsedManifest,
  Selection,
  Tab,
  ValidationIssue,
  WorkspaceJson,
} from "@/lib/blockEditor";
import TabButton from "./blockEditor/TabButton";
import ReflexList from "./blockEditor/ReflexList";
import ToolList from "./blockEditor/ToolList";
import AbilityList from "./blockEditor/AbilityList";
import DetailPane from "./blockEditor/DetailPane";

loader.config({ paths: { vs: "/monaco/vs" } });
const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

type Props = {
  value: string;
  onChange: (next: string) => void;
  validationIssues?: ValidationIssue[];
};

export default function BlockEditor({ value, onChange, validationIssues }: Props) {
  const wsRef = useRef<HTMLDivElement | null>(null);
  const workspace = useRef<Blockly.WorkspaceSvg | null>(null);
  const ignoreNextChange = useRef(false);
  // Tracks the YAML we last emitted up so we don't echo our own
  // changes back when the parent re-renders us with the same value.
  const lastEmitted = useRef<string>(value);
  // Set when an external value-prop change re-parses our state. The
  // resulting `parsed` change should NOT trigger a re-emit upward —
  // doing so would canonicalize through yaml.dump and overwrite
  // surgical edits from sibling panels (e.g. HeroDetailsPanel
  // preserves trailing whitespace; yaml.dump does not).
  const skipNextEmit = useRef(false);
  const [parsed, setParsed] = useState<ParsedManifest>(() => parseManifest(value));
  const [tab, setTab] = useState<Tab>("reflexes");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  // Mirror selection into a ref so the long-lived Blockly change
  // listener (registered once) sees the current value without us
  // re-binding.
  const selectionRef = useRef<Selection | null>(null);
  useEffect(() => { selectionRef.current = selection; }, [selection]);

  // Re-parse when the parent passes a different YAML (template pick,
  // fork prefill, raw paste, sibling-panel edit). Echo-skip if it
  // matches what we emitted.
  useEffect(() => {
    if (value === lastEmitted.current) return;
    lastEmitted.current = value;
    skipNextEmit.current = true;
    setParsed(parseManifest(value));
    setSelection(null);
  }, [value]);

  // Whenever parsed changes from within (master-pane action or block
  // edit), re-emit YAML up. Skip emissions caused by external value
  // changes (above) so surgical edits in sibling panels survive.
  useEffect(() => {
    if (skipNextEmit.current) {
      skipNextEmit.current = false;
      return;
    }
    const dumped = parsedToYaml(parsed);
    if (dumped === lastEmitted.current) return;
    lastEmitted.current = dumped;
    onChange(dumped);
  }, [parsed, onChange]);

  // Initialize Blockly workspace once.
  useEffect(() => {
    if (!wsRef.current || workspace.current) return;
    registerAllBlocks();
    workspace.current = Blockly.inject(wsRef.current, {
      toolbox: TOOLBOX as any,
      media: "/blockly/media/",
      trashcan: false,
      grid: { spacing: 20, length: 3, colour: "#222", snap: true },
      zoom: { controls: true, wheel: true, startScale: 0.9 },
    });

    workspace.current.addChangeListener((event) => {
      if (event.isUiEvent) return;
      if (ignoreNextChange.current) {
        ignoreNextChange.current = false;
        return;
      }
      if (!workspace.current) return;
      const sel = selectionRef.current;
      if (!sel) return;
      try {
        const ws = Blockly.serialization.workspaces.save(workspace.current) as WorkspaceJson;
        const partial = workspaceToManifest(ws, {});
        setParsed((prev) => spliceItem(prev, sel, partial));
        setError(null);
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

  // Reload the workspace when selection changes.
  useEffect(() => {
    if (!workspace.current) return;
    ignoreNextChange.current = true;
    workspace.current.clear();
    if (!selection) return;
    const partial = singleItemManifest(parsed, selection);
    if (!partial) return;
    try {
      const ws = manifestToWorkspace(partial);
      ignoreNextChange.current = true;
      Blockly.serialization.workspaces.load(ws as any, workspace.current);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? "load failed");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection]);

  // Surface validation errors that target the currently-selected item
  // as block warnings. Errors on other items show only as a banner —
  // the master list shows their counts.
  useEffect(() => {
    if (!workspace.current || !selection) return;
    for (const b of workspace.current.getAllBlocks(false)) {
      b.setWarningText(null);
    }
    if (!validationIssues) return;
    const msgs: string[] = [];
    for (const issue of validationIssues) {
      if (issue.severity !== "error" || !issue.path) continue;
      if (!issuePathMatchesSelection(issue.path, selection)) continue;
      msgs.push(issue.message);
    }
    if (msgs.length === 0) return;
    const top = workspace.current.getTopBlocks(false)[0];
    if (top) top.setWarningText(msgs.join("\n"));
  }, [validationIssues, selection]);

  // ---- Master-pane actions (extracted into a hook) ----
  const {
    addItem, deleteSelected, duplicateSelected, toggleDisabled,
    onDragStart, onDragOver, onDrop,
  } = useBlockEditorActions({
    tab, selection, setParsed, setSelection,
    dragIndex, setDragIndex, setOverIndex,
  });

  // ---- Render ----

  const counts = useMemo(() => ({
    reflexes: parsed.reflexes.length,
    tools: parsed.tools.length,
    abilities: Object.keys(parsed.abilities).length,
  }), [parsed]);

  // Per-item error counts so the master list can hint where issues live.
  const errorsByPath = useMemo(() => {
    const by: Record<string, number> = {};
    for (const issue of validationIssues ?? []) {
      if (issue.severity !== "error" || !issue.path) continue;
      const top = pathToItemKey(issue.path);
      if (!top) continue;
      by[top] = (by[top] ?? 0) + 1;
    }
    return by;
  }, [validationIssues]);

  return (
    <div className="relative left-1/2 right-1/2 -mx-[50vw] w-screen border-y border-border">
      {error && (
        <div className="bg-rose-950 text-rose-200 text-xs px-3 py-2 border-b border-rose-800">
          out of sync: {error}
        </div>
      )}

      {/* Tab strip + add button */}
      <div className="flex items-center gap-1 px-3 py-2 bg-bg-card border-b border-border text-sm">
        <TabButton current={tab} t="reflexes" count={counts.reflexes} onClick={() => { setTab("reflexes"); setSelection(null); }}>
          Reflexes
        </TabButton>
        <TabButton current={tab} t="tools" count={counts.tools} onClick={() => { setTab("tools"); setSelection(null); }}>
          Tools
        </TabButton>
        <TabButton current={tab} t="abilities" count={counts.abilities} onClick={() => { setTab("abilities"); setSelection(null); }}>
          Abilities
        </TabButton>
        <div className="ml-auto flex items-center gap-3">
          {tab === "reflexes" && (
            <span className="text-xs text-fg-muted">
              order = priority (first match wins) · drag to reorder
            </span>
          )}
          <button
            onClick={addItem}
            className="text-xs border border-amber-dim/60 text-amber-dim px-2 py-1 hover:bg-amber-dim/10"
          >
            + new {tab === "abilities" ? "ability" : tab.replace(/es$/, "").replace(/s$/, "")}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-[320px_1fr] min-h-[60vh]">
        {/* Master pane */}
        <div className="border-r border-border bg-bg-card/40 overflow-y-auto max-h-[75vh]">
          {tab === "reflexes" && (
            <ReflexList
              reflexes={parsed.reflexes}
              selection={selection}
              dragIndex={dragIndex}
              overIndex={overIndex}
              errorsByPath={errorsByPath}
              onSelect={(i) => setSelection({ kind: "reflex", index: i })}
              onToggleDisabled={toggleDisabled}
              onDragStart={onDragStart}
              onDragOver={onDragOver}
              onDrop={onDrop}
            />
          )}
          {tab === "tools" && (
            <ToolList
              tools={parsed.tools}
              selection={selection}
              errorsByPath={errorsByPath}
              onSelect={(i) => setSelection({ kind: "tool", index: i })}
            />
          )}
          {tab === "abilities" && (
            <AbilityList
              abilities={parsed.abilities}
              selection={selection}
              errorsByPath={errorsByPath}
              onSelect={(name) => setSelection({ kind: "ability", name })}
            />
          )}
        </div>

        <DetailPane
          ref={wsRef}
          parsed={parsed}
          selection={selection}
          onDuplicate={duplicateSelected}
          onDelete={deleteSelected}
        />
      </div>

      {/* YAML pane — full manifest, always visible below */}
      <div className="h-[40vh] border-t border-border">
        <MonacoEditor
          language="yaml"
          theme="vs-dark"
          value={value}
          onChange={(v) => onChange(v ?? "")}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: "on",
            wordWrap: "on",
            scrollBeyondLastLine: false,
          }}
        />
      </div>
    </div>
  );
}
