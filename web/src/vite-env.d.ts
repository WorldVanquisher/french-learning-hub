// Build-time flags read through import.meta.env (Vite replaces them at build).
interface ImportMetaEnv {
  // "1" builds the FLH-073 read-only public demo instead of the workbench.
  readonly VITE_FLH_PUBLIC_DEMO?: string;
  // Same-origin API prefix (default "/api"; validated in vite.config.ts).
  readonly VITE_FLH_API_BASE?: string;
  // Candidate identity written into index.html (validated in vite.config.ts).
  readonly VITE_FLH_BUILD_ID?: string;
  // The public demo's https address, linked from the private entry preview
  // (portal.tsx validates it; unset or invalid means no link).
  readonly VITE_FLH_PUBLIC_DEMO_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
