-- Delete statements written before machine/sector scoping existed.
--
-- Those rows attached lift statuses to whatever feature the fuzzy matcher
-- liked best: TSD INDEX to the Flégère sector, TC MER DE GLACE to the Mer de
-- Glace *glacier*. They are wrong, not merely stale, so they go.
--
-- Documents are deleted too, purely to defeat the content-hash check and force
-- a refetch. In a mature system you would re-extract from the stored document
-- instead — that is what immutable documents are for — but no re-extract entry
-- point exists yet, and one live refetch is cheaper than building one now.

BEGIN;

DELETE FROM statements
WHERE source_id IN (SELECT id FROM sources WHERE slug = 'mbnr-live');

DELETE FROM unresolved_mentions
WHERE source_id IN (SELECT id FROM sources WHERE slug = 'mbnr-live');

DELETE FROM documents
WHERE source_id IN (SELECT id FROM sources WHERE slug = 'mbnr-live');

UPDATE sources
SET last_fetch_at = NULL, consecutive_failures = 0, last_error = NULL
WHERE slug = 'mbnr-live';

DELETE FROM feature_status
WHERE statement_id IS NOT NULL
  AND statement_id NOT IN (SELECT id FROM statements);

INSERT INTO schema_migrations (version) VALUES ('0002_reset_mbnr_statements');

COMMIT;
