# massif — design brief

A brief for redesigning an existing, working web application. The data layer and
the copy are done and are not the problem; the presentation has never had a
design pass.

---

## 1. What it is

**massif** answers one question about the Mont Blanc massif: *what is currently
shut, restricted, or officially flagged as dangerous?*

It is a **directory of published notices**. It aggregates what lift operators,
mairies (French town halls, who issue legally binding closure decrees), and
mountain-safety bodies have actually published, attributes every single line to
its source with a link, and never makes a claim of its own. Coverage today:
17 lifts and mountain railways, 19 huts, 13 routes and couloirs, 3 glaciers,
2 access roads — 54 curated features plus 21 auto-discovered individual lifts.

It is **not a safety service** and must never read as one. This is the single
most important constraint in the whole design, and it is a design problem, not
a copy problem — see §3.

Audience: alpinists and ski-mountaineers planning trips in the Chamonix valley
and the Italian side. A small, expert, unsentimental audience who are checking a
fact, not browsing.

## 2. The three moments someone opens it

Design for these, in this order of frequency:

1. **Planning, at a desk, at night.** Deciding whether a route is on for next
   week. Wants the seasonal picture — is the Aiguille du Midi lift running at
   all this season, is the Goûter route legally open — and does not care that
   everything is shut at 11pm because it's 11pm.
2. **The night before, on a phone.** Final check. Wants the exceptions only:
   what changed, what's newly shut.
3. **In a hut, on a phone, on bad signal.** Wants one feature's page and the
   date on it. This is where fast first paint and legible small type matter
   more than anything else on this list.

Nobody is browsing. Nobody is here for pleasure. Time-on-page is not a goal;
being right and being quick to read is.

## 3. The rule that outranks aesthetics

> **A stale "open" must never read as clearance to go.**

People die in this massif. If the site says a route is open because a scraper
last succeeded four days ago and nothing has been published since, and the
design presents that with the same confidence as a status confirmed six minutes
ago, the design has done real harm.

So:

- **Every status carries its age**, visibly, always — "last confirmed 6 min ago"
  / "3 days ago" / "never checked". This is not metadata to be tucked away in
  grey 11px at the bottom of a card. It is part of the claim.
- **Stale must be visually distinct**, not just annotated. Currently it gets a
  "⚠" glyph and an amber tint, which is weak.
- Absence of a notice is **not** evidence of safety. "unknown" must never look
  like a quiet "fine".
- Never let visual polish imply authority the data does not have.

Existing disclaimer copy (keep the substance, it can be reset typographically):

> A directory of what operators and authorities have published. Statuses may be
> out of date, and being confidently stale is the failure mode this page tries
> hardest to avoid — every row shows when it was last confirmed. Verify locally
> before committing to anything.

## 4. The central design problem: routine vs newsworthy

This is the thing to solve. Everything else is tidying.

A lift is "closed" at 3am because it is 3am. A lift is also "closed" because a
cable broke. The Goûter route is "closed" because the mairie issued a decree
banning access. **These are the same word and the same colour, and they must not
be the same weight.**

An earlier version coloured by live status and the entire page went grey every
evening — the one genuine seasonal closure hidden among eleven sleeping lifts.
The fix was to introduce two parallel axes:

- **`status`** — what is true *right now*. Includes `closure_kind:
  "outside_hours"`, meaning routine: night, or out of season.
- **`season`** — what is true *this season*. This is what the page colours by,
  because it is what a trip planner is actually asking.

So a lift can be `status: closed` (it's 9pm) and `season: open` (running all
winter), and it should read as **green with a quiet footnote**, not red.

The current page expresses this with two tiers — big "headline" cards for real
closures, and a compressed table for everything routine. The principle is right;
the execution is a slightly larger card and a slightly smaller table. **The gap
between "the reason this page exists" and "eleven lifts asleep" should be far
wider than it currently is.**

## 5. Surfaces

**`/` — the massif map and the answer.** Currently: a 460px map, a legend, then
headline closures, then a disclaimer, then two tables (routes/huts/access;
lifts). *Problem: the answer is below the fold. You land on forty undifferentiated
dots.*

**`/[type]/[slug]` — the feature page.** e.g. `/route/gouter-route`,
`/lift/aiguille-du-midi`. Server-rendered, and **this is where the traffic
actually arrives** — someone googles "aiguille du midi closed". It carries: the
name, type and altitude; a small map; the current status with its age; "also
currently in force" (other live notices that didn't win the headline slot); the
lifts inside a sector; child features; and a full history table of everything
ever published about it, each row linking to the original source. *Problem: every
section is the same size, so it reads as a flat list of equal things.*

**`/feed` — planned, not built.** What changed, reverse-chronological. The
endpoint exists. Worth designing for; it's the surface that gives someone a
reason to return.

## 6. Real data — please design with this, not lorem ipsum

**Real feature names** (they are long, accented, bilingual, and some are
disambiguated with an em dash — the type has to cope):

```
Téléphérique de l'Aiguille du Midi        lift     3842 m
Chemin de fer du Montenvers               lift
Tramway du Mont-Blanc                     lift     2372 m
Téléphérique des Grands Montets           lift
Skyway Monte Bianco                       lift     3466 m
Megève — Rochebrune                       lift
Domaine de Balme — Le Tour                lift
Goûter Route                              route    1653–4808 m
Grand Couloir du Goûter                   couloir  3400 m
Arête des Cosmiques                       route    3842 m
Dent du Géant — normal route              route    4013 m
Petite Aiguille Verte — normal route      route
Éperon Frendo                             route
Goulotte Chéré                            route
Refuge du Goûter                          hut      3835 m
Refuge de Tête Rousse                     hut      3167 m
Rifugio Torino                            hut      3375 m
Abri Vallot                               hut      4362 m
Bivacco della Fourche                     hut
Route/accès du Nid d'Aigle                access_road
Mer de Glace                              glacier
```

**Real status strings**, as they appear:

```
"Réouverture pour la saison d'hiver 2026-2027"      (source's own words, French)
"closed for the day · runs 07:20–16:10"             (routine — must look quiet)
"Reopening 26–29 May 2026"
"Closed 12 Mar – 3 Apr 2026"
"Closure notice — no dates stated"
"Winter season 28 Nov 2026 – 2 May 2027"
"Fermé de 13h00 et 14h00"                            (a lunch break, not a closure)
```

Source text is often French or Italian and is **reproduced verbatim in quotes**
alongside an English summary — the design needs a treatment for "here is what
they actually said" that reads as a quotation, not as our own prose.

**The shape of a feature** (TypeScript, abbreviated):

```ts
Feature {
  slug, type, name, names: {fr, it, en, de}, country,
  alt_min, alt_max, parent_slug, geometry, geom_verified,
  status: {
    value: "open" | "closed" | "restricted" | "unknown",
    severity: number,
    summary: string | null,          // "closed for the day · runs 07:20–16:10"
    observed_at: string | null,      // drives "last confirmed …"
    stale: boolean,
    closure_kind: string | null,     // "outside_hours" = routine
    altitude_m, other_notices: number,
    lifts: [{ name, status, times: string[], message }] | null
  },
  season: { value, reason, kind: "in_season"|"out_of_season"|"notice" }
}
```

Feature detail adds `other_notices: Notice[]`, `parent`, `children[]`, and
`history[]` — every row with `observed_at`, `summary`, `original_text`,
`original_language`, and `source: {name, url, type}`.

**Sources you'll see named**, each needing an attribution treatment:
Compagnie du Mont-Blanc (operator), Mairie de Saint-Gervais (legal authority),
Chamoniarde / OHM (institutional advisory). They carry different weight — a
mairie decree is law, an operator is authoritative about its own inventory, an
advisory is neither — and the design may want to make that legible.

## 7. Colour semantics that must survive

Four status values, and the meaning must not shift:

| value        | meaning                                      | current |
|--------------|----------------------------------------------|---------|
| `open`       | operating this season                        | `#3fb950` |
| `restricted` | open with conditions, or an advisory in force| `#d29922` |
| `closed`     | shut, or not running this season             | `#f85149` |
| `unknown`    | **no information** — never "probably fine"   | `#6e7681` |

Those hexes are GitHub's palette used verbatim, which is a large part of why the
site currently reads as a developer dashboard rather than as anything to do with
mountains. **Replace them** — but keep four clearly separable states that survive
colour-blindness (they must not rely on hue alone; there are dots, pills and
lines carrying this) and stay legible on a small phone screen outdoors.

There is a fifth, non-status line colour: routes drawn on the map purely for
context, with no notices attached. Currently a dashed grey.

## 8. What's wrong now — the specific brief

1. **The page doesn't answer its own question above the fold.** You land on a
   460px map with forty dots and a five-item legend; "3 closures and
   restrictions — the reason this page exists" is below the fold on a laptop.
   The map is context, not the headline.
2. **The map and the list don't know about each other.** Hovering a row
   highlights nothing on the map; clicking a dot scrolls nowhere. Same data
   feeds both.
3. **No identity.** GitHub's dark palette, system sans at one size, no
   typographic voice. It should feel like a precise, slightly austere reference
   instrument. Not a ski-resort marketing site, not adventure photography behind
   text, no hero imagery — nobody is here to be inspired.
4. **The feature page is flat.** Every section is a 15px `h3` with the same
   margin, so "Also currently in force" and "Everything published about this"
   weigh identically. Needs a real hierarchy, and the history table needs a
   treatment that survives twenty rows of quoted French.
5. **Mobile is unverified.** Three-column tables with a `width: 34%` first
   column. Moment 3 above happens on a phone.
6. **Stale is under-expressed.** A "⚠" and an amber tint is not enough weight
   for the failure mode the whole project is organised around.

## 9. Technical constraints

- **Next.js 15, App Router, React Server Components.** Content is server-rendered
  for SEO; the feature pages must stay indexable. Avoid designs that require
  client-side data fetching to show the primary content.
- **MapLibre GL JS** with **IGN Géoplateforme** raster tiles (French national
  mapping, free, key-less). The basemap imagery is fixed and cannot be
  restyled — it's a real topographic map, not a vector style we control. Marker,
  line and label layers on top are ours.
  - Two known MapLibre limits already hit: only one zoom `interpolate` per
    expression and it must be outermost; `line-dasharray` cannot vary per
    feature. Both fail silently.
- **Dark-first** currently. A light mode is fine to propose; outdoor phone
  legibility is a genuine argument for one.
- Plain CSS in a single `globals.css`, ~210 lines. No CSS framework, no
  component library. Happy to change that if there's a reason.
- Two feature geometries are deliberately absent (the Goûter route and the Grand
  Couloir): nobody has surveyed them, and a drawn line would imply a precision
  that does not exist. Any design must tolerate a feature with no geometry, and
  must not invent one.

## 10. Tone

Quiet, accurate, unglamorous. The register of a tide table or a NOTAM, not of a
travel brand. Confidence is expressed through precision and attribution, never
through polish. If a choice makes the site look more authoritative than its data
warrants, it is the wrong choice.
