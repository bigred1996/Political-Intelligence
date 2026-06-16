import type { NextConfig } from "next";

// Proxy API + server-rendered report/PDF routes to the FastAPI backend so the
// browser stays same-origin in dev (no CORS). Override with POLARIS_API_BASE.
const API_BASE = process.env.POLARIS_API_BASE ?? "http://127.0.0.1:8077";

const nextConfig: NextConfig = {
  // Pin the workspace root — multiple lockfiles exist up the tree.
  turbopack: { root: __dirname },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_BASE}/api/:path*` },
      { source: "/report/:path*", destination: `${API_BASE}/report/:path*` },
    ];
  },
};

export default nextConfig;
