import type { Metadata } from "next";
import Flag from "@/components/Flag";
import { listFeatures, type Feature } from "@/lib/api";

export const revalidate = 60;

/** Search, done the way this site does everything: server-rendered, no
 *  JavaScript, one GET form. 133 features is not a corpus that needs an
 *  index — the whole list is already fetched for the front page, and a
 *  substring test over it answers in the same request.
 *
 *  NOINDEX. Query pages are thin duplicates of the feature pages they link
 *  to, and the feature pages are the SEO surface; two indexable copies of
 *  "Refuge du Goûter" is an invitation for Google to pick the wrong one. */
export const metadata: Metadata = {
  title: "Search",
  robots: { index: false, follow: false },
  alternates: { canonical: "/" },
};

/** Accent- and case-blind, because the audience types "gouter" on an English
 *  keyboard and the massif spells it "Goûter". The same folding the backend
 *  applies to French text, for the same reason — rule 1: "Réouverture" did
 *  not match "reouverture", and a search box that misses Goûter for want of a
 *  circumflex teaches people it is broken. */
function fold(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

function matches(feature: Feature, needle: string): boolean {
  const haystack = [
    feature.name,
    feature.slug.replace(/-/g, " "),
    ...Object.values(feature.names ?? {}),
  ];
  return haystack.some((h) => fold(h ?? "").includes(needle));
}

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const needle = fold((q ?? "").trim());
  const { features } = await listFeatures();
  const hits = needle ? features.filter((f) => matches(f, needle)) : [];

  return (
    <main className="subpage">
      <a className="back" href="/">
        <span aria-hidden="true">←</span>
        All statuses
      </a>
      <h1>Search</h1>

      {/* A GET form: the URL carries the query, so a result page can be
          bookmarked, shared, and reached with JavaScript off — a phone in a
          hut on bad signal searches like anything else. */}
      <form action="/search" method="get" className="search" role="search">
        <input
          type="search"
          name="q"
          defaultValue={q ?? ""}
          placeholder="Goûter, Cosmiques, Flégère…"
          aria-label="Search huts, lifts and routes"
          autoFocus={!needle}
        />
        <button type="submit">Search</button>
      </form>

      {needle === "" ? (
        <p className="meta">
          Every hut, lift, railway, route and glacier this site tracks —
          {" "}{features.length} of them — by name, in any of its spellings.
          Accents do not matter.
        </p>
      ) : hits.length === 0 ? (
        <p className="disclaimer">
          Nothing tracked here matches <b>{q}</b>. That means this site does
          not carry the feature — not that the feature does not exist, and not
          that anything is open or shut. If it belongs in the massif,{" "}
          <a href="/feedback">tell us and it gets added</a>.
        </p>
      ) : (
        <>
          <p className="meta">
            {hits.length} of {features.length} tracked features match{" "}
            <b>{q}</b>.
          </p>
          <ul className="search__hits">
            {hits.map((f) => (
              <li key={f.slug}>
                <a href={`/${f.type}/${f.slug}`}>{f.name}</a>
                <span className="search__kind">
                  {f.type}
                  {f.alt_max ? ` · ${f.alt_max} m` : ""}{" "}
                  <Flag code={f.country} />
                </span>
                {/* The status word, only when there is one to say. UNKNOWN is
                    spelled out on the feature page with its full caveat, and
                    a bare grey "unknown" in a result list reads as a verdict
                    rather than as an absence. */}
                {f.status.value !== "unknown" && (
                  <span className={`pill ${f.status.value}`}>{f.status.value}</span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
