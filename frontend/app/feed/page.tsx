import type { Metadata } from "next";
import { getFeed, resortTime, sinceLabel } from "@/lib/api";

export const revalidate = 60;

export const metadata: Metadata = {
  title: "What changed — Mont Blanc massif",
  description:
    "Every notice published about the Mont Blanc massif, newest first, with a " +
    "link to whoever said it.",
};

// The masthead has linked here from every page since the redesign, and the
// route did not exist — so every page on the site carried a nav item to a 404.
// The API has returned this data since the scaffold.
export default async function Feed() {
  let items;
  let error: string | null = null;
  try {
    ({ items } = await getFeed(80));
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  // Same rule as the front page: failing to reach our own data is not a
  // statement about the mountain, and must never read as one.
  if (error || !items) {
    return (
      <main className="subpage">
        <h1>Feed unavailable</h1>
        <p className="disclaimer">
          This page could not reach its own data, so it is showing you nothing
          rather than something stale. That is not a statement about conditions
          in the massif.
        </p>
      </main>
    );
  }

  return (
    <main className="subpage">
      <h1>What changed</h1>
      <p className="meta">
        Every notice we hold, newest first — {items.length} of them. This is a
        record of what sources published, not a claim about what is true now: a
        notice near the top may have been lifted since, and one near the bottom
        may still be in force. The feature&rsquo;s own page is where you find
        out which.
      </p>

      <div className="feed">
        {items.map((item, index) => (
          <article className="feed__row" key={`${item.feature.slug}-${index}`}>
            <span className={`feed__status ${item.status}`}>{item.status}</span>
            <span className="feed__what">
              <a href={`/${item.feature.type}/${item.feature.slug}`}>
                {item.feature.name}
              </a>
              {item.summary && <span className="feed__summary">{item.summary}</span>}
            </span>
            {/* Their clock and ours, kept apart — the same distinction the
                feature page draws. "Published" is the source's date; the
                re-check is ours, and conflating them once badged a decree
                valid until September as unverified. */}
            <span className="feed__when mono">
              <span className="feed__published">
                {resortTime(item.observed_at)}
              </span>
              {item.last_seen_at && (
                <span className="feed__checked">
                  re-checked {sinceLabel(item.last_seen_at)}
                </span>
              )}
            </span>
            <span className="feed__source">
              <a href={item.source.url} rel="nofollow noopener">
                {item.source.name}
              </a>
            </span>
          </article>
        ))}
      </div>

      <p className="disclaimer">
        A directory of what operators and authorities have published, with a
        source for every line. Not a safety service. Verify locally before
        committing to anything. <a href="/feedback">Something wrong? Report it.</a>
      </p>
    </main>
  );
}
