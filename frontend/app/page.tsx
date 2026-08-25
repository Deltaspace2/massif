import MassifMap from "@/components/MassifMap";
import { listFeatures, getHealth, sinceLabel, type Feature } from "@/lib/api";

export const revalidate = 300;

/** Routine closures are ranked below real ones: the point of the page is what
 *  is unexpectedly shut, not what is asleep. */
function rank(feature: Feature): number {
  if (feature.status.closure_kind === "outside_hours") return 3;
  return { closed: 0, restricted: 1, open: 2, unknown: 4 }[
    feature.status.value
  ] ?? 5;
}

function cardClass(feature: Feature): string {
  if (feature.status.closure_kind === "outside_hours") return "card routine";
  return `card ${feature.status.value}`;
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

  // Sectors only. The individual machines inside them are auto-created from
  // the operator feed and belong on the sector's own page — listing them here
  // buries one real closure under twenty lifts reading "pending", and counts
  // Grands Montets twice because its single lift is also closed.
  const sectors = features
    .filter((f) => f.type === "lift" && !f.parent_slug && f.status.summary)
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));

  const childCount = new Map<string, number>();
  for (const f of features) {
    if (f.parent_slug) {
      childCount.set(f.parent_slug, (childCount.get(f.parent_slug) ?? 0) + 1);
    }
  }

  const notable = sectors.filter(
    (f) => f.status.value !== "unknown" && f.status.closure_kind === null,
  );

  return (
    <>
      <MassifMap features={features} />

      <p className="disclaimer">
        A directory of what operators and authorities have published. Statuses
        may be out of date, and being confidently stale is the failure mode
        this page tries hardest to avoid — every card shows when it was last
        confirmed. Verify locally before committing to anything.
      </p>

      <p className="meta">
        Last successful ingest: {sinceLabel(lastIngest)} · {features.length}{" "}
        features tracked
      </p>

      <h2 style={{ fontSize: 16, marginTop: 28 }}>
        {notable.length > 0
          ? `${notable.length} closure${notable.length === 1 ? "" : "s"} worth knowing about`
          : "Nothing unexpectedly shut"}
      </h2>

      <div className="grid">
        {sectors.map((feature) => (
          <a
            key={feature.slug}
            className={cardClass(feature)}
            href={`/${feature.type}/${feature.slug}`}
          >
            <h3>
              {feature.name}{" "}
              {feature.status.closure_kind === null &&
                feature.status.value !== "unknown" && (
                  <span className={`pill ${feature.status.value}`}>
                    {feature.status.value}
                  </span>
                )}
            </h3>
            <p>{feature.status.summary}</p>
            <div className={`meta ${feature.status.stale ? "stale" : ""}`}>
              {feature.status.stale ? "⚠ not confirmed recently · " : ""}
              last confirmed {sinceLabel(feature.status.observed_at)}
              {childCount.get(feature.slug)
                ? ` · ${childCount.get(feature.slug)} lifts`
                : ""}
            </div>
          </a>
        ))}
      </div>
    </>
  );
}
