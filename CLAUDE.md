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
pytest -q                                   # no DB needed (186 -> 204 in one
                                            # day; the count is not worth
                                            # keeping current here)
python -m massif.scripts.seed_features      # load seeds/, merge OSM geometry
python -m massif.scripts.run_ingest [slug]  # all due sources, or one
python -m massif.scripts.reextract <slug> [--dry-run]  # re-parse stored docs
python -m massif.scripts.review_queue       # names that did not resolve
python -m massif.scripts.recompute          # rebuild feature_status from scratch
python -m massif.scripts.import_hut_facts [--apply]  # refuges.info directory facts
uvicorn massif.main:app --reload            # API on :8000

# any scraper, dry run, no DB writes:
python -m massif.ingest.sources.<name>

cd ../frontend && npm run dev               # :3000
npx tsc --noEmit                            # typecheck; CI runs this + next build
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
- **The frontend cannot assume the API's version.** They deploy separately, so
  for the length of every deploy the frontend renders against an API that
  predates its newest field. New fields
  are typed optional and read as `?? []`. `facts` was typed required once, and
  `feature.facts.map` turned every feature page — the SEO surface — into a 500
  for that window.

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

8. **A name score cannot tell you which mountain something is on.** Altitude
   can. `"Voie normale"` matched the Goûter route at 95 and topped out at
   2965 m, 20 km north. Every geographic import validates against altitude and
   span, and keeps a decoy list: `"Ancien refuge du Goûter"` clears both the
   score floor *and* altitude tolerance (3817 m vs 3835 m), and is the hut the
   mairie demolished.
9. **A stored sentence does not stay true.** `summary_en` is composed once at
   extraction. "Reopening 26 Aug 2026" was correct when published and absurd
   five days later beside a green dot. Anything whose truth depends on *now*
   is phrased at read time — see `phrase_for_now` in `main.py`.
10. **Two clocks, two columns.** `observed_at` is when the source published;
    `last_seen_at` is when we last fetched and found it still standing. The UI
    once labelled the first as the second, badging a decree valid till
    September as UNVERIFIED. Do not let one column carry both.
11. **Every migration registers itself.** `migrate.py` does not record what it
    ran; each file ends with `INSERT INTO schema_migrations`. Two of them
    forgot, applied cleanly, printed ok, and failed on the *next* run against
    a database that already had their changes. `test_migrations.py` enforces
    it now.
12. **Do not re-implement a backend rule in the UI.** `STALE_DAYS` answers
    staleness per statement type — an arrêté holds 90 days, a live lift status
    one. The front page overrode all of it with a flat 48 hours and would have
    flagged every valid decree in the massif forever.

Also: **no silent caps.** If a run bounds coverage, log what was dropped.

## Facts vs statements

A **statement** is a claim from a source, valid over a window, that can be in
force. A **fact** (`feature_facts`) is a property of a thing: hut capacity,
whether there is water. Facts never enter the status pipeline — they would
compete for the status slot and age with `STALE_DAYS`, neither of which means
anything for how many bunks a building has. The warden *season* is a statement;
the bunk count is a fact.

**Attribution is data, not a string in the renderer.** A facts source carries
`licence` and `licence_url` in `seeds/sources.yaml`; `seed_features` puts them
in `sources.fetch_config`, and the API reads them from there. A source without
them renders **nothing** — no heading, no table, no credit. That is deliberate:
refuges.info is CC BY-SA 2.0, so a block we cannot attribute is one we must not
show, and a missing block is visible where a missing credit is not. Every fact
row links to its own entry, never one shared footer.

## LLM extraction

`massif/ingest/llm.py` is phase 1 and offline: no API key, no network. Rules
stay on structured sources forever; the model is for prose only (arrêté PDFs,
OHM bulletins). Four guards on its output, all tested via cassettes in
`tests/cassettes/`:

1. **Evidence** — every statement carries the verbatim span it came from and
   that span must be in the document. Whitespace forgiven, accents not.
2. **Dates read twice** — the model returns the French phrase, never a parsed
   range; `fr_dates.parse_range` reads it independently and they must agree.
3. **No feature picking** — it returns a mention that must appear in the
   document; `FeatureResolver` does the matching at the usual 88 floor.
4. **The gate** — `payload.needs_review` is set inside the writer, so no caller
   can opt out by forgetting.

Phase 2 is built — `massif/ingest/llm_client.py`, defaulting to
`claude-sonnet-5`. Two objects kept apart so each is testable without the
other: `AnthropicExtractor` calls the API and knows nothing about the database,
`CachedExtractor` wraps any extractor with the `llm_cache` table and knows
nothing about Anthropic.

- **No key is not an error.** `build_extractor` returns None and the caller
  skips, exactly as `registry.py` skips a source with no scraper. A run on a
  machine without a key completes rather than half-completing. The `anthropic`
  package is an optional extra (`pip install -e '.[llm]'`).
- **The cache is not optional.** Documents are stored immutably so a better
  parser can be re-run over history; with a model that re-run is a bill, and
  `reextract` over one source is hundreds of calls. Keyed on content hash +
  prompt version + model, because a change to either of the last two is a
  different question and must MISS rather than return the old answer.
- **A broken response raises, never returns `[]`.** An empty array means "this
  document contains no notice" — real and common — so a parse failure
  disguised as one would read as clean coverage.
- **The prompt and PROMPT_VERSION are one design.** Every instruction in the
  prompt exists because a guard in `llm.py` checks it, and a test pins the
  prompt's hash so it cannot be edited without bumping the version.
- The document goes in the user turn, never interpolated into the
  instructions: it is untrusted text from someone else's website.

NOT YET WIRED TO A SOURCE, and Saint-Gervais is NOT the place to start —
which is the opposite of what the obvious number says. "28 of 36 stored
documents produce nothing" is true and misleading: those 36 rows are 15
distinct URLs, each re-stored on a later fetch. Four of the fifteen are
notices, and the title-based rule parser already catches all four. The other
eleven were put through the model one by one and it returned nothing for every
single one — correctly, because they are sports sponsorship, an olympic
welcome, cherry blossoms, a planning consultation and the overcrowding appeal
that famously produced three false closures with a regex.

So the model adds NOTHING here. The prose is unread because there is nothing
in it, not because rules cannot reach it, and the honest measurement cost
about 30,000 tokens and saved wiring up a source that would have produced no
statements and a recurring bill.

Where it is still worth pointing: sources that are ONLY prose and have
therefore never been built — the préfecture's press feed, whose notice bodies
are PDFs, and the 25 individual hut websites behind the wardened-hut gap. Weigh
the review load first: everything from this path is written `needs_review`, so
a human clears each statement before it can take a status slot.

Weigh the review load before pointing it at anything wide. Everything from
this path is written `needs_review`, so a human clears each statement before
it can take a status slot; for a handful of arrêtés that is a safety net, and
across 25 hut websites weekly it becomes the bottleneck.

## Sources

Live: `mbnr-live` (lift status, 30 min), `mbnr-openings` (seasonal calendar,
daily), `mairie-saint-gervais` (municipal notices — Goûter route regulation),
`refuges-info` (hut directory facts, weekly, API client not a scraper —
CC BY-SA 2.0, so the permalink is a licence condition and every hut links back).
Covers all 19 huts. It read as 13 for most of a day, then 18, because
refuges.info writes Italian huts under the French generic — their "Refuge
Torino" is our "Rifugio Torino" — and five sat just under the name floor, while
the Fourche bivouac is filed under its dedication ("Bivouac Alberico Borgna")
and scores 54 against the location name we chose. The importer explained the
shortfall as the Italian side being uncovered: a story that fitted the number
and stopped anyone checking it, and it survived two rounds of correction
because each round fixed the count and kept the story.
**A tool's own summary of its coverage is a claim like any other.** "No entry"
means we failed to match, never that they do not have it.

Next: `mairie-chamonix` at **chamonix.fr** (not chamonix-mont-blanc.fr, which
is the tourist office). WordPress, permissive robots.txt, publishes
`sitemaps.xml`.

The Italian side has no source and is **blocked, not unstarted**. Fondazione
Montagna Sicura was the plan and does not survive recon: its conditions page
was abandoned in January 2025, and what is there is OHM Chamonix's French-side
bulletins republished — the parked source, one hop away. The equivalent of
`mairie-saint-gervais` is `comune.courmayeur.ao.it`, which currently does not
resolve at all; an unreachable robots.txt is a refusal, so we wait rather than
work around it. `courmayeurmontblanc.it` is reachable and does publish the Val
Veny and Val Ferret road closures that gate the Italian huts, and was declined
anyway: it is the tourist office, and that is the same distinction as the line
about chamonix.fr above. Until the commune answers, the Italian huts carry
directory facts and no notices, which is the honest state. Detail in the task
queue, so nobody repeats the recon.

Conduct: honour robots.txt, real User-Agent with a contact URL, rate-limit
hard, attribute everything, link every displayed statement to its original.
We are guests on these servers.

## Not in v1

Weather, avalanche bulletins, route topos, user accounts, anything predictive.

**Crowd-sourced condition reports were brought forward**, against the line that
used to stand here, on an explicit instruction to get route status checked
weekly. `camptocamp-outings` reads the structured `condition_rating` enum on
dated trip reports. It was built only after the two in-scope alternatives were
reconned and came up empty: La Chamoniarde publishes nobody's data but other
people's, and the préfecture's mountain output is avalanche vigilance plus one
access ban that lives in a PDF.

Three things keep it from being the thing that line was guarding against:

* It can never produce a closure. Every statement is `condition` at status
  UNKNOWN, so a route's badge is untouched and only its notices gain a line.
  "Poor" is not "shut", and a community rating driving a red dot would be this
  site inventing closures out of opinions.
* Routes are matched by a hand-pinned id, never by search. Nine of thirteen are
  pinned; the rest stay silent.
* `STALE_DAYS` answers `condition` with 14 days, so most of these render greyed
  almost at once. That is correct, and it is most of what this source does:
  measured on 1 Sep 2026, one of nine pinned routes had a report inside the
  window. Route conditions are seasonal and sparse.

`active: false` in `seeds/sources.yaml` reverses the decision and nothing else
has to change.
