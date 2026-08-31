import MassifMap from "@/components/MassifMap";
import {
  listFeatures,
  getHealth,
  resortTime,
  sinceLabel,
  type Feature,
} from "@/lib/api";

export const revalidate = 60;

/** How long we tolerate not having re-checked a source before saying so.
 *  This is about OUR diligence, not about the claim: it is the answer to
 *  "when did we last look", and every source is swept far more often. */
const UNCHECKED_AFTER_HOURS = 24;

function ageHours(iso: string | null): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 3_600_000;
}

/** Rule 1: a stale "open" must never read as clearance.
 *
 *  This used to be a flat "older than 48 hours" test against observed_at, which
 *  was wrong twice over. observed_at is when the MAIRIE published, not when we
 *  looked — so a decree valid until 25 September, re-checked minutes earlier,
 *  was badged UNVERIFIED 6 D. And the backend already answers this properly,
 *  per statement type: an arrêté holds 90 days, a reopening 30, a live lift
 *  status one. The UI had quietly overridden all of it with one blunt number,
 *  which would have flagged every legally valid decree in the massif forever —
 *  and a badge that is always on stops being read.
 *
 *  Two questions now, both shown: has the claim aged out (the backend's
 *  `stale`), and have we failed to re-check it (last_seen_at). Never checked
 *  at all counts, because the absence of a check is not a passing check. */
function unverified(feature: Feature): boolean {
  if (feature.status.stale) return true;
  const sinceCheck = ageHours(feature.status.last_seen_at);
  return sinceCheck === null || sinceCheck > UNCHECKED_AFTER_HOURS;
}

/** Worth interrupting a trip planner for. Season, never the clock: a lift
 *  asleep for the evening is still running this season, and colouring by the
 *  hour turned the whole page grey every night. */
function isNotice(feature: Feature): boolean {
  return feature.season.value === "closed" || feature.season.value === "restricted";
}

function rank(feature: Feature): number {
  return { closed: 0, restricted: 1, open: 2, unknown: 3 }[feature.season.value] ?? 4;
}

const GLYPH: Record<string, string> = {
  open: "●",
  restricted: "▲",
  closed: "■",
  unknown: "○",
};

/** Short age for the right-hand column: "6 min", "3 h", "3 d", "never". */
function shortAge(iso: string | null): string {
  const hours = ageHours(iso);
  if (hours === null) return "never";
  const minutes = Math.round(hours * 60);
  if (minutes < 60) return `${Math.max(1, minutes)} min`;
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} d`;
}

/** "closed for the day · runs 07:20–16:10" is routine and belongs in the
 *  quiet column; a seasonal reason outranks it. Returns the operator's own
 *  words where we have them, so the italics can mark them as a quotation. */
function saidAbout(feature: Feature): { text: string; quoted: boolean } {
  const seasonal = feature.season.reason;
  const live = feature.status.summary;
  if (seasonal) return { text: seasonal, quoted: /[«"“]/.test(seasonal) };
  if (live) return { text: live, quoted: false };
  return { text: "no notices in force", quoted: false };
}

function Row({ feature }: { feature: Feature }) {
  const said = saidAbout(feature);
  const isUnknown = feature.season.value === "unknown";
  const stale = unverified(feature);
  const altitude =
    feature.alt_min && feature.alt_max && feature.alt_min !== feature.alt_max
      ? `${feature.alt_min}–${feature.alt_max} m`
      : feature.status.altitude_m
        ? `${feature.status.altitude_m} m`
        : null;

  return (
    <>
      <span
        className={`glyph ${feature.season.value}`}
        style={{ color: `var(--${feature.season.value})` }}
        aria-hidden="true"
      >
        {GLYPH[feature.season.value] ?? "○"}
      </span>
      <span className="name">
        <a href={`/${feature.type}/${feature.slug}`}>{feature.name}</a>
        {altitude && <span className="alt"> {altitude}</span>}
        {stale && <span className="pill-unverified">UNVERIFIED</span>}
      </span>
      <span className={`what${isUnknown ? " unknown" : said.quoted ? " quoted" : ""}`}>
        {isUnknown ? "unknown — no information, not “fine”" : said.text}
        {/* The old quiet table carried this and the rewrite dropped it. It
            matters most exactly where it went missing: the Goûter route
            headlined OPEN on the front page while an 11 August notice about
            lethal rockfall sat one click away with nothing to hint at it. */}
        {feature.status.other_notices > 0 && (
          <span className="what__more">
            {" · "}
            {feature.status.other_notices} other notice
            {feature.status.other_notices === 1 ? "" : "s"} in force
          </span>
        )}
      </span>
      {/* Two facts, not one. "published" is the mairie's date; "checked" is
          ours. Conflating them is what produced "last confirmed 6 days ago"
          for a decree we had re-read minutes earlier. */}
      <span className={`age mono${stale ? " caution" : ""}`}>
        <span className="age__published">{shortAge(feature.status.observed_at)}</span>
        <span className="age__checked">
          checked {shortAge(feature.status.last_seen_at)}
        </span>
      </span>
    </>
  );
}

/** The newsworthy ones, given room and their source. The design showed these
 *  on the mobile frame only because its desktop frame was a quiet day with
 *  none to show — they belong on both. */
function NoticeCard({ feature }: { feature: Feature }) {
  const stale = unverified(feature);
  const value = feature.season.value;
  const altitude = feature.status.altitude_m ? `${feature.status.altitude_m} m` : null;
  return (
    <article className={`notice-card${stale ? " unverified-card" : ""}`}>
      <div className="notice-card__head">
        <span className={`notice-card__status ${value}`}>
          {GLYPH[value]} {value.toUpperCase()}
        </span>
        <span className={`notice-card__age mono${stale ? " caution" : ""}`}>
          {stale && <span className="pill-unverified">UNVERIFIED</span>}{" "}
          {shortAge(feature.status.observed_at)}
        </span>
      </div>
      <h3>
        <a href={`/${feature.type}/${feature.slug}`}>{feature.name}</a>{" "}
        {altitude && <span className="alt">{altitude}</span>}
      </h3>
      {feature.season.reason && <p>{feature.season.reason}</p>}
      {feature.status.summary && feature.status.summary !== feature.season.reason && (
        <p>Today: {feature.status.summary}</p>
      )}
      {feature.status.other_notices > 0 && (
        <p className="notices">
          {feature.status.other_notices} other notice
          {feature.status.other_notices === 1 ? "" : "s"} also in force
        </p>
      )}
    </article>
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

  // The build statically generates this page, and `next build` succeeds with no
  // backend running — which means a failed fetch here is baked into the output
  // and served to real people until the next revalidation. So the failure state
  // has to be shippable copy, not a note to whoever is running it locally. It
  // must also refuse to imply anything about the mountain: "we cannot reach our
  // own data" is emphatically not "nothing is shut".
  if (error) {
    return (
      <main className="subpage">
        <h1>Status unavailable</h1>
        <p className="disclaimer">
          This page could not reach its own data, so it is showing you nothing
          rather than something stale. That is not a statement about conditions
          in the massif — go to the operators and the mairies directly:{" "}
          <a href="https://www.montblancnaturalresort.com/">
            Compagnie du Mont-Blanc
          </a>{" "}
          for lifts, and the commune&rsquo;s own site for arrêtés.
        </p>
        {process.env.NODE_ENV !== "production" && (
          <p className="meta mono">dev: {error}</p>
        )}
      </main>
    );
  }

  const tracked = features.filter((f) => !f.parent_slug);
  const withStatus = tracked.filter((f) => f.status.summary || f.season.reason);

  const notices = withStatus
    .filter(isNotice)
    .sort((a, b) => b.status.severity - a.status.severity || a.name.localeCompare(b.name));
  const noticed = new Set(notices.map((f) => f.slug));

  const routine = withStatus.filter((f) => !noticed.has(f.slug));
  const lifts = routine
    .filter((f) => f.type === "lift")
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  const rest = routine
    .filter((f) => f.type !== "lift")
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));

  // Every hut, not just the ones with a notice. Seventeen of nineteen have
  // nothing published about them, so a status listing shows two — while their
  // capacity, warden and phone are the only reason most people arrive at all.
  // Highest first: it is how the massif is described and how they are climbed.
  const hutAlt = (f: Feature): number | null =>
    f.alt_max ?? f.alt_min ?? (f.facts ?? [])[0]?.values.altitude_m ?? null;
  const huts = features
    .filter((f) => f.type === "hut")
    .sort((a, b) => (hutAlt(b) ?? -1) - (hutAlt(a) ?? -1) || a.name.localeCompare(b.name));
  const hutSource = huts.flatMap((f) => f.facts ?? [])[0];

  const asleep = routine.filter(
    (f) => f.status.closure_kind === "outside_hours" && f.season.value === "open",
  ).length;
  const unverifiedList = tracked.filter(unverified);

  const quiet = notices.length === 0;

  return (
    <main>
      <section className="hero">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          className="hero__img"
          src="/backgrounds/hero-spires-1600.jpg"
          srcSet={[
            "/backgrounds/hero-spires-768.avif 768w",
            "/backgrounds/hero-spires-1200.avif 1200w",
            "/backgrounds/hero-spires-1600.avif 1600w",
            "/backgrounds/hero-spires-2400.avif 2400w",
          ].join(", ")}
          sizes="100vw"
          alt=""
          fetchPriority="high"
          decoding="async"
          width={1600}
          height={1200}
        />
        <div className="hero__scrim" />
        <div className="hero__copy">
          <div className="hero__kicker">MONT BLANC MASSIF · FR / IT</div>
          <h1 className="hero__headline">
            What&rsquo;s open,
            <br />
            what&rsquo;s shut.
          </h1>
        </div>

      </section>

      {/* Sibling of the hero, not a child. As a child its only option is
          absolute positioning, and the mobile layout needs it in flow. It laps
          up over the photo with a negative margin instead, which behaves the
          same at every card height. */}
      <div className="verdict">
        <span className={`verdict__dot ${quiet ? "verdict__dot--ok" : "verdict__dot--alert"}`} />
        <span className="verdict__line">
          {quiet
            ? "Nothing unexpectedly shut."
            : `${notices.length} notice${notices.length === 1 ? "" : "s"} in force.`}
          </span>
        {/* One full rendering per fact. When something is in force the headline
            already says how many, so repeating it here is noise; when nothing
            is, saying "0 notices in force" out loud is exactly the point. */}
        <span className="verdict__counts">
          {quiet && "0 notices in force · "}
          {asleep} lift{asleep === 1 ? "" : "s"} asleep on schedule ·{" "}
          {features.length} features tracked
        </span>
        <span className="verdict__sweep mono">
          sweep {sinceLabel(lastIngest)}
          {lastIngest && ` · ${resortTime(lastIngest)}`}
        </span>
      </div>

      <div className="layout">
        <div className="col">
          {unverifiedList.length > 0 && (
            <div className="unverified">
              <span className="unverified__label">UNVERIFIED</span>
              <span className="unverified__text">
                {unverifiedList
                  .slice(0, 3)
                  .map(
                    (f) =>
                      `${f.name} last confirmed ${
                        f.status.observed_at ? sinceLabel(f.status.observed_at) : "never"
                      }`,
                  )
                  .join(" · ")}
                {unverifiedList.length > 3 &&
                  ` · and ${unverifiedList.length - 3} more`}
                . A status is only as good as its date.
              </span>
            </div>
          )}

          {notices.length > 0 && (
            <div>
              <div className="sec-head">
                <h2>In force now</h2>
                <span>each with the source that published it</span>
              </div>
              <div style={{ marginTop: 14 }}>
                {notices.map((f) => (
                  <NoticeCard key={f.slug} feature={f} />
                ))}
              </div>
            </div>
          )}

          {/* Closed by default. The mock has these open on desktop and collapsed
              on mobile, which server-rendered CSS cannot express without either
              JS or shipping the rows twice — and moment three of the brief is a
              phone on bad signal, so the phone wins the tie. The answer above is
              always visible; this is the routine remainder. */}
          <details className="remainder">
            <summary>
              <b>
                Everything else — {lifts.length + rest.length} features, routine
              </b>
              <span>SHOW ↓</span>
            </summary>
            <div className="remainder__body">

            {lifts.length > 0 && (
              <div style={{ marginTop: 18 }}>
                <div className="sec-head">
                  <h2>Lifts &amp; railways</h2>
                  <span>coloured by season, not by the clock</span>
                </div>
                <div className="tbl">
                  {lifts.map((f) => (
                    <Row key={f.slug} feature={f} />
                  ))}
                </div>
              </div>
            )}

            {rest.length > 0 && (
              <div style={{ marginTop: 26 }}>
                <div className="sec-head">
                  <h2>Routes, huts &amp; access</h2>
                </div>
                <div className="tbl">
                  {rest.map((f) => (
                    <Row key={f.slug} feature={f} />
                  ))}
                </div>
              </div>
            )}
            </div>
          </details>

          {/* Outside the "everything else" drawer on purpose. That drawer is
              about status; this is a directory, and it is the half of the site
              that has something to say about a hut nobody has published a
              notice for. Also the SEO surface — people search "refuge du
              requin", not "mont blanc closures". */}
          {huts.length > 0 && (
            <div style={{ marginTop: 30 }}>
              <div className="sec-head">
                <h2>Huts &amp; refuges</h2>
                <span>{huts.length} in the massif, highest first</span>
              </div>
              <div className="huts">
                {huts.map((f) => {
                  const values = (f.facts ?? [])[0]?.values;
                  const alt = hutAlt(f);
                  // Absent is not zero and not false — the same three-state
                  // rule as the feature page. A hut we know nothing about says
                  // so, rather than rendering a row of confident blanks.
                  const detail = values
                    ? [
                        values.capacity !== undefined
                          ? `sleeps ${values.capacity}`
                          : null,
                        values.guarded !== undefined
                          ? values.guarded
                            ? "staffed"
                            : "unstaffed"
                          : null,
                        values.water === true ? "water" : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")
                    : "no directory entry";
                  return (
                    <a className="huts__row" key={f.slug} href={`/hut/${f.slug}`}>
                      <span className="huts__name">{f.name}</span>
                      <span className="huts__alt mono">
                        {alt ? `${alt} m` : "—"}
                      </span>
                      <span
                        className={`huts__detail${values ? "" : " huts__detail--none"}`}
                      >
                        {detail}
                      </span>
                      {/* A hut with a live notice must not look like one
                          without. The same omission on the status table put
                          the Goûter route on this page as OPEN with an 11
                          August notice about lethal rockfall one click away
                          and nothing to hint at it — and the Goûter refuge
                          carries those notices too. A capacity is not a
                          reason to drop them a second time. */}
                      {isNotice(f) ? (
                        <span className={`pill ${f.season.value}`}>
                          {f.season.value}
                        </span>
                      ) : f.status.other_notices > 0 ? (
                        <span className="huts__notices">
                          {f.status.other_notices} notice
                          {f.status.other_notices === 1 ? "" : "s"}
                        </span>
                      ) : null}
                    </a>
                  );
                })}
              </div>
              {hutSource && (
                <p className="meta huts__credit">
                  Capacities, warden and water from{" "}
                  <a href={hutSource.source.url} rel="nofollow noopener">
                    {hutSource.source.name}
                  </a>
                  , under{" "}
                  {hutSource.licence_url ? (
                    <a href={hutSource.licence_url} rel="license noopener">
                      {hutSource.licence}
                    </a>
                  ) : (
                    hutSource.licence
                  )}
                  . Each hut&rsquo;s page links the entry its community wrote.
                  These describe the building, not today — a hut being listed
                  here is not a report that it is open.
                </p>
              )}
            </div>
          )}

          <p className="disclaimer">
            A directory of what operators and authorities have published, with a
            source for every line. Statuses may be out of date — every row shows
            when it was last confirmed. Not a safety service. Verify locally
            before committing to anything.{" "}
            {/* Deliberately here and not in the masthead: people report a wrong
                status at the moment they notice one, which is while they are
                reading the statuses — not from a nav item they saw on the way
                in. */}
            <a href="/feedback">Something wrong? Report it.</a>
          </p>
        </div>

        <aside className="mappane" id="map">
          <div className="mappane__head">
            <b>MAP · {features.length} FEATURES</b>
            <a href="/map" className="mappane__full">FULL SCREEN ↗</a>
          </div>
          <div className="mappane__map">
            <MassifMap features={features} />
          </div>
          <div className="mappane__legend">
            <span>
              <i style={{ color: "var(--open)" }}>●</i>open
            </span>
            <span>
              <i style={{ color: "var(--restricted-glass)" }}>▲</i>restricted
            </span>
            <span>
              <i style={{ color: "var(--closed)" }}>■</i>closed
            </span>
            <span>
              <i style={{ color: "var(--unknown)" }}>○</i>unknown
            </span>
          </div>
        </aside>
      </div>
    </main>
  );
}
