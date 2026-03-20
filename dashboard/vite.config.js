import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: false,
    minify: "esbuild",
  },
  server: {
    // Dev proxy — mirrors nginx proxy config for local development
    proxy: {
      "/api": {
        target: "http://localhost:8100",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8100",
        changeOrigin: true,
      },
      "/docs": {
        target: "http://localhost:8100",
        changeOrigin: true,
      },
      "/openapi.json": {
        target: "http://localhost:8100",
        changeOrigin: true,
      },
    },
  },
});
