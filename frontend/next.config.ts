import type { NextConfig } from "next";

// Allow connect-src to reach the world-api. NEXT_PUBLIC_WORLD_API_URL is
// also read at runtime in lib/api.ts; we mirror it here so the CSP allows
// the same origin (and its websocket twin) for fetch / EventSource / WS.
const WORLD_API_URL =
  process.env.NEXT_PUBLIC_WORLD_API_URL || "http://localhost:47800";
const wsUrl = WORLD_API_URL.replace(/^http/, "ws");

// Notes on the script/style allowances:
//   - 'unsafe-eval' is required by Monaco (its JS workers compile snippets)
//     and by Next.js dev mode (HMR runtime). Acceptable trade-off in a
//     single-app same-origin spectator UI; revisit when adopting strict
//     dynamic / nonces.
//   - 'unsafe-inline' covers Tailwind-injected style tags and Next.js
//     inline boot scripts. Tightening requires nonce middleware.
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-eval' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${WORLD_API_URL} ${wsUrl}`,
  "worker-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
