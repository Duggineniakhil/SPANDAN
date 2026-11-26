import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The API token stays on the dev server: the proxy adds it to /api calls,
// so it is never shipped to the browser.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.API_URL || "http://localhost:8000";
  const token = env.API_TOKEN || "change-me";
  const proxy = {
    target,
    changeOrigin: true,
    headers: { Authorization: `Bearer ${token}` },
  };
  return {
    plugins: [react()],
    server: { port: 5173, proxy: { "/api": proxy, "/health": proxy } },
    preview: { proxy: { "/api": proxy, "/health": proxy } },
    test: { environment: "node" },
  };
});
