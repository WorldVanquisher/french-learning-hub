/// <reference types="vitest/config" />
import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { DEMO_MESSAGE_NAMESPACES, pruneCatalog } from "./src/demo/catalogScope";

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

// Public demo builds only (VITE_FLH_PUBLIC_DEMO=1, as the app itself reads it).
// The workbench build is unchanged.
//  - main.tsx's import of the private workbench (./App) resolves to an empty
//    component, so no workbench code or lazily loaded workbench file is built
//    into, or served from, the public package. main.tsx renders PublicDemoApp
//    in these builds, so the stub never renders.
//  - The message catalogs keep only the namespaces the demo's code references
//    (src/demo/catalogScope.ts; its test walks the same graph without ./App).
const NO_WORKBENCH = "\0flh-demo-no-workbench";
function demoScope(): Plugin {
  return {
    name: "flh-demo-scope",
    enforce: "pre",
    resolveId(source, importer) {
      if (source === "./App" && importer && /[\\/]src[\\/]main\.tsx$/.test(importer)) return NO_WORKBENCH;
      return null;
    },
    load(id) {
      return id === NO_WORKBENCH ? "export default function App() { return null; }\n" : null;
    },
    transform(code, id) {
      if (!/[\\/]src[\\/]i18n[\\/](en|zh-CN)\.ts$/.test(id)) return null;
      return { code: pruneCatalog(code, DEMO_MESSAGE_NAMESPACES).code, map: null };
    },
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    ...(loadEnv(mode, process.cwd(), "VITE_").VITE_FLH_PUBLIC_DEMO === "1" ? [demoScope()] : []),
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
}));
