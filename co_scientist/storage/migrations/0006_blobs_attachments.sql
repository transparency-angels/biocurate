-- Migration 0006: generic blob store and attachment metadata.
--
-- `blobs` is the SQLite stand-in for GridFS; `attachments` holds the metadata
-- of user uploads (the bytes live in `blobs`).

CREATE TABLE IF NOT EXISTS blobs (
    id         TEXT PRIMARY KEY,
    bucket     TEXT NOT NULL,
    name       TEXT NOT NULL,
    data       BLOB NOT NULL,
    metadata   TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    filename     TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size         INTEGER NOT NULL,
    sha256       TEXT NOT NULL,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,
    blob_id      TEXT NOT NULL,
    uploaded_at  TEXT NOT NULL,
    error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_attachments_sess ON attachments(session_id, uploaded_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_attachments_dedupe
    ON attachments(session_id, sha256, filename);
