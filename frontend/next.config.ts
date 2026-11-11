import type { NextConfig } from "next";
const nextConfig: NextConfig = {
  distDir: process.env.ATLAS_BUILD_DIR || ".next",
  output: "standalone",
  poweredByHeader: false,
  devIndicators: false,
  turbopack: { root: process.cwd() },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_URL || "http://127.0.0.1:8000"}/api/:path*`,
      },
    ];
  },
};
export default nextConfig;
