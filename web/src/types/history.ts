// Portable learning history (learning_history_export_v1, private workbench).

export interface HistoryExportOptions {
  transcripts: boolean;
  notes: boolean;
}

export interface HistoryExportFile {
  format: "ndjson" | "text";
  extension: string;
  opens_as_text: boolean;
  app_import: "preview_only" | "none";
  description: string;
}

// GET /learning-history/export-preview
export interface HistoryExportPreview {
  header: {
    format: "learning_history_export_v1";
    exported_at: string;
    included: { transcripts: boolean; notes: boolean; audio: false; credentials: false };
    never_exported: string[];
    parts: Record<string, boolean>;
    counts: Record<string, number>;
    omitted_texts: Record<string, number>;
  };
  footer: { records: number; sha256: string };
  bytes: number;
  files: HistoryExportFile[];
}

export interface HistoryImportRow {
  line: number;
  kind: string;
  key: string;
  status: "new" | "same" | "conflict";
  fields: string[];
  resolution: string;
}

// POST /learning-history/import-preview: a report only, nothing written.
export interface HistoryImportPreview {
  format: string | null;
  integrity: "complete" | "truncated" | "corrupted" | "unchecked" | "unreadable";
  problems: string[];
  counts: Record<string, number>;
  missing_fields: string[];
  included: Record<string, boolean> | null;
  rows: HistoryImportRow[];
  new: number;
  same: number;
  conflicts: number;
  writes: false;
}
