BEGIN;

-- Opt `mbnr-live` in to retiring statements it has stopped mentioning.
--
-- A migration and not only a seed edit, for the same reason as 0013: the
-- ingest workflow runs `migrate` on every sweep and never runs
-- `seed_features`, so seeds/sources.yaml is the source of truth for a fresh
-- database and not a way to change a deployed one.
--
-- The bug: `retire_replaced` retires an old reading when a NEW one arrives for
-- the same feature and source. A source that stops listing a feature never
-- sends that successor, so nothing retires. Six Megève features were dropped
-- from the live feed when the ski season ended and have been frozen since on
-- "close — départ toutes les 30 mn à partir de 9h".
--
-- Why this source and not the others: absence is only evidence when one fetch
-- enumerates everything the source speaks about. Measured 8 Sep 2026,
-- mbnr-live's 32 live statements were exactly the 27 it re-emits each run plus
-- the 5 Megève orphans. A notice feed is the opposite case — mairie-saint-
-- gervais caps at MAX_ARTICLES, so absence there can be our own cap rather
-- than the mairie's silence, and retiring on it would drop a valid arrêté and
-- turn a shut route UNKNOWN.
--
-- jsonb_set with create_missing, so the licence and notes already in
-- fetch_config survive. Guarded on the key being absent: if somebody has tuned
-- the threshold by hand, that decision is newer than this file and wins.
UPDATE sources
   SET fetch_config = jsonb_set(
           COALESCE(fetch_config, '{}'::jsonb),
           '{retire_after_unmentioned_runs}',
           '3'::jsonb,
           true
       )
 WHERE slug = 'mbnr-live'
   AND NOT (COALESCE(fetch_config, '{}'::jsonb) ? 'retire_after_unmentioned_runs');

INSERT INTO schema_migrations (version) VALUES ('0014_mbnr_live_retire_unmentioned')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
