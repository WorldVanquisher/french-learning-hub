// A synthetic, accent-rich workbook note for the practice-draft tests.
import type { NotebookItem } from "../types/notebook";

export const accentItem = (entry: number, over: Partial<NotebookItem> = {}): NotebookItem => ({
  entry_id: entry,
  capture_id: `listening-7-900-${entry}`,
  saved_at: "2026-11-18T09:00:00Z",
  skill: "listening",
  source: { type: "listening_item", record_id: 900, item: entry, attempt: "Parce qu'elle préfère l'été." },
  title: "Hélène à l'hôpital Saint-Éloi",
  prompt: "Pourquoi Hélène choisit-elle le cours du soir à l'école Saint-Éloi ?",
  category: "detail",
  quote: null,
  reference: "Parce qu'elle travaille à l'hôpital la journée — « c'est ça » !",
  explanation_en: "e",
  explanation_zh: "z",
  hint_en: null,
  hint_zh: null,
  link: { listening_material_id: 7, listening_exercise_id: 900, listening_transcript_version: 1 },
  record: { original_input: "x", original_context: "y" },
  retry: { marked: false, since: null },
  source_status: "resolved",
  reference_origin: "authored",
  generator: "authored:flh_listening_script_pack_v1",
  latest_version: null,
  ...over,
});
