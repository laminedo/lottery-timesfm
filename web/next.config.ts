import type { NextConfig } from "next";

// The FastAPI backend. The browser only ever talks to this app; /api is proxied.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

// The read-only demo: a static export that reads public/data instead of calling the API.
// Build it with `npm run build:static`; set NEXT_PUBLIC_BASE_PATH when it is served under a sub-path.
const IS_STATIC = process.env.NEXT_PUBLIC_STATIC_DATA === "1";

const shared: NextConfig = {
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

const staticExport: NextConfig = {
  // Cache Components prerenders partially and streams the rest, which needs a server; a static export has none.
  output: "export",
  // Static hosts serve /powerball/ from powerball/index.html.
  trailingSlash: true,
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
};

const server: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
      {
        // The service worker must never be served stale, or installed apps cannot update.
        source: "/sw.js",
        headers: [
          { key: "Content-Type", value: "application/javascript; charset=utf-8" },
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self'" },
        ],
      },
    ];
  },
};

const nextConfig: NextConfig = { ...shared, ...(IS_STATIC ? staticExport : server) };

export default nextConfig;
