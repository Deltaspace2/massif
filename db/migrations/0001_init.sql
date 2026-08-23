-- massif v1 initial schema
--
-- Design note: a closure and a condition report are the same shape — a
-- statement, about a feature, from a source, valid over a time window, with a
-- confidence. Modelling that once means v2 (conditions aggregation) is new
-- rows, not new tables. Type-specific data goes in statements.payload.

BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------- enums ----

CREATE TYPE feature_type AS ENUM (
    'route',        -- an alpine route or itinerary
    'hut',          -- refuge, rifugio, bivouac
    'lift',         -- cable car, gondola, mountain railway (the line)
    'lift_station', -- a station on a lift
    'glacier',
    'couloir',      -- named hazard-bearing section, e.g. the Grand Couloir
    'access_road',
    'trail',
    'zone',         -- an administratively defined area, e.g. an arrêté polygon
    'peak'
);

CREATE TYPE source_type AS ENUM (
    'official',       -- mairie, préfecture — legally authoritative
    'operator',       -- lift company, hut warden
    'institutional',  -- OHM/Chamoniarde, Fondazione Montagna Sicura
    'community'       -- forums, social media
);

CREATE TYPE statement_type AS ENUM (
    -- v1
    'closure',
    'restriction',
    'opening',
    'operational_status',
    -- v2 (conditions aggregation) — declared now so the enum never migrates
    'condition',
    'hazard_observation'
);

CREATE TYPE status_value AS ENUM ('open', 'closed', 'restricted', 'unknown');

CREATE TYPE extraction_method AS ENUM ('manual', 'rule', 'llm');

-- ------------------------------------------------------------- features ----

CREATE TABLE features (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug          TEXT NOT NULL UNIQUE,
    feature_type  feature_type NOT NULL,

    name_default  TEXT NOT NULL,
    -- {"fr": "...", "it": "...", "en": "...", "de": "..."}
    names         JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- every way a source might spell this. The quiet hard problem: four
    -- sources in three languages name the same route four different ways.
    aliases       TEXT[] NOT NULL DEFAULT '{}',

    geom          GEOMETRY(Geometry, 4326),
    -- coordinates carried over from OSM or estimated are not authoritative
    -- until a human has checked them against IGN
    geom_verified BOOLEAN NOT NULL DEFAULT FALSE,

    alt_min       INTEGER,
    alt_max       INTEGER,
    massif        TEXT NOT NULL DEFAULT 'mont-blanc',
    country       CHAR(2),

    -- {"osm": "node/123", "camptocamp": "456", "refuges_info": "789"}
    external_ids  JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- the Grand Couloir belongs to the Goûter route; a station to its lift
    parent_id     UUID REFERENCES features(id) ON DELETE SET NULL,

    notes         TEXT,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX features_geom_idx      ON features USING GIST (geom);
CREATE INDEX features_aliases_idx   ON features USING GIN (aliases);
CREATE INDEX features_name_trgm_idx ON features USING GIN (name_default gin_trgm_ops);
CREATE INDEX features_type_idx      ON features (feature_type) WHERE active;
CREATE INDEX features_parent_idx    ON features (parent_id);

-- -------------------------------------------------------------- sources ----

CREATE TABLE sources (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    url          TEXT NOT NULL,
    source_type  source_type NOT NULL,
    language     CHAR(2) NOT NULL,
    country      CHAR(2),

    -- an arrêté outranks an Instagram post
    trust_weight NUMERIC(3,2) NOT NULL DEFAULT 0.50
                 CHECK (trust_weight >= 0 AND trust_weight <= 1),

    fetch_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetch_interval_minutes INTEGER NOT NULL DEFAULT 360,

    robots_checked_at TIMESTAMPTZ,
    robots_allows     BOOLEAN,
    last_fetch_at     TIMESTAMPTZ,
    last_success_at   TIMESTAMPTZ,
    last_error        TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,

    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------ documents ----
-- Immutable. Never deleted. Extraction runs FROM here, so improving a parser
-- means re-running over history instead of re-fetching. Also the audit trail
-- when a source disputes what we published.

CREATE TABLE documents (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id         UUID NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    url               TEXT NOT NULL,
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at      TIMESTAMPTZ,

    content_hash      TEXT NOT NULL,
    content_type      TEXT,
    raw_content       BYTEA,
    raw_text          TEXT,
    language_detected CHAR(2),

    http_status       INTEGER,
    extracted_at      TIMESTAMPTZ,
    extraction_error  TEXT
);

-- unchanged content writes no new document
CREATE UNIQUE INDEX documents_source_hash_idx ON documents (source_id, content_hash);
CREATE INDEX documents_fetched_idx   ON documents (fetched_at DESC);
CREATE INDEX documents_unextracted_idx ON documents (source_id)
    WHERE extracted_at IS NULL;

-- ----------------------------------------------------------- statements ----

CREATE TABLE statements (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feature_id   UUID NOT NULL REFERENCES features(id) ON DELETE CASCADE,
    source_id    UUID NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    document_id  UUID REFERENCES documents(id) ON DELETE SET NULL,

    statement_type statement_type NOT NULL,
    status         status_value NOT NULL DEFAULT 'unknown',
    severity       SMALLINT NOT NULL DEFAULT 0 CHECK (severity BETWEEN 0 AND 3),

    observed_at  TIMESTAMPTZ NOT NULL,
    valid_from   TIMESTAMPTZ,
    valid_to     TIMESTAMPTZ,

    summary_en        TEXT,
    original_text     TEXT,
    original_language CHAR(2),

    -- type-specific structured data. v2 puts snow line, bergschrund state,
    -- rockfall activity, ice quality here without touching this schema.
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,

    extraction_method     extraction_method NOT NULL DEFAULT 'rule',
    extraction_confidence NUMERIC(3,2)
                          CHECK (extraction_confidence IS NULL
                                 OR (extraction_confidence >= 0
                                     AND extraction_confidence <= 1)),

    superseded_by UUID REFERENCES statements(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE INDEX statements_feature_time_idx ON statements (feature_id, observed_at DESC);
CREATE INDEX statements_current_idx      ON statements (feature_id)
    WHERE superseded_by IS NULL;
CREATE INDEX statements_type_idx         ON statements (statement_type);
CREATE INDEX statements_observed_idx     ON statements (observed_at DESC);
CREATE INDEX statements_payload_idx      ON statements USING GIN (payload);

-- ------------------------------------------------------- feature_status ----
-- Materialised current state. Recomputed on ingest, read by the map.
-- Resolution: highest trust_weight, then most recent observed_at, then
-- highest severity.

CREATE TABLE feature_status (
    feature_id       UUID PRIMARY KEY REFERENCES features(id) ON DELETE CASCADE,
    status           status_value NOT NULL DEFAULT 'unknown',
    severity         SMALLINT NOT NULL DEFAULT 0,
    summary_en       TEXT,

    statement_id     UUID REFERENCES statements(id) ON DELETE SET NULL,
    source_id        UUID REFERENCES sources(id) ON DELETE SET NULL,

    observed_at      TIMESTAMPTZ,
    -- past this, the UI greys the status out rather than implying it is
    -- current. Being confidently out of date is what destroys trust.
    stale_after      TIMESTAMPTZ,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX feature_status_status_idx ON feature_status (status)
    WHERE status <> 'open';

-- -------------------------------------------------- unresolved_mentions ----
-- Review queue. A name that did not match a feature goes here, never to
-- /dev/null. Every alias added makes the next match better; every silent
-- drop is invisible data loss.

CREATE TABLE unresolved_mentions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  UUID REFERENCES documents(id) ON DELETE CASCADE,
    source_id    UUID REFERENCES sources(id) ON DELETE CASCADE,
    mention_text TEXT NOT NULL,
    context      TEXT,
    -- best fuzzy guesses: [{"feature_id": "...", "score": 0.72}]
    candidates   JSONB NOT NULL DEFAULT '[]'::jsonb,
    seen_count   INTEGER NOT NULL DEFAULT 1,
    resolved_to  UUID REFERENCES features(id) ON DELETE SET NULL,
    dismissed    BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX unresolved_mentions_uniq
    ON unresolved_mentions (source_id, lower(mention_text));
CREATE INDEX unresolved_mentions_open_idx ON unresolved_mentions (seen_count DESC)
    WHERE resolved_to IS NULL AND NOT dismissed;

-- ------------------------------------------------------ ingest_runs -------
-- Front page shows last successful ingest. Abandonment is the real failure
-- mode: a conditions site that stopped updating in November is worse than no
-- site, because people trust it anyway.

CREATE TABLE ingest_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID REFERENCES sources(id) ON DELETE CASCADE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    ok              BOOLEAN,
    documents_new   INTEGER NOT NULL DEFAULT 0,
    statements_new  INTEGER NOT NULL DEFAULT 0,
    unresolved_new  INTEGER NOT NULL DEFAULT 0,
    error           TEXT
);

CREATE INDEX ingest_runs_source_time_idx ON ingest_runs (source_id, started_at DESC);

-- ----------------------------------------------------------- migrations ----

CREATE TABLE schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES ('0001_init');

COMMIT;
