-- Remove feature_status rows whose statement no longer exists.
--
-- Migration 0002 tried to do this and failed. feature_status.statement_id is
-- ON DELETE SET NULL, so deleting the statements nulled the references before
-- the cleanup clause ran, and "statement_id NOT IN (...)" matched nothing.
-- Two rows survived holding pre-fix machine statuses — panoramic-mont-blanc
-- and vallorcine — and nothing would ever have corrected them, because
-- recompute only revisits features whose statements changed.
--
-- A materialised status with no statement behind it is unsourced by
-- definition. There is nothing to show a visitor and nothing to link to, so
-- it should not exist.

BEGIN;

DELETE FROM feature_status WHERE statement_id IS NULL;

INSERT INTO schema_migrations (version) VALUES ('0003_purge_orphaned_status');

COMMIT;
