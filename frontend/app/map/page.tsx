import MapKey from "@/components/MapKey";
import type { Metadata } from "next";
import MassifMap from "@/components/MassifMap";
import { listFeatures, getHealth, sinceLabel, type Feature } from "@/lib/api";

export const revalidate = 60;

export const metadata: Metadata = {
  title: "Map",
  description:
    "Every tracked feature in the Mont Blanc massif on one map, coloured by " +
    "season: lifts, mountain railways, huts, routes and couloirs.",
};

export default async function MapPage() {
  let features: Feature[] = [];
  let lastIngest: string | null = null;
  let failed = false;

  try {
    const [list, health] = await Promise.all([listFeatures(), getHealth()]);
    features = list.features;
    lastIngest = health.last_successful_ingest;
  } catch {
    failed = true;
  }

  if (failed) {
    return (
      <main className="subpage">
        <h1>Map unavailable</h1>
        <p className="disclaimer">
          This page could not reach its own data. An empty map is not a claim
          that nothing is shut — <a href="/">the list</a> may still be cached,
          and the operators and mairies are authoritative either way.
        </p>
      </main>
    );
  }

  // Only features with geometry can appear. Two — the Goûter route and the
  // Grand Couloir — deliberately have none, because nobody has surveyed them
  // and a drawn line would claim a precision that does not exist. Saying so
  // out loud beats letting someone conclude they are not tracked.
  const placed = features.filter((f) => f.geometry).length;
  const missing = features.length - placed;

  return (
    <main className="mapfull">
      <div className="mapfull__canvas">
        <MassifMap features={features} />
      </div>

      <div className="mapfull__bar">
        <span className="mapfull__count">
          <b>{placed}</b> of {features.length} features placed
          {missing > 0 && (
            <span className="mapfull__missing">
              {" · "}
              {missing} tracked but unmapped
            </span>
          )}
        </span>

        <MapKey className="mapfull__legend" />

        <span className="mapfull__sweep mono">
          sweep {sinceLabel(lastIngest)} · <a href="/">back to status</a>
        </span>
      </div>
    </main>
  );
}
