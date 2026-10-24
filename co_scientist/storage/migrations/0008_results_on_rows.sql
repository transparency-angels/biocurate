-- Migration 0008: citations, evidence and data evidence live on the rows.
--
-- All four columns hold JSON. Rows written before this migration have NULL,
-- which the repos read back as [] / None. The canonical schema.sql already
-- carries these columns for fresh databases; the duplicate-column error from
-- the first ALTER is tolerated by db._apply_pending.

ALTER TABLE hypotheses ADD COLUMN citations TEXT;
ALTER TABLE hypotheses ADD COLUMN data_evidence TEXT;
ALTER TABLE reviews ADD COLUMN evidence TEXT;
ALTER TABLE reviews ADD COLUMN assumptions TEXT;
