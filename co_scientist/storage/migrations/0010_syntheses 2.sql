-- Migration 0010: the final synthesis (overview + sources, cite-lines JSON).
--
-- `doc` holds JSON text. One synthesis per session.

CREATE TABLE IF NOT EXISTS syntheses (
    session_id TEXT PRIMARY KEY,
    doc        TEXT NOT NULL,
    created_at TEXT NOT NULL
);
