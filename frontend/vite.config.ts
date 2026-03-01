import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/ws/drawing": {
        target: "ws://localhost:8002",
        ws: true,
        rewrite: (path) => path.replace(/^\/ws\/drawing/, "/ws"),
      },
      "/api/drawing": {
        target: "http://localhost:8002",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/drawing/, ""),
      },
      "/api/orchestrator": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/orchestrator/, ""),
      },
    },
  },
});
