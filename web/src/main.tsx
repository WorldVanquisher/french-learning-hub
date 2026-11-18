import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import PublicDemoApp from "./PublicDemoApp";
import { installKeepFieldInView } from "./keepFieldInView";
import "./styles.css";
import "./theme-endfield.css";

// VITE_FLH_PUBLIC_DEMO=1 at build time produces the FLH-073 read-only public
// demo; every other build is the unchanged workbench.
const publicDemo = import.meta.env.VITE_FLH_PUBLIC_DEMO === "1";

// A release or staging build names itself (VITE_FLH_BUILD_ID, see
// vite.config.ts): readable on the page element, and part of the bundle, so
// two candidates never share an entry script name (see freshness.tsx).
if (import.meta.env.VITE_FLH_BUILD_ID) {
  document.documentElement.dataset.flhBuild = import.meta.env.VITE_FLH_BUILD_ID;
}

// A focused text field stays in view when a phone keyboard opens.
installKeepFieldInView();

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("root element not found");
}
createRoot(rootEl).render(<StrictMode>{publicDemo ? <PublicDemoApp /> : <App />}</StrictMode>);
