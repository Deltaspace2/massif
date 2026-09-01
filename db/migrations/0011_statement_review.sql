BEGIN;

-- A person's decision about a statement a model produced.
--
-- llm.py writes `needs_review` into the payload of everything the model reads,
-- and recompute keeps those out of the status slot until someone clears them.
-- Until now there was no way to clear one, so the gate was a wall: eleven
-- readings sat on feature pages that nothing could ever act on.
--
-- SEPARATE COLUMNS RATHER THAN EDITING THE PAYLOAD. The payload is what the
-- model said and what the guards made of it; our decision about it is a
-- different fact with a different author, and overwriting `needs_review` would
-- destroy the record that the statement ever needed review. A cleared
-- statement should still be identifiable as one a machine read.
--
-- Rejection is NOT recorded here. A statement a reviewer throws out is
-- superseded, which is the mechanism that already exists for a claim that
-- should stop being served, and it removes the row from notices and history
-- as well as from the status slot. Only acceptance needs a new column.

ALTER TABLE statements
    ADD COLUMN IF NOT EXISTS reviewed_at  timestamptz,
    ADD COLUMN IF NOT EXISTS review_note  text;

-- The queue is "needs review and nobody has looked", which is the query the
-- reviewing tool opens with and the one recompute negates.
CREATE INDEX IF NOT EXISTS statements_awaiting_review_idx
    ON statements (observed_at DESC)
    WHERE reviewed_at IS NULL
      AND superseded_at IS NULL
      AND payload->'needs_review' = 'true'::jsonb;

INSERT INTO schema_migrations (version) VALUES ('0011_statement_review')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
