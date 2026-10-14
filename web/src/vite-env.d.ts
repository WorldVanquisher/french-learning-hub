// Build-time flags read through import.meta.env (Vite replaces them at build).
interface ImportMetaEnv {
  // "1" builds the FLH-073 read-only public demo instead of the workbench.
  readonly VITE_FLH_PUBLIC_DEMO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
