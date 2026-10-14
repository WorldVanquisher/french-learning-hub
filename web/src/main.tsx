import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import PublicDemoApp from "./PublicDemoApp";
import "./styles.css";

// VITE_FLH_PUBLIC_DEMO=1 at build time produces the FLH-073 read-only public
// demo; every other build is the unchanged workbench.
const publicDemo = import.meta.env.VITE_FLH_PUBLIC_DEMO === "1";

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("root element not found");
}
createRoot(rootEl).render(<StrictMode>{publicDemo ? <PublicDemoApp /> : <App />}</StrictMode>);
