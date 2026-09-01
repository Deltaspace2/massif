BEGIN;

-- "Open, but nobody is running it" as a status in its own right.
--
-- The Alps already speak this way — gardé, non gardé, fermé — and a third of
-- the huts here are in the middle state: seventeen typed "cabane non gardée"
-- by refuges.info, the Swiss huts the CAS system reports UNSERVICED, and the
-- winter rooms that stay open when a warden goes home. Until now all of them
-- read exactly like a fully serviced refuge, which answers "can I get in" and
-- says nothing about what a walker will find when they do.
--
-- IT IS A VARIANT OF OPEN, NOT A WARNING. It renders in the open colour and
-- reads "open · unstaffed", because the door is unlocked and the one thing
-- this site must never do is make an open hut look shut. What changes is the
-- sentence beside it and a hollow rather than filled marker: nobody home.
--
-- Severity stays 0, so a real closure on the same hut still wins the status
-- slot on severity as it always has.

ALTER TYPE status_value ADD VALUE IF NOT EXISTS 'unstaffed';

INSERT INTO schema_migrations (version) VALUES ('0012_unstaffed_status')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
