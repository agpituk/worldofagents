"use client";

import { useEffect, useRef, useState } from "react";
import { WORLD_API_URL } from "./api";

export type StreamEvent = {
  kind: "tick" | "narrator" | "hello" | "ping";
  ts: number;
  data: any;
};

/**
 * Subscribe to a zone's SSE stream. Returns the most recent N events (newest
 * last). The stream auto-reconnects via the browser's native EventSource.
 *
 * `keepHistory` mode: when the slug changes (e.g. a hero travels), do NOT
 * reset the events buffer — keep accumulating so the spectator follows the
 * subject across zones. The "moved to X" transition is naturally visible
 * because the previous zone's tail and the new zone's head sit next to each
 * other in the same feed.
 */
export function useZoneStream(
  slug: string | undefined,
  max = 200,
  keepHistory = false,
) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<"connecting" | "open" | "closed">("connecting");
  const ref = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!slug) return;
    if (!keepHistory) setEvents([]);
    const url = `${WORLD_API_URL}/zones/${slug}/stream`;
    const es = new EventSource(url);
    ref.current = es;
    setStatus("connecting");

    const onOpen = () => setStatus("open");
    const onError = () => setStatus("closed");

    const append = (kind: StreamEvent["kind"]) => (ev: MessageEvent) => {
      let data: any = ev.data;
      try {
        data = JSON.parse(ev.data);
      } catch {
        /* ping carries no data */
      }
      setEvents((prev) => {
        const next = [...prev, { kind, ts: Date.now(), data }];
        return next.length > max ? next.slice(next.length - max) : next;
      });
    };

    es.addEventListener("open", onOpen);
    es.addEventListener("error", onError);
    es.addEventListener("hello", append("hello"));
    es.addEventListener("tick", append("tick"));
    es.addEventListener("narrator", append("narrator"));
    es.addEventListener("ping", append("ping"));

    return () => {
      es.close();
      ref.current = null;
    };
  }, [slug, max, keepHistory]);

  return { events, status };
}

