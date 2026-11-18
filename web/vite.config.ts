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

// Explicit build configuration for a release or staging candidate (all optional):
//   VITE_FLH_API_BASE  the API prefix the page calls, default "/api". It must be a
//                      same-origin path: the backend allows no cross-origin calls.
//   VITE_FLH_BUILD_ID  the candidate's identity (for example a tree digest),
//                      written into index.html as <meta name="flh-build">.
// Either one, when invalid, stops the build instead of producing a page that
// calls the wrong place or names the wrong candidate.
const apiBase = process.env.VITE_FLH_API_BASE ?? "/api";
if (!/^\/[A-Za-z0-9._~-]+(\/[A-Za-z0-9._~-]+)*$/.test(apiBase)) {
  throw new Error(`VITE_FLH_API_BASE must be a same-origin path such as /api, got ${JSON.stringify(apiBase)}`);
}
const buildId = process.env.VITE_FLH_BUILD_ID ?? "";
if (buildId !== "" && !/^[A-Za-z0-9._:+-]{1,80}$/.test(buildId)) {
  throw new Error(`VITE_FLH_BUILD_ID must be 1-80 characters of [A-Za-z0-9._:+-], got ${JSON.stringify(buildId)}`);
}

export default defineConfig({
  plugins: [
    react(),
    {
      name: "flh-build-identity",
      transformIndexHtml: () => [
        { tag: "meta", attrs: { name: "flh-api-base", content: apiBase }, injectTo: "head" },
        ...(buildId ? [{ tag: "meta", attrs: { name: "flh-build", content: buildId }, injectTo: "head" as const }] : []),
      ],
    },
  ],
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
    // Test-only. Node 26 enables an experimental built-in localStorage that,
    // without --localstorage-file, is undefined and hides jsdom's, so every test
    // touching storage fails. The test workers turn it off; Node versions without
    // the flag are left alone, and the built app never runs under Node.
    ...(process.allowedNodeEnvironmentFlags.has("--no-experimental-webstorage")
      ? { poolOptions: { forks: { execArgv: ["--no-experimental-webstorage"] } } }
      : {}),
  },
});
