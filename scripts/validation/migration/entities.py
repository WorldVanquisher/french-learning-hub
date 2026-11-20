"""The migration surface of the private learner database (shared by inventory.py and rehearse.py).

Standard library only. It names, for every table of migrations 001-021:
  role      learner (authored by the learner), learner-derived (made from the learner's actions:
            marks, attempts, sessions), generated (provider or rule output about learner data),
            authored (pack content imported as rows), operational (requests, leases, receipts),
            cache (rebuildable from other rows: embeddings, semantic index bookkeeping), ledger;
  daily     True when daily practice or history reads it (Review Today, the learning week, the
            Mistake Notebook, Speaking, Writing, Listening, Reading, Mock Exam, the history export);
  private   its free-text columns that may hold the learner's own words (counted by size, never
            printed);
  revision  the column that numbers versions of one source, when it has one;
  when      its timestamp columns.
The destination of every table in a NAS -> AWS move is the same table and column of the same
schema (the move is a byte copy of app.db, then the server's own migrations); DESTINATION records
that identity mapping, and the history-export kind each table feeds, if any.
"""

TABLES = {
    # learner records and their interpretation
    "learning_entries": dict(role="learner", daily=True, private=["original_input", "original_context"], when=["created_at", "updated_at"], export="record"),
    "learning_captures": dict(role="learner", daily=True, private=["discussion_summary"], when=["created_at"], export="record"),
    "learning_capture_sources": dict(role="learner", daily=True, private=[], when=["created_at"], export="record"),
    "mistake_retry_marks": dict(role="learner-derived", daily=True, private=[], when=["created_at"], export="record"),
    "entry_analyses": dict(role="generated", daily=False, private=[], when=["created_at"], export="record"),
    "analysis_feedback": dict(role="learner", daily=False, private=["user_note", "corrected_explanation", "corrected_explanation_en", "corrected_explanation_zh"], when=["created_at"], export="record"),
    # knowledge (extraction, concepts, annotation)
    "knowledge_extractions": dict(role="generated", daily=False, private=[], when=["created_at"]),
    "knowledge_units": dict(role="generated", daily=False, private=[], when=["created_at"]),
    "knowledge_admission_recommendations": dict(role="generated", daily=False, private=[], when=["created_at"]),
    "knowledge_admission_overrides": dict(role="learner", daily=False, private=["note"], when=["created_at"]),
    "knowledge_concepts": dict(role="learner", daily=False, private=[], when=["created_at", "updated_at"]),
    "entry_current_extractions": dict(role="learner", daily=False, private=[], when=["updated_at"]),
    "unit_concept_links": dict(role="learner", daily=False, private=[], when=["created_at"]),
    "unit_concept_memberships": dict(role="learner", daily=False, private=[], when=["updated_at"]),
    "unit_resolution_judgments": dict(role="learner", daily=False, private=["note"], when=["created_at"]),
    "unit_concept_distinctions": dict(role="learner", daily=False, private=[], when=["created_at"]),
    "annotation_operations": dict(role="operational", daily=False, private=[], when=["created_at"]),
    "concept_suggestion_runs": dict(role="operational", daily=False, private=[], when=["created_at"]),
    "concept_suggestion_items": dict(role="generated", daily=False, private=[], when=["created_at"]),
    "concept_suggestion_confirmations": dict(role="learner", daily=False, private=[], when=["created_at"]),
    # listening
    "listening_materials": dict(role="learner", daily=True, private=[], when=["created_at"], export="lesson"),
    "listening_transcripts": dict(role="learner", daily=True, private=["segments"], revision="version", when=["created_at"], export="lesson"),
    "listening_exercises": dict(role="generated", daily=True, private=[], when=["created_at"], export="lesson"),
    "listening_preparations": dict(role="operational", daily=False, private=[], when=["started_at", "finished_at"]),
    "listening_pull_runs": dict(role="operational", daily=False, private=[], when=["started_at", "finished_at"]),
    "listening_playlist_items": dict(role="operational", daily=False, private=[], when=["created_at"]),
    "listening_notifications": dict(role="operational", daily=False, private=[], when=["started_at", "finished_at"]),
    # reading
    "reading_lessons": dict(role="learner", daily=True, private=[], when=["created_at"], export="lesson"),
    "reading_passages": dict(role="learner", daily=True, private=["segments"], revision="version", when=["created_at"], export="lesson"),
    "reading_exercises": dict(role="generated", daily=True, private=[], when=["created_at"], export="lesson"),
    "reading_preparations": dict(role="operational", daily=False, private=[], when=["started_at", "finished_at"]),
    # writing
    "writing_tasks": dict(role="learner", daily=True, private=["prompt"], when=["created_at"], export="writing"),
    "writing_drafts": dict(role="learner", daily=True, private=["text"], revision="version", when=["created_at"], export="writing"),
    "writing_feedback": dict(role="generated", daily=True, private=[], when=["created_at"], export="writing"),
    "writing_feedback_requests": dict(role="operational", daily=False, private=[], when=["started_at", "finished_at"]),
    # speaking (audio is never stored: takes keep metadata only)
    "speaking_exercises": dict(role="authored", daily=True, private=[], when=["created_at"], export="speaking"),
    "speaking_takes": dict(role="learner", daily=True, private=[], when=["created_at"], export="speaking"),
    "speaking_transcriptions": dict(role="generated", daily=True, private=["text"], when=["created_at"], export="speaking"),
    "speaking_transcription_requests": dict(role="operational", daily=False, private=[], when=["started_at", "finished_at"]),
    "speaking_transcripts": dict(role="learner", daily=True, private=["text"], revision="version", when=["created_at"], export="speaking"),
    "speaking_feedback": dict(role="generated", daily=True, private=[], when=["created_at"], export="speaking"),
    "speaking_feedback_requests": dict(role="operational", daily=False, private=[], when=["started_at", "finished_at"]),
    # mock exam
    "exam_sessions": dict(role="learner-derived", daily=True, private=[], when=["started_at", "deadline_at"], export="exam"),
    "exam_session_items": dict(role="authored", daily=True, private=[], when=[], export="exam"),
    "exam_answers": dict(role="learner", daily=True, private=[], when=["saved_at"], export="exam"),
    "exam_submissions": dict(role="learner", daily=True, private=[], when=["submitted_at"], export="exam"),
    # semantic search (derived, rebuildable)
    "semantic_embedding_cache": dict(role="cache", daily=False, private=[], when=["created_at"]),
    "semantic_index_collections": dict(role="cache", daily=False, private=[], when=["updated_at"]),
    "semantic_index_points": dict(role="cache", daily=False, private=[], when=["published_at"]),
    "semantic_index_spaces": dict(role="cache", daily=False, private=[], when=[]),
    "semantic_index_physical_collections": dict(role="cache", daily=False, private=[], when=["created_at", "updated_at"]),
    "semantic_index_manifest": dict(role="cache", daily=False, private=[], when=[]),
    "schema_migrations": dict(role="ledger", daily=False, private=[], when=["applied_at"]),
}

# Logical references the schema cannot declare (MistakeSourceResolver): a notebook record names a
# stored item by (source type, record id, 1-based item) inside that record's JSON content.
SOURCE_REFS = {
    "listening_item": ("listening_exercises", "items"),
    "reading_item": ("reading_exercises", "items"),
    "writing_correction": ("writing_feedback", "corrections"),
    "speaking_improvement": ("speaking_feedback", "improvements"),
}

# Rows a rehearsal may leave out, and why (R3-009).
EXCLUDABLE = {
    "cache": "rebuildable from learner rows (semantic-index sync); never learner data",
    "operational": "request and lease bookkeeping; copied byte for byte, but never compared field by field after a move",
}


def destination(table: str) -> str:
    return f"{table} (same columns; the server's migrations upgrade the copy in place)"
