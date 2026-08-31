import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import FeatureMap from "@/components/FeatureMap";
import { getFeature, monthYear, resortTime, sinceLabel } from "@/lib/api";

export const revalidate = 60;

// Named, because "(fr)" beside a paragraph of French tells an English reader
// nothing they had not already worked out.
const LANGUAGE: Record<string, string> = {
  fr: "French",
  it: "Italian",
  de: "German",
  en: "English",
};

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

  // Absent means "the source does not say"; false means "no, there isn't".
  // Collapsing those two into one blank would invent an answer — the site's
  // signature failure. Only an explicit boolean produces a row.
  const yesNo = (value: boolean | undefined) =>
    value === undefined ? null : value ? "Yes" : "No";

  // A notice either asserts something about now, or it does not. Mixing the
  // two under one heading is what made this page contradict itself.
  const inForce = feature.other_notices.filter(
    (n) => n.status === "closed" || n.status === "restricted",
  );
  const undated = feature.other_notices.filter(
    (n) => n.status !== "closed" && n.status !== "restricted",
  );

  return (
    // Not redesigned in this pass — wrapped so it inherits the new page
    // gutters and tokens rather than sitting flush against the viewport now
    // that the layout no longer supplies a container.
    <main className="subpage">
      {/* A link, not history.back(). This is the SEO surface — people arrive
          here from a search for "aiguille du midi closed" with no back stack
          at all, and a control that does nothing for them is worse than none.
          It names where it goes: the parent sector when there is one, since
          that is more useful than the front page from inside a lift. */}
      <a
        className="back"
        href={feature.parent ? `/lift/${feature.parent.slug}` : "/"}
      >
        <span aria-hidden="true">←</span>
        {feature.parent ? feature.parent.name : "All statuses"}
      </a>

      <h1>{feature.name}</h1>
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
        {/* "Last confirmed" was doing two jobs and telling the truth about
            neither: it printed the mairie's publication date under a label
            claiming it was our check. Both are shown now, separately. */}
        <div className={`meta ${feature.status.stale ? "stale" : ""}`}>
          Published {resortTime(feature.status.observed_at)} resort time (
          {sinceLabel(feature.status.observed_at)})
          {feature.status.last_seen_at && (
            <> · source re-checked {sinceLabel(feature.status.last_seen_at)}</>
          )}
          {feature.status.stale &&
            " — this has aged past the window its kind of notice holds for"}
        </div>
        {routine && (
          <div className="meta">
            Routine: shut because of the hour or the season, not an incident.
          </div>
        )}
      </div>

      {inForce.length > 0 && (
        <>
          <h3 style={{ fontSize: 15, marginTop: 26 }}>Also in force now</h3>
          <p className="meta">
            Notices that assert something about right now and are not the
            headline status. A route can be legally open and still carry a
            warning — only one of them gets to be the colour of the card, so
            the rest are here rather than buried in the history.
          </p>
          {inForce.map((notice, index) => (
            <div className="notice" key={index}>
              <h4>
                {notice.summary ?? notice.type}{" "}
                <span className={`pill ${notice.status}`}>{notice.status}</span>
              </h4>
              {/* The English line above is the one to read. The source's own
                  words are kept verbatim — that is the whole promise of the
                  site — but a French paragraph set at full weight under an
                  English heading made the page look untranslated, and the
                  reader has to get past it to reach the date and the link. */}
              {notice.original_text && (
                <details className="original">
                  <summary>
                    Read it as published
                    {notice.original_language
                      ? ` (in ${LANGUAGE[notice.original_language] ?? notice.original_language})`
                      : ""}
                  </summary>
                  <blockquote lang={notice.original_language ?? undefined}>
                    {notice.original_text}
                  </blockquote>
                </details>
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

      {/* Undated notices had been filed under "Also currently in force" — a
          heading that asserts the present, about statements whose entire
          definition is that they do NOT assert the present. status=unknown is
          how this project says "real notice, no window, makes no claim about
          today", and then the page claimed today on their behalf. The result
          read as a flat contradiction: OPEN at the top, "currently in force"
          closures underneath. Same statements, honest heading. */}
      {undated.length > 0 && (
        <>
          <h3 style={{ fontSize: 15, marginTop: 26 }}>
            Published about this, without dates
          </h3>
          <p className="meta">
            These carry no start or end date, so we cannot tell you whether they
            still apply — and we will not guess. They are here because a
            published warning should not disappear merely for being open-ended.
            Where a later notice from the same authority lifted one, it is gone
            from this list; anything remaining has not been superseded that we
            can see. Read the dates and judge for yourself.
          </p>
          {undated.map((notice, index) => (
            <div className="notice notice--undated" key={index}>
              <h4>
                {notice.summary ?? notice.type}{" "}
                <span className="pill">undated</span>
              </h4>
              {notice.original_text && (
                <details className="original">
                  <summary>
                    Read it as published
                    {notice.original_language
                      ? ` (in ${LANGUAGE[notice.original_language] ?? notice.original_language})`
                      : ""}
                  </summary>
                  <blockquote lang={notice.original_language ?? undefined}>
                    {notice.original_text}
                  </blockquote>
                </details>
              )}
              <p className="meta">
                Published {resortTime(notice.observed_at)} ·{" "}
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

      {/* Directory facts about the building. Kept well below the status and
          the notices on purpose: this answers "what is this hut like", which
          is a different and much less urgent question than "is it shut". It
          carries no colour, no pill and no staleness styling, because a bunk
          count does not expire and must never read as a warning. */}
      {feature.facts.map((fact) => {
        const v = fact.values;
        const rows: { label: string; value: ReactNode }[] = [];
        if (v.capacity !== undefined)
          rows.push({ label: "Sleeps", value: `${v.capacity} places` });
        if (v.guarded !== undefined)
          rows.push({
            label: "Warden",
            value: v.guarded ? "Staffed refuge" : "Unstaffed",
          });
        if (v.water !== undefined)
          rows.push({ label: "Water", value: yesNo(v.water) });
        if (v.latrines !== undefined)
          rows.push({ label: "Latrines", value: yesNo(v.latrines) });
        if (v.altitude_m !== undefined)
          rows.push({ label: "Altitude", value: `${v.altitude_m} m` });
        if (v.phone !== undefined)
          rows.push({
            label: "Phone",
            value: (
              <a href={`tel:${v.phone.replace(/[^+\d]/g, "")}`}>{v.phone}</a>
            ),
          });
        const edited = monthYear(fact.source_modified_at);

        return (
          <section className="facts" key={fact.permalink}>
            {/* Not "hut". _facts filters on feature_id, not feature_type, so
                this path renders for anything that has a fact row — only huts
                do today, and only because the importer selects them. */}
            <h3 style={{ fontSize: 15, marginTop: 30 }}>
              About this {feature.type}
            </h3>
            <p className="meta">
              How {fact.source.name} describes the building. These are
              properties of the hut, not a status — they do not expire, and we
              have not verified them. Any altitude below is their survey, not
              ours, and the two do not always agree.
            </p>
            <dl className="facts__list">
              {rows.map((row) => (
                <div className="facts__row" key={row.label}>
                  <dt>{row.label}</dt>
                  <dd>{row.value}</dd>
                </div>
              ))}
            </dl>
            {/* Attribution is a licence condition, not a courtesy: the credit,
                a link to the licence, and a link to the specific entry their
                community wrote — per hut, not one shared footer. */}
            <p className="meta facts__credit">
              From{" "}
              <a href={fact.permalink} rel="nofollow noopener">
                the {fact.source.name} entry
              </a>
              , written by their contributors and used under{" "}
              {fact.licence_url ? (
                <a href={fact.licence_url} rel="license noopener">
                  {fact.licence}
                </a>
              ) : (
                fact.licence
              )}
              .{/* Their clock and ours, kept apart — see the status card. */}
              {edited && ` Last edited there ${edited}`}
              {fact.fetched_at &&
                `${edited ? "; " : " "}we pulled it ${sinceLabel(fact.fetched_at)}`}
              .
            </p>
          </section>
        );
      })}

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
                  <details className="original">
                    <summary>
                      as published
                      {entry.original_language
                        ? ` (${LANGUAGE[entry.original_language] ?? entry.original_language})`
                        : ""}
                    </summary>
                    <blockquote lang={entry.original_language ?? undefined}>
                      {entry.original_text}
                    </blockquote>
                  </details>
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
    </main>
  );
}
