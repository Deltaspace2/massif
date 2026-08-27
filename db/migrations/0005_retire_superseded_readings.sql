-- Retire older readings that a newer one from the same source replaced.
--
-- mbnr_live sets no validity window on its statements, so every reading from
-- every ingest run stayed permanently "currently valid". recompute_feature
-- still picked the newest, so the status was right — but the older ones piled
-- up invisibly, and the moment the API began surfacing statements that did not
-- win the status slot, every lift sector reported "3 other current notices"
-- that were simply yesterday's reading of itself.
--
-- A reading is superseded by a later reading of the SAME feature, from the
-- SAME source, of the SAME type, whose validity window overlaps. The overlap
-- test matters: mbnr-openings publishes a summer and a winter season for one
-- feature, both OPENING, both from the same source, and those are two
-- different facts rather than two readings of one.

BEGIN;

WITH replaced AS (
    SELECT older.id AS old_id, MIN(newer.created_at) AS retired_at
    FROM statements older
    JOIN statements newer
      ON  newer.feature_id     = older.feature_id
      AND newer.source_id      = older.source_id
      AND newer.statement_type = older.statement_type
      AND newer.id            <> older.id
      AND newer.observed_at    > older.observed_at
      -- windows overlap (NULL bounds are unbounded, so they always overlap)
      AND (newer.valid_from IS NULL OR older.valid_to   IS NULL
           OR newer.valid_from <= older.valid_to)
      AND (older.valid_from IS NULL OR newer.valid_to   IS NULL
           OR older.valid_from <= newer.valid_to)
    WHERE older.superseded_at IS NULL
      AND older.superseded_by IS NULL
      AND newer.superseded_at IS NULL
      AND newer.superseded_by IS NULL
    GROUP BY older.id
)
UPDATE statements SET superseded_at = replaced.retired_at
FROM replaced WHERE statements.id = replaced.old_id;

INSERT INTO schema_migrations (version) VALUES ('0005_retire_superseded_readings');

COMMIT;
