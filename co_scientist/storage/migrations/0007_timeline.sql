-- Migration 0007: per-session timeline messages.
--
-- `seq` is allocated per session (MAX+1 inside BEGIN IMMEDIATE); the unique
-- index is the backstop against duplicate sequence numbers.

CREATE TABLE IF NOT EXISTS timeline (
    session_id    TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    ts            TEXT NOT NULL,
    role          TEXT NOT NULL,
    agent         TEXT,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    body_markdown TEXT NOT NULL,
    refs          TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (session_id, seq)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_timeline_sess_seq ON timeline(session_id, seq);
