BEGIN;

-- Directory facts about a feature: capacity, altitude, whether it is guarded,
-- whether there is water.
--
-- These are NOT statements. A statement is a claim from a source, valid over a
-- window, that can be in force or not; capacity is a property. Running hut
-- capacity through the statement pipeline would put it in the running for the
-- status slot, age it with STALE_DAYS, and let it be "retired" — none of which
-- means anything for a fact about how many bunks a building has.
--
-- One row per (feature, source), payload as JSONB rather than a column per
-- field, because the shape differs per source and this is a directory
-- annotation rather than something we compute over.
--
-- Provenance is not optional here. refuges.info is CC BY-SA 2.0: attribution
-- is a licence condition, not a courtesy, so the permalink is a NOT NULL
-- column and every fact we display carries a link back to whoever wrote it.
-- source_modified_at is their own last-edited date, which is the honest
-- "last confirmed" for directory data and is usually months old — quite
-- unlike a lift status, and the UI should not pretend otherwise.

CREATE TABLE IF NOT EXISTS feature_facts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    feature_id      uuid NOT NULL REFERENCES features(id) ON DELETE CASCADE,
    source_id       uuid NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,

    -- Their identifier for the thing, so a rename on either side does not
    -- silently re-match to something else next run.
    external_ref    text NOT NULL,
    source_url      text NOT NULL,

    payload         jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- When THEY last changed it, versus when WE last looked. Same distinction
    -- as statements.observed_at and statements.last_seen_at, and it matters
    -- more here: directory data is edited yearly.
    source_modified_at timestamptz,
    fetched_at      timestamptz NOT NULL DEFAULT now(),

    -- How the match was made and how confident we are, kept so a wrong link
    -- can be traced to its rule rather than guessed at. The Goûter is the
    -- reason: "Refuge du Goûter" fuzzy-matches "Ancien refuge du Goûter" — the
    -- demolished one — at a high score and within altitude tolerance.
    match_method    text NOT NULL DEFAULT 'curated',
    match_score     numeric(5,2),

    UNIQUE (feature_id, source_id)
);

CREATE INDEX IF NOT EXISTS feature_facts_feature_idx ON feature_facts (feature_id);
CREATE INDEX IF NOT EXISTS feature_facts_fetched_idx ON feature_facts (fetched_at DESC);

-- Every migration registers itself; migrate.py does not do it for you.
-- Both 0008 and 0009 originally omitted this, so they applied once,
-- printed ok, and then failed on the next run against a database that
-- already had their changes. ON CONFLICT so a database that ran the
-- unregistered version heals instead of erroring.
INSERT INTO schema_migrations (version) VALUES ('0009_feature_facts')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
