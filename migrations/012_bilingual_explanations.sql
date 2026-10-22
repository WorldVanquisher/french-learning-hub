-- FLH-095 bilingual learning explanations. Additive only; no backfill.
--
-- Generated explanatory text may now carry an English and a Simplified Chinese
-- variant. Every existing column keeps its meaning:
--   * entry_analyses.explanation and knowledge_units.statement stay the primary
--     text read by every existing consumer (extraction source, admission,
--     retrieval, embedding and search representations). For new bilingual rows
--     they equal the English variant.
--   * NULL variants mean the language was not recorded: every row written before
--     this migration, imported Capture analyses and fixture units. They are never
--     filled in automatically, so a stored text is never presented as a
--     translation it is not.
-- Rows stay immutable: these columns are written once, on insert.

-- Analysis explanation variants. When explanation_en is present it equals
-- explanation (enforced by the application).
ALTER TABLE entry_analyses ADD COLUMN explanation_en TEXT;
ALTER TABLE entry_analyses ADD COLUMN explanation_zh TEXT;

-- Knowledge-unit statement variants. When statement_en is present it equals
-- statement (enforced by the application). canonical and example are unchanged.
ALTER TABLE knowledge_units ADD COLUMN statement_en TEXT;
ALTER TABLE knowledge_units ADD COLUMN statement_zh TEXT;

-- Human feedback per explanation language:
--   * corrected_explanation_en / _zh: a person's corrected text in that language
--     (status = corrected only). The legacy corrected_explanation stays for
--     analyses without recorded variants and is never combined with these.
--   * reviewed_explanation_languages: the explanation languages shown when the
--     decision was recorded, as a comma-separated subset of 'en,zh' in that
--     order; NULL means not recorded (all earlier feedback).
ALTER TABLE analysis_feedback ADD COLUMN corrected_explanation_en TEXT;
ALTER TABLE analysis_feedback ADD COLUMN corrected_explanation_zh TEXT;
ALTER TABLE analysis_feedback ADD COLUMN reviewed_explanation_languages TEXT
    CHECK (reviewed_explanation_languages IS NULL
           OR reviewed_explanation_languages IN ('en', 'zh', 'en,zh'));
