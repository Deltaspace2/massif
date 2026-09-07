import type { MetadataRoute } from "next";
import { listFeatures } from "@/lib/api";
import { SITE_URL } from "@/lib/site";

// Regenerated hourly rather than per request. The feature list changes when
// ingest writes something, not when a crawler calls.
export const revalidate = 3600;

/** The hand-written pages. Priorities are relative to each other only —
 *  Google treats them as a hint at best — so they say what this site is
 *  organised around rather than trying to game anything. */
const STATIC = [
  { path: "", priority: 1.0, changeFrequency: "hourly" as const },
  { path: "/huts", priority: 0.9, changeFrequency: "daily" as const },
  { path: "/lifts", priority: 0.9, changeFrequency: "hourly" as const },
  { path: "/routes", priority: 0.9, changeFrequency: "daily" as const },
  { path: "/feed", priority: 0.7, changeFrequency: "hourly" as const },
  { path: "/map", priority: 0.6, changeFrequency: "daily" as const },
  { path: "/about", priority: 0.4, changeFrequency: "monthly" as const },
  { path: "/feedback", priority: 0.3, changeFrequency: "monthly" as const },
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  const staticEntries: MetadataRoute.Sitemap = STATIC.map((s) => ({
    url: `${SITE_URL}${s.path}`,
    lastModified: now,
    changeFrequency: s.changeFrequency,
    priority: s.priority,
  }));

  let featureEntries: MetadataRoute.Sitemap = [];
  try {
    const { features } = await listFeatures();
    featureEntries = features.map((f) => ({
      url: `${SITE_URL}/${f.type}/${f.slug}`,
      // `observed_at` — when the SOURCE published — and deliberately NOT
      // `last_seen_at`. Rule 10: two clocks, two columns. `last_seen_at`
      // moves every time ingest re-fetches and finds the same notice
      // standing, which on the live lift feed is every thirty minutes. A
      // sitemap that claims 75 pages changed hourly when their content did
      // not is the exact pattern crawlers learn to distrust, and it would
      // spend the crawl budget re-reading pages that say what they said
      // before. Undated statuses simply carry no lastmod, which is honest.
      lastModified: f.status?.observed_at
        ? new Date(f.status.observed_at)
        : undefined,
      changeFrequency: "daily" as const,
      // Above the index pages. These ARE the SEO surface — the whole thesis
      // is someone googling "aiguille du midi closed" and landing on one.
      priority: 0.8,
    }));
  } catch {
    // The frontend and the read API deploy separately, and CI builds with no
    // MASSIF_API at all. A sitemap that throws here fails the build for a
    // backend that is merely absent, so an unreachable API costs the feature
    // URLs and nothing else. The next hourly regeneration picks them up.
  }

  return [...staticEntries, ...featureEntries];
}
