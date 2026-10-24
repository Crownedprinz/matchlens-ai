import type { NextConfig } from "next";
if (process.env.NODE_ENV === "production" && !process.env.NEXT_PUBLIC_API_URL) {
  throw new Error("NEXT_PUBLIC_API_URL is required for a production static build");
}
const nextConfig: NextConfig = { reactStrictMode: true, output: "export", trailingSlash: true };
export default nextConfig;
