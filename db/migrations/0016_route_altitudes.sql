BEGIN;

-- Altitudes for six routes, so rule 8's guard can run at all.
--
-- `import_route_geometry` checks a candidate's elevation against ours before
-- accepting its line, because "a name score cannot tell you which mountain
-- something is on". The check is written `if feature.alt_max and elevation:`,
-- so a null alt_max skipped it silently and the match was accepted on name
-- score alone. Seven of thirteen routes were in that state, three of them with
-- geometry already imported and never validated.
--
-- Sourced from natural=peak nodes carrying ele in seeds/osm_candidates.yaml —
-- OSM, and therefore independent of camptocamp. Validating a camptocamp match
-- against camptocamp's own elevation would check nothing at all.
--
-- Guarded on the value being absent, so a hand-entered altitude is never
-- overwritten by this file.
UPDATE features SET alt_max = 3542 WHERE slug = 'aiguille-du-tour-normal' AND alt_max IS NULL;
UPDATE features SET alt_max = 4248 WHERE slug = 'arete-du-diable'         AND alt_max IS NULL;
UPDATE features SET alt_max = 3842 WHERE slug = 'arete-midi-plan'         AND alt_max IS NULL;
UPDATE features SET alt_max = 3842 WHERE slug = 'frendo-spur'             AND alt_max IS NULL;
UPDATE features SET alt_max = 3512 WHERE slug = 'petite-aiguille-verte'   AND alt_max IS NULL;
UPDATE features SET alt_max = 3842 WHERE slug = 'vallee-blanche'          AND alt_max IS NULL;

-- chere-couloir is deliberately left null. The Goulotte Chéré tops out on the
-- Triangle du Tacul, which is not a peak node in our OSM candidates, and a
-- number invented to satisfy a guard defeats the guard. It carries a
-- hand-pinned camptocamp id instead, which is the stronger protection.

INSERT INTO schema_migrations (version) VALUES ('0016_route_altitudes')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
