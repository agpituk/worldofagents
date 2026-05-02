"use client";

// Structured trace tree — renders the per-call tool_events array as a
// nested tree with color coding. Composite expansions become parents;
// `tool.gated` / `tool.clamped` events surface inline.

type TraceEntry = { event: string; payload: Record<string, any> };

type Props = {
  trace: TraceEntry[];
};

type Node = {
  label: string;
  detail?: string;
  tone: "ok" | "gated" | "clamp" | "error" | "info";
  children: Node[];
};

export default function TraceTree({ trace }: Props) {
  const root = buildTree(trace);
  return (
    <ul className="text-xs font-mono space-y-1">
      {root.map((n, i) => (
        <NodeRow key={i} node={n} depth={0} />
      ))}
    </ul>
  );
}

function NodeRow({ node, depth }: { node: Node; depth: number }) {
  const dotColor =
    node.tone === "ok"
      ? "text-emerald-400"
      : node.tone === "gated"
      ? "text-amber-400"
      : node.tone === "clamp"
      ? "text-sky-400"
      : node.tone === "error"
      ? "text-rose-400"
      : "text-zinc-400";
  return (
    <li>
      <div
        className="flex gap-2"
        style={{ paddingLeft: `${depth * 14}px` }}
      >
        <span className={dotColor}>●</span>
        <span className="text-zinc-200">{node.label}</span>
        {node.detail && (
          <span className="text-zinc-500 truncate">{node.detail}</span>
        )}
      </div>
      {node.children.length > 0 && (
        <ul className="space-y-1">
          {node.children.map((c, i) => (
            <NodeRow key={i} node={c} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

function buildTree(trace: TraceEntry[]): Node[] {
  // Use the linear order of events. tool.expanded opens a child block
  // that subsequent events attach to until the next sibling tool.expanded
  // at the same logical depth — but we don't have explicit depth, so we
  // approximate: the first tool.expanded is the root; subsequent
  // expansions nest one level deeper, child events attach to the most
  // recent open node.
  const stack: Node[] = [];
  const roots: Node[] = [];

  for (const entry of trace) {
    const node = entryToNode(entry);
    if (entry.event === "tool.expanded") {
      if (stack.length === 0) {
        roots.push(node);
      } else {
        stack[stack.length - 1].children.push(node);
      }
      stack.push(node);
    } else if (stack.length > 0) {
      stack[stack.length - 1].children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

function entryToNode(entry: TraceEntry): Node {
  const { event, payload } = entry;
  if (event === "tool.expanded") {
    return {
      label: `${payload.tool}(${shortArgs(payload.args)})`,
      tone: "ok",
      children: [],
    };
  }
  if (event === "tool.gated") {
    return {
      label: "blocked by when",
      detail: payload.reason ?? "",
      tone: "gated",
      children: [],
    };
  }
  if (event === "tool.clamped") {
    return {
      label: `clamp ${payload.verb}.${payload.param}`,
      detail: `${JSON.stringify(payload.from)} → ${JSON.stringify(payload.to)}`,
      tone: "clamp",
      children: [],
    };
  }
  if (event === "tool.clamp.invalid" || event === "tool.clamp.error") {
    return {
      label: `${event} ${payload.verb}.${payload.param}`,
      detail: payload.error ?? payload.reason ?? "",
      tone: "error",
      children: [],
    };
  }
  if (event === "tool.after.step") {
    const step = payload.step ?? {};
    return {
      label: `after: ${step.do ?? "?"}`,
      detail: shortArgs(step.args),
      tone: "ok",
      children: [],
    };
  }
  if (event === "tool.after.step.failed") {
    return {
      label: `after FAILED: ${payload.step?.do ?? "?"}`,
      detail: payload.error ?? "",
      tone: "error",
      children: [],
    };
  }
  if (event === "tool.budget_exceeded") {
    return {
      label: "budget exceeded",
      detail: `primitives_used=${payload.primitives_used}, ms=${payload.elapsed_ms}`,
      tone: "error",
      children: [],
    };
  }
  if (event === "tool.expression.type_error") {
    return {
      label: `expr type error (${payload.stage})`,
      detail: payload.error ?? "",
      tone: "error",
      children: [],
    };
  }
  if (event === "llm.tools_offered") {
    return {
      label: `LLM offered ${payload.tools_offered?.length ?? 0} tools`,
      detail: `chose ${payload.chosen_tool ?? "—"}`,
      tone: "info",
      children: [],
    };
  }
  return {
    label: event,
    detail: JSON.stringify(payload),
    tone: "info",
    children: [],
  };
}

function shortArgs(args: any): string {
  if (!args) return "";
  if (typeof args !== "object") return String(args);
  const keys = Object.keys(args);
  if (keys.length === 0) return "";
  return JSON.stringify(args).slice(0, 80);
}
