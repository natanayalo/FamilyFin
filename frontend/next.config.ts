import type { NextConfig } from "next";

const localDev = process.env.FAMILY_FINANCE_LOCAL_DEV === "1";
const hotReload = process.env.NODE_ENV === "development";
const apiPort = process.env.FAMILY_FINANCE_API_PORT || "8000";
if (localDev && (!/^\d+$/.test(apiPort) || Number(apiPort) < 1 || Number(apiPort) > 65535)) {
  throw new Error("FAMILY_FINANCE_API_PORT must be between 1 and 65535");
}

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  `connect-src 'self'${hotReload ? " ws://127.0.0.1:* ws://localhost:*" : ""}`,
  "font-src 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "img-src 'self' data: blob:",
  "manifest-src 'self'",
  "object-src 'none'",
  `script-src 'self' 'unsafe-inline'${hotReload ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "worker-src 'self' blob:",
].join("; ");

const nextConfig: NextConfig = {
  // Docker's standalone server carries the complete compiled production config.
  // The existing Linux npm start deployment keeps its original output mode.
  output: process.env.FAMILY_FINANCE_DOCKER === "1" ? "standalone" : undefined,
  poweredByHeader: false,
  distDir: localDev ? ".next-local" : ".next",
  async rewrites() {
    return localDev ? [{ source: "/api/:path*", destination: `http://127.0.0.1:${apiPort}/api/:path*` }] : [];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "Cache-Control", value: "private, no-store" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
