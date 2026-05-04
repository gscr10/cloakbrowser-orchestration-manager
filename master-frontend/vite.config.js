import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(() => {
  const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://localhost:8080";
  return {
    plugins: [react()],
    server: {
      allowedHosts: [".monkeycode-ai.online"],
      proxy: {
        "/api": apiProxyTarget
      }
    }
  };
});
