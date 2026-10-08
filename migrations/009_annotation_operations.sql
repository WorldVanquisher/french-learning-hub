-- Committed receipts only; no pending reservation or cancellation semantics.
CREATE TABLE annotation_operations (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
