# massif — favicon brief

A brief for designing the favicon and app icon for an existing, deployed site.
Everything below is measured from the live product, not proposed.

The site has **no icon at all** today — `/favicon.ico` and `/favicon.png` both
404 in production, so browsers show a blank page glyph.

---

## 1. What the site is

**massif** answers one question about the Mont Blanc massif: *what is currently
shut, restricted, or officially flagged as dangerous?*

It is a **directory of published notices** — it aggregates what lift operators,
mairies (French town halls, who issue legally binding closure decrees), hut
federations and booking systems have actually published, attributes every line
to its source, and never makes a claim of its own.

Live at https://massif-beige.vercel.app. Coverage: 132 features — 40 lifts and
mountain railways, 74 huts and bivouacs, 13 routes and couloirs, plus glaciers
and access roads, across France, Italy and Switzerland.

Audience: alpinists and ski-mountaineers checking a fact before committing to a
route. Small, expert, unsentimental. Not browsing.

## 2. The constraint that outranks everything else

**The icon must not encode a status.**

This is not a style preference, it is the product's central safety rule, and it
bites favicons specifically.

The site's whole visual language is status colour: green means open, amber
restricted, red closed, grey unknown. A green dot in a browser tab would be
read — correctly, by anyone who has used the site for five minutes — as *"the
massif is fine right now"*. It would be a status claim, rendered from a static
file, that nothing updates and no source stands behind. On a site whose stated
failure mode is "a confident wrong answer", that is the worst possible artefact
to ship.

So:

- **No green.** Not as an accent, not as a dot, not as a highlight.
- **No red, no amber.** Same reasoning inverted: a permanently red tab is
  alarmism, and it is equally untrue.
- **No traffic-light or dot motif at all**, even in a neutral colour — the
  circular pip is this site's status glyph, and using it as identity teaches
  people to read the tab as a state.

The favicon is an **identity mark**. The status lives on the page, where it has
a date and a source next to it.

## 3. What the site already looks like

**Wordmark.** `MASSIF`, set in Archivo 600 at 16px with `letter-spacing:
0.22em`, white on a `#1a1f24` bar 52px tall. That bar is the only dark surface
on the site and exists because the masthead sits over a photograph — white on
`#1a1f24` measures 15.6:1.

**Everything else is light.** Page background `#fbfcfd`. The front page is a
full-bleed photograph of rock spires and a glacier, then a "ruled ledger" — a
label rail beside one unbroken column of hairline-ruled rows, no boxes except
pills and buttons.

**Type.** Archivo (200–700) for UI, IBM Plex Mono (400–600) for timestamps,
ages, altitudes and source lines. Both from Google Fonts.

**Register.** Quiet, accurate, unglamorous — a tide table or a NOTAM, not a
travel brand. Confidence is expressed through precision and attribution, never
polish. If a choice makes the site look more authoritative than its data
warrants, it is the wrong choice.

## 4. Palette

Every value below was measured against the page background `#fbfcfd`; the
ratios are why they are these values and not the ones originally proposed.

**Usable for the icon:**

| token | hex | note |
|---|---|---|
| ink | `#22282e` | 14.49:1 — headings, feature names. The site's near-black. |
| masthead | `#1a1f24` | the dark bar the wordmark sits on |
| page | `#fbfcfd` | the off-white background |
| body | `#4d545c` | 7.47:1 |
| secondary | `#5f6873` | 5.50:1 |
| tertiary | `#6d7580` | 4.54:1 — the floor for text |
| decor | `#9aa2ab` | 2.51:1 — **never text**; rules and hairlines only |

**Off limits for the icon** (status colours, see §2):
`#3d8f63` open · `#b3831d` restricted · `#b23c31` closed · `#6e757e` unknown

An icon in ink-on-off-white, or reversed white-on-ink, is on-brand by default.

## 5. What it has to survive

- **16×16.** This is the real test. Browser tabs render at 16px, sometimes
  17px on odd scaling. Anything with more than about three strokes turns to
  mud. Design at 16 first and scale up, not the reverse.
- **Both tab chromes.** Browsers put favicons on light *and* dark toolbars, and
  there is no media query for it in an `.ico`. A mark that relies on a white
  background disappears in dark mode. Either give it its own solid ground
  (a filled tile, which also matches the masthead bar) or make the shape work
  as a silhouette in both.
- **Monochrome legibility.** Pinned tabs and some OS surfaces render a single
  flat colour. If the idea only works with two tones, it does not work.
- **Not a photograph.** The hero image is a real photo of the massif and is
  lovely at 1600px; at 16px it is a grey smear.
- **Not a flag.** The massif spans FR, IT and CH and the site is careful about
  this — country codes appear per row, and the map deliberately does not colour
  by nation. A tricolour of any one country would be wrong.

## 6. Ideas worth exploring

Offered as starting points, not a spec. The strongest mark is probably the one
that says "mountain reference" without saying "adventure brand".

1. **The letter M as a massif.** The wordmark is `MASSIF` and the M can be read
   as two peaks. A geometric Archivo-weight M, white on `#1a1f24`, is the most
   obvious and most defensible route — it inherits the masthead directly.
2. **A summit profile.** Mont Blanc's actual skyline reduced to two or three
   strokes. Specific rather than generic: this is a site about one massif, not
   about mountains.
3. **A ruled mark.** The ledger's hairline rules are the site's real signature
   — the thing that makes it look like a record rather than an app. Something
   built from two or three horizontal rules of different weight, with a peak
   breaking the top one, would be unusually honest to the product.

Avoid: pins and map markers (map-app cliché, and this is not a map app),
compasses, carabiners, crampons, anything with motion or a gradient.

## 7. Deliverables and where they go

The frontend is **Next.js 15, App Router**, which wires icons automatically by
filename — no `<link>` tags needed. Files go in `frontend/app/`:

| file | size | purpose |
|---|---|---|
| `app/icon.svg` | vector | the favicon; Next serves and links it |
| `app/apple-icon.png` | 180×180 | iOS home screen |

An `app/icon.svg` alone covers modern browsers. If a raster fallback is wanted
for older ones, add `app/icon.png` at 32×32 — Next will emit both.

**SVG notes:** no external references, no embedded fonts (convert any lettering
to paths — a font-dependent SVG icon renders as a fallback face or nothing),
and a `viewBox` on a square canvas. Keep it under a few KB.

Please also supply a **16×16 PNG preview** of the final mark so it can be
judged at the size it will actually be seen at, rather than at 512px where
everything looks good.
