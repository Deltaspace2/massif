"""Each hut's own website, from the OSM object we already hold an id for.

    python -m massif.scripts.import_osm_websites            # dry run
    python -m massif.scripts.import_osm_websites --apply

camptocamp's `operator_url` covers 44 of the 74 huts and is already shown. The
other 30 have a `website` tag in OpenStreetMap and nowhere else we hold, so the
site knew where those huts live and never said so.

NO SEARCHING, and that is the whole reason this is cheap and safe. Every hut
here already carries `external_ids.osm` from the OSM import — a node or way id
somebody matched once, against altitude and position. This asks Overpass for
those exact objects and reads one tag off each. There is no name matching to
get wrong, which is what rule 8 is about.

FACTS, NEVER STATEMENTS. A URL is a property of a building, like a bunk count.
It has no validity window, it does not age into a warning, and it never enters
the status pipeline.

ATTRIBUTION IS THE POINT OF THE SOURCE ROW. OSM is ODbL, so the credit is a
licence condition and not a courtesy — `_fact_block` refuses to render a block
whose source carries no `licence` in `fetch_config`, and each fact links back
to its own object rather than to one shared footer.

Stored under the key `operator_url`, which is camptocamp's name for it. One key
means one renderer and nothing to drift; the page shows the HOSTNAME either
way, so a directory link still reads as a directory link.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, text

from massif.db import session_scope
from massif.models import Feature, FeatureFact, Source

SOURCE_SLUG = "openstreetmap"
OVERPASS = "https://overpass-api.de/api/interpreter"
UA = {"User-Agent": "massif/0.1 (+https://montblancmassif.org/about; steven@innes.io)"}

# Same shape as the other fact importers: the cadence lives in the data, not in
# the cron, so the weekly workflow can call this every hour and do nothing 167
# times out of 168.
REFRESH_DAYS = 7

# In tag preference order. `website` is the documented one; `contact:website`
# is the same thing under the contact: scheme and is common on older objects.
TAGS = ("website", "contact:website")


def _due(session, force: bool) -> bool:
    if force:
        return True
    last = session.scalar(
        text(
            "SELECT max(f.fetched_at) FROM feature_facts f "
            "JOIN sources s ON s.id = f.source_id WHERE s.slug = :slug"
        ),
        {"slug": SOURCE_SLUG},
    )
    return last is None or last < datetime.now(UTC) - timedelta(days=REFRESH_DAYS)


def targets(session) -> list[tuple]:
    """Huts with an OSM id and no website from anywhere else yet.

    Skipping the ones camptocamp already covers is not just tidiness: two
    sources offering the same key would print the same row twice under two
    credits, and the page's own dedupe compares rendered text rather than
    meaning.
    """
    rows = session.execute(
        select(Feature.id, Feature.slug, Feature.name_default, Feature.external_ids).where(
            Feature.feature_type == "hut", Feature.active.is_(True)
        )
    ).all()
    covered = {
        fid
        for (fid,) in session.execute(
            text(
                "SELECT feature_id FROM feature_facts "
                "WHERE payload ? 'operator_url'"
            )
        ).all()
    }
    out = []
    for fid, slug, name, ext in rows:
        osm = (ext or {}).get("osm")
        if osm and fid not in covered:
            out.append((fid, slug, name, osm))
    return out


def fetch_tags(osm_ids: list[str]) -> dict[str, dict]:
    """Tags for exactly these objects. One request, no search."""
    if not osm_ids:
        return {}
    parts = []
    for oid in osm_ids:
        kind, _, num = oid.partition("/")
        if kind in ("node", "way", "relation") and num.isdigit():
            parts.append(f"{kind}({num});")
    if not parts:
        return {}
    query = f"[out:json][timeout:120];({''.join(parts)});out tags;"
    response = httpx.post(OVERPASS, data={"data": query}, headers=UA, timeout=180)
    response.raise_for_status()
    return {
        f"{element['type']}/{element['id']}": element.get("tags", {})
        for element in response.json().get("elements", [])
    }


def website_of(tags: dict) -> str | None:
    for key in TAGS:
        value = (tags.get(key) or "").strip()
        # Anything that is not http(s) is not a website we should link: OSM
        # carries the occasional bare domain, mailto: and facebook handle.
        if value.startswith(("http://", "https://")):
            return value
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    parser.add_argument("--force", action="store_true", help="fetch even if not due")
    args = parser.parse_args()

    with session_scope() as session:
        source = session.scalar(select(Source).where(Source.slug == SOURCE_SLUG))
        if source is None:
            print(f"source {SOURCE_SLUG!r} not seeded — add it to seeds/sources.yaml")
            return 1
        if not _due(session, args.force):
            print(f"{SOURCE_SLUG}: last pull is under {REFRESH_DAYS} days old, nothing to do")
            return 0

        wanted = targets(session)
        print(f"{len(wanted)} huts with an OSM id and no website yet")
        tags = fetch_tags([osm for _f, _s, _n, osm in wanted])

        found = 0
        now = datetime.now(UTC)
        for fid, slug, _name, osm in wanted:
            url = website_of(tags.get(osm, {}))
            if not url:
                continue
            found += 1
            print(f"  {slug:34} {url[:52]}")
            if args.apply:
                fact = session.scalar(
                    select(FeatureFact).where(
                        FeatureFact.feature_id == fid, FeatureFact.source_id == source.id
                    )
                ) or FeatureFact(feature_id=fid, source_id=source.id)
                fact.payload = {"operator_url": url}
                # Per object, never one shared footer: ODbL attaches to the
                # data and the link has to reach the thing it came from.
                fact.source_url = f"https://www.openstreetmap.org/{osm}"
                fact.external_ref = osm
                fact.fetched_at = now
                fact.match_method = "osm_id"
                fact.match_score = 100
                session.add(fact)

        print(f"\n{found} of {len(wanted)} had a website tag")
        if not args.apply:
            print("dry run — nothing written; pass --apply")
            session.rollback()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
