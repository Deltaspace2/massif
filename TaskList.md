# Task list

Steven's items as headings, kept verbatim. Notes underneath are mine, with
state as of 1 Sep 2026. This file is now the only task list — the agent-side
one went away with its MCP server, so anything that mattered is folded in here.

---

## Weather updates/ status
NOT STARTED, and deliberately out of scope: CLAUDE.md "Not in v1" excludes
weather and avalanche bulletins until v1 has run a full season. Both are
already linked from sources we scrape (Meteo VDA, BERA, bollettino valanghe),
so the cheap version is linking out rather than ingesting.

## Events happening within the massif? - ie. races, concerts etc.
NOT STARTED. Also v1-excluded as "events", BUT the Courmayeur recon turned up
the part that IS in scope: UTMB and Tor des Géants close roads
(`chiusura-strade-utmb`, `chiusura-strade-torx`). A race is not our business; a
road shut for a race is exactly "what is currently shut".

## Feed Page
**DONE.** Built at /feed: every notice we hold, newest first, source on each
row, two clocks kept apart. It was worse than "not built" — the masthead had
linked to it from every page for days, so the whole site carried a 404 in its
global navigation.

## Bug/Feedback page
**DONE.** The page existed but was reachable from one buried text link and the
404 page. REPORT is now in the masthead on every page, and feature pages carry
an inline prompt — that is where someone actually notices a wrong status.
Contact address is steven@innes.io.

Still open: the scraping User-Agent in `.env` and `DEPLOY.md` carries the old
gmail. That string is what we present to every server we fetch from, so it is
an outward-facing identity and Steven's to change.

## List cabanes and other similar things on the webpage.
**DONE for now, 24 -> 59 huts.** Front page lists every hut, highest first,
with capacity/warden/water and per-hut CC BY-SA attribution. 29 FR, 25 IT,
5 CH; all have geometry and an altitude; 50 of 59 carry directory facts.

The Swiss ones went in (Trient, Envers des Dorées, Orny, A Neuve, Saleinaz).
Three Swiss remain unimported pending a call on where the massif ends: Col de
Balme (on the border itself), Petoudes and Le Peuty — all valley-floor or col
rather than alpine. They are in `seeds/osm_candidates.yaml`.

Watch the low-altitude tail: `chalet-du-caf-contamines` (1164 m),
`auberge-du-truc` (1750 m), `rifugio-maison-vieille-bar-ristorante` (1956 m)
and `la-casermetta` (an Espace Mont-Blanc visitor centre) are what OSM tags as
huts, not what a climber means by one. Prune by hand or add an altitude floor.

## Refuges that need adding: Montenvers, Flégère, Lac Blanc
**NOT DONE — and all three are explained, none is missing from OSM.**

- **Refuge du Montenvers** — OSM way/97315062, tagged `tourism=hotel`. Our
  recon query in `fetch_osm_candidates.py` asks for `tourism=alpine_hut`,
  `wilderness_hut` and `amenity=shelter+basic_hut`, so it never asked for
  hotels. THIS IS THE THIRD TIME that exact bug has bitten: the rack railways
  and the bivouacs were both "OSM does not have it" when the query simply never
  asked. Fix in the query, not by hand, and expect more than Montenvers to
  arrive with it — the massif has several refuges that are legally hotels.
- **La Flégère** — a hut in OSM, 14.2 km from the summit.
- **Refuge du Lac Blanc** — a hut in OSM, 2352 m, 16.7 km from the summit.

Both of the last two are real massif huts that the 12 km import radius cut off,
along with Dalmazzi (15 km) and Comino (15 km). The radius was chosen because
at 14 km the Beaufortain starts arriving (Mont-Joly, Nant Borrant), so widening
it is not the answer — hand-written entries are, which is what the curated file
is for. `python -m massif.scripts.import_osm_huts --radius 17` would show what
a wider net catches if you want to compare.

## Refuge de la Leisse
**ADDED ON REQUEST, BUT IT IS NOT IN THIS MASSIF — needs a decision first.**

OSM has it: `tourism=alpine_hut`, 2487 m, at 45.3969, 6.8824. That is **48.4 km
from the summit of Mont Blanc**, in the Vanoise — a different massif, a
different national park, and four times further out than the furthest thing we
carry on purpose (Dalmazzi and Comino at 15 km). For scale, the 12 km import
radius was drawn where it is because the Beaufortain starts arriving at 14.

So this is not a "which huts in the massif have we missed" item like Flégère
and Lac Blanc; it is a question about what the site is. CLAUDE.md opens with
"the Mont Blanc massif", the front page says "in the massif", and the hut
directory header counts "N in the massif". Carrying a Vanoise hut makes all
three of those untrue, and the honest version would be to widen the stated
scope rather than quietly stretch it.

Three ways to go, Steven's call:
- **Not the massif, leave it out.** Nothing changes.
- **Widen the scope deliberately** to "the French Alps around Mont Blanc", or
  similar, and change the copy that currently promises otherwise. Then Leisse
  goes in along with a lot of the Vanoise.
- **It was a different hut.** "Leisse" is distinctly Vanoise; if the one meant
  is nearer, name it and it goes straight in — the import script and the
  curated file both take single additions easily.

## Need to add Italian and Swiss lifts/railways too
RECONNED. The stark numbers were **37 French lifts, 1 Italian, 0 Swiss** — but
two of those three are not the gap they look like, and the recon is worth more
than the count.

**The French side is not short of features.** Our lift model is sector →
machine: `aiguille-du-midi` carries the geometry, and `TPH AIGUILLE DU MIDI`,
`TPH PLAN DE L'AIGUILLE`, `TC PANORAMIC MONT BLANC` hang off it as children
auto-created from the operator feed. Those children have no geometry BY DESIGN.
An OSM comparison that counts them as missing gets a frightening and wrong
answer — a name match said "26 not carried", a position match said "33", and
both were mostly the same machines under other names. Do not import from
either number.

**Italian: blocked on TLS, not unstarted.** Skyway is the operator, and neither
hostname presents a verifiable chain: `www.montebianco.com` never sends its
Sectigo intermediate (openssl verify error 21), `skywaymontebianco.com` is
self-signed (error 18). We do not turn verification off and do not pin their
missing intermediate for them — an operator's TLS is theirs to fix. Full
diagnosis is in `seeds/sources.yaml`. Re-check with
`openssl s_client -connect www.montebianco.com:443`; if it stops saying 21,
this becomes an ordinary scraper.

**Swiss: genuinely thin, and small.** Inside the published boundary OSM has
essentially one operator — La Breya 1 and 2 at Champex-Lac (Téléchampex). The
Trient and Le Châble lifts are outside the massif ring. A two-feature job, not
a region.

**Genuinely missing and worth adding:** the Mont Blanc Express railway line
(SNCF Réseau, `Ligne de Saint-Gervais-les-Bains-Le Fayet à ...`, 112 OSM
segments inside the boundary). It is the access railway for the whole valley
and we do not carry it.

**The Tramway du Mont-Blanc now has a status source** — `tmb-tramway`, weekly.
Found via OHM's outbound links: the `tramway-montblanc` slug on the operator's
own site redirects off-site to tramwaydumontblanc.fr, which publishes the
season's running periods. Emitted as OPENING at UNKNOWN, feeding `season`, so
the page reads "Scheduled to run 31 Aug – 27 Sep 2026 (operator timetable, not
a report that it is running)" rather than a green dot. Original finding, kept
because it is what made the search worth doing:
Neither operator page publishes it — checked rather than assumed. Both
`infos-live` and `annual-openings` contain the string "Tramway du Mont-Blanc"
against the slug `tramway-montblanc`, which looks exactly like a row we drop.
It is not: the only occurrence is in the RSC payload's `resort` table of
display labels, with no season or live row behind it. Giving the Tramway a
status needs a source of its own.

## Need to do more scans on the routes
**Diagnosed: 13 routes and couloirs in the database, exactly 1 visible.**
Not a scanning problem — a listing problem. The front page only lists features
something has been published about, and Saint-Gervais publishes about the
Goûter route and nothing else. The other 12 (Trois Monts, Aiguilles Grises,
Cosmiques, Midi-Plan, Dent du Géant, Diable, Frendo, Chéré, Petite Verte,
Aiguille du Tour, Vallée Blanche, Grand Couloir) are held and reachable only by
URL or the map.

Fix is the same pattern as the hut directory: a routes section that lists all
of them regardless of status. Cheap, and it is the other half of the "huts and
lifts are findable, routes are not" gap.

## A date-only source is being printed with an invented hour
The Cosmiques route page reads "Published 10 Aug, 02:00 resort time". camptocamp
gives a trip report a DATE and no time; the 02:00 is midnight UTC rendered in
Paris. Harmless-looking, and still a precision we do not have — the same family
as everything else on this list.

The fix is a display one, not a data one: a statement whose source published
only a day should print only the day. Needs an optional flag from the API
(`date_only`, set where the payload says so) and a branch in the meta line.
Left undone because the meta line is shared by every source and the wording
there is yours.

## Re-extraction throws away review decisions
Accepting a statement sets `reviewed_at` on that ROW. `reextract` supersedes
every statement a document produced and writes fresh ones, so the new rows come
back with `needs_review` and no `reviewed_at` — the human decision is gone and
the item reappears in the queue. Seen for real: the Cosmiques statement
accepted from the admin page was back in the queue after the next re-extract.

Not wrong exactly — the new statement genuinely IS a different reading, and
silently inheriting an approval would be worse. But a reviewer whose work
evaporates every time a parser improves will stop reviewing.

Options, roughly in order of how much they cost:
  * carry `reviewed_at` forward when the new statement is byte-identical to the
    superseded one (same feature, type, status, window and evidence);
  * record decisions against the EVIDENCE SPAN rather than the row, so the same
    sentence stays approved however often it is re-read;
  * leave it, and re-extract deliberately rather than casually.

The second is the honest one and the most work.

## Triage the statements waiting for review
Eleven statements a model read are sitting in the queue, visible on feature
pages but unable to take a status slot until a person clears one. Several look
like real coverage — Saleinaz "unstaffed from 8 August until...", Plan Glacier's
summer hours, the Requin's winter room. Each accepted one is potentially a hut,
which is the cheapest route from 37 to low 40s.

    python -m massif.scripts.review              # the list
    python -m massif.scripts.review --show ID    # evidence, in full
    python -m massif.scripts.review --accept ID --note "why"

Read the evidence, not the summary: the summary is the only field the model
WROTE rather than copied. Where a reading says "unknown" check the `demoted`
line — rule 3 turns an undated closure into unknown, so "unknown" there means
"it wanted to say closed and gave no dates", not "the model had no opinion".

## Deployment has never actually run
`gh secret list` and `gh variable list` are both EMPTY. No DATABASE_URL, no
INGEST_ENABLED — which is why scheduled ingest runs show "skipped" rather than
"success", and why a manual dispatch fails in 12 seconds on the config check.
DEPLOY.md still has `<api-project>.vercel.app` placeholders and there is no
.vercel link in the repo.

So everything built so far lives in the local Postgres and on GitHub. "Runs
weekly" is true of the code and the cron and untrue of the deployment.

To finish it: set the Supabase `:5432` session URL as the DATABASE_URL secret,
set USER_AGENT (with a real contact address — see the note about the gmail
in it), set INGEST_ENABLED=true, then `gh workflow run ingest.yml`, which
runs migrate before anything else.

**Order matters now.** Migrations 0010 (llm_cache) and 0011 (statement_review)
are not on the hosted database, and the ORM selects `statements.reviewed_at`.
If Vercel is connected to this repo, the API will 500 on every request until
that migration runs.

## Hut websites via the model — MEASURED across all 25
robots.txt on every host: **23 allow, 2 REFUSE** — `refuge-lac-blanc.fr` and
`www.rifugiogonella.com`. Those stay out, not worked around.

Then every allowed site was fetched and measured (free, no model):

    15 of 24   have readable prose containing a month name
     8 of 24   are JS-rendered and yield under 400 characters:
               Miage, Bertone, Charpoua, Montenvers, Nid d'Aigle,
               Grands Mulets, Dalmazzi, Elena
     1         Auberge du Truc — camptocamp's URL 404s

**ITALIAN WAS THE WRONG TARGET, and that was my call to make and I got it
wrong.** I proposed extending fr_dates to Italian as "the single highest-value
change". Of the 15 readable sites, ELEVEN are French-language — the seven
French huts plus the four Suisse-romande CAS huts, where parse_range already
works. Only four are Italian, and of those Bonatti's only date is 1948, Torino
publishes one closing date and Monzino "APERTURA 12 GIUGNO" with no year.
Italian date support is worth one or two huts, not the unlock I claimed.

**THE REAL BLOCKER IS YEARLESS RECURRING SEASONS.** Refuge de Tré la Tête says
"vous accueillent du 15 mars au 15 octobre" — a real season, no year, because
it recurs annually. parse_range requires a year, so guard 2 drops the dates and
the new rule-3 guard demotes the statement to unknown. Most hut homepages are
written this way. This is the same shape `_coarse_windows` already solves for
FFCAM, where the year comes from the document and the result is flagged
`approximate` because the dates are OURS.

Doing it here means letting a caller pass an assumed year into
`cross_check_dates` — deliberately weakening a shared guard for one source —
so it needs the same care FFCAM's version got: narrow the window, mark it
approximate, and never let phrase_for_now print it as a published date.

**IT DOES WORK WHERE THE PIECES LINE UP.** Cabane d'Orny returned "open,
26 Jun – 13 Sep 2026", dated and parsed, from the operator's own page. The
second statement on that page — "outside the season the A Neuve is completely
closed" — was correctly demoted to unknown with `undated_status: closed`,
which is the rule-3 guard doing its job on live data.

Realistic ceiling: roughly 11 French-language sites, minus those whose season
is prose the model declines, so call it 6-9 huts. Worth building. Not worth
pretending it is more.

Also: the operator URLs came from camptocamp and at least two are wrong
(Saleinaz 404, Plan de l'Aiguille points at a regional gîte directory rather
than the hut). They need curating and checking, not trusting.

## One document, three rows — every "documents" count is inflated
Saint-Gervais has 36 document rows for 15 distinct URLs. `store_document`
dedupes on a hash of the content, and these pages change slightly on every
fetch — a rotating nav item, a date somewhere — so the same article is stored
again as a new row each time.

Harmless for correctness (extraction is per document, and re-extraction
supersedes per document), but it inflates every count anyone quotes, and it
inflated one badly enough to nearly cost money: "28 of 36 documents produce
nothing" is 11 distinct articles, not 28. Worth either hashing the extracted
prose rather than the raw HTML, or reporting distinct URLs wherever a document
count is printed.

## "Published" is our fetch clock wearing the source's label
FOUND, NOT FIXED — the wording is a call for you, not for me.

A feature page prints "Published 1 Sept, 19:42 resort time · source re-checked
13 min ago". The second half is right. The first half is `observed_at`, and for
three of our five sources `observed_at` IS the moment we fetched:

    mairie-saint-gervais   10 statements   real publication date  ✅
    refuges-info            6 statements   their derniere_modif   ✅
    mbnr-live              32 statements   our clock
    mbnr-openings          21 statements   our clock
    ffcam-refuges           9 statements   our clock

For mbnr-live that is nearly true — a live feed's reading is published
continuously, so our fetch time is about when it was published. For the two
seasonal sources it is not: FFCAM put the Goûter's season up in the spring and
the page says we published it today. That is rule 10 running backwards, one
column carrying both clocks in the direction that manufactures freshness.

This predates the FFCAM work (53 of the 62 affected statements are mbnr's); the
new source made it visible rather than causing it.

Fix shape: the API knows which it is — `document.published_at` is None exactly
when the date is ours. Expose that as an optional boolean (optional for the
usual deploy-skew reason) and let the page say "Published" only when it is
true. What it should say otherwise is the open question — "First seen",
"Recorded", "Known since" all read differently, and on this site that choice
matters more than the plumbing.

## Add search function to be able to find routes,huts,lifts etc.
NOT STARTED. 115 features, all server-rendered, so this can be a plain
server-side filter on /features rather than a client-side index. Worth doing
before the filter below — search subsumes most of what a filter is for.

## Add filter (to be able to organise huts,lifts etc)
NOT STARTED. The hut directory at 59 rows is the first listing long enough to
need it.

## If possible, add the ability to choose what layer you want to see on the map
NOT STARTED. Feasible: the map takes a single raster source, and IGN publishes
several key-less layers on the same WMTS endpoint — PLANIGNV2 (current),
Scan25 (`GEOGRAPHICALGRIDSYSTEMS.MAPS`), and orthophoto
(`ORTHOIMAGERY.ORTHOPHOTOS`). A control that swaps the tile URL is small.

Worth knowing before designing it: IGN is the FRENCH national mapper, and we
now hold 25 Italian and 5 Swiss huts. Check what its cartography actually looks
like over Courmayeur and Trient before committing to it as the only base —
swisstopo and the Italian regional layers may be better on their own side.

---

# Settled, with the reasoning, so it does not get re-opened

## The map drew two symbols per hut — RESOLVED
IGN draws its own green hut glyph, and we painted a marker on top: two icons,
one clickable. A ring around theirs was worse — it made the doubling obvious.

The fix was neither: IGN only starts drawing refuges at **z13**, measured by
pulling tiles over the Goûter and the Cosmiques at z11–z16 and counting the
glyph's green. The map opens at 10.2. So below z13 we draw a small locator dot,
and from z13 up it fades and IGN's symbol has the point to itself. Status
markers stay ours at every zoom, because a source having published something is
the one thing IGN cannot know. The outer element is only ever a hit area, so
every hut is clickable at any zoom.

Checked for clutter at the opening view: 66 markers on screen at 1280×848, 5
overlapping pairs. Not crowded. Nothing further needed here.

Note for anyone testing map behaviour: **neither clicking the zoom control nor
dispatching wheel events from script moves a MapLibre map.** Both silently
proved nothing until I measured the zoom itself. Set the initial zoom and
reload instead.

## Why so much "unknown" — NOT A BUG
Current, after FFCAM: **huts 11/74, lifts 4/38, routes 1/12** carry a status
that is not "unknown".

Huts moved 2 → 11: refuges.info's `etat` says which are shut, and FFCAM
publishes a dated warden season for the ones it runs. The remaining 63 are
mostly Italian and Swiss huts and small bivouacs that nobody publishes a status
for at all.

Lifts read 4/38 not because we are missing lifts but because it is 1 September:
the operator's own feed says "En préparation" for the ski sectors, which is
rule 3 working — "unknown, no information, not fine". That number moves on its
own in December without a line of code.

A coverage fact, not a defect. It only improves with more sources.

---

# Recon notes (so nobody repeats them)

## Hut coverage: the operator-by-operator route (the biggest remaining move)
FFCAM turned out to be the shape that works — an OPERATOR publishing its own
huts' warden seasons on its own pages — and it took French huts from 2 to 14.
The same shape exists on the other two sides and is not built.

Wardened huts with NO status, by country (the ones a season exists for):

    FR  22   mostly non-FFCAM: Cosmiques, Plan de l'Aiguille, Charpoua, Lac
             Blanc, Bellachat, Flégère, Montenvers, Miage, Tré la Tête, Plan
             Glacier, Robert-Blanc, Fioux, Bionnassay, Truc, Lognan
    IT  10   Torino, Gonella, Monzino, Elisabetta, Dalmazzi, Bonatti, Elena,
             Monte Bianco, Maison Vieille, Le Randonneur
    CH   6   Trient, Orny, Saleinaz, A Neuve, Col de Balme, Le Peuty

**Italy — the CAI sezioni.** Torino, Gonella, Monzino and Elisabetta are each
run by a CAI section that publishes its own season, exactly as FFCAM does.
Start there rather than with a regional aggregator: an operator is
authoritative about its own inventory, which is the whole reason the FFCAM
parser could be strict. Also worth checking whether the Valle d'Aosta region
publishes a rifugi dataset with opening periods.

**Switzerland — SAC/CAS.** Trient, Orny, Saleinaz and A Neuve are CAS huts.
sac-cas.ch has a per-hut portal; check whether the opening period is in the
server HTML before reaching for anything heavier.

**Already ruled out:** hut-reservation.org (the SAC booking platform) publishes
`/api/v1/reservation/hutInfo/<id>` openly — name, coordinates, altitude,
warden, website — but no season or availability. Everything past hut metadata
is behind login, and neither it nor alpsonline.org serves a real robots.txt
(both return the SPA HTML for it, so no rules are declared).

## Route status — MEASURED, and the ceiling is much lower than it looks
The question "why do 12 of 13 routes read unknown" has an answer now, and it is
not about our automation. Two candidate sources, both reconned properly.

### Préfecture de la Haute-Savoie (the seeded `pghm-chamonix`) — thin
robots allows; `/contenu/action?SearchText=` is a working server-side search;
`/Actualites/Espace-presse/Communiques-de-presse-2026` is a dated,
server-rendered list of ~95 press releases with PDFs attached.

Of those ~95, roughly a dozen are mountain-related and almost all are avalanche
or weather VIGILANCE — which is "avalanche bulletins", explicitly Not in v1.
The access bans amount to one story: "Démontage de l'ancien refuge du Goûter et
interdiction temporaire d'accès" (published twice, 07/04 and 22/05). Two
problems with it: the body is a PDF, so the ban's validity window needs
extraction we do not do yet, and by rule 3 an undated closure must emit UNKNOWN
rather than a closure — and the subject is "l'ancien refuge du Goûter", which is
on our DECOY list, being the hut the mairie demolished.

Worth building eventually as the authoritative publisher of access bans. It
will not move the route numbers.

### camptocamp outings — real, structured, and far sparser than it sounds
Their `/outings` API is a genuine route-conditions feed: `date_start`, and
`condition_rating` as a STRUCTURED ENUM (excellent / good / average / poor),
not prose. That matters — it means this needs no LLM, so the phase-2
`ANTHROPIC_API_KEY` decision is NOT what blocks it.

What blocks it is CLAUDE.md: "Crowd-sourced condition reports ... do not start
them until v1 has run a full season." That is your call, so it was not started.

Before making it, here is what it would actually buy, measured on 1 Sep 2026
(naive name matching, so the misses are pessimistic — real aliases would
recover several):

    our route              c2c route                    all   90d  rated  latest
    cosmiques-arete        Arête des Cosmiques          644    14     10  2026-08-10 average
    frendo-spur            Espolón Frendo               104     6      5  2026-06-17 average
    chere-couloir          Goulotte Chéré               299     0      0  2026-04-26 poor
    aiguilles-grises       Via delle Aguilles Grises     77     0      0  2025-06-23 good
    arete-du-diable        Arête du Diable Intégrale     66     0      0  2025-11-29 excellent
    vallee-blanche         Vraie Vallée Blanche          30     0      0  2026-03-05 good
    (7 more matched no c2c route on name alone)

**2 of 13 routes have any report in the last 90 days.** The Chéré has 299
lifetime reports and nothing since April, because it is an ice route and it is
September. Route conditions are seasonal and sparse: the biggest community
database in the Alps has nothing recent to say about eleven of our thirteen.

So the honest ceiling from this source today is roughly 1/13 -> 3/13, decaying
as reports age past STALE_DAYS. It is worth having in a full season, which is
more or less exactly what CLAUDE.md already says. The reason to revisit is
winter, not effort.

## La Chamoniarde / OHM — it is a DIRECTORY, not a publisher
This was the last obvious candidate for ROUTE conditions, and CLAUDE.md still
lists it as "client-side rendered: find the XHR endpoint". Two corrections.

It is **server-rendered**, so that note is out of date — but the conditions are
not in the HTML either. `/montagne/fil-info` renders only an intro paragraph.
`/actualites/conditions` is news prose, and its lead item republishes the
Saint-Gervais arrêté we already ingest directly — one hop from the authority,
the same reason Fondazione Montagna Sicura was rejected.

The decisive check was what its pages link OUT to:

    /montagne/refuges              -> fondazionemontagnasicura.org/fr/infos-refuges
    /montagne/remontees-mecaniques -> montblancnaturalresort.com/... and montebianco.com

Every one is a source we already ingest, have already rejected, or cannot reach.
OHM is a well-made directory of other people's data, not an independent
publisher of structured status. Nothing to scrape.

The remaining honest route to per-route conditions is their news prose, and
that needs the phase-2 LLM decision (`ANTHROPIC_API_KEY`) which CLAUDE.md still
lists as open. Rules stay on structured sources; there is no structured source
here.

**One thing did come out of it.** The lifts page linked to
`montblancnaturalresort.com/fr/tramway-montblanc`, which redirects off-site to
tramwaydumontblanc.fr — where the Tramway's running periods actually live. That
is now the `tmb-tramway` source.

## Fondazione Montagna Sicura — REJECTED as a closure source
Was the plan in CLAUDE.md for the Italian side. Does not survive contact:
- **/condizioni-montagna** — abandoned January 2025. Every recent entry is
  authored "OHM Chamonix", in FRENCH, about the CHAMONIX side. Scraping it
  would republish the parked `chamoniarde-ohm` source one hop away and date it
  2025. Structure if ever revisited: bulletins are WordPress COMMENTS
  (`.comment.depth-1`), 10 per page, paginated /2 … /7, dated in Italian.
- **/diario-salite** — current and moderated, but it is the Cahier de courses:
  crowd-sourced condition reports, which CLAUDE.md "Not in v1" defers.
- **/rss + /news** — institutional news. Clean RSS 2.0, full bodies, RFC-822
  dates. ONE notice in 20 items over three years (the Tour du Mont Blanc
  camping/bivouac ban, 3 Jul 2026, a real Courmayeur restriction). The only FMS
  surface worth scraping, and it is news, not conditions.
- **/info-rifugi** — 67 Aosta huts, but facts not statements, and it tells
  readers to phone the guardian. Same shape as refuges.info -> feature_facts.
- robots.txt 404s, which means allow-all, not refusal.

## The Italian side is BLOCKED, not unstarted
- **comune.courmayeur.ao.it** — the right source, a TCP connect timeout as of
  31 Aug. An unreachable robots.txt is a refusal here, so we wait. Retry:
  `curl -sS -o /dev/null -w '%{http_code}\n' --max-time 15 https://www.comune.courmayeur.ao.it/robots.txt`
- **courmayeurmontblanc.it** — reachable, robots-permissive, WordPress + Yoast
  with ld+json dates, and it DOES publish the Val Veny / Val Ferret / tunnel
  closures that gate Elisabetta, Monzino and Gonella. Declined 31 Aug: it is
  the tourist office, the same distinction CLAUDE.md draws for chamonix.fr vs
  chamonix-mont-blanc.fr. Seasonal, not dead — Val Veny closes each October, so
  a nine-month gap is the season, not abandonment.
- True of any Italian scraper: `fr_dates.parse_range` cannot read Italian, and
  `FeatureResolver` has no Italian-generic handling — it is a SEPARATE code
  path from the hut-facts matcher and did not get `match_key`, so "Refuge
  Francesco Gonella" still scores 85.5 against our "Rifugio Gonella", under the
  88 floor, if a notice ever names it. That is the highest-value small fix on
  this page.

## The lesson that cost the most
"6 with no entry — the Italian side is not covered" was a story that explained
a number, so nobody checked the number. refuges.info had all six. The claim was
wrong three times in one day (6 missing, then 1, then 0) and each correction
fixed the count while keeping the story. **"No entry" means we failed to match,
never that they do not have it.** The OSM query gap above is the same error in
a different costume: three times now, "OSM does not have it" has meant "we
never asked for that tag".

## Known and not acted on
- Six `.tbl` name cells overflow at 375 px. Measured with the flags hidden:
  the same six, so it is lift-name length, not the flags.
- NEXT_STEPS.md and OVERNIGHT.md are both stale — NEXT_STEPS describes the
  Aug-23 scaffold as unbuilt, OVERNIGHT's queue has drifted. Left alone
  because their status is Steven's call.
- The ingest only runs when someone runs it. The Actions cron is gated behind
  `INGEST_ENABLED` and there is no deployed database, so `last_seen_at` ages
  until a human intervenes.

## Implement new front page from Design (design 9C)

## Fix unkown status for majority of the huts/refuges

## Tell me when there is something to review

The review queue only works if somebody knows it is non-empty. Right now the
only way to find out is to go and look, which means it will be looked at
enthusiastically for a week and then never.

**Design, and the trap to avoid.** The ingest workflow already runs hourly and
already has repo credentials. Add a final step that counts statements with
`needs_review` true, `reviewed_at` null and `superseded_at` null, and — when
that count is above zero — opens or **updates one issue**, never a new one per
run. GitHub emails on issue activity, so there is no new service, no new
secret and no push provider to sign up for.

The "updates one" half is the whole design. A fresh issue every hour is the
same mistake the top of `ingest.yml` already records: it failed 48 times a day
and emailed every time, "which is not monitoring, it is training yourself to
ignore the emails that will matter". One issue, edited in place, title carrying
the count.

Worth including in the body: which features are waiting, and how long the
oldest has been. A queue of two is a chore; a queue of forty means a source is
emitting noise and the useful fix is upstream, not in the panel.

**Verified by:** a test over a seeded set asserting the count query ignores
superseded and already-reviewed statements, plus one manual `workflow_dispatch`
with a deliberately seeded queue.

## Keep the admin panel off the public internet

Current state, checked in production 6 Sep 2026: `/admin/review` returns
**404** on massif-api.vercel.app. Not a login page — the routes are not
mounted, because `ADMIN_TOKEN` is unset and `include_admin` refuses to register
them without one. Absent rather than open. That is the design working, and it
is also why nobody can use the panel yet.

The question is what happens when it IS turned on. Today that would be HTTP
Basic over TLS, POST-only accept/reject with an `Origin` check, and
`noindex, nofollow` — decent, and all of it still on a public hostname where
the only thing between a stranger and the queue is one password.

**The better shape: a third Vercel project.** Same repo, same
`backend/` root, `ADMIN_TOKEN` set, and Vercel's own **Deployment Protection**
switched on so the whole hostname requires a Vercel login. The public API
project keeps `ADMIN_TOKEN` unset and therefore keeps returning 404. Two
independent gates, no new code, and the public surface loses the routes
entirely rather than merely guarding them.

Note the constraint that rules out the obvious alternative: Deployment
Protection cannot go on the existing API project, because the frontend
server-renders every page by calling it and SSO would block those calls too.
That is the same trap as the 302 we hit on the first deployment URL.

**Verified by:** `/admin/review` still 404 on the public API; the admin project
returning a Vercel SSO redirect to an unauthenticated client and the real page
to a signed-in one.

## Let a human force one source from the Actions tab

`run_ingest <slug>` runs one source ignoring its cadence — that is the
documented CLI usage and it is how the weekly hut sources get refreshed on
demand. The workflow cannot do it: its step is a bare `run_ingest`, so a
`workflow_dispatch` only ever runs what is already due.

The consequence is that "refresh the huts now" currently requires a laptop
with the production connection string on it, which is exactly the dependency
deploying was supposed to remove.

Add a `workflow_dispatch` input — `source`, optional, free text — and pass it
through. Empty keeps today's behaviour.

**Verified by:** one dispatch with the field blank running the due set, and one
with `refuges-info` running that source when it is not due.

## Re-run the hut-website recon across all 74 huts

`seeds/hut_sites.yaml` configures **8**. That file was written when the
inventory was smaller and the recon covered about 25 candidate sites; there are
74 active huts now and 32 with no usable status, so most of them have never
had their own website looked at.

Two entries in it are also stale: `auberge-du-truc` and `refuge-du-fioux` point
at `montourdumontblanc.com` in the legacy `il4-refuge_….aspx` form. That portal
is now read properly, as structured availability, by `tmb-refuges` — which is a
better source for it than asking a model to read the prose around a booking
calendar. Drop both from `hut_sites.yaml`.

The recon itself is mechanical and should be scripted rather than done by hand,
because it will need doing again: for each hut with no status, find a candidate
URL, check `robots.txt`, fetch once, measure `readable_text` length, and record
the outcome **with its reason** — robots refusal, JS-rendered and under 400
characters, already covered by a better source, or usable. The reasons are the
valuable half: the current file's header is the only thing stopping the next
person re-testing sites that have already been ruled out.

Weigh the review load before turning any of it on. Everything from this path is
written `needs_review`, so a person clears each statement before it can take a
status slot — that is a safety net across eight huts and a bottleneck across
fifty.

**Verified by:** the recon script's output committed as the seed file's header,
and a test that every entry in `hut_sites.yaml` names a hut that exists.

