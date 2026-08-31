BEGIN;

-- Two different facts were being carried by one column.
--
-- `observed_at` is when the SOURCE said a thing: the date on the arrêté, the
-- timestamp on the article. `last_seen_at` is when WE last fetched the source
-- and found the thing still standing. The UI was labelling observed_at as
-- "last confirmed", which is a claim about our diligence made using a number
-- about somebody else's publishing schedule. On the Goûter route that read as
-- "last confirmed 6 days ago" for a decree that is valid until 25 September
-- and had been re-checked minutes earlier.
--
-- Both matter and neither substitutes for the other. A six-day-old claim about
-- a mountain is worth showing; so is the fact that nobody has re-checked it.

ALTER TABLE statements
    ADD COLUMN IF NOT EXISTS last_seen_at timestamptz NOT NULL DEFAULT now();

-- Existing rows: we genuinely do not know when they were last confirmed, so
-- they inherit observed_at. That reads as "not re-checked since it was
-- published", which is the honest reading of an unknown, and it corrects
-- itself on the next ingest.
UPDATE statements SET last_seen_at = observed_at;

ALTER TABLE feature_status
    ADD COLUMN IF NOT EXISTS last_seen_at timestamptz;

-- An opening lifts an undated closure from the same authority.
--
-- retire_replaced() matches on feature + source + TYPE, so a closure was never
-- a candidate for retirement by an opening. An undated closure has no validity
-- window either, so nothing else ever expired it. The result: Saint-Gervais
-- closed access to Mont Blanc on 11 August over lethal rockfall, reopened the
-- Tête Rousse and Goûter refuges on 26 August, and the closure notice was
-- still being served as "currently in force" on 30 August.
--
-- One-off correction of the existing rows; base.py now does this at write time.
UPDATE statements AS closure
SET superseded_at = now()
FROM statements AS opening
WHERE closure.statement_type = 'closure'
  AND closure.valid_from IS NULL
  AND closure.valid_to IS NULL
  AND closure.superseded_at IS NULL
  AND closure.superseded_by IS NULL
  AND opening.statement_type = 'opening'
  AND opening.superseded_at IS NULL
  AND opening.superseded_by IS NULL
  AND opening.feature_id = closure.feature_id
  AND opening.source_id = closure.source_id
  AND opening.observed_at > closure.observed_at;

-- Every migration registers itself; migrate.py does not do it for you.
-- Both 0008 and 0009 originally omitted this, so they applied once,
-- printed ok, and then failed on the next run against a database that
-- already had their changes. ON CONFLICT so a database that ran the
-- unregistered version heals instead of erroring.
INSERT INTO schema_migrations (version) VALUES ('0008_statement_last_seen_at')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
