import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Frontend is a thin SPA over the world-api; no server-side fetching here.
  reactStrictMode: true,
};

export default nextConfig;
