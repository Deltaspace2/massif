// Server-side only. Every fetch happens in a React Server Component, which is
// what makes each feature page indexable — this site lives or dies on someone
// googling "aiguille du midi closed".

const API = process.env.MASSIF_API ?? "http://localhost:8000";

export type StatusValue = "open" | "closed" | "restricted" | "unknown";

export interface FeatureStatus {
  value: StatusValue;
  severity: number;
  summary: string | null;
  /** When the SOURCE published it — the date on the arrêté. */
  observed_at: string | null;
  /** When WE last fetched the source and found it still standing. */
  last_seen_at: string | null;
  /** The backend's own verdict, per statement type: an arrêté holds 90 days,
   *  a reopening 30, a live lift status one. Do not re-derive this in the UI. */
  stale: boolean;
  /** Whether WE have failed to re-check within the source's own cadence —
   *  also the backend's verdict, and for the same reason. The UI used to ask
   *  this with a flat 24 hours, which is exactly mbnr-openings' fetch
   *  interval, so a healthy daily source was badged before every run. */
  unchecked?: boolean;
  /** The entry whose author wrote this, where the source publishes one.
   *
   *  For camptocamp this is a LICENCE CONDITION — CC BY-SA attaches to the
   *  individual report — so a statement carrying one must render it. Optional
   *  for the usual deploy-skew reason, and absent for sources whose page is
   *  itself the statement. */
  permalink?: string | null;
  /** "outside_hours" means routine — night, or out of season. */
  closure_kind: string | null;
  counts: Record<string, { open: number; total: number }> | null;
  altitude_m: number | null;
  /** Currently-valid statements that did not win the status slot. */
  other_notices: number;
  lifts:
    | {
        name: string;
        status: StatusValue;
        raw_status: string | null;
        times: string[];
        message: string;
      }[]
    | null;
}

/** Availability THIS SEASON, ignoring the hour. What a trip planner asks. */
export interface Season {
  value: StatusValue;
  reason: string | null;
  /** "in_season" | "out_of_season" | "notice" | null */
  kind: string | null;
}

export interface Feature {
  season: Season;
  slug: string;
  type: string;
  /** Null for a sector; set for an individual machine inside one. */
  parent_slug: string | null;
  name: string;
  names: Record<string, string>;
  alt_min: number | null;
  alt_max: number | null;
  country: string | null;
  geometry: { type: string; coordinates: unknown } | null;
  geom_verified: boolean;
  status: FeatureStatus;
  /** Directory facts, carried on the list as well as the detail.
   *
   *  OPTIONAL on purpose. The frontend and the read API are two separate
   *  Vercel projects that deploy independently, so during any deploy this
   *  renders against an API that predates the field. Typing it as required
   *  made `feature.facts.map` a 500 on every feature page — the SEO surface
   *  — for the length of a deploy window. Read it as `?? []`. */
  facts?: FactBlock[];
}

export interface Notice {
  type: string;
  status: StatusValue;
  severity: number;
  observed_at: string;
  last_seen_at: string | null;
  valid_from: string | null;
  valid_to: string | null;
  summary: string | null;
  original_text: string | null;
  original_language: string | null;
  advisory: boolean;
  /** See FeatureStatus.permalink — a licence condition where present. */
  permalink?: string | null;
  source: { name: string; url: string; type: string };
}

/** A directory description of the building itself, with its credit attached.
 *
 *  Not a Notice: facts have no status, no severity and no staleness. A bunk
 *  count does not expire, so nothing here may be styled as a warning. Every
 *  value is optional and absent means "the source does not say" — which is a
 *  different thing from `false`, and must render differently. */
export interface FactBlock {
  source: { name: string; url: string; type: string };
  /** The specific entry their community wrote. Per hut, never one shared
   *  footer — the link back is a condition of the licence. */
  permalink: string;
  licence: string;
  licence_url: string | null;
  /** When THEY last edited the entry. Routinely months old; that is normal
   *  for a directory and is context, not a freshness flag. */
  source_modified_at: string | null;
  /** When WE last pulled it. */
  fetched_at: string | null;
  values: {
    capacity?: number;
    guarded?: boolean;
    /** camptocamp: access relative to the warden, already in English. */
    custodianship?: string;
    capacity_staffed?: number;
    capacity_unstaffed?: number;
    water?: boolean;
    latrines?: boolean;
    altitude_m?: number;
    phone?: string;
  };
}

export interface FeatureDetail extends Feature {
  /** The detail endpoint returns the notices themselves, not just a count. */
  other_notices: Notice[];
  /** Our own editorial line about this feature, shown above the directory
   *  facts. Optional for the same deploy-skew reason as `facts` below. */
  notes?: string | null;
  parent: { slug: string; name: string } | null;
  children: {
    slug: string;
    name: string;
    status: StatusValue;
    summary: string | null;
  }[];
  history: {
    type: string;
    status: StatusValue;
    severity: number;
    observed_at: string;
    summary: string | null;
    original_text: string | null;
    original_language: string | null;
    source: { name: string; url: string; type: string };
  }[];
}

// One window for everything on a page. Mixing lifetimes produced a page that
// disagreed with itself: a two-minute-old ingest timestamp printed beside
// eleven-minute-old lift data, from a cached response that predated a schema
// change. Parts of one view must age together.
const REVALIDATE = 60;

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    // In dev, never cache: you are editing the API and the parser, and a
    // stale fetch reads exactly like a bug in whichever you touched last.
    ...(process.env.NODE_ENV === "production"
      ? { next: { revalidate: REVALIDATE } }
      : { cache: "no-store" as const }),
  });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function listFeatures() {
  return get<{ count: number; features: Feature[]; disclaimer: string }>(
    "/features",
  );
}

export function getFeature(slug: string) {
  return get<FeatureDetail>(`/features/${slug}`);
}

/** One published statement, newest first. What changed, not what is. */
export interface FeedItem {
  feature: { slug: string; name: string; type: string };
  status: StatusValue;
  severity: number;
  summary: string | null;
  /** When the SOURCE published it. */
  observed_at: string;
  /** When WE last fetched and still found it. Two clocks, two columns. */
  last_seen_at: string | null;
  source: { name: string; url: string };
}

export function getFeed(limit = 50) {
  return get<{ items: FeedItem[]; disclaimer: string }>(`/feed?limit=${limit}`);
}

export function getHealth() {
  return get<{
    last_successful_ingest: string | null;
    features: number;
    disclaimer: string;
  }>("/health");
}

/** Resort-local, always. The mountain keeps its own clock, not the reader's. */
export function resortTime(iso: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: "Europe/Paris",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Month and year — for dates that are context rather than freshness.
 *
 *  Deliberately NOT `sinceLabel`. A directory entry last edited in Oct 2024 is
 *  a perfectly good description of a building, but "672 days ago" states it in
 *  this site's staleness vocabulary, where that number always means something
 *  is wrong. It also cannot drift into a false present tense the way a
 *  relative phrase can, which is why it is safe to compose here. */
export function monthYear(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-GB", {
    timeZone: "Europe/Paris",
    month: "short",
    year: "numeric",
  });
}

export function sinceLabel(iso: string | null): string {
  if (!iso) return "never checked";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}
