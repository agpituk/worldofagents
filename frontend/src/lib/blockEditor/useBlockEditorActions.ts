// Action callbacks for the master-detail block editor: + new, delete,
// duplicate, toggle-disabled, drag-reorder. Extracted into a hook so
// the orchestrator component stays under the 300-line cap and these
// can be tested in isolation if needed.

import { useCallback } from "react";
import {
  newAbility,
  newReflex,
  newTool,
  uniqueName,
} from "./itemHelpers";
import type { Selection, Tab } from "./itemHelpers";
import type { ParsedManifest } from "./types";

type Args = {
  tab: Tab;
  selection: Selection | null;
  setParsed: React.Dispatch<React.SetStateAction<ParsedManifest>>;
  setSelection: (s: Selection | null) => void;
  dragIndex: number | null;
  setDragIndex: (i: number | null) => void;
  setOverIndex: (i: number | null) => void;
};

export function useBlockEditorActions({
  tab, selection, setParsed, setSelection,
  dragIndex, setDragIndex, setOverIndex,
}: Args) {
  const addItem = useCallback(() => {
    setParsed((prev) => {
      if (tab === "reflexes") {
        const next = { ...prev, reflexes: [...prev.reflexes, newReflex()] };
        setSelection({ kind: "reflex", index: next.reflexes.length - 1 });
        return next;
      }
      if (tab === "tools") {
        const stub = newTool(prev);
        const next = { ...prev, tools: [...prev.tools, stub] };
        setSelection({ kind: "tool", index: next.tools.length - 1 });
        return next;
      }
      const { name, spec } = newAbility(prev);
      const next = { ...prev, abilities: { ...prev.abilities, [name]: spec } };
      setSelection({ kind: "ability", name });
      return next;
    });
  }, [tab, setParsed, setSelection]);

  const deleteSelected = useCallback(() => {
    if (!selection) return;
    setParsed((prev) => {
      if (selection.kind === "reflex") {
        return { ...prev, reflexes: prev.reflexes.filter((_, i) => i !== selection.index) };
      }
      if (selection.kind === "tool") {
        return { ...prev, tools: prev.tools.filter((_, i) => i !== selection.index) };
      }
      const { [selection.name]: _drop, ...rest } = prev.abilities;
      return { ...prev, abilities: rest };
    });
    setSelection(null);
  }, [selection, setParsed, setSelection]);

  const duplicateSelected = useCallback(() => {
    if (!selection) return;
    setParsed((prev) => {
      if (selection.kind === "reflex") {
        const src = prev.reflexes[selection.index];
        if (!src) return prev;
        const reflexes = [...prev.reflexes];
        reflexes.splice(selection.index + 1, 0, JSON.parse(JSON.stringify(src)));
        setSelection({ kind: "reflex", index: selection.index + 1 });
        return { ...prev, reflexes };
      }
      if (selection.kind === "tool") {
        const src = prev.tools[selection.index] as any;
        if (!src) return prev;
        const taken = new Set(prev.tools.map((t: any) => t.name).filter(Boolean));
        const copy = JSON.parse(JSON.stringify(src));
        copy.name = uniqueName(`${src.name || "tool"}_copy`, taken);
        const tools = [...prev.tools];
        tools.splice(selection.index + 1, 0, copy);
        setSelection({ kind: "tool", index: selection.index + 1 });
        return { ...prev, tools };
      }
      const src = prev.abilities[selection.name];
      if (!src) return prev;
      const taken = new Set(Object.keys(prev.abilities));
      const newName = uniqueName(`${selection.name}_copy`, taken);
      const next = { ...prev, abilities: { ...prev.abilities, [newName]: JSON.parse(JSON.stringify(src)) } };
      setSelection({ kind: "ability", name: newName });
      return next;
    });
  }, [selection, setParsed, setSelection]);

  const toggleDisabled = useCallback((index: number) => {
    setParsed((prev) => {
      const reflexes = [...prev.reflexes];
      const cur = reflexes[index] as any;
      if (!cur) return prev;
      const isDisabled = cur.disabled === true;
      const { disabled: _drop, ...rest } = cur;
      reflexes[index] = isDisabled ? rest : { ...rest, disabled: true };
      return { ...prev, reflexes };
    });
  }, [setParsed]);

  // Drag handlers — reflexes only. Reordering rewrites priority.
  const onDragStart = (i: number) => (e: React.DragEvent) => {
    setDragIndex(i);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(i));
  };
  const onDragOver = (i: number) => (e: React.DragEvent) => {
    e.preventDefault();
    setOverIndex(i);
  };
  const onDrop = (i: number) => (e: React.DragEvent) => {
    e.preventDefault();
    if (dragIndex === null || dragIndex === i) {
      setDragIndex(null);
      setOverIndex(null);
      return;
    }
    setParsed((prev) => {
      const reflexes = [...prev.reflexes];
      const [moved] = reflexes.splice(dragIndex, 1);
      reflexes.splice(i, 0, moved);
      setSelection({ kind: "reflex", index: i });
      return { ...prev, reflexes };
    });
    setDragIndex(null);
    setOverIndex(null);
  };

  return {
    addItem,
    deleteSelected,
    duplicateSelected,
    toggleDisabled,
    onDragStart,
    onDragOver,
    onDrop,
  };
}
