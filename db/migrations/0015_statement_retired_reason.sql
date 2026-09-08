BEGIN;

-- Why a statement was retired, so the feature page can tell two cases apart.
--
-- `superseded_at` set with `superseded_by` null is NOT a distinguishing shape:
-- `retire_replaced` leaves it that way for every ordinary supersession, and
-- mbnr-live alone has 659 such rows. Three different things share it —
--
--   ordinary  a newer reading arrived and replaced this one
--   reextract a better parser no longer emits it; we retract it
--   unmentioned  the source stopped listing the feature (retire_unmentioned)
--
-- — and only the third is worth showing a reader. The first is superseded by
-- something they can already see; the second is a claim we withdrew and should
-- not repeat.
ALTER TABLE statements ADD COLUMN IF NOT EXISTS retired_reason TEXT;

COMMENT ON COLUMN statements.retired_reason IS
    'Why superseded_at was set: null for an ordinary replacement, '
    '''unmentioned'' when the source stopped listing the feature.';

-- Backfill the five Megève rows, which were retired by `retire_unmentioned`
-- on 8 Sep 2026 shortly before this column existed. Without this the feature
-- page keeps printing "no source has published anything about this" on
-- exactly the five features the whole mechanism was built for.
--
-- Selected on the GAP between last_seen_at and superseded_at, which is what
-- actually separates them: an ordinary supersession happens in the run that
-- re-confirmed the statement, so its gap is one fetch interval at most. On the
-- measured data the five sit at 31.98 h and every other retirement that day at
-- 0.59 h, with mbnr-live's cadence being 3 h. Six hours is above any ordinary
-- gap and far below theirs. Verified to touch exactly 5 rows before shipping.
UPDATE statements
   SET retired_reason = 'unmentioned'
 WHERE source_id = (SELECT id FROM sources WHERE slug = 'mbnr-live')
   AND superseded_by IS NULL
   AND superseded_at >= TIMESTAMPTZ '2026-09-08 07:00:00+00'
   AND superseded_at - last_seen_at > INTERVAL '6 hours'
   AND retired_reason IS NULL;

INSERT INTO schema_migrations (version) VALUES ('0015_statement_retired_reason')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
