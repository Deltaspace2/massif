BEGIN;

-- `mbnr-live` from a 30-minute declared cadence to 180.
--
-- A migration and not just a seed edit, because the ingest workflow runs
-- `migrate` on every sweep and never runs `seed_features`. seeds/sources.yaml
-- is the source of truth for a fresh database; it is not a deploy mechanism,
-- and editing it alone would have changed nothing in production while looking
-- exactly like a fix.
--
-- Why the number changed at all: the cadence is what `_unchecked` in main.py
-- measures our diligence against, badging a feature OVERDUE at two missed
-- intervals. Ingest is triggered by a GitHub Actions cron, and measured over
-- 6-8 Sep 2026 the delivered gaps between scheduled runs were min 91 / median
-- 188 / mean 225 / max 434 minutes against a `*/30` schedule. At a declared 30
-- the badge appeared after 60 minutes, so eight lifts carried it about
-- five-sixths of the time. A badge that is nearly always lit is one nobody
-- reads, and this one is half the answer to "is this stale".
--
-- 180 is the measured median, so OVERDUE now means a sweep was genuinely
-- missed rather than that GitHub queued us again.
--
-- Guarded on the old value: if somebody has already tuned this by hand, that
-- decision is newer than this file and wins.
UPDATE sources
   SET fetch_interval_minutes = 180
 WHERE slug = 'mbnr-live'
   AND fetch_interval_minutes = 30;

INSERT INTO schema_migrations (version) VALUES ('0013_mbnr_live_cadence')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
