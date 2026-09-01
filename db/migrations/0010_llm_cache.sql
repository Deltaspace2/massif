BEGIN;

-- Cached model readings, so the same prose is never paid for twice.
--
-- The whole point of storing documents immutably is that an improved parser is
-- re-run over history rather than re-fetching it. For a rule parser that is
-- free. For a model it is a bill, and `reextract` over one source is hundreds
-- of documents — so without this, the cheapest way to improve a parser becomes
-- the most expensive thing the project does.
--
-- KEYED ON CONTENT, NOT ON DOCUMENT. Two documents with identical text — the
-- same notice fetched twice, or republished at a second URL — are one reading.
-- The key is a hash of the text together with the prompt version and the
-- model, because a change to either of those is a different question and must
-- miss the cache rather than silently return the old answer. That is the
-- reason prompt_version exists at all.
--
-- The raw response is stored verbatim, before any of llm.py's guards run.
-- Storing the accepted statements instead would mean a fix to a guard could
-- never be tested against the readings that motivated it — and the guards are
-- the part of this that is most likely to change.

CREATE TABLE IF NOT EXISTS llm_cache (
    -- sha256(content_hash | prompt_version | model). Deterministic, so a
    -- lookup needs no query planning and no uniqueness worries.
    key             text PRIMARY KEY,

    -- Kept as their own columns as well as inside the key, so a human can ask
    -- "what did prompt 1 say about this text" without recomputing hashes.
    content_hash    text NOT NULL,
    prompt_version  text NOT NULL,
    model           text NOT NULL,

    -- Exactly what came back, parsed as JSON and no further.
    response        jsonb NOT NULL,

    -- What it cost, where the API tells us. Not for billing — for knowing
    -- whether pointing this at 25 hut sites weekly is sane before doing it.
    input_tokens    integer,
    output_tokens   integer,

    created_at      timestamptz NOT NULL DEFAULT now()
);

-- "Everything prompt 2 has read so far", which is the question asked when a
-- prompt changes and someone wants to know what it has cost and covered.
CREATE INDEX IF NOT EXISTS llm_cache_prompt_idx
    ON llm_cache (prompt_version, model, created_at DESC);

INSERT INTO schema_migrations (version) VALUES ('0010_llm_cache')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
