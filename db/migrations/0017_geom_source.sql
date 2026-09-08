BEGIN;

-- Where a feature's geometry came from, because "schematic" has to be sayable.
--
-- `geom_verified` cannot carry this. It means "not checked against IGN" — it is
-- false on every feature we hold, surveyed camptocamp linestrings included, and
-- seed_features prints exactly that when it runs. Overloading it to also mean
-- "we drew this ourselves" would make a real surveyed line and a line through
-- six waypoints indistinguishable, which is the one thing the route work must
-- not do.
--
-- fetch_route_geometry's docstring has always allowed the schematic fallback,
-- and always with the same condition: "honest if labelled as schematic; it
-- puts the route roughly where it is without pretending to be a GPX track."
-- This column is the label. Nothing may be written 'schematic' unless the map
-- can draw it differently from a surveyed line.
ALTER TABLE features ADD COLUMN IF NOT EXISTS geom_source TEXT;

COMMENT ON COLUMN features.geom_source IS
    'Provenance of geom: ''camptocamp'' or ''osm'' for surveyed geometry, '
    '''schematic'' for a polyline we built through waypoints we already hold. '
    'Null means unknown, which for legacy rows means OSM.';

-- Backfill. camptocamp first: those rows carry the document id they came from.
UPDATE features
   SET geom_source = 'camptocamp'
 WHERE geom IS NOT NULL
   AND geom_source IS NULL
   AND external_ids ? 'camptocamp';

-- Everything else with geometry arrived through the OSM candidate pipeline —
-- import_osm_huts for the huts, seed_features merging osm_candidates.yaml for
-- the rest.
UPDATE features
   SET geom_source = 'osm'
 WHERE geom IS NOT NULL
   AND geom_source IS NULL;

INSERT INTO schema_migrations (version) VALUES ('0017_geom_source')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
