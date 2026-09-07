import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/** There is nothing here to hide from a crawler: every page is a
 *  server-rendered directory entry, and being read is the entire
 *  distribution strategy. The file exists mainly to carry the sitemap
 *  pointer — that is the line that does the work. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/" }],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
