// Human-readable lifespan from raw tick counts. Each tick is `WORLD_TICK_SECONDS`
// real seconds (default 6s). The spectator UI deliberately shows real-time
// duration (not in-fiction time) — the headline metric is "how long has this
// hero been alive in the world", and that's a wall-clock thing.

export const TICK_SECONDS = 6;

export function ticksToSeconds(ticks: number): number {
  return Math.max(0, Math.floor(ticks * TICK_SECONDS));
}

export function formatLifespan(ticks: number): string {
  const s = ticksToSeconds(ticks);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const mr = m % 60;
  if (h < 24) return mr ? `${h}h ${mr}m` : `${h}h`;
  const d = Math.floor(h / 24);
  const hr = h % 24;
  return hr ? `${d}d ${hr}h` : `${d}d`;
}
