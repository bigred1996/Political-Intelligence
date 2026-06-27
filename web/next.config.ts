import type { NextConfig } from "next";

// Proxy API + server-rendered report/PDF routes to the FastAPI backend so the
// browser stays same-origin in dev (no CORS). Override with POLARIS_API_BASE.
const API_BASE = process.env.POLARIS_API_BASE ?? "http://127.0.0.1:8077";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Pin the workspace root — multiple lockfiles exist up the tree.
  turbopack: { root: __dirname },
  // Default rewrite-proxy timeout is 30s — too short for /api/research,
  // which runs many sequential real Claude calls and can take minutes
  // (deep tier: up to 6 rounds / 36 interpretations).
  experimental: { proxyTimeout: 600_000 },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_BASE}/api/:path*` },
      { source: "/report/:path*", destination: `${API_BASE}/report/:path*` },
      { source: "/memo/:path*", destination: `${API_BASE}/memo/:path*` },
    ];
  },
};

export default nextConfig;
