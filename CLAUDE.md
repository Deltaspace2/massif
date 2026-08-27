# massif — Mont Blanc massif closure and status map

Answers one question well: **what is currently shut, restricted, or officially
flagged as dangerous in the Mont Blanc massif?**

This is a directory of published notices, **not a safety service**. It reports
what sources have said; it never tells anyone whether to go. Keep that framing
in every string a user can read — a stale "open" must never read as clearance.

Unattended sessions (scheduled overnight runs) have their own contract in
`OVERNIGHT.md` — read it first if nobody is watching.

## Commands

```bash
# database (native Postgres, no Docker) — port 5432
./scripts/setup_db_native.sh

cd backend && source .venv/bin/activate
python -m massif.scripts.migrate            # apply db/migrations/*.sql in order
pytest -q                                   # ~60 tests
python -m massif.scripts.seed_features      # load seeds/, merge OSM geometry
python -m massif.scripts.run_ingest [slug]  # all due sources, or one
python -m massif.scripts.reextract <slug> [--dry-run]  # re-parse stored docs
python -m massif.scripts.review_queue       # names that did not resolve
python -m massif.scripts.recompute          # rebuild feature_status from scratch
uvicorn massif.main:app --reload            # API on :8000

# any scraper, dry run, no DB writes:
python -m massif.ingest.sources.<name>

cd ../frontend && npm run dev               # :3000
```

## Architecture

Four ingest stages, each independently re-runnable. **Never fuse them:**

```
fetch → store document → extract statements → resolve to feature → recompute status
```

Tables: `features`, `sources`, `documents`, `statements`, `feature_status`,
`unresolved_mentions`, `ingest_runs`.

The core idea: **a closure and a condition report are the same shape** — a
statement, about a feature, from a source, valid over a window, with a
confidence. Type-specific data goes in `statements.payload` (JSONB), so new
kinds of information need new rows, not new tables.

`documents` is immutable and never deleted. Extraction runs *from* stored
documents so improving a parser means re-running over history, not re-fetching.
`reextract` is that entry point: it calls each scraper's `extract_stored()`,
retires the document's previous statements by setting `superseded_at`, and
writes the new ones. Grain is the **document**, never the statement — an
improved parser can emit fewer statements than it did before, or none, and
those orphans have no successor for `superseded_by` to point at. Re-extraction
must date statements from `published_at`/`fetched_at`, never `now()`: it is not
a new observation.

`feature_status` is a materialised cache. Ingest refreshes only what it
touched; run `recompute` after anything that edits statements out of band.

## Conventions

- **Python 3.12 backend** (FastAPI, SQLAlchemy 2.0, selectolax, no ORM magic).
  Chosen because the eventual hazard model needs GRIB/raster work.
- **Next.js frontend**, server-rendered. SEO is the distribution channel: this
  lives on people googling "aiguille du midi closed".
- Plain SQL migrations in `db/migrations/`, applied in filename order.
- Scrapers subclass `Scraper` and implement `collect()`. Register in
  `massif/ingest/registry.py`. A source with no registered scraper is skipped,
  which is how `seeds/sources.yaml` can list not-yet-built sources.
- Every scraper gets a `_dump()` / `__main__` dry run that hits the live page
  and writes nothing. Use it before touching the database.
- **Recon before writing a parser.** Every assumption made without looking at
  the real page has been wrong so far.

## Resolution rules

- `ExtractedStatement.feature_slug` — exact lookup. Use whenever the source
  publishes a stable id (`<div id="brevent">`). Never fuzzy-match what a
  source tells you outright.
- `ExtractedStatement.parent_slug` — scope to one parent's children, and
  auto-create the child if absent. Operators are authoritative about their own
  inventory. Without scoping, `TC MER DE GLACE` resolves to the Mer de Glace
  *glacier*.
- Otherwise fuzzy match via `FeatureResolver`, auto-accept ≥88.
- **Unmatched goes to `unresolved_mentions`, never to `/dev/null`.** Every
  alias added makes the next match better; every silent drop is invisible data
  loss.

## Hard-won rules

Seven bugs in the first two sessions. Every one produced a **plausible, silent,
wrong answer**; none crashed. The pattern is the lesson.

1. **Normalise accents before matching French text.** `"Réouverture"` did not
   match `reouverture`, so a reopening published as a closure — on the morning
   the Goûter refuges reopened.
2. **Classify from the title, not the body.** An article *about* closures is
   not a closure. The mayor's piece on overcrowding produced three false ones.
3. **Never let an undated notice claim a present-tense status.**
   `recompute_feature` treats null validity bounds as *currently valid*, so an
   undated closure would sit on the map forever. Emit `UNKNOWN` instead.
4. **Routine ≠ newsworthy.** `closure_kind: "outside_hours"` marks things shut
   because it is night or out of season. They render grey, never red, and rank
   below real closures. Ten sectors asleep must not look like a mountain that
   fell down.
5. **Resort clock, not reader clock.** All wording and display derives from
   `Europe/Paris`. "Not yet running today" is true at 06:00 and absurd at
   21:00, and the difference is invisible from another timezone.
6. **Prefer structured data over rendered HTML.** `mbnr-openings` reads the
   Next.js RSC payload: ISO dates, both seasons. The rendered table shows
   `5/1/2026` in English and `01/05/2026` in French for the same day.
7. **"It works against the live page" is not sufficient evidence** — in either
   direction. `find_objects` looped `while start > 0`, which only failed on an
   object at index 0, which only a test fixture ever produces.

Also: **no silent caps.** If a run bounds coverage, log what was dropped.

## Sources

Live: `mbnr-live` (lift status, 30 min), `mbnr-openings` (seasonal calendar,
daily), `mairie-saint-gervais` (municipal notices — Goûter route regulation).

Next: `mairie-chamonix` at **chamonix.fr** (not chamonix-mont-blanc.fr, which
is the tourist office). WordPress, permissive robots.txt, publishes
`sitemaps.xml`. Then Fondazione Montagna Sicura for the Italian side.

Conduct: honour robots.txt, real User-Agent with a contact URL, rate-limit
hard, attribute everything, link every displayed statement to its original.
We are guests on these servers.

## Not in v1

Crowd-sourced condition reports, weather, avalanche bulletins, route topos,
user accounts, anything predictive. The schema already accommodates conditions
(`statement_type` carries `condition` and `hazard_observation`); do not start
them until v1 has run a full season.
