-- Clear geometry on curated point-like features so one rule assigns all of it.
--
-- seed_features only ever SETS geometry; it never clears it. So after the
-- matching rule changed, the map became a blend of two regimes: some features
-- carrying coordinates from the old fuzzy key, others from the new strict one,
-- with no way to tell which from the outside. That is how a second Grand
-- Couloir hides.
--
-- Auto-created children (parent_id NOT NULL) are left alone: they come from
-- operator feeds, never from OSM, and have no geometry to lose.

BEGIN;

UPDATE features
SET geom = NULL,
    geom_verified = FALSE,
    external_ids = external_ids - 'osm'
WHERE parent_id IS NULL
  AND feature_type IN ('hut', 'lift', 'lift_station', 'peak');

INSERT INTO schema_migrations (version) VALUES ('0007_reset_point_geometry');

COMMIT;
