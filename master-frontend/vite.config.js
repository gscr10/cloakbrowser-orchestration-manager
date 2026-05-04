import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(() => {
  const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://localhost:8080";
  const allowedHosts = (process.env.VITE_ALLOWED_HOSTS || ".monkeycode-ai.online")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean);
  return {
    plugins: [react()],
    server: {
      allowedHosts,
      proxy: {
        "/api": apiProxyTarget
      }
    }
  };
});
