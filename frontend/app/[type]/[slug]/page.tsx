import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getFeature, resortTime, sinceLabel } from "@/lib/api";

export const revalidate = 300;

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

      <div className={routine ? "card routine" : `card ${feature.status.value}`}>
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
