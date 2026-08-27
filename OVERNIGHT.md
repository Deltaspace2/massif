# Overnight sessions

A scheduled task starts a fresh Claude session in an Anthropic cloud container,
on a schedule, with nobody watching. This file is the contract for that session.
Read it before doing anything else.

You are not continuing a conversation. Nothing is in your context except this
repo. `CLAUDE.md` has the architecture and the seven hard-won rules; this file
has the rules that only apply when no human is present.

## What is different when unattended

Three things are missing, and they are the three things that caught most of the
bugs in this project's history:

- **No eyes on the browser.** You cannot look at the map. Four bugs were found
  by a human noticing something looked wrong, and one by him opening devtools.
- **No live sources you should be leaning on.** Scraping is rate-limited and
  polite by design; a source's live page is not a test fixture.
- **No one to say "that's not what I meant."** A wrong turn runs for hours.

So the scope rule is absolute:

> **Only work whose correctness a test can settle.**

If you cannot write a test that fails before your change and passes after it,
the task is not for an overnight session. Put it in `Deferred` at the bottom of
the queue below and move on. Do not guess at visual work.

## Setup

Proven working in this container image on 2026-08-27 — 121 tests, real PostGIS.

```bash
apt-get update -qq
apt-get install -y --no-install-recommends postgresql-16 postgresql-16-postgis-3
PGBIN=/usr/lib/postgresql/16/bin
mkdir -p /tmp/pgdata /tmp/pgrun && chown -R postgres /tmp/pgdata /tmp/pgrun
su postgres -c "$PGBIN/initdb -D /tmp/pgdata -U massif --auth=trust"
su postgres -c "$PGBIN/pg_ctl -D /tmp/pgdata \
  -o '-p 5433 -k /tmp/pgrun -c listen_addresses=127.0.0.1' -l /tmp/pg.log start"
psql -h 127.0.0.1 -p 5433 -U massif -d postgres -c "CREATE DATABASE massif;"
psql -h 127.0.0.1 -p 5433 -U massif -d massif -c "CREATE EXTENSION postgis;"

cd backend
python3.12 -m venv .venv          # NOT python3 — that is 3.11 here, and the
.venv/bin/pip install -e ".[dev]" # package requires >=3.12
export DATABASE_URL="postgresql+psycopg://massif:massif@127.0.0.1:5433/massif"
.venv/bin/python -m massif.scripts.migrate
.venv/bin/pytest -q               # expect 121 passed
.venv/bin/ruff check massif       # expect clean
```

If `pytest` or `ruff` is not clean **before** you have changed anything, stop.
Something upstream is broken and fixing it blind is how you make it worse.
Write the report, push nothing, and say so.

## Rules

1. **Branch, never `master`.** `git checkout -b night/YYYY-MM-DD`. Push the
   branch. Do not merge, do not rebase `master`, do not force-push anything.
2. **Test first.** Write the failing test, watch it fail, then fix. A test
   written after the fix proves only that you can restate the fix.
3. **"It works against the live page" is not evidence.** `find_objects` had a
   `while start > 0` that skipped index 0, and real data hid it in both
   directions. Test the boundary, not the happy path.
4. **Accents are the house speciality.** Four separate bugs. Any comparison
   against a French literal goes through `strip_accents`. If you add one that
   does not, you have added the fifth.
5. **Scraping stays polite.** `robots.txt` is honoured and an unreachable one
   is a refusal. Real User-Agent with a contact URL. One fetch per source per
   run, at most, and only if a queue item actually needs fresh bytes. Extraction
   work runs from stored documents via `reextract.py` — that is the whole point
   of storing them.
6. **Never edit an applied migration.** Add a new one.
7. **No silent caps.** If you bound the work — stopped at N files, skipped a
   case, sampled — say so in the report. Truncation you do not mention reads as
   coverage you did not have.
8. **Do not publish a claim you have not checked.** This site's failure mode is
   a confident wrong status. Same standard applies to your report: if you did
   not run it, do not say it passed.
9. **Stop when the queue is done.** Do not invent scope at 3am. Finish, report,
   push.

## Reporting

Write `reports/YYYY-MM-DD.md` on the branch and commit it. Structure:

- What was attempted, in order.
- For each item: done / partial / abandoned, and **why**, in one line.
- Every test added, by name, and what regression it pins.
- Anything you noticed and did not act on.
- Anything you got wrong mid-run and corrected — those are the useful part.

Then push the branch. That is the end of the run.

## Queue

Work top-down. Each item states how it is verified; if it does not, it is not
ready and you should skip it.

### 1. Fix the twenty mypy errors
`mypy` is a dev dependency and has never been run in CI. It reports 20 errors
across 10 files, and several are real `None`-safety holes — the same shape as
every bug this project has shipped: no crash, a plausible wrong value.
`chamoniarde.py:436` calls `.groups()` on a possibly-`None` match;
`reextract.py:122` assigns `Statement | None` into `Statement`.
Fix them properly — narrow the type, do not `# type: ignore` and do not cast.
Where a `None` was genuinely reachable, add a test that reaches it.
**Verified by:** `mypy massif` clean, `pytest -q` still green, plus one new test
per genuinely-reachable `None`.

### 2. Add mypy and the frontend typecheck to CI
`.github/workflows/ci.yml` runs ruff, migrate, pytest. Add `mypy massif` after
ruff. Add a frontend job: `npm ci && npx tsc --noEmit && npm run build`.
Do item 1 first or CI goes red on arrival.
**Verified by:** every command in the workflow run locally and passing.

### 3. Regression tests for the bug history
`CLAUDE.md` lists seven hard-won rules. Some have tests, several do not. Go
through them and pin each one that does not. Highest value first — these are
all bugs that shipped a wrong public claim:
- Lunch-break hours read as a closure (`"Fermé de 13h00 et 14h00"`).
- Unscoped fuzzy matching (`TC MER DE GLACE` resolving to the glacier).
- Resort clock vs reader clock (status computed in the wrong timezone).
- `classify()` on an accented title (`Réouverture` published as a closure).
- `classify()` reading the body instead of the title.
- Undated notices claiming the present (null validity ≠ currently true).
- `_season_status` reading `statement_type` where it meant `status`.
**Verified by:** each test fails against the pre-fix behaviour. Prove that —
`git stash` the fix if it is still reachable in history, or reconstruct the bad
input and assert the *correct* output with a comment naming the commit.

### 4. Property tests for `fr_dates.parse_range`
Eight ordered patterns, tried in sequence, and order matters. There is no test
asserting that an earlier pattern does not swallow input meant for a later one.
Enumerate real French date phrasings, assert each parses to the right range,
and assert that pattern order is load-bearing by testing the ambiguous cases.
**Verified by:** new tests in `tests/test_fr_dates.py`.

### 5. An accent-safety test that generalises
Rule 4 above is currently enforced by a human remembering it. Write a test that
walks the ingest modules' ASTs and fails on a string comparison against a
literal containing a non-ASCII character, unless the other side went through
`strip_accents`. Allow-list the deliberate cases explicitly, with a reason.
**Verified by:** the test passes now, and fails if you reintroduce bug #8 —
show that by temporarily reverting the `classify()` fix in a scratch copy.

### 6. A naive-datetime test
Same shape as 5, narrower. Ingest and status code must not call
`datetime.now()` without a timezone. Walk the AST, fail on the naive form.
**Verified by:** the test, plus confirming it catches a deliberately naive call.

### 7. Rank the unresolved mentions
`unresolved_mentions` exists so nothing goes to `/dev/null`, but nothing reads
it in aggregate. Extend `review_queue.py` (or add a script) to group by
normalised text, count occurrences, and sort — so the most common thing the
resolver cannot match is the first thing a human sees.
**Verified by:** a test over a seeded fixture set asserting the ordering.

### Deferred — not for an unattended session
- Schematic geometry for the Goûter route and the Grand Couloir. Needs a
  judgement about what a line on a map implies. It must never read as a
  surveyed track, and no test can tell you whether it does.
- Feature-page and SEO surface polish. Visual.
- Anything touching the OHM/Chamoniarde source. It is parked, `active: false`,
  and turning it on is a product decision, not a code one.
- Deployment. Needs credentials that are not in this container.
