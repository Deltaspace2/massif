import Flag from "@/components/Flag";
import MapKey from "@/components/MapKey";
import MassifMap from "@/components/MassifMap";
import {
  listFeatures,
  getFeed,
  getHealth,
  resortTime,
  sinceLabel,
  type Feature,
  type FactBlock,
  type FeedItem,
} from "@/lib/api";

export const revalidate = 60;

function ageHours(iso: string | null): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 3_600_000;
}

/** Rule 1: a stale "open" must never read as clearance.
 *
 *  Two questions, both the backend's to answer, and they are NOT the same
 *  thing — which is why one badge for both was wrong. Steven asked what
 *  UNVERIFIED meant, and the honest answer was "one of two opposite problems":
 *
 *    old        the CLAIM has aged past what its kind of notice holds for.
 *               Rifugio Pavillon carried a refuges.info closure last edited 446
 *               days ago. We had checked it minutes before — the information is
 *               old, our reading of it is not.
 *    unchecked  WE have not re-read the source within its own cadence. Grands
 *               Montets was 17 hours behind a feed published every 30 minutes.
 *               Nothing wrong with the claim; we simply had not looked.
 *
 *  Showing both as UNVERIFIED told the reader neither, and a badge that means
 *  two opposite things is a badge nobody can act on. Stale wins when both are
 *  true: old information you have just re-read is still old.
 *
 *  Both come from the API. The flat "48 hours" this used to compute in the UI
 *  would have flagged every valid decree in the massif forever, and the flat
 *  "24 hours" that replaced half of it was exactly mbnr-openings' fetch
 *  interval, so a healthy daily source drifted into the badge before every run.
 *  Numbers chosen here to stand in for facts the backend holds have been wrong
 *  twice; there are none left.
 *
 *  The 9C handoff asks for one UNVERIFIED pill on "ages > 48h". The pill is
 *  implemented; the 48 hours is not, and the single label is not. Both of those
 *  are the two bugs above, written down as a spec by someone who had not hit
 *  them. */
type Doubt = "old" | "unchecked";

function doubt(feature: Feature): Doubt | null {
  if (feature.status.stale) return "old";
  if (feature.status.unchecked) return "unchecked";
  return null;
}

const DOUBT_LABEL: Record<Doubt, string> = {
  old: "OLD",
  unchecked: "UNCHECKED",
};

/** Why it is flagged, in words, for the banner and for a title attribute. */
const DOUBT_WHY: Record<Doubt, string> = {
  old: "this has aged past the window its kind of notice holds for",
  unchecked: "we have not re-read the source within its own cadence",
};

/** Worth interrupting a trip planner for. Season, never the clock: a lift
 *  asleep for the evening is still running this season, and colouring by the
 *  hour turned the whole page grey every night. */
function isNotice(feature: Feature): boolean {
  return feature.season.value === "closed" || feature.season.value === "restricted";
}

function rank(feature: Feature): number {
  // Unstaffed ranks with open, immediately after it: it is a variant of open,
  // not a step towards closed, and sorting it between restricted and open
  // would put "nobody home" above "held for wind" on a page about closures.
  return (
    { closed: 0, restricted: 1, open: 2, unstaffed: 3, unknown: 4 }[
      feature.season.value
    ] ?? 5
  );
}

const GLYPH: Record<string, string> = {
  open: "●",
  // Hollow, in the open colour: open, and nobody home. Never a triangle —
  // that is the caution glyph and this is not a caution. The handoff's glyph
  // set is ● ▲ ■ ○ and predates this state existing.
  unstaffed: "◍",
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

function altitudeLabel(feature: Feature): string | null {
  if (feature.alt_min && feature.alt_max && feature.alt_min !== feature.alt_max) {
    return `${feature.alt_min}–${feature.alt_max} m`;
  }
  if (feature.alt_max ?? feature.alt_min) return `${feature.alt_max ?? feature.alt_min} m`;
  return feature.status.altitude_m ? `${feature.status.altitude_m} m` : null;
}

/** The right-hand end of a ledger row: how old, and whether that is a problem.
 *
 *  Two clocks, two lines — rule 10. `observed_at` is when the source published;
 *  `last_seen_at` is when we last fetched and found it still standing. The
 *  handoff shows a single age, which is the conflation that badged a decree
 *  valid till September as unverified. */
function Age({ feature }: { feature: Feature }) {
  const flag = doubt(feature);
  return (
    <span className={`lrow__age mono${flag ? " lrow__age--caution" : ""}`}>
      {flag && (
        <span className="pill-doubt" title={DOUBT_WHY[flag]}>
          {DOUBT_LABEL[flag]}
        </span>
      )}
      <span className="lrow__age-pub">{shortAge(feature.status.observed_at)}</span>
      <span className="lrow__age-chk">
        checked {shortAge(feature.status.last_seen_at)}
      </span>
    </span>
  );
}

/** One ruled line in the ledger: glyph, name, what was said, how old.
 *
 *  `emphasis` is the IN FORCE NOW treatment — a status word at the head of the
 *  line and a larger name. Everything else about the row is identical, so the
 *  two never drift apart.
 */
function LedgerRow({
  feature,
  emphasis = false,
}: {
  feature: Feature;
  emphasis?: boolean;
}) {
  const said = saidAbout(feature);
  const isUnknown = feature.season.value === "unknown";
  const value = feature.season.value;
  const altitude = altitudeLabel(feature);

  return (
    <div className={`lrow${emphasis ? " lrow--force" : ""}`}>
      {emphasis ? (
        <span className={`lrow__status ${value}`} style={{ color: `var(--${value})` }}>
          {GLYPH[value] ?? "○"} {value.toUpperCase()}
        </span>
      ) : (
        <span
          className={`lrow__glyph ${value}`}
          style={{ color: `var(--${value})` }}
          aria-hidden="true"
        >
          {GLYPH[value] ?? "○"}
        </span>
      )}
      <span className="lrow__name">
        <a href={`/${feature.type}/${feature.slug}`}>{feature.name}</a>
        <Flag code={feature.country} />
        {altitude && <span className="lrow__alt mono"> {altitude}</span>}
      </span>
      <span className={`lrow__what${isUnknown ? " unknown" : said.quoted ? " quoted" : ""}`}>
        {isUnknown ? "unknown — no information, not “fine”" : said.text}
        {/* The old quiet table carried this and the first rewrite dropped it.
            It matters most exactly where it went missing: the Goûter route
            headlined OPEN on the front page while an 11 August notice about
            lethal rockfall sat one click away with nothing to hint at it. */}
        {feature.status.other_notices > 0 && (
          <span className="lrow__more">
            {" · "}
            {feature.status.other_notices} other notice
            {feature.status.other_notices === 1 ? "" : "s"} in force
          </span>
        )}
      </span>
      <Age feature={feature} />
    </div>
  );
}

/** A band of the ledger: a label rail on the left, content on the right.
 *
 *  The rail is what makes this a ledger rather than a stack of tables — the
 *  section name and its caveat sit beside the rows, not above them, so the
 *  rows themselves stay a single unbroken column of ruled lines. */
function Band({
  label,
  note,
  tone,
  first = false,
  children,
}: {
  label: React.ReactNode;
  note?: React.ReactNode;
  tone?: "alert";
  first?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className={`band${first ? " band--first" : ""}`}>
      <div className="band__rail">
        <h2 className={`band__label${tone === "alert" ? " band__label--alert" : ""}`}>
          {label}
        </h2>
        {note && <p className="band__note">{note}</p>}
      </div>
      <div className="band__body">{children}</div>
    </section>
  );
}

export default async function Home() {
  let features: Feature[] = [];
  let lastIngest: string | null = null;
  let latest: FeedItem | null = null;
  let error: string | null = null;

  try {
    // One try, one catch: the page either has its data or it does not. A
    // separate fetch with its own failure path would let the page render a
    // confident verdict beside a silently missing "latest change".
    const [list, health, feed] = await Promise.all([
      listFeatures(),
      getHealth(),
      getFeed(1),
    ]);
    features = list.features;
    lastIngest = health.last_successful_ingest;
    latest = feed.items[0] ?? null;
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
  // Huts are excluded: they have their own complete section below, and listing
  // the two that happen to carry a notice here as well printed each of them
  // twice on one screen. A hut that is actually shut still appears above in
  // IN FORCE NOW, which is a different job from an index — that pairing is
  // intentional, two rows in two routine listings was not.
  const rest = routine
    .filter((f) => f.type !== "lift" && f.type !== "hut")
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));

  // Within a band, what still deserves a line of its own. The handoff shows
  // exceptions above a collapsed "9 lifts routine" row, and the thing that
  // makes a row an exception is that it is NOT plainly running, or that we
  // cannot vouch for how fresh it is. Both are the reader's business; a lift
  // running its normal season is not.
  const exceptional = (f: Feature) => f.season.value !== "open" || doubt(f) !== null;
  const split = (rows: Feature[]) => ({
    shown: rows.filter(exceptional),
    quiet: rows.filter((f) => !exceptional(f)),
  });
  const liftRows = split(lifts);
  const restRows = split(rest);

  // Every hut, not just the ones with a notice. Most have nothing published
  // about them, so a status listing shows a handful — while their capacity,
  // warden and phone are the only reason most people arrive at all.
  // Highest first: it is how the massif is described and how they are climbed.
  // Everything the directories say about one hut, merged across ALL of its
  // blocks. Reading `facts[0]` only was why most rows in this list were blank:
  // a hut with a camptocamp block first showed nothing, because camptocamp
  // writes `capacity_staffed` and `custodianship` where refuges.info writes
  // `capacity` and `guarded` — and the Cosmiques had refuges.info sitting in
  // block TWO saying "sleeps 145, staffed" while the row rendered empty.
  const hutValues = (f: Feature) => {
    const merged: Record<string, unknown> = {};
    for (const block of f.facts ?? []) {
      for (const [key, value] of Object.entries(block.values)) {
        if (value !== undefined && merged[key] === undefined) merged[key] = value;
      }
    }
    return merged as FactBlock["values"];
  };
  const hutAlt = (f: Feature): number | null =>
    f.alt_max ?? f.alt_min ?? hutValues(f).altitude_m ?? null;
  const huts = features
    .filter((f) => f.type === "hut")
    .sort((a, b) => (hutAlt(b) ?? -1) - (hutAlt(a) ?? -1) || a.name.localeCompare(b.name));
  // EVERY source that fed this list, not the first one found. Two directories
  // contribute here and crediting one of them is exactly the under-attribution
  // the facts block exists to prevent — a missing credit is invisible in a way
  // a missing table is not.
  const hutSources = Array.from(
    new Map(
      huts.flatMap((f) => f.facts ?? []).map((block) => [block.source.name, block]),
    ).values(),
  );

  // Every route and couloir, for the same reason as the huts: the status
  // listings only show what a source has published about, and Saint-Gervais
  // publishes about the Goûter and nothing else — so twelve of thirteen routes
  // were reachable only by typing the URL. Summit-first, because that is the
  // order anyone thinks about them in.
  const routes = features
    .filter((f) => f.type === "route" || f.type === "couloir")
    .sort(
      (a, b) =>
        (b.alt_max ?? 0) - (a.alt_max ?? 0) || a.name.localeCompare(b.name),
    );

  const asleep = routine.filter(
    (f) => f.status.closure_kind === "outside_hours" && f.season.value === "open",
  ).length;
  const doubted = tracked.filter((f) => doubt(f) !== null);

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

      <div className="layout">
        <div className="col">
          {/* The verdict, stated once. It used to be a white card lapping over
              the photo; 9C opens the ledger with it instead, and running both
              would have printed the same count twice within one screen. */}
          <header className="verdict">
            <span
              className={`verdict__count${quiet ? " verdict__count--ok" : ""}`}
              aria-hidden="true"
            >
              {notices.length}
            </span>
            <div className="verdict__said">
              <p className="verdict__line">
                {quiet
                  ? "Nothing unexpectedly shut."
                  : `notice${notices.length === 1 ? "" : "s"} in force.`}
              </p>
              <p className="verdict__counts">
                {tracked.length - notices.length} of {tracked.length} features
                routine · {asleep} lift{asleep === 1 ? "" : "s"} asleep on
                schedule · sweep {sinceLabel(lastIngest)}
                {lastIngest && ` · ${resortTime(lastIngest)}`}
              </p>
            </div>
            <div className="verdict__latest">
              {latest && (
                <p className="verdict__change">
                  Latest: {latest.feature.name} marked{" "}
                  <b style={{ color: `var(--${latest.status})` }}>{latest.status}</b>{" "}
                  · {sinceLabel(latest.observed_at)}
                </p>
              )}
              <a className="verdict__feed" href="/feed">
                All changes → feed
              </a>
            </div>
          </header>

          {doubted.length > 0 && (
            <div className="unverified">
              {/* Named separately, because they are separate problems: one is
                  about the information, the other about us. */}
              <span className="unverified__label">
                {doubted.some((f) => doubt(f) === "old") ? "OLD" : "UNCHECKED"}
              </span>
              <span className="unverified__text">
                {doubted
                  .slice(0, 3)
                  .map((f) =>
                    doubt(f) === "old"
                      ? `${f.name} was last published ${
                          f.status.observed_at ? sinceLabel(f.status.observed_at) : "never"
                        } and has aged out`
                      : `${f.name} has not been re-checked${
                          f.status.last_seen_at
                            ? ` since ${sinceLabel(f.status.last_seen_at)}`
                            : " at all"
                        }`,
                  )
                  .join(" · ")}
                {doubted.length > 3 && ` · and ${doubted.length - 3} more`}
                . A status is only as good as its date.
              </span>
            </div>
          )}

          {notices.length > 0 && (
            <Band
              first
              tone="alert"
              label="IN FORCE NOW"
              note="each with the source that published it, on its own page"
            >
              {notices.map((f) => (
                <LedgerRow key={f.slug} feature={f} emphasis />
              ))}
            </Band>
          )}

          {lifts.length > 0 && (
            <Band
              first={notices.length === 0}
              label="LIFTS & RAILWAYS"
              note={
                <>
                  {lifts.length + notices.filter((f) => f.type === "lift").length} tracked
                  <br />
                  coloured by season,
                  <br />
                  not by the clock
                </>
              }
            >
              {liftRows.shown.map((f) => (
                <LedgerRow key={f.slug} feature={f} />
              ))}
              <QuietRows rows={liftRows.quiet} noun="lift" />
            </Band>
          )}

          {rest.length > 0 && (
            <Band
              label="ROUTES & ACCESS"
              note="routes, glaciers and the roads that reach them"
            >
              {restRows.shown.map((f) => (
                <LedgerRow key={f.slug} feature={f} />
              ))}
              <QuietRows rows={restRows.quiet} noun="feature" />
            </Band>
          )}

          {/* A directory, not a status listing — which is why it is not folded
              into any "everything else" drawer. It is the half of the site that
              has something to say about a hut nobody has published a notice
              for, and the SEO surface: people search "refuge du requin", not
              "mont blanc closures". */}
          {huts.length > 0 && (
            <Band
              label="HUTS & REFUGES"
              note={
                <>
                  {huts.length} tracked · highest first
                  <br />
                  these describe the building,
                  <br />
                  not today
                </>
              }
            >
              <div className="cells">
                {huts.map((f) => {
                  const values = hutValues(f);
                  const known = (f.facts ?? []).length > 0;
                  const alt = hutAlt(f);
                  // The two directories count beds differently: refuges.info
                  // gives one `capacity`, camptocamp splits it by whether the
                  // warden is in. Prefer the plain figure, then the staffed
                  // one, then the winter room.
                  const sleeps =
                    values.capacity ??
                    values.capacity_staffed ??
                    values.capacity_unstaffed;
                  // `guarded` is a boolean and says it outright. camptocamp
                  // instead describes ACCESS relative to the warden, which is
                  // not the same question, and only some of its answers imply
                  // an answer to this one:
                  //
                  //   "Open only when the warden is there"    -> a warden
                  //   "Closed when the warden is away"        -> a warden
                  //   "No warden"                             -> none
                  //   "Some shelter accessible even when
                  //    unwardened"                            -> SAYS NOTHING
                  //
                  // The last one is their `always_accessible`, and treating it
                  // as "staffed" printed exactly that against the Bivacco
                  // della Brenva and the Bivacco Luigi Pascal — two unmanned
                  // bivacchi, one of which carries no bed count except
                  // `capacity_unstaffed`. It asserts the shelter is reachable,
                  // never that anyone runs it.
                  //
                  // These strings are our own gloss, written in
                  // import_camptocamp_facts.CUSTODIANSHIP. If they are
                  // reworded there, reword them here.
                  const WARDEN_IMPLIED = [
                    "Open only when the warden is there",
                    "Closed when the warden is away",
                  ];
                  const staffed =
                    values.guarded !== undefined
                      ? values.guarded
                      : values.custodianship === "No warden"
                        ? false
                        : values.custodianship !== undefined &&
                            WARDEN_IMPLIED.includes(values.custodianship)
                          ? true
                          : undefined;
                  // Absent is not zero and not false — the same three-state
                  // rule as the feature page. A hut we know nothing about says
                  // so, rather than rendering a row of confident blanks.
                  const detail = known
                    ? [
                        sleeps !== undefined ? `sleeps ${sleeps}` : null,
                        staffed !== undefined
                          ? staffed
                            ? "staffed"
                            : "unstaffed"
                          : null,
                        // Their `always_accessible`, which answers a different
                        // question from "is there a warden" and is the only
                        // thing we know about some bivacchi. Said in its own
                        // words rather than squeezed into the staffing slot,
                        // which is what made it read as "staffed".
                        values.custodianship ===
                        "Some shelter accessible even when unwardened"
                          ? "shelter always accessible"
                          : null,
                        values.water === true ? "water" : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")
                    : "no directory entry";
                  return (
                    <a className="cell" key={f.slug} href={`/hut/${f.slug}`}>
                      <span className="cell__head">
                        <span className="cell__name">{f.name}</span>
                        <span className="cell__alt mono">
                          {alt ? `${alt} · ` : ""}
                          {f.country ?? "—"}
                        </span>
                        {/* A hut with a live notice must not look like one
                            without. The same omission on the status table put
                            the Goûter route on this page as OPEN with an 11
                            August notice about lethal rockfall one click away
                            and nothing to hint at it — and the Goûter refuge
                            carries those notices too. A capacity is not a
                            reason to drop them a second time. */}
                        {isNotice(f) ? (
                          <span className={`chip chip--${f.season.value}`}>
                            {f.season.value}
                          </span>
                        ) : f.status.other_notices > 0 ? (
                          <span className="chip">
                            {f.status.other_notices} notice
                            {f.status.other_notices === 1 ? "" : "s"}
                          </span>
                        ) : null}
                      </span>
                      <span className={`cell__detail${known ? "" : " cell__detail--none"}`}>
                        {detail}
                      </span>
                    </a>
                  );
                })}
              </div>
              {hutSources.length > 0 && (
                <p className="band__credit">
                  Capacities, warden and water from{" "}
                  {hutSources.map((block, index) => (
                    <span key={block.source.name}>
                      {index > 0 && (index === hutSources.length - 1 ? " and " : ", ")}
                      <a href={block.source.url} rel="nofollow noopener">
                        {block.source.name}
                      </a>
                      , under{" "}
                      {block.licence_url ? (
                        <a href={block.licence_url} rel="license noopener">
                          {block.licence}
                        </a>
                      ) : (
                        block.licence
                      )}
                    </span>
                  ))}
                  . Each hut&rsquo;s page links the entry its community wrote.
                  These describe the building, not today — a hut being listed
                  here is not a report that it is open. Country is shown per row:
                  the massif spans FR · IT · CH.
                </p>
              )}
            </Band>
          )}

          {routes.length > 0 && (
            <Band
              label="ROUTES & COULOIRS"
              note={
                <>
                  {routes.length} tracked · highest first
                  <br />
                  only the Goûter has a source
                  <br />
                  that publishes about it
                </>
              }
            >
              <div className="cells">
                {routes.map((f) => {
                  const span =
                    f.alt_min && f.alt_max && f.alt_min !== f.alt_max
                      ? `${f.alt_min}–${f.alt_max}`
                      : f.alt_max
                        ? `${f.alt_max}`
                        : null;
                  return (
                    <a className="cell" key={f.slug} href={`/${f.type}/${f.slug}`}>
                      <span className="cell__head">
                        <span className="cell__name">{f.name}</span>
                        <span className="cell__alt mono">
                          {span ? `${span} · ` : ""}
                          {f.country ?? "—"}
                        </span>
                        {isNotice(f) ? (
                          <span className={`chip chip--${f.season.value}`}>
                            {f.season.value}
                          </span>
                        ) : f.status.other_notices > 0 ? (
                          <span className="chip">
                            {f.status.other_notices} notice
                            {f.status.other_notices === 1 ? "" : "s"}
                          </span>
                        ) : null}
                      </span>
                      {/* A route with nothing published says so, rather than
                          leaving a blank the reader has to interpret. */}
                      <span
                        className={`cell__detail${
                          f.season.reason || f.status.summary ? "" : " cell__detail--none"
                        }`}
                      >
                        {f.season.reason ??
                          f.status.summary ??
                          "nothing published about this route"}
                      </span>
                    </a>
                  );
                })}
              </div>
              <p className="band__credit">
                Saint-Gervais regulates the Goûter and publishes about it. The
                rest are tracked and findable, and will carry a status the day
                anybody publishes one. Absence here is our coverage, not a
                report that a route is fine.
              </p>
            </Band>
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
          <MapKey className="mappane__legend" />
        </aside>
      </div>
    </main>
  );
}

/** The routine remainder of one band, behind a pill.
 *
 *  `<details>`, not a button: moment three of the brief is a phone in a hut on
 *  bad signal, so this has to open with no JavaScript at all. The pill in the
 *  handoff is the summary's styling, not a control of its own. */
function QuietRows({ rows, noun }: { rows: Feature[]; noun: string }) {
  if (rows.length === 0) return null;
  return (
    <details className="quiet">
      <summary className="quiet__summary">
        <span className="lrow__glyph open" style={{ color: "var(--open)" }} aria-hidden="true">
          ●
        </span>
        <span className="quiet__text">
          {rows.length} {noun}
          {rows.length === 1 ? "" : "s"} routine, in season · all checked this
          sweep
        </span>
        <span className="quiet__pill">
          Show all {rows.length} <span aria-hidden="true">▾</span>
        </span>
      </summary>
      <div className="quiet__body">
        {rows.map((f) => (
          <LedgerRow key={f.slug} feature={f} />
        ))}
      </div>
    </details>
  );
}
