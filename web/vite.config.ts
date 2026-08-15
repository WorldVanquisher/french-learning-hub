/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Go backend is the source of data. In development the frontend talks to it
// through a "/api" prefix that Vite proxies to the backend, so the browser makes
// same-origin requests and there is no CORS to weaken on the backend. The backend
// itself is never modified for the frontend's convenience: the proxy strips the
// "/api" prefix before forwarding, so the Go routes stay exactly as they are.
//
// Override the backend location with FRENCH_HUB_URL when it is not on :8080.
const backend = process.env.FRENCH_HUB_URL ?? "http://localhost:8080";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: backend,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
