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
