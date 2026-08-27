-- Remove point geometry wrongly assigned to routes and couloirs.
--
-- seed_features matched OSM candidates using normalise(), the resolver's
-- fuzzy key. normalise() deliberately strips generic mountain nouns — route,
-- voie, arête, refuge, du — so that a French notice saying "la voie du Goûter"
-- resolves to the Goûter route. That aggression is correct for reading prose
-- and disastrous for assigning coordinates: "Goûter Route" and "Refuge du
-- Goûter" both collapse to "gouter", so the route inherited the hut's point.
--
-- Result, live in the database until now:
--   gouter-route     45.8511, 6.8306  way/246399016  (Refuge du Goûter)
--   grand-couloir    45.8511, 6.8306  way/246399016  (the same building)
--   cosmiques-arete  45.8732, 6.8856  way/193208257  (Refuge des Cosmiques)
--
-- The Grand Couloir is the most safety-critical feature here and it was
-- pinned on a hut. Invisible for two days because routes were not rendered.
--
-- Beyond the bad match: a route is a line. A point is the wrong shape for it
-- even when the match is right, so all point geometry on routes and couloirs
-- goes, and seed_features no longer assigns any.

BEGIN;

UPDATE features
SET geom = NULL,
    geom_verified = FALSE,
    external_ids = external_ids - 'osm'
WHERE feature_type IN ('route', 'couloir')
  AND geom IS NOT NULL
  AND ST_GeometryType(geom) = 'ST_Point';

INSERT INTO schema_migrations (version) VALUES ('0006_clear_route_point_geometry');

COMMIT;
