import type { NextConfig } from "next";
const productionApiUrl = process.env.NEXT_PUBLIC_API_URL;
if (process.env.NODE_ENV === "production") {
  if (!productionApiUrl) throw new Error("NEXT_PUBLIC_API_URL is required for a production static build");
  const parsedApiUrl = new URL(productionApiUrl);
  if (
    parsedApiUrl.protocol !== "https:" ||
    parsedApiUrl.hostname === "localhost" ||
    parsedApiUrl.hostname === "127.0.0.1" ||
    parsedApiUrl.hostname.endsWith(".example.com") ||
    parsedApiUrl.hostname.endsWith(".example.invalid")
  ) {
    throw new Error("NEXT_PUBLIC_API_URL must be the real HTTPS production API URL");
  }
}
const nextConfig: NextConfig = { reactStrictMode: true, output: "export", trailingSlash: true };
export default nextConfig;
