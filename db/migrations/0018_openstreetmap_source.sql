BEGIN;

-- The OpenStreetMap facts source, so a hut's website can be shown with the
-- credit ODbL requires.
--
-- A migration as well as a seed entry, for the reason 0013 records: the ingest
-- workflow runs `migrate` on every sweep and never runs `seed_features`, so
-- seeds/sources.yaml is the source of truth for a fresh database and not a way
-- to change a deployed one.
--
-- licence and licence_url are not decoration. `_fact_block` returns None when
-- a source has no licence in fetch_config, so without them every OSM fact
-- renders as nothing — which is the correct failure and not one to rely on.
INSERT INTO sources (slug, name, url, source_type, language, trust_weight,
                     fetch_interval_minutes, active, fetch_config)
VALUES (
    'openstreetmap',
    'OpenStreetMap',
    'https://www.openstreetmap.org/',
    'community',
    'en',
    0.50,
    10080,
    true,
    jsonb_build_object(
        'licence', 'ODbL 1.0',
        'licence_url', 'https://opendatacommons.org/licenses/odbl/1-0/'
    )
)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO schema_migrations (version) VALUES ('0018_openstreetmap_source')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
