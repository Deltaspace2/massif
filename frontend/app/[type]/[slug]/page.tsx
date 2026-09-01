import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import FeatureMap from "@/components/FeatureMap";
import Flag from "@/components/Flag";
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

  // What "unknown" actually means for THIS feature. It was one sentence for
  // every case — "No source this site watches has published anything about X"
  // — printed on 58 of the 63 huts that read unknown, directly above a table
  // of what a source had published about them. It was simply false there, and
  // it made a thin patch of coverage look like total ignorance.
  //
  // Three different situations, and the directory already tells them apart:
  //   * an unstaffed bivouac has no warden season to open or close, so there
  //     is nothing to report and never will be;
  //   * a wardened hut has a season that nobody we watch publishes;
  //   * and for a handful we really do hold nothing.
  // None of this promotes a fact to a status — the badge is untouched. It
  // just stops the page claiming an ignorance it does not have.
  const factValues = (feature.facts ?? []).map((fact) => fact.values);
  const saysWardened = factValues.some((v) => v.guarded === true);
  const saysUnwardened = !saysWardened && factValues.some((v) => v.guarded === false);
  const haveDirectoryEntry = factValues.length > 0;

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
      {/* Our curated altitude first, and only falling back to the one carried
          on a statement. This line read `status.altitude_m`, which is null for
          every hut — so the Goûter showed no altitude of its own and the only
          figure on the page was refuges.info's 3815 m, inside the facts block,
          against our 3835. Theirs stays where it is, attributed; ours is the
          one in our own voice, and it is the number the hut matcher uses to
          tell this refuge from the demolished one at 3817 m. */}
      <p className="meta">
        {feature.type}
        {(() => {
          const altitude =
            feature.alt_max ?? feature.alt_min ?? feature.status.altitude_m;
          return altitude ? ` · ${altitude} m` : "";
        })()}
        {/* Was the bare code "FR". The flag carries an accessible country
            name, so this reads as "France" rather than two letters. */}
        {feature.country ? " · " : ""}
        <Flag code={feature.country} />
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
            claiming it was our check. Both are shown now, separately.

            And when there is no notice at all, both dates are null and this
            line read "Published never resort time (never checked)" — which is
            not a sentence. That is the common case now, not the rare one: 78
            of 115 features have had nothing published about them. It gets
            plain words instead. */}
        {feature.status.observed_at ? (
          <div className={`meta ${feature.status.stale ? "stale" : ""}`}>
            Published {resortTime(feature.status.observed_at)} resort time (
            {sinceLabel(feature.status.observed_at)})
            {feature.status.last_seen_at && (
              <> · source re-checked {sinceLabel(feature.status.last_seen_at)}</>
            )}
            {feature.status.stale &&
              " — this has aged past the window its kind of notice holds for"}
          </div>
        ) : saysUnwardened ? (
          <div className="meta">
            {feature.name} is an unstaffed shelter, so there is no warden
            season for anyone to open or close — nothing is scheduled to be
            published about it, and the status above says unknown for want of
            a better word rather than because something is missing. Whether it
            is standing, reachable and fit to use on any given day is not
            something this site can tell you.
          </div>
        ) : haveDirectoryEntry ? (
          <div className="meta">
            Nobody this site watches publishes an opening status for{" "}
            {feature.name}
            {saysWardened ? ", though it is a wardened hut and so has a season" : ""}.
            The directory entry below describes the building; it says nothing
            about whether it is open today. That is a gap in our coverage, not
            a report that all is well.
          </div>
        ) : (
          <div className="meta">
            No source this site watches has published anything about{" "}
            {feature.name}. That is a gap in our coverage, not a report that
            all is well — and it is why the status above says unknown rather
            than open.
          </div>
        )}
        {routine && (
          <div className="meta">
            Routine: shut because of the hour or the season, not an incident.
          </div>
        )}
        {/* Where the source publishes a per-entry link, show it. For
            camptocamp this is a licence condition rather than a courtesy:
            CC BY-SA attaches to the individual report somebody wrote, so a
            line we cannot link back to is a line we must not print. Rendered
            from the API's own field — never assembled here from an id.

            The wording is deliberately NEUTRAL. It used to read "one person's
            account of one day", which is true of a camptocamp trip report and
            false of everything else carrying a permalink — refuges.info also
            publishes one, so a wiki classification of a bivouac was captioned
            as somebody's day out. A caption that fits one source and is shown
            for all of them is a wrong sentence with a correct link. */}
        {feature.status.permalink && (
          <div className="meta">
            <a
              href={feature.status.permalink}
              target="_blank"
              rel="noopener noreferrer"
            >
              Read the entry this came from
            </a>{" "}
            — what the source published, in their words.
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
      {(feature.facts ?? []).map((fact) => {
        const v = fact.values;
        const rows: { label: string; value: ReactNode }[] = [];
        if (v.capacity !== undefined)
          rows.push({ label: "Sleeps", value: `${v.capacity} places` });
        // camptocamp splits the beds by whether the warden is there, which is
        // a different and more useful number than a single total.
        if (v.capacity_staffed !== undefined)
          rows.push({ label: "Sleeps, wardened", value: `${v.capacity_staffed} places` });
        if (v.capacity_unstaffed !== undefined)
          rows.push({
            label: "Sleeps, unwardened",
            value: `${v.capacity_unstaffed} places`,
          });
        if (v.custodianship !== undefined)
          rows.push({ label: "Access", value: v.custodianship });
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
            {/* Ours, above theirs, because a directory fact can mislead on its
                own: refuges.info lists 12 places at Abri Vallot, which is true
                and reads as a bunkroom, and it is a shelter of last resort at
                4362 m. Deliberately rendered only here, where facts are — most
                curated notes are bookkeeping ("auto-created from an operator
                feed") and belong nowhere near a reader. */}
            {feature.notes && (
              <p className="facts__note">{feature.notes}</p>
            )}
            <p className="meta">
              How {fact.source.name} describes the building. These are
              properties of the hut, not a status — they do not expire, and we
              have not verified them. Any altitude below is their survey, not
              ours — where it differs from the figure at the top of this page,
              the one at the top is ours.
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

      {/* The report link belongs on THIS page above all others: someone who
          knows a status is wrong knows it while looking at the thing, and this
          is the page they arrive on from a search. It carried no way to say so. */}
      <p className="meta report-inline">
        Is any of this wrong?{" "}
        <a href="/feedback">Tell us</a> — a green dot on something shut is the
        failure this site exists to avoid.
      </p>

      <h3 style={{ fontSize: 15, marginTop: 30 }}>
        Everything published about this
      </h3>
      {/* An empty table under a heading that promises content reads as a
          broken page, not as an empty one. This is the common case, not the
          rare one: 17 of the 19 huts have no notice at all, because the only
          municipal source we watch is Saint-Gervais and it publishes about
          two of them. "We have found nothing" is information; a blank grid is
          an absence the reader has to interpret. */}
      {feature.history.length === 0 ? (
        <p className="meta">
          Nothing. No source this site watches has published about{" "}
          {feature.name}, so there is no history to show — which is a gap in
          our coverage, not a statement that all is well.
        </p>
      ) : (
        <>
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
        </>
      )}
    </main>
  );
}
