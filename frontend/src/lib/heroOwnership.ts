// Local store of {heroId → auth_token} so the browser remembers which
// heroes the user deployed. Used by the prompt inspector to authenticate
// the owner-only GET. There is no real session/login — possession of the
// auth_token is the proof of ownership the world-api already trusts.

const KEY = "worldofagents:owned_heroes:v1";

type Owned = Record<string, string>;

function read(): Owned {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") return parsed as Owned;
  } catch {}
  return {};
}

function write(value: Owned): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(value));
  } catch {}
}

export function rememberOwnedHero(heroId: string, authToken: string): void {
  if (!heroId || !authToken) return;
  const o = read();
  o[heroId] = authToken;
  write(o);
}

export function ownerTokenFor(heroId: string): string | null {
  const o = read();
  return o[heroId] ?? null;
}
