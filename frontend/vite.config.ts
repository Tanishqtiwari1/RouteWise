/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  // GitHub Pages serves the demo from /<repo>/; set VITE_BASE=/RouteWise/ for that build.
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    // Same-origin API in development; the target is the local backend.
    proxy: { "/api": { target: process.env.ROUTEWISE_API_PROXY ?? "http://localhost:8010", changeOrigin: true } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], css: false },
});
