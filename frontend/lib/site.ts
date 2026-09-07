/** The canonical origin, in one place.
 *
 * Used by `metadataBase`, `sitemap.ts` and `robots.ts`. If these three ever
 * disagree, the damage is invisible in testing and expensive in production:
 * canonical tags pointing at one host and a sitemap listing another is how a
 * site asks Google to index two copies of itself and rank neither.
 *
 * Overridable so a preview deploy can be pointed at itself, but the default
 * is deliberately the production domain rather than the Vercel URL. Preview
 * builds that fall back to this emit canonicals pointing at production, which
 * is the correct answer for duplicate content — the preview is not the page
 * anyone should land on.
 *
 * No trailing slash, ever: everything downstream concatenates `/path` onto it.
 */
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://montblancmassif.org"
).replace(/\/+$/, "");
