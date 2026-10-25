-- Migration 0009: analysis report and per-candidate survival points.
--
-- `doc` and `points` hold JSON text. One report per session; one points row per
-- (session, candidate_key).

CREATE TABLE IF NOT EXISTS analysis_reports (
    session_id TEXT PRIMARY KEY,
    doc        TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_points (
    session_id    TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    metric        TEXT NOT NULL,
    unit          TEXT NOT NULL,
    points        TEXT NOT NULL,
    PRIMARY KEY (session_id, candidate_key)
);
