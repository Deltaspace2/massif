# Task list

Steven's items as headings. Notes underneath are mine.

Cleaned up 10 Sep 2026: everything finished was collapsed into **Done** at the
foot of this file, one line each. Nothing measured was deleted — the recon
notes are the most valuable thing here, because every one of them is an
afternoon somebody does not have to spend twice.

---

# Next up

Ranked. The top one is the recommendation.

## Saint-Gervais stores the same article three times over
The mechanism for this already exists and exactly one source uses it.

`store_document` now takes an `identity` — what makes a document the same
document — and `hut-sites` passes the extracted prose, because those pages
rotate a token in the markup while the words stay identical. Saint-Gervais has
the same shape and still hashes raw HTML: **52 document rows for 18 distinct
URLs**, which is what made "28 of 36 stored documents produce nothing" a number
nobody could reconcile with the 11 articles actually behind it.

Two things to get right, because this source is not hut-sites:

* Identity has to be **title + body**, not body alone. Rule 2 classifies from
  the title, so two articles differing only in title are two documents and must
  stay two.
* **Measure first**, the way hut-sites was measured: pull the stored copies of
  one article and compare extracted text across them. If the prose genuinely
  differs between fetches then this is not the same bug, and the fix is the
  other option — report distinct URLs wherever a document count is printed.

Small, well understood, and it makes every count in this file trustworthy.

## The Mont Blanc Express railway is not carried
SNCF Réseau's line through the valley, 112 OSM segments inside the boundary. It
is the access railway for the whole Chamonix side and we hold nothing for it.
Genuinely missing, unlike most of the apparent lift gap.

## 26 of 40 lifts have no geometry
The biggest remaining hole on the map now that routes are 12 of 12. Start by
widening `fetch_osm_candidates`' tag query: the Grands Montets cable car was
invisible because it is tagged `aerialway=construction`, the FOURTH time "not
in OSM" has meant "we never asked for that tag" — after the rack railways, the
bivouacs and the Refuge du Montenvers. Expect more than lifts to arrive with it.

Steven's related note below: lifts are drawn inconsistently — some marked, some
with a line, some a bare dot — and every tram, telecabine and chairlift should
be on the map. Standardise the symbology in the same pass.

## Filter (search shipped first, as planned)
Search is live at /search — one GET form, server-rendered, accent-blind, and
an empty result says "not carried" rather than implying anything is open or
shut. It subsumes most of what a filter was for; whether a filter is still
worth having is now a question to answer from use, not up front.

---

# Waiting on you

## Vercel's firewall — RESOLVED 10 Sep 2026, and the answer changes our tooling
Steven opened the Firewall tab: **Bot Protection is set to Challenge**, which
challenges non-browser requests *excluding verified bots* — so Googlebot
passes and the SEO channel is intact. AI Bots is on Log. Attack Mode, the one
that would have gated crawlers, is OFF. All three left as they are, on
purpose.

**What this means for us:** the frontend can no longer be verified with curl.
Every scripted request to montblancmassif.org answers 429 with
`x-vercel-mitigated: challenge`, which looks exactly like an outage and is
not one — it was misread as one for half an hour the day it appeared. Verify
frontend deploys in a real browser (the browser pane); curl still works
against api.montblancmassif.org, which is a different Vercel project with no
Bot Protection. Any "Verified by: curl <frontend url>" line elsewhere in this
file now means "in a browser" — the email item's /about check included.

## Make a new email, put it on the website, and take my personal one off

DECIDED 9 Sep 2026: the address is **`contact@montblancmassif.org`**. Not
started — and the mailbox has to exist before any of the code changes. Both
addresses below have already been broadcast to every server we fetch, so this
is not a find-and-replace: the strings come out of the repo, the mailboxes
stay reachable.

**Where an address is published today.** Two different ones, both personal:

| Where | Address | What it is |
| --- | --- | --- |
| `frontend/app/about/page.tsx:12` (`CONTACT`) | `steven@innes.io` | the "please stop fetching" contact on /about |
| `frontend/app/about/page.tsx:25` (`USER_AGENT`) | `steven@innes.io` | the string /about quotes verbatim |
| `frontend/app/feedback/page.tsx:11` (`CONTACT`) | `steven@innes.io` | every `mailto:` on /feedback |
| `DEPLOY.md` §5 | `steven@innes.io` | the `gh variable set USER_AGENT` line — it carried the gmail until 10 Sep 2026, two deploys behind the variable |

`.env.example` and `backend/massif/config.py:27` carry
`contact@example.org` — placeholders, nothing to remove.

**The live values are not in the repo.** The User-Agent actually sent is the
GitHub Actions repository variable `USER_AGENT` (Settings → Secrets and
variables → Actions → Variables) and the same variable on the Vercel API
project. Editing `DEPLOY.md` changes the instructions, not what goes out on
the wire. Both have to be set by hand, and `about/page.tsx:25` is a hand-copy
of that same string with nothing enforcing the match — its own comment says
so. All three move together or the page quotes an address we do not send.

**Why this address.** Same domain as the site, so it needs no explaining in a
log line, and it survives the person behind it changing.

**Being days old does not block it.** The 60-day lock in the registrar item
above is ICANN's *transfer* lock — it stops the registration moving to another
registrar and says nothing about DNS. MX records, nameservers and receiving
mail are all available immediately. Asked and answered, so it is not asked
again.

**Route: Namecheap forwarding now, Cloudflare Email Routing later.** Namecheap
gives free forwarding on domains registered with them while the domain is on
their BasicDNS — they write the MX records, you point `contact@` at whatever
inbox you already read. Five minutes, no DNS migration. Email Routing is the
same thing free on the Cloudflare side and wants Cloudflare's nameservers,
which the domain gets anyway when the registrar item runs in December: the
natural replacement then, and a bad reason to move DNS now, mid-Vercel-setup.
A swap, not a dependency.

CHECK FIRST, NOT VERIFIED: that the domain is still on Namecheap BasicDNS. If
DNS has already moved for the Vercel wiring, the free forwarding is not there
and the `eforward*.registrar-servers.com` MX records have to go in by hand
wherever the zone now lives.

**Forwarding receives; it does not send.** A reply to a sysadmin who mails
`contact@` leaves from whatever inbox the forward lands in, showing that
address rather than this one. Untidy, not harmful, and worth knowing before it
surprises someone. Replying *as* `contact@montblancmassif.org` is a separate
purchase — a real mailbox (Fastmail, Migadu, Zoho) or Gmail "send mail as"
over an SMTP relay, plus SPF, DKIM and DMARC. A domain registered on 7 Sep
2026 has no sending reputation, so early mail from it can be filtered; volume
is what fixes that and this address will never have any. Not worth solving
until someone needs a reply to come from the domain.

**Forward BOTH old addresses, do not just drop them.** Neither is only a
string in a file. The gmail was the deployed `USER_AGENT` and went out on
every request up to 8 Sep 2026 — `4f07d57` records the page printing
`steven@innes.io` while the variable actually sent
`steven.innes8@gmail.com` — and the innes.io one has gone out since. Both are
sitting in other people's access logs, and that address is what a sysadmin
uses when they want us to stop. A bounce there is the one failure this project
promised not to have, and it arrives months later with no way to know it
happened. Keep both forwarding for a season at least; delete the strings from
the repo, not the mailboxes.

**Check what the variable actually says before changing anything.** `4f07d57`
changed the page, not the deployment, and nothing enforces the match — the
value in Actions may still be the gmail. `gh variable list` (or the Actions
Variables tab) settles it, and whatever it says is what the logs of every
server we fetch currently carry.

**Order:**

1. Set up the forward and confirm mail actually arrives — send from an address
   OUTSIDE the destination inbox, because a Gmail-to-itself test can pass
   while the outside world bounces.
2. Set the Actions variable and the Vercel env var to, character for
   character:
   `massif/0.1 (+https://montblancmassif.org/about; contact@montblancmassif.org)`
3. Change `CONTACT` on both pages, `USER_AGENT` in `about/page.tsx`, and the
   example line in `DEPLOY.md`; `grep -rn 'innes\.io\|innes8' frontend backend
   DEPLOY.md` should then come back empty.
4. Leave both old addresses forwarding, and note where that forwarding lives
   so the next person does not switch it off as tidying.

**Verified by:** sending a message to the new address from outside and getting
it; and `curl -s https://montblancmassif.org/about | grep massif/0.1` matching
the deployed variable character for character.

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

## Move the domain to a cost-price registrar — window opens 6 Nov 2026

`montblancmassif.org` was registered at Namecheap on 7 Sep 2026 for **$7.98**,
promotional. It renews at **$14.48/yr**, which is above the $10 budget that
picked this name in the first place.

Cloudflare Registrar sells at cost — roughly $10–11 for `.org`, with no promo
and no hike, because they make their money elsewhere. A transfer **adds a
year** rather than resetting it, so nothing already paid for is wasted.

**Dates.** ICANN locks a new registration against transfer for 60 days, so:

- **not before 6 Nov 2026** — it will simply be refused
- **do it around early Dec 2026** — comfortably past the lock, far from renewal
- **not later than ~Aug 2027** — leave room before the 7 Sep 2027 renewal, or
  auto-renew charges $14.48 first and the saving is gone for a year

**Leave auto-renew ON throughout.** It is insurance, not the plan: losing the
domain to a lapsed renewal once the feature pages are indexed costs far more
than $6, and SEO is this project's only distribution channel.

**The one trade-off, decided in advance so it is not a surprise:** Cloudflare
Registrar requires the domain to use Cloudflare's nameservers, so DNS moves
there from wherever it is. Vercel gives you the records to paste in. Set every
record pointing at Vercel to **grey cloud ("DNS only")** — orange proxies the
traffic through Cloudflare's CDN on top of Vercel's, which causes caching
oddities and can interfere with certificate issuance.

**A new zone starts EMPTY, and two of the records in it are invisible when
missing.** Moving nameservers carries nothing across. The Vercel records
announce their own absence — the site goes down — but these two fail silently
and are the reason this list ends with more than "the website loads":

- The **Google Search Console TXT** at the apex. Verified 10 Sep 2026, and
  Google re-checks it: lose it and the property un-verifies, the data stops,
  and nothing says why.
- The **`contact@` MX records** from the email item below. A bounce there is
  the address a sysadmin uses when they want us to stop fetching, months
  later, with no way to know it happened.

So the move is not done when the site loads. It is done when the site loads,
Search Console still reports the domain verified, and a test message sent from
outside still reaches `contact@`.

**Worth roughly $4/yr.** Small. If it is more fiddle than it is worth when the
reminder comes round, staying put is a perfectly reasonable answer — this note
exists so that is a decision rather than a default.

## Confirm design 11a, or go back to 9c
`/classic` still renders 9c, and `StatusLedgerRuled.tsx` is a second copy of
the row logic promised not to drift. Deleting that component, `app/classic/`
and the `.ruled` CSS block is one clean step the day you are sure — and it
stops being clean once the two diverge.

## Does Megève belong in this site at all?
19-22 km from Chamonix and outside the massif; its lifts never went through the
boundary polygon the hut import uses. They read `unknown` now rather than
frozen on a closure, so this is tidiness rather than a wrong answer — but it is
still unanswered, and the same question probably covers other operator-feed
children.

## A retired statement leaves no trace of what was last said
`retire_unmentioned` removes a withdrawn claim from the feature page entirely.
That may be right — it is not current, and this site shows what is current — or
the page may want a "last reported" line, the way a source going quiet gets
one. Worth deciding rather than leaving as a side effect of `superseded_at`.

---

# Open, not yet scoped

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

## Add Filter for map.


## Some lifts are not marked, some lifts are marked and have a line, some lifts just have a green dot. This needs to be standardised, and all trams, telecabines, chairlifts etc.., need to be shown on the map.


## Find a way to get on the google website list


## Create a scraper for latest important news.


## Hut-website recon — RERUN 10 Sep 2026, across every hut with a known URL

What changed since the 25-site original: the operator_url facts (camptocamp +
OSM) mean the URL inventory finally exists, so this pass gated every
unknown-status hut that has a website — 24 of them. Three survive all three
gates and are configured in `seeds/hut_sites.yaml`; the review-load worry that
capped the original recon is gone, because prose-identity means an unchanged
page is never re-decided and inherit_review keeps a decision across re-reads.

    ADDED   refuge-le-peuty (CH)          8646 chars, season stated
    ADDED   refuge-robert-blanc (FR)      3714 chars, season stated
    ADDED   refuge-du-plan-de-laiguille   its own page on the
            monrefugepaysdumontblanc directory, with a DATED season
            ("Ouvert du 23 mai 2026 au 1er novembre 2026"). camptocamp's URL
            pointed at the directory's front page, which is why the old note
            wrote this hut off.

    ROBOTS REFUSES (real Disallow)   refuge-lac-blanc.fr
    ROBOTS UNREADABLE that day       rifugioelisabetta.com · rifugiogonella.com
                                     — the transient kind; worth one retry on
                                     a later run before believing it
    404                              refugeducoldebalme.com
    JS-THIN (<400 chars of prose)    bellachat 51 · charpoua 128 · miage 214 ·
                                     montenvers 115 · nid-d-aigle 80 ·
                                     bertone 161 · dalmazzi 17 · elena 0 ·
                                     flegere 309 · grands-mulets 34 ·
                                     envers-des-aiguilles 34 · contamines 36
    READABLE, NO SEASON STATED       bionnassay 4594 · durier 1748 ·
                                     combal 3325 (it) · casermetta 6152 ·
                                     randonneur 1402 — their "season words"
                                     are a closed road and farm history, not
                                     a hut season; adding them would buy model
                                     calls and review noise for nothing

Worth a separate look sometime: five of the JS-thin sites are FFCAM
subdomains (durier, grands-mulets, envers, contamines, nid-d-aigle) for huts
that read unknown even though `ffcam-refuges` is a live source — the question
is why that source misses them, not whether their websites parse.
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

## Fix unkown status for majority of the huts/refuges


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


---

# Settled, with the reasoning, so it does not get re-opened

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

## Italian hut seasons — RECONNED 9 Sep 2026, ceiling is 3 huts not 10

"IT 10" above counts wardened rifugi with no status. Reconned properly, and
the number that can actually be reached is **three**.

31 Italian huts are held. Thirteen are bivouacs and already read `unstaffed`,
which is complete and correct — a bivouac has no warden season for anyone to
open or close. Five more already carry a status. That leaves ten rifugi, and
we hold no website for any of them, so the URLs came from the OSM ids we
already have (`website` tag) rather than from guessing domains.

Then the same three gates `hut-sites` applies, run for real:

    REFUSED by robots.txt      cabaneducombal.com · rifugioelisabetta.com
                               rifugiogonella.com · randonneurmb.com
    JS-rendered, no prose      caitorino.it/rifugi/dalmazzi (17 chars)
                               rifugioelena.it (0 chars)
    READABLE, states a season  rifugiotorino.com      1911 chars
                               rifugiomonzino.com     1336 chars
                               rifugiobonatti.it      3579 chars

Four refusals is the single biggest cause, and they are refusals: not fetched,
not worked around. `base.fetch` would raise on them anyway.

**The blocker on the remaining three is dates, not access.** They say
"!! CHIUSURA 13 SETTEMBRE" and "Il rifugio è aperto" — Italian. `llm.py`
verifies every model-returned date phrase by re-reading it with
`fr_dates.parse_range`, unconditionally and in French only, so an Italian
phrase fails that check, the statement arrives undated, and rule 3 correctly
demotes it to UNKNOWN. Adding these three to `seeds/hut_sites.yaml` before
that is fixed would add three items to the review queue and gain no status.

**So the order is: Italian dates first, then the three huts.** Extending
`fr_dates` rather than writing an `it_dates` beside it, because the grammar is
nearly identical — "dal 20 giugno al 20 settembre" is "du 20 juin au 20
septembre" with different vocabulary — and the subtle part being duplicated
would be the coarse ranges, the qualifiers and the year-crossing, not the
month names.

**Verified by:** the three sites producing dated statements that a person
clears, and `Rifugio Torino`, `Monzino` and `Bonatti` reading something other
than unknown.

**Not worth doing:** chasing the four refusals, or a headless browser for the
two JS sites. The Valle d'Aosta region is also out — `regione.vda.it/robots.txt`
disallows `/turismo/` entirely, and `lovevda.it` is the regional tourist board,
which is the same distinction already made for chamonix.fr over the tourist
office and for courmayeurmontblanc.it.

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

## What happens when a source stops mentioning a feature

Found 7 Sep 2026 by five lifts sitting permanently UNCHECKED after the cron
was fixed. All six Megève features — `megeve`, `megeve-mont-arbois`,
`megeve-rochebrune` and three child lifts — come from `mbnr-live` and were last
seen **1109 minutes ago**, while every other feature from that same source
refreshed minutes earlier in the same run.

The scraper is not broken. Megève is a ski area, it is September, and the
operator simply dropped them from the live feed. Their statements are frozen
mid-sentence — *"close — départ toutes les 30 mn à partir de 9h"* — and will
stay that way until someone notices.

**This is the general bug, and Megève is only where it surfaced.**
`retire_replaced` retires an old statement when a NEW one arrives for the same
feature, source and type. A source that stops mentioning a feature never sends
that successor, so nothing retires, and the last thing it ever said stands for
ever. The same shape has now been seen three times in a week: FFCAM switching
to English (seasons froze), re-extraction over stored history (duplicates
stayed live), and this.

The badges are doing their job — OLD and UNCHECKED are exactly what a reader
needs here — but they are the only thing standing between a reader and a
sentence the source withdrew months ago.

**NOT the same bug as the Goûter case found the same day** — see the next
section. That one looked identical from the outside and has a different cause,
which is worth remembering before reading a frozen statement as evidence of a
quiet source.

**Two things to decide, and they are separate.**

1. **The mechanism — DONE 8 Sep 2026.** `retire_unmentioned` in
   `massif/ingest/base.py`, opted in per source via
   `retire_after_unmentioned_runs` in `fetch_config`, set to 3 for `mbnr-live`
   by migration `0014`. The five frozen statements retired on the first run
   that carried it and the features now read `unknown` / nothing published,
   which is what this section asked for.

   Two things about the shape, both deliberate:

   * **Opt-in, because absence is only evidence when one fetch enumerates
     everything a source speaks about.** `mbnr-live` does — its 32 live
     statements were exactly the 27 it re-emits plus the 5 orphans.
     `mairie-saint-gervais` does not, and it caps at `MAX_ARTICLES`, so
     absence there can be *our own cap*. Retiring on it would drop a valid
     arrêté and turn a shut route `unknown` — the Goûter bug with the polarity
     reversed, and that direction fails unsafe. Do not make this a default.
   * **No counter column.** The count is "successful runs of this source that
     started after we last saw this statement", which works only because
     `confirm_still_standing` now advances `last_seen_at` on every run that did
     mention it, unchanged pages included. Before that landed the same code
     would have retired everything from any source whose pages sit still.

   **Still open from this:** a retired statement vanishes from the feature page
   entirely, so there is no trace of what the operator last said before it
   stopped saying it. That may be right — it is not current, and this site
   shows what is current — or the feature page may want a "last reported"
   line. Decide it rather than leaving it as a side effect of `superseded_at`.

2. **The scope — still open, and no longer urgent.** Megève is 19–22 km from Chamonix and outside the massif; the
   OSM hut import already filters on a boundary polygon and these lifts did
   not go through it. Either they belong and should be refreshed, or they do
   not and should never have been auto-discovered. Note the same question
   probably covers other operator-feed children — check what else came in that
   way before deciding.

**Verified by:** a test that a statement whose source has completed N runs
without re-emitting it stops being current; and, if the scope answer is "out",
a boundary check on lift import mirroring `import_osm_huts.load_boundary`.


---

# Done

One line each; the reasoning lives in the commit that closed it.

- **Feed page** — /feed: every notice, newest first, source per row, two clocks apart.
- **Bug/feedback page** — REPORT in the masthead on every page, plus an inline prompt on feature pages.
- **List cabanes on the webpage** — Every hut listed, highest first, with per-hut attribution. 24 -> 74.
- **Refuges that need adding: Montenvers, Flégère, Lac Blanc** — All three are features now. The OSM query gap that hid Montenvers is under 'the lesson that cost the most'.
- **More scans on the routes** — Routes have their own section and 12 of 12 carry geometry: 6 from camptocamp, 5 schematic, grand-couloir deliberately unmapped.
- **Implement new front page from Design (9C)** — Shipped, then superseded by 11a (photo headers). 9c kept at /classic until the choice is confirmed.
- **Add show all button to each section, minimised by default** — All four bands fold, closed on load, count on the pill. QuietRows stopped being a second fold inside the first.
- **Deployment has never actually run** — Supabase, two Vercel projects and the Actions cron, live on montblancmassif.org.
- **Tell me when there is something to review** — review_digest opens one GitHub issue and edits it in place.
- **Keep the admin panel off the public internet** — Separate Vercel project, token-gated; /admin is 404 on the public API.
- **Let a human force one source from the Actions tab** — workflow_dispatch takes a source slug.
- **Triage the statements waiting for review** — Queue cleared; it sits at 0.
- **Re-extraction throws away review decisions** — inherit_review carries an approval to the same sentence re-read. Five things must match; approvals only, never rejections.
- **last_seen_at only advances when the page bytes change** — confirm_still_standing: an unchanged document is confirmed rather than skipped.
- **Hut websites on the detail page** — camptocamp's operator_url sat unexposed on 44 huts; OSM's website tag covers 18 more. 62 of 74.
- **Italian dates** — fr_dates reads Italian, so the Courmayeur huts stop arriving undated. Torino, Monzino and Bonatti added.
- **The Anthropic key reaches Actions** — hut-sites runs in CI; the workflow installs the .[llm] extra it needs.
