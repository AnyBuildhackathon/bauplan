import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The agent backend (FastAPI, agent/) listens on 8100. Proxying /api keeps the
// SSE stream and prompt calls same-origin, so the backend needs no CORS setup.
const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8100";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      // CAD parts, renders and other files the backend produces.
      "/files": { target: BACKEND, changeOrigin: true },
    },
  },
  preview: { port: 5180, strictPort: true },
  // three.js is large on its own; the dashboard runs from localhost, so big chunks are fine.
  build: { chunkSizeWarningLimit: 2000 },
});
