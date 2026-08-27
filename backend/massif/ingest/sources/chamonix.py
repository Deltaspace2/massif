"""Mairie de Chamonix-Mont-Blanc — RECON ONLY. Investigated and parked.

OUTCOME: not a productive source. The decree register is empty, the news feed
carries no route closures, and there is no acts portal. Full reasoning is in
seeds/sources.yaml under mairie-chamonix. Kept because it re-runs the whole
investigation in one command if the register ever starts publishing:

    python -m massif.ingest.sources.chamonix --structure   # REST, sitemap, page
    python -m massif.ingest.sources.chamonix --decree      # the acts endpoint
    python -m massif.ingest.sources.chamonix --hunt        # search 471 news items
    python -m massif.ingest.sources.chamonix --acts        # portal? other types?


https://www.chamonix.fr/la-commune/publications-municipales/deliberations/

NOT chamonix-mont-blanc.fr, which is the tourist office. Same trap as the
Compagnie du Mont-Blanc corporate site: the official-looking domain is not the
one carrying the data.

Chamonix regulates the Chamonix side of the massif — the Aiguille du Midi
approaches, valley access tracks, and the town's own mountain restrictions.
Together with Saint-Gervais (which regulates the Goûter route) this is where
the closures alpinists actually care about are published.

Known: WordPress, permissive robots.txt (only /wp-admin/), publishes
sitemaps.xml. Three ways in, cheapest first:

1. The WordPress REST API. If /wp-json/wp/v2/ is exposed, arrêtés are probably
   a custom post type served as clean JSON with real dates — the mbnr-openings
   lesson, where structured data beat scraping the rendered page.
2. sitemaps.xml, which hands over the URL inventory instead of crawling.
3. The rendered listing page, as a last resort.

Run from a machine the site will talk to:

    python -m massif.ingest.sources.chamonix --structure
"""

from __future__ import annotations

import re
import sys

from selectolax.parser import HTMLParser

from massif.ingest.base import fetch, robots_allows

ROOT = "https://www.chamonix.fr"
LISTING = f"{ROOT}/la-commune/publications-municipales/deliberations/"

REST_PROBES = [
    f"{ROOT}/wp-json/",
    f"{ROOT}/wp-json/wp/v2/types",
    f"{ROOT}/wp-json/wp/v2/posts?per_page=3",
]

INTERESTING = re.compile(
    r"arrete|deliberation|decision|acte|reglementaire|montagne|"
    r"securite|voirie|circulation",
    re.I,
)


def _try(label: str, url: str):
    print(f"\n--- {label}\n    {url}")
    try:
        response = fetch(url)
    except Exception as exc:
        print(f"    FAILED {type(exc).__name__}: {exc}")
        return None
    ctype = response.headers.get("content-type", "")
    print(f"    HTTP {response.status_code}  {ctype}  {len(response.content)} bytes")
    return response


DECREE = f"{ROOT}/wp-json/wp/v2/decree"
NEWS = f"{ROOT}/wp-json/wp/v2/news"

MOUNTAIN = re.compile(
    r"montagne|alpin|glacier|couloir|refuge|voie normale|aiguille|"
    r"telepherique|acces|sentier|randonn|escalade|chute de pierre|"
    r"eboulement|seracs?|avalanche|midi|montenvers|brevent|flegere|"
    r"grands montets|bossons|mer de glace|interdi|ferme",
    re.I,
)


def _shape(obj, prefix: str = "", depth: int = 0) -> None:
    """Print the shape of one record so we can see what is actually on offer."""
    if depth > 2:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                size = len(value)
                print(f"      {prefix}{key}: {type(value).__name__}({size})")
                if size and depth < 2:
                    _shape(value, prefix + "  ", depth + 1)
            else:
                text = str(value)
                if len(text) > 90:
                    text = text[:90] + "..."
                print(f"      {prefix}{key}: {text!r}")
    elif isinstance(obj, list) and obj:
        _shape(obj[0], prefix + "  ", depth + 1)


def _endpoint(label: str, url: str, show: int = 3) -> None:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}\n    {url}")
    response = _try("fetch", url)
    if response is None:
        return
    total = response.headers.get("x-wp-total")
    pages = response.headers.get("x-wp-totalpages")
    print(f"    X-WP-Total={total}  X-WP-TotalPages={pages}")

    try:
        records = response.json()
    except Exception:
        print("    (not JSON)")
        return
    if not isinstance(records, list) or not records:
        print("    (empty)")
        return

    print("\n    --- shape of one record ---")
    _shape(records[0])

    print(f"\n    --- {min(show, len(records))} recent titles ---")
    for record in records[:show]:
        title = (record.get("title") or {}).get("rendered", "")
        title = re.sub(r"<[^>]+>", "", title)
        date = record.get("date", "")[:10]
        mountain = " <-- MOUNTAIN" if MOUNTAIN.search(title) else ""
        print(f"      {date}  {title[:78]!r}{mountain}")

    hits = [
        r for r in records
        if MOUNTAIN.search(re.sub(r"<[^>]+>", "", (r.get("title") or {}).get("rendered", "")))
    ]
    print(f"\n    {len(hits)}/{len(records)} of this page look mountain-related")


def _decree() -> int:
    _endpoint("DECREE — Publicité des actes",
              f"{DECREE}?per_page=20&orderby=date&order=desc", show=20)
    _endpoint("NEWS — Actualités",
              f"{NEWS}?per_page=10&orderby=date&order=desc", show=10)
    return 0


# Terms worth asking the search endpoint about. Paging 48 pages of municipal
# news to find a handful of mountain notices is the wrong shape; WordPress
# will filter server-side if asked.
HUNT_TERMS = [
    "arrete", "arrêté", "montagne", "sentier", "eboulement", "éboulement",
    "chutes de pierres", "glacier", "interdiction", "fermeture",
    "grand couloir", "aiguille du midi", "alpinisme", "refuge",
    "mer de glace", "acces interdit",
]


def _clean(html: str) -> str:
    import html as html_mod
    return html_mod.unescape(re.sub(r"<[^>]+>", "", html or "")).strip()


def _hunt() -> int:
    # ---- does the decree sitemap have anything the REST endpoint denies?
    print("=" * 70 + "\nDECREE SITEMAP vs REST\n" + "=" * 70)
    response = _try("decree sitemap", f"{ROOT}/decree-sitemap1.xml")
    if response is not None:
        locs = re.findall(r"<loc>([^<]+)</loc>", response.text)
        print(f"    {len(locs)} decree URLs in the sitemap")
        for loc in locs[:10]:
            print(f"      {loc}")
        if locs:
            print("\n    REST said 0 records but the sitemap lists these — the")
            print("    posts exist and the API is withholding them. Fetching one:")
            sample = _try("one decree page", locs[0])
            if sample is not None:
                tree = HTMLParser(sample.text)
                heading = tree.css_first("h1")
                print(f"      h1: {_clean(heading.html) if heading else None!r}")
                pdfs = [
                    a.attributes.get("href", "")
                    for a in tree.css("a[href]")
                    if ".pdf" in (a.attributes.get("href") or "").lower()
                ]
                print(f"      {len(pdfs)} PDF links")
                for href in pdfs[:5]:
                    print(f"        {href}")

    # ---- search the news archive server-side
    print("\n" + "=" * 70 + "\nNEWS SEARCH (471 items, filtered server-side)\n" + "=" * 70)
    seen: dict[str, tuple[str, str]] = {}
    for term in HUNT_TERMS:
        url = f"{NEWS}?search={term}&per_page=20&orderby=date&order=desc"
        try:
            response = fetch(url)
            records = response.json()
        except Exception as exc:
            print(f"  {term:<20} FAILED {type(exc).__name__}")
            continue
        if not isinstance(records, list):
            continue
        total = response.headers.get("x-wp-total", "?")
        print(f"  {term:<20} {total:>4} hits")
        for record in records:
            title = _clean((record.get("title") or {}).get("rendered", ""))
            if MOUNTAIN.search(title):
                seen[record.get("link", title)] = (record.get("date", "")[:10], title)

    print(f"\n  --- {len(seen)} distinct mountain-looking notices ---")
    for link, (date, title) in sorted(seen.items(), key=lambda kv: kv[1][0], reverse=True):
        print(f"    {date}  {title[:82]}")
        print(f"              {link}")
    return 0


def _acts() -> int:
    """Where do the arrêtés actually live?

    The decree register is empty and the news feed carries no route closures.
    Since the 2022 electronic-publication reform many communes push their acts
    to a third-party portal instead of their own site, so before writing this
    source off, check whether the page points somewhere else.
    """
    print("=" * 70 + "\nOUTBOUND LINKS FROM THE ACTES RÉGLEMENTAIRES PAGE\n" + "=" * 70)
    response = _try("listing", LISTING)
    if response is not None:
        tree = HTMLParser(response.text)
        external: dict[str, str] = {}
        for node in tree.css("a[href]"):
            href = node.attributes.get("href") or ""
            if not href.startswith("http"):
                continue
            if "chamonix.fr" in href:
                continue
            text = " ".join(node.text(separator=" ", strip=True).split())
            external.setdefault(href, text)
        print(f"    {len(external)} distinct external links")
        for href, text in external.items():
            print(f"      {text[:46]!r:<50} {href}")

        # the three cards on that page are the likely routes in
        print("\n    card links (any target):")
        for card in tree.css("[class*='card']"):
            link = card.css_first("a[href]")
            if link is None:
                continue
            text = " ".join(card.text(separator=" ", strip=True).split())
            print(f"      {text[:60]!r}")
            print(f"        -> {link.attributes.get('href')}")

    print("\n" + "=" * 70 + "\nOTHER POST TYPES\n" + "=" * 70)
    for kind in ("publication", "report", "procedure"):
        url = f"{ROOT}/wp-json/wp/v2/{kind}?per_page=5&orderby=date&order=desc"
        try:
            response = fetch(url)
            records = response.json()
        except Exception as exc:
            print(f"  {kind:<14} FAILED {type(exc).__name__}")
            continue
        total = response.headers.get("x-wp-total", "?")
        print(f"  {kind:<14} total={total}")
        if isinstance(records, list):
            for record in records[:5]:
                title = _clean((record.get("title") or {}).get("rendered", ""))
                print(f"      {record.get('date','')[:10]}  {title[:70]}")
    return 0


def _structure() -> int:
    print(f"robots_allows({LISTING}) -> {robots_allows(LISTING)}")

    # ---- 1. WordPress REST API
    print("\n" + "=" * 70 + "\nWORDPRESS REST API\n" + "=" * 70)
    for url in REST_PROBES:
        response = _try("probe", url)
        if response is None:
            continue
        try:
            data = response.json()
        except Exception:
            print("    (not JSON)")
            continue

        if url.endswith("/wp-json/"):
            routes = list((data.get("routes") or {}).keys())
            print(f"    {len(routes)} routes; interesting ones:")
            for route in routes:
                if INTERESTING.search(route):
                    print(f"      {route}")
        elif url.endswith("types"):
            print("    post types:")
            for key, value in (data or {}).items():
                name = value.get("name") if isinstance(value, dict) else ""
                rest = value.get("rest_base") if isinstance(value, dict) else ""
                flag = " <-- likely" if INTERESTING.search(f"{key} {name}") else ""
                print(f"      {key:<28} {name!r:<34} rest_base={rest!r}{flag}")
        elif isinstance(data, list):
            print(f"    {len(data)} posts; first titles + dates:")
            for post in data[:3]:
                title = (post.get("title") or {}).get("rendered", "")
                print(f"      {post.get('date')}  {title[:60]!r}")

    # ---- 2. sitemap
    print("\n" + "=" * 70 + "\nSITEMAP\n" + "=" * 70)
    response = _try("sitemap index", f"{ROOT}/sitemaps.xml")
    if response is not None:
        locs = re.findall(r"<loc>([^<]+)</loc>", response.text)
        print(f"    {len(locs)} entries")
        for loc in locs[:20]:
            mark = " <--" if INTERESTING.search(loc) else ""
            print(f"      {loc}{mark}")

    # ---- 3. the rendered page
    print("\n" + "=" * 70 + "\nLISTING PAGE\n" + "=" * 70)
    response = _try("listing", LISTING)
    if response is not None:
        tree = HTMLParser(response.text)

        pdfs = [
            a.attributes.get("href", "")
            for a in tree.css("a[href]")
            if ".pdf" in (a.attributes.get("href") or "").lower()
        ]
        print(f"\n    {len(pdfs)} PDF links; first few:")
        for href in pdfs[:8]:
            print(f"      {href}")

        print("\n    headings:")
        for node in tree.css("h1, h2, h3")[:12]:
            text = " ".join(node.text(separator=" ", strip=True).split())
            if text:
                print(f"      <{node.tag}> {text[:70]!r}")

        print("\n    repeated container classes (likely rows):")
        counts: dict[str, int] = {}
        for node in tree.css("div, li, article, tr"):
            cls = node.attributes.get("class") or ""
            if cls:
                counts[cls] = counts.get(cls, 0) + 1
        for cls, count in sorted(counts.items(), key=lambda kv: -kv[1])[:15]:
            if count > 2:
                print(f"      {count:>4}x  {cls[:70]}")

        print("\n    embedded JSON payloads (Next-style or WP data):")
        for marker in ("__NEXT_DATA__", "wp-json", "window.wp", "application/ld+json"):
            if marker in response.text:
                print(f"      found: {marker}")

        print("\n    pagination hints:")
        for node in tree.css("a[href]"):
            href = node.attributes.get("href") or ""
            if re.search(r"page[/=]\d+|paged=", href):
                print(f"      {href}")
                break
        else:
            print("      none found")

    return 0


if __name__ == "__main__":
    if "--acts" in sys.argv:
        raise SystemExit(_acts())
    if "--hunt" in sys.argv:
        raise SystemExit(_hunt())
    if "--decree" in sys.argv:
        raise SystemExit(_decree())
    if "--structure" in sys.argv:
        raise SystemExit(_structure())
    print(__doc__)
