# massif — the current UI, in full

Companion to `design-brief.md`. This is what exists today: four files, ~670
lines. Read it to see what is being replaced, and to know what shape a
replacement has to slot into. The comments explain why things are the way they
are — several encode bugs that were shipped and fixed, so they are worth
reading before overriding them.


---

## `frontend/app/layout.tsx`

```tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Mont Blanc massif — what's open, what's shut",
    template: "%s — massif",
  },
  description:
    "Live closure and status directory for the Mont Blanc massif: lifts, " +
    "mountain railways, huts and routes, with the source for every claim.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="wrap">
          <header className="site">
            <h1>
              <a href="/" style={{ textDecoration: "none" }}>
                Mont Blanc massif — what&rsquo;s open, what&rsquo;s shut
              </a>
            </h1>
            <p>Published notices, with a source for every line. Not a safety service.</p>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
```

---

## `frontend/app/globals.css`

```css
:root {
  --bg: #0e1116;
  --panel: #161b22;
  --line: #263041;
  --text: #e6edf3;
  --muted: #8b949e;

  /* Status. Routine closures must never look like incidents, so
     outside-hours borrows the muted grey rather than the red. */
  --open: #3fb950;
  --closed: #f85149;
  --restricted: #d29922;
  --unknown: #6e7681;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--text);
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}

a { color: inherit; }

.wrap { max-width: 1100px; margin: 0 auto; padding: 0 20px 64px; }

header.site {
  border-bottom: 1px solid var(--line);
  padding: 18px 0;
  margin-bottom: 22px;
}
header.site h1 { font-size: 19px; margin: 0; letter-spacing: -0.01em; }
header.site p { margin: 4px 0 0; color: var(--muted); font-size: 13px; }

.disclaimer {
  border: 1px solid var(--line);
  border-left: 3px solid var(--restricted);
  background: var(--panel);
  padding: 10px 14px;
  border-radius: 6px;
  color: var(--muted);
  font-size: 13px;
  margin: 18px 0;
}

#map { height: 460px; border-radius: 8px; border: 1px solid var(--line); }

.grid { display: grid; gap: 10px; margin-top: 22px; }
@media (min-width: 720px) { .grid { grid-template-columns: repeat(2, 1fr); } }

.card {
  display: block;
  background: var(--panel);
  border: 1px solid var(--line);
  border-left: 3px solid var(--unknown);
  border-radius: 6px;
  padding: 12px 14px;
  text-decoration: none;
}
.card.open { border-left-color: var(--open); }
.card.closed { border-left-color: var(--closed); }
.card.restricted { border-left-color: var(--restricted); }
.card.routine { border-left-color: var(--unknown); }

.card h3 { margin: 0 0 3px; font-size: 15px; }
.card p { margin: 0; color: var(--muted); font-size: 13px; }

.pill {
  display: inline-block;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 2px 7px;
  border-radius: 999px;
  border: 1px solid var(--line);
  color: var(--muted);
}
.pill.closed { color: var(--closed); border-color: var(--closed); }
.pill.open { color: var(--open); border-color: var(--open); }
.pill.restricted { color: var(--restricted); border-color: var(--restricted); }

.meta { color: var(--muted); font-size: 12px; margin-top: 6px; }
.stale { color: var(--restricted); }

table.history { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
table.history th, table.history td {
  text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line);
  vertical-align: top;
}
table.history th { color: var(--muted); font-weight: 500; }

.lifts { list-style: none; padding: 0; margin: 12px 0 0; }
.lifts li {
  display: flex; justify-content: space-between; gap: 12px;
  padding: 7px 0; border-bottom: 1px solid var(--line); font-size: 13px;
}
.lifts .times { color: var(--muted); font-variant-numeric: tabular-nums; }

/* Feature kind, shown so a route closure is not mistaken for a lift one. */
.pill.type {
  color: var(--muted);
  border-color: var(--line);
  text-transform: lowercase;
  letter-spacing: 0.02em;
}

/* A status word is a lossy summary. When other live notices exist they are
   flagged on the card itself, not left for whoever scrolls to the history. */
.notices {
  margin: 6px 0 0 !important;
  color: var(--restricted) !important;
  font-size: 13px;
}

.notice {
  border: 1px solid var(--line);
  border-left: 3px solid var(--restricted);
  background: var(--panel);
  border-radius: 6px;
  padding: 10px 13px;
  margin-bottom: 8px;
}
.notice h4 { margin: 0 0 4px; font-size: 14px; font-weight: 600; }
.notice p { margin: 0; color: var(--muted); font-size: 13px; }

/* --- hierarchy ---------------------------------------------------------
   The page answers one question: what is shut that should not be. A real
   closure and a lift asleep for the night were the same size card, so
   answering it meant reading twenty of them. Weight now tracks how much a
   thing deserves attention. */

.headline {
  border: 1px solid var(--line);
  border-left: 4px solid var(--closed);
  background: linear-gradient(180deg, rgba(248,81,73,0.07), transparent 60%),
              var(--panel);
  border-radius: 8px;
  padding: 18px 20px;
  margin-bottom: 10px;
  display: block;
  text-decoration: none;
}
.headline.restricted { border-left-color: var(--restricted); }
.headline h3 { margin: 0 0 6px; font-size: 20px; letter-spacing: -0.01em; }
.headline p { margin: 0; font-size: 15px; color: var(--text); opacity: 0.85; }

/* Routine status: a table, not a wall of cards. Present, scannable, quiet. */
.quiet {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-top: 10px;
}
.quiet td {
  padding: 7px 10px;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
}
.quiet td:first-child { color: var(--text); width: 34%; }
.quiet td.state { width: 1%; white-space: nowrap; }
.quiet tr:hover td { background: rgba(255, 255, 255, 0.02); }
.quiet a { text-decoration: none; }

.dot {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  margin-right: 7px;
  vertical-align: 1px;
}
.dot.open { background: var(--open); }
.dot.closed { background: var(--closed); }
.dot.restricted { background: var(--restricted); }
.dot.unknown { background: var(--unknown); }

.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin: 34px 0 4px;
}
.section-head h2 { font-size: 15px; margin: 0; }
.section-head span { color: var(--muted); font-size: 12px; }

/* Map key. Six line colours and forty markers had nothing explaining them. */
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--muted);
}
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i {
  display: inline-block;
  width: 18px; height: 0;
  border-top: 2px solid currentColor;
}
.legend i.dashed { border-top-style: dashed; }

.feature-map {
  height: 280px;
  border-radius: 8px;
  border: 1px solid var(--line);
  margin-top: 14px;
}
```

---

## `frontend/app/page.tsx`

```tsx
import MassifMap from "@/components/MassifMap";
import { listFeatures, getHealth, sinceLabel, type Feature } from "@/lib/api";

export const revalidate = 60;

const TYPE_LABEL: Record<string, string> = {
  route: "route",
  couloir: "couloir",
  hut: "hut",
  lift: "lift",
  lift_station: "station",
  glacier: "glacier",
  access_road: "access",
  trail: "trail",
  peak: "peak",
  zone: "zone",
};

/** Worth interrupting a TRIP PLANNER for. Not "shut because it is 3am" —
 *  colouring by the hour turned the page grey every night and hid the one
 *  genuine seasonal closure among eleven sleeping lifts. */
function isNotable(feature: Feature): boolean {
  return (
    feature.season.value === "closed" || feature.season.value === "restricted"
  );
}

function rank(feature: Feature): number {
  return (
    { closed: 0, restricted: 1, open: 2, unknown: 4 }[feature.season.value] ?? 5
  );
}

/** "closed for the day · runs 07:20–16:10" is a detail, not a headline.
 *
 *  Returns null when there is nothing to add: no live status, the season line
 *  already says it, or the thing is shut for the season anyway. A feature
 *  with only a calendar entry was printing the same sentence twice. */
function rightNow(feature: Feature): string | null {
  const summary = feature.status.summary;
  if (!summary) return null;
  if (feature.season.value === "closed") return null;
  if (summary === feature.season.reason) return null;
  return summary;
}

/** The answer to the page's question, given room to be read. */
function Headline({ feature }: { feature: Feature }) {
  return (
    <a
      className={`headline ${feature.status.value}`}
      href={`/${feature.type}/${feature.slug}`}
    >
      <h3>
        {feature.name}{" "}
        <span className={`pill ${feature.season.value}`}>
          {feature.season.kind === "out_of_season"
            ? "not this season"
            : feature.season.value}
        </span>
      </h3>
      <p>{feature.season.reason ?? feature.status.summary}</p>
      {rightNow(feature) && <p className="meta">Today: {rightNow(feature)}</p>}
      {feature.status.other_notices > 0 && (
        <p className="notices">
          ⚠ {feature.status.other_notices} other current notice
          {feature.status.other_notices === 1 ? "" : "s"} on this feature
        </p>
      )}
      <div className={`meta ${feature.status.stale ? "stale" : ""}`}>
        {TYPE_LABEL[feature.type] ?? feature.type} ·{" "}
        {feature.status.stale ? "⚠ not confirmed recently · " : ""}
        last confirmed {sinceLabel(feature.status.observed_at)}
      </div>
    </a>
  );
}

/** Everything routine: present and scannable, never competing for attention. */
function QuietTable({ features }: { features: Feature[] }) {
  return (
    <table className="quiet">
      <tbody>
        {features.map((feature) => (
          <tr key={feature.slug}>
            <td>
              <a href={`/${feature.type}/${feature.slug}`}>
                <span className={`dot ${feature.season.value}`} />
                {feature.name}
              </a>
            </td>
            <td>
              {feature.season.reason ?? feature.status.summary}
              {rightNow(feature) && (
                <div className="meta">Today: {rightNow(feature)}</div>
              )}
            </td>
            <td className="state">
              {feature.status.other_notices > 0 && (
                <span className="notices">
                  ⚠ {feature.status.other_notices}
                </span>
              )}{" "}
              {feature.status.stale ? "⚠ " : ""}
              {sinceLabel(feature.status.observed_at)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default async function Home() {
  let features: Feature[] = [];
  let lastIngest: string | null = null;
  let error: string | null = null;

  try {
    const [list, health] = await Promise.all([listFeatures(), getHealth()]);
    features = list.features;
    lastIngest = health.last_successful_ingest;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error) {
    return (
      <p className="disclaimer">
        Backend unreachable ({error}). Start it with{" "}
        <code>uvicorn massif.main:app --reload</code>.
      </p>
    );
  }

  const withStatus = features.filter((f) => f.status.summary && !f.parent_slug);

  const notable = withStatus
    .filter(isNotable)
    .sort(
      (a, b) =>
        b.status.severity - a.status.severity || a.name.localeCompare(b.name),
    );
  const notableSlugs = new Set(notable.map((f) => f.slug));

  const routes = withStatus
    .filter((f) => f.type !== "lift" && !notableSlugs.has(f.slug))
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));

  const lifts = withStatus
    .filter((f) => f.type === "lift" && !notableSlugs.has(f.slug))
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));

  return (
    <>
      <MassifMap features={features} />

      <div className="legend">
        <span style={{ color: "var(--closed)" }}>
          <i /> closed, or not running this season
        </span>
        <span style={{ color: "var(--restricted)" }}>
          <i /> restricted
        </span>
        <span style={{ color: "var(--open)" }}>
          <i /> operating this season
        </span>
        <span style={{ color: "var(--unknown)" }}>
          <i /> no seasonal information
        </span>
        <span style={{ color: "#4a5563" }}>
          <i className="dashed" /> route drawn for context — no notices
        </span>
      </div>

      {notable.length > 0 ? (
        <>
          <div className="section-head">
            <h2>
              {notable.length === 1
                ? "1 closure or restriction"
                : `${notable.length} closures and restrictions`}
            </h2>
            <span>the reason this page exists</span>
          </div>
          {notable.map((feature) => (
            <Headline key={feature.slug} feature={feature} />
          ))}
        </>
      ) : (
        <div className="section-head">
          <h2>Nothing unexpectedly shut</h2>
          <span>everything below is routine</span>
        </div>
      )}

      <p className="disclaimer">
        A directory of what operators and authorities have published. Statuses
        may be out of date, and being confidently stale is the failure mode this
        page tries hardest to avoid — every row shows when it was last
        confirmed. Verify locally before committing to anything.
      </p>

      {routes.length > 0 && (
        <>
          <div className="section-head">
            <h2>Routes, huts and access</h2>
            <span>{routes.length} tracked</span>
          </div>
          <QuietTable features={routes} />
        </>
      )}

      <div className="section-head">
        <h2>Lifts and mountain railways</h2>
        <span>{lifts.length} sectors</span>
      </div>
      <QuietTable features={lifts} />

      <p className="meta" style={{ marginTop: 24 }}>
        Last successful ingest: {sinceLabel(lastIngest)} · {features.length}{" "}
        features tracked
      </p>
    </>
  );
}
```

---

## `frontend/app/[type]/[slug]/page.tsx`

```tsx
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import FeatureMap from "@/components/FeatureMap";
import { getFeature, resortTime, sinceLabel } from "@/lib/api";

export const revalidate = 60;

type Params = Promise<{ type: string; slug: string }>;

// The SEO surface. Someone googling "aiguille du midi closed" should land
// here, on a server-rendered page that answers them and cites its source.
export async function generateMetadata({
  params,
}: {
  params: Params;
}): Promise<Metadata> {
  const { slug } = await params;
  try {
    const feature = await getFeature(slug);
    return {
      title: `${feature.name} — ${feature.status.summary ?? feature.status.value}`,
      description:
        `Current status for ${feature.name} in the Mont Blanc massif. ` +
        `${feature.status.summary ?? ""} Last confirmed ` +
        `${resortTime(feature.status.observed_at)} (resort time).`,
    };
  } catch {
    return { title: "Not found" };
  }
}

export default async function FeaturePage({ params }: { params: Params }) {
  const { slug } = await params;

  let feature;
  try {
    feature = await getFeature(slug);
  } catch {
    notFound();
  }

  const routine = feature.status.closure_kind === "outside_hours";

  return (
    <>
      {feature.parent && (
        <p className="meta">
          <a href={`/lift/${feature.parent.slug}`}>← {feature.parent.name}</a>
        </p>
      )}

      <h2 style={{ marginBottom: 4 }}>{feature.name}</h2>
      <p className="meta">
        {feature.type}
        {feature.status.altitude_m ? ` · ${feature.status.altitude_m} m` : ""}
        {feature.country ? ` · ${feature.country}` : ""}
      </p>

      <FeatureMap feature={feature} />

      <div
        className={routine ? "card routine" : `card ${feature.status.value}`}
        style={{ marginTop: 14 }}
      >
        <h3>
          {feature.status.summary ?? feature.status.value}{" "}
          {!routine && feature.status.value !== "unknown" && (
            <span className={`pill ${feature.status.value}`}>
              {feature.status.value}
            </span>
          )}
        </h3>
        <div className={`meta ${feature.status.stale ? "stale" : ""}`}>
          Last confirmed {resortTime(feature.status.observed_at)} resort time (
          {sinceLabel(feature.status.observed_at)})
          {feature.status.stale && " — nobody has reconfirmed this recently"}
        </div>
        {routine && (
          <div className="meta">
            Routine: shut because of the hour or the season, not an incident.
          </div>
        )}
      </div>

      {feature.other_notices.length > 0 && (
        <>
          <h3 style={{ fontSize: 15, marginTop: 26 }}>
            Also currently in force
          </h3>
          <p className="meta">
            Live notices about this feature that are not the headline status. A
            route can be legally open and still carry a warning — only one of
            them gets to be the colour of the card, so the rest are here rather
            than buried in the history.
          </p>
          {feature.other_notices.map((notice, index) => (
            <div className="notice" key={index}>
              <h4>
                {notice.summary ?? notice.type}{" "}
                <span className={`pill ${notice.status}`}>{notice.status}</span>
              </h4>
              {notice.original_text && (
                <p>
                  “{notice.original_text.slice(0, 240)}
                  {notice.original_text.length > 240 ? "…" : ""}”
                </p>
              )}
              <p className="meta">
                {resortTime(notice.observed_at)} ·{" "}
                <a href={notice.source.url} rel="nofollow noopener">
                  {notice.source.name}
                </a>
              </p>
            </div>
          ))}
        </>
      )}

      {feature.status.lifts && feature.status.lifts.length > 0 && (
        <>
          <h3 style={{ fontSize: 15, marginTop: 26 }}>Lifts in this sector</h3>
          <ul className="lifts">
            {feature.status.lifts.map((lift) => (
              <li key={lift.name}>
                <span>
                  {lift.name}
                  {lift.message && (
                    <span className="meta"> — {lift.message}</span>
                  )}
                </span>
                <span className="times">{lift.times.join("  ·  ")}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {feature.children.length > 0 && (
        <>
          <h3 style={{ fontSize: 15, marginTop: 26 }}>Individual lifts</h3>
          <div className="grid">
            {feature.children.map((child) => (
              <a
                key={child.slug}
                className={`card ${child.status}`}
                href={`/lift/${child.slug}`}
              >
                <h3>{child.name}</h3>
                <p>{child.summary}</p>
              </a>
            ))}
          </div>
        </>
      )}

      <h3 style={{ fontSize: 15, marginTop: 30 }}>
        Everything published about this
      </h3>
      <p className="meta">
        Never our own claim — each row links to whoever said it.
      </p>
      <table className="history">
        <thead>
          <tr>
            <th>When</th>
            <th>Status</th>
            <th>What was said</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {feature.history.map((entry, index) => (
            <tr key={index}>
              <td>{resortTime(entry.observed_at)}</td>
              <td>{entry.status}</td>
              <td>
                {entry.summary}
                {entry.original_text && (
                  <div className="meta">
                    “{entry.original_text.slice(0, 180)}”
                    {entry.original_language && ` (${entry.original_language})`}
                  </div>
                )}
              </td>
              <td>
                <a href={entry.source.url} rel="nofollow noopener">
                  {entry.source.name}
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
```

---

## `frontend/components/MassifMap.tsx`

```tsx
"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature } from "@/lib/api";

// IGN Géoplateforme: open, key-less, and the best alpine cartography there is.
const IGN_PLAN =
  "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
  "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM" +
  "&TILEMATRIX={z}&TILECOL={x}&TILEROW={y}&FORMAT=image/png";

const COLOURS: Record<string, string> = {
  open: "#3fb950",
  closed: "#f85149",
  restricted: "#d29922",
  unknown: "#6e7681",
};

// "Nobody has said anything about this" and "this is shut because it is
// night" were both being painted the same grey, which made the whole map look
// dead and put a route with no information at the same visual weight as a
// live status. Anything without a statement is CONTEXT: thin, dashed, faded.
// Only things somebody has actually reported on get solid colour.
function hasStatus(feature: Feature): boolean {
  return (
    Boolean(feature.status.summary) ||
    (feature.season?.value ?? "unknown") !== "unknown"
  );
}

// Colour by SEASON, not by the hour. Colouring by operational status turned
// the whole map grey after the last lift of the day, which is useless to
// anyone planning a trip — and made a genuine seasonal closure look identical
// to nightfall.
function colourFor(feature: Feature): string {
  if (feature.season?.value && feature.season.value !== "unknown") {
    return COLOURS[feature.season.value] ?? COLOURS.unknown;
  }
  if (!hasStatus(feature)) return "#4a5563";
  return COLOURS.unknown;
}

function isLine(feature: Feature): boolean {
  const kind = feature.geometry?.type;
  return kind === "LineString" || kind === "MultiLineString";
}

export default function MassifMap({ features }: { features: Feature[] }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!container.current || map.current) return;

    const instance = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {
          ign: {
            type: "raster",
            tiles: [IGN_PLAN],
            tileSize: 256,
            attribution: "© IGN Géoplateforme · routes © camptocamp.org",
          },
        },
        layers: [{ id: "ign", type: "raster", source: "ign" }],
      },
      center: [6.87, 45.9],
      zoom: 10.2,
    });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl(), "top-right");

    // ---- points: huts, lift sectors, glaciers
    for (const feature of features) {
      if (feature.geometry?.type !== "Point") continue;
      const [lon, lat] = feature.geometry.coordinates as [number, number];

      const known = hasStatus(feature);
      // Notable now means notable to a PLANNER: shut this season, or under a
      // restriction. Not "shut because it is 3am".
      const notable =
        feature.season?.value === "closed" ||
        feature.season?.value === "restricted";

      const marker = document.createElement("div");
      Object.assign(marker.style, {
        width: notable ? "16px" : known ? "12px" : "8px",
        height: notable ? "16px" : known ? "12px" : "8px",
        borderRadius: "50%",
        background: known ? colourFor(feature) : "transparent",
        border: known
          ? "2px solid #0e1116"
          : "1.5px solid rgba(120,132,145,0.85)",
        boxShadow: notable ? `0 0 0 3px ${colourFor(feature)}33` : "none",
        cursor: "pointer",
      });

      new maplibregl.Marker({ element: marker })
        .setLngLat([lon, lat])
        .setPopup(
          new maplibregl.Popup({ offset: 14 }).setHTML(
            `<strong>${feature.name}</strong><br/>` +
              `<span style="color:#57606a">${
                feature.status.summary ?? feature.status.value
              }</span><br/>` +
              `<a href="/${feature.type}/${feature.slug}">details</a>`,
          ),
        )
        .addTo(instance);
    }

    // ---- lines: routes and couloirs, from camptocamp
    const lines = features.filter(isLine);

    instance.on("load", () => {
      if (lines.length === 0) return;

      instance.addSource("routes", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: lines.map((feature) => ({
            type: "Feature" as const,
            geometry: feature.geometry as GeoJSON.Geometry,
            properties: {
              slug: feature.slug,
              name: feature.name,
              type: feature.type,
              colour: colourFor(feature),
              known: hasStatus(feature) ? 1 : 0,
              summary:
                feature.status.summary ?? "no notices — shown for context",
            },
          })),
        },
      });

      // A dark casing under the line keeps it readable over IGN's busy
      // contours and glacier hatching, where a bare 2px stroke disappears.
      // Casing only under lines that assert something. On a light basemap a
      // dark casing under a thin faded line swamps it — you see the casing,
      // not the route, which is why the context routes vanished.
      instance.addLayer({
        id: "routes-casing",
        type: "line",
        source: "routes",
        filter: ["==", ["get", "known"], 1],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": 7, "line-opacity": 0.9 },
      });

      instance.addLayer({
        id: "routes-line",
        type: "line",
        source: "routes",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["get", "colour"],
          // A zoom interpolate must be the OUTERMOST expression: it cannot
          // sit inside a case (one interpolate per expression) and it cannot
          // sit inside a multiply either. Since this layer is already
          // filtered to reported routes, per-feature width was never needed —
          // the two layers differ by filter, and each gets a plain
          // interpolate of its own.
          "line-width": ["interpolate", ["linear"], ["zoom"], 9, 2.6, 14, 5],
          "line-opacity": 1,
        },
        filter: ["==", ["get", "known"], 1],
      });

      // Separate layer for context routes: line-dasharray is a paint property
      // that cannot vary per feature, so "dashed when unreported" needs its
      // own layer rather than an expression.
      instance.addLayer({
        id: "routes-context",
        type: "line",
        source: "routes",
        filter: ["!=", ["get", "known"], 1],
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: {
          "line-color": ["get", "colour"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.7, 14, 3.2],
          "line-opacity": 0.9,
          // a solid line reads as a claim about the route's condition, and we
          // are not making one
          "line-dasharray": [2, 1.6],
        },
      });

      // Invisible hit target. A 2px line demands pixel-perfect aim; this
      // gives routes the same click tolerance a 16px marker has.
      instance.addLayer({
        id: "routes-hit",
        type: "line",
        source: "routes",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#000000", "line-width": 18, "line-opacity": 0 },
      });

      instance.on("click", "routes-hit", (event) => {
        const hit = event.features?.[0];
        if (!hit) return;
        const props = hit.properties as Record<string, string>;
        new maplibregl.Popup({ offset: 8 })
          .setLngLat(event.lngLat)
          .setHTML(
            `<strong>${props.name}</strong><br/>` +
              `<span style="color:#57606a">${props.summary}</span><br/>` +
              `<a href="/${props.type}/${props.slug}">details</a>`,
          )
          .addTo(instance);
      });

      instance.on("mouseenter", "routes-hit", () => {
        instance.getCanvas().style.cursor = "pointer";
      });
      instance.on("mouseleave", "routes-hit", () => {
        instance.getCanvas().style.cursor = "";
      });
    });

    return () => {
      instance.remove();
      map.current = null;
    };
  }, [features]);

  return <div id="map" ref={container} />;
}
```

---

## `frontend/components/FeatureMap.tsx`

```tsx
"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureDetail } from "@/lib/api";

const IGN_PLAN =
  "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
  "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM" +
  "&TILEMATRIX={z}&TILECOL={x}&TILEROW={y}&FORMAT=image/png";

const COLOURS: Record<string, string> = {
  open: "#3fb950",
  closed: "#f85149",
  restricted: "#d29922",
  unknown: "#6e7681",
};

/** Every coordinate in a geometry, flattened — enough to fit the view. */
function positions(geometry: GeoJSON.Geometry | null): [number, number][] {
  if (!geometry) return [];
  if (geometry.type === "Point") return [geometry.coordinates as [number, number]];
  if (geometry.type === "LineString") return geometry.coordinates as [number, number][];
  if (geometry.type === "MultiLineString") {
    return (geometry.coordinates as [number, number][][]).flat();
  }
  if (geometry.type === "Polygon") {
    return (geometry.coordinates as [number, number][][]).flat();
  }
  return [];
}

export default function FeatureMap({ feature }: { feature: FeatureDetail }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  const geometry = (feature.geometry ?? null) as GeoJSON.Geometry | null;
  const points = positions(geometry);

  useEffect(() => {
    if (!container.current || map.current || points.length === 0) return;

    const colour =
      feature.season?.value && feature.season.value !== "unknown"
        ? COLOURS[feature.season.value] ?? COLOURS.unknown
        : COLOURS.unknown;
    const isLine = geometry?.type !== "Point";

    const lons = points.map((p) => p[0]);
    const lats = points.map((p) => p[1]);
    const bounds = new maplibregl.LngLatBounds(
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    );

    const instance = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {
          ign: {
            type: "raster",
            tiles: [IGN_PLAN],
            tileSize: 256,
            attribution: "© IGN Géoplateforme · routes © camptocamp.org",
          },
        },
        layers: [{ id: "ign", type: "raster", source: "ign" }],
      },
      // A single point has no extent to fit, so it gets a sensible zoom
      // instead; a line gets fitted with padding once the style is up.
      center: bounds.getCenter(),
      zoom: isLine ? 11 : 14,
    });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl(), "top-right");

    if (!isLine) {
      const marker = document.createElement("div");
      Object.assign(marker.style, {
        width: "16px",
        height: "16px",
        borderRadius: "50%",
        background: colour,
        border: "2px solid #0e1116",
        boxShadow: `0 0 0 4px ${colour}33`,
      });
      new maplibregl.Marker({ element: marker })
        .setLngLat(points[0])
        .addTo(instance);
    }

    instance.on("load", () => {
      if (isLine) {
        instance.addSource("feature", {
          type: "geojson",
          data: { type: "Feature", geometry, properties: {} },
        });
        instance.addLayer({
          id: "feature-casing",
          type: "line",
          source: "feature",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": "#ffffff", "line-width": 8, "line-opacity": 0.9 },
        });
        instance.addLayer({
          id: "feature-line",
          type: "line",
          source: "feature",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": colour, "line-width": 4 },
        });
        instance.fitBounds(bounds, { padding: 48, duration: 0, maxZoom: 14 });
      }
    });

    return () => {
      instance.remove();
      map.current = null;
    };
  }, [feature, geometry, points]);

  if (points.length === 0) {
    return (
      <p className="meta" style={{ marginTop: 12 }}>
        No geometry for this feature yet — we would rather show nothing than
        put it in the wrong place.
      </p>
    );
  }

  return <div className="feature-map" ref={container} />;
}
```
