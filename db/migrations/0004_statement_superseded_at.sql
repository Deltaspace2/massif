-- Let a statement be retired without naming a successor.
--
-- `superseded_by` is a self-FK: it can only say "this row was replaced by
-- that specific row". Re-extraction is not 1:1. Re-running an improved parser
-- over a stored document turns three statements into two, or into none at all
-- — a tightened classifier deciding the mayor's op-ed was never a closure is
-- the whole point of re-extracting. Those orphans have no successor to point
-- at, so `superseded_by` stays NULL, so `recompute_feature` keeps counting
-- them as live. A statement you meant to retire that keeps voting is exactly
-- the plausible-silent-wrong-answer shape this schema keeps getting bitten by.
--
-- So retirement gets its own mark. `superseded_at` says THAT a statement is
-- retired; `superseded_by` stays, and still says WHICH row replaced it when
-- there is a single obvious one. Nothing is deleted: superseded statements
-- remain readable as the history of what the parser used to think.

BEGIN;

ALTER TABLE statements ADD COLUMN superseded_at TIMESTAMPTZ;

-- Anything already pointed at a successor was retired at that moment; we no
-- longer know when, so use created_at of the row that replaced it. Without
-- this the new filter would resurrect rows the old filter excluded.
UPDATE statements AS old
SET superseded_at = COALESCE(new.created_at, now())
FROM statements AS new
WHERE old.superseded_by = new.id
  AND old.superseded_at IS NULL;

-- The "currently live" index has to follow the new definition of live.
DROP INDEX IF EXISTS statements_current_idx;
CREATE INDEX statements_current_idx ON statements (feature_id)
    WHERE superseded_by IS NULL AND superseded_at IS NULL;

-- Re-extraction retires and rewrites a whole document's output at once, so
-- that is the access path.
CREATE INDEX statements_document_idx ON statements (document_id)
    WHERE superseded_at IS NULL;

INSERT INTO schema_migrations (version) VALUES ('0004_statement_superseded_at');

COMMIT;
