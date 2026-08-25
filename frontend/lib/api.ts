// Server-side only. Every fetch happens in a React Server Component, which is
// what makes each feature page indexable — this site lives or dies on someone
// googling "aiguille du midi closed".

const API = process.env.MASSIF_API ?? "http://localhost:8000";

export type StatusValue = "open" | "closed" | "restricted" | "unknown";

export interface FeatureStatus {
  value: StatusValue;
  severity: number;
  summary: string | null;
  observed_at: string | null;
  stale: boolean;
  /** "outside_hours" means routine — night, or out of season. */
  closure_kind: string | null;
  counts: Record<string, { open: number; total: number }> | null;
  altitude_m: number | null;
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

export interface Feature {
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
}

export interface FeatureDetail extends Feature {
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

export function getFeed(limit = 50) {
  return get<{ items: unknown[]; disclaimer: string }>(`/feed?limit=${limit}`);
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

export function sinceLabel(iso: string | null): string {
  if (!iso) return "never checked";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)} days ago`;
}
