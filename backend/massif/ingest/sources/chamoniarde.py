"""La Chamoniarde / Office de Haute Montagne — mountain conditions and hazards.

https://www.chamoniarde.com/actualites/conditions

What the mairie de Chamonix does not publish, this does. Server-rendered
(despite an earlier note to the contrary), bilingual French/English, with the
title and date in an h2 as "TITLE Posté le 11/08/2026 dans CATEGORY" and the
body in div.txtblc.

THE OHM CANNOT CLOSE ANYTHING. It is the local safety office, not the mairie:
institutional authority, trust 0.85 against Saint-Gervais's 1.00. Its language
is "déconseillé", "pas en conditions", "différer son projet" — advice, not an
arrêté. So it emits RESTRICTION, never CLOSURE, unless it is explicitly
reporting someone else's interdiction.

Why that distinction earns its keep, from the live data:

    Saint-Gervais (1.00): the Goûter route is open.
    OHM (0.85): "Réouverture « administrative » ... Cela ne signifie pas une
    disparition des risques… ! ... Différer son projet d'ascension à une autre
    période semble préférable !"

Both true. Legal authority decides open/closed, so Saint-Gervais wins the
status slot — and the OHM's warning is surfaced alongside as an advisory
rather than buried, because a technically accurate "open" that reads as
clearance is the failure this project exists to avoid.

SCOPE. Most of these articles are conditions reports, which are v2. We fetch
and store all of them from day one — documents are immutable and extraction is
a separate stage — but extract only access restrictions now. When v2 arrives,
reextract.py mines the accumulated archive instead of starting cold.
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from datetime import UTC, datetime, timedelta

from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.ingest.base import (
    ExtractedStatement,
    Scraper,
    fetch,
    robots_allows,
    store_document,
)
from massif.ingest.fr_features import features_mentioned, norm

ROOT = "https://www.chamoniarde.com"
PAGES = [
    f"{ROOT}/en/mountain-topics/route-reports",
    f"{ROOT}/",
]

# Framework fingerprints, cheapest identification first.
FRAMEWORKS = {
    "WordPress REST": "wp-json",
    "Next.js (RSC)": "__next_f",
    "Next.js (pages)": "__NEXT_DATA__",
    "Nuxt": "__NUXT__",
    "Drupal": "drupalSettings",
    "GraphQL": "graphql",
    "JSON-LD": "application/ld+json",
    "Algolia": "algolia",
}

# Anything that smells like an endpoint, harvested from HTML and inline JS.
ENDPOINT = re.compile(
    r"""["'`](/(?:api|ajax|rest|wp-json|graphql|_next/data)[^"'`\s]{0,120})["'`]"""
)
ABSOLUTE = re.compile(
    r"""["'`](https?://[^"'`\s]{0,160}(?:/api/|/ajax|/rest/|wp-json|graphql)[^"'`\s]{0,80})["'`]"""
)


def _get(url: str):
    try:
        response = fetch(url)
    except Exception as exc:
        print(f"    FAILED {type(exc).__name__}: {exc}")
        return None
    print(f"    HTTP {response.status_code}  "
          f"{response.headers.get('content-type','')}  {len(response.content)} bytes")
    return response


DATEISH = re.compile(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b|\b\d{1,2}\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)", re.I)
ROUTEISH = re.compile(r"cosmiques|midi|tacul|maudit|goutter|go[uû]ter|verte|drus|jorasses|tour ronde|argenti|talefre|couvercle|charpoua|glacier|couloir|ar[êe]te|bergschrund|rimaye", re.I)


def _content() -> int:
    """Is the conditions content in the HTML, or does it arrive over XHR?

    63k chars of visible text says the page is not an empty shell, so the
    first question is not "where is the endpoint" but "do we even need one".
    """
    # find the French sections from the nav rather than guessing URLs
    print("=" * 70 + "\nCANDIDATE SECTIONS\n" + "=" * 70)
    response = _get(f"{ROOT}/")
    if response is None:
        return 1
    tree = HTMLParser(response.text)

    wanted = re.compile(r"condition|course|fil.info|refuge|neige|montagne", re.I)
    sections: dict[str, str] = {}
    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        text = " ".join(node.text(separator=" ", strip=True).split())
        if not text or not wanted.search(text):
            continue
        url = urljoin(ROOT, href)
        if ROOT in url:
            sections.setdefault(url, text)
    for url, text in list(sections.items())[:20]:
        print(f"  {text[:44]!r:<48} {url}")

    # then look hard at each one for actual report content
    print("\n" + "=" * 70 + "\nDOES THE HTML CARRY THE REPORTS?\n" + "=" * 70)
    for url in list(sections)[:6]:
        print(f"\n--- {url}")
        response = _get(url)
        if response is None:
            continue
        tree = HTMLParser(response.text)
        text = " ".join(tree.text(separator=" ", strip=True).split())

        dates = DATEISH.findall(text)
        routes = set(m.group(0).lower() for m in ROUTEISH.finditer(text))
        print(f"    {len(dates)} date-shaped strings, {len(routes)} route words")
        if routes:
            print(f"    routes seen: {sorted(routes)[:12]}")

        # repeated containers are where the list items live
        counts: dict[str, int] = {}
        for node in tree.css("div, li, article"):
            cls = node.attributes.get("class") or ""
            if cls:
                counts[cls] = counts.get(cls, 0) + 1
        repeated = [(c, n) for c, n in counts.items() if n >= 4]
        repeated.sort(key=lambda kv: -kv[1])
        print("    repeated containers:")
        for cls, count in repeated[:8]:
            print(f"      {count:>4}x  {cls[:64]}")

        if dates and routes:
            print("    -> content IS server-rendered; no XHR hunt needed")
        elif not dates and not routes:
            print("    -> shell only; the payload arrives over XHR")

    print("\n" + "=" * 70 + "\nJSON-LD BLOCKS\n" + "=" * 70)
    response = _get(f"{ROOT}/en/mountain-topics/route-reports")
    if response is not None:
        for block in HTMLParser(response.text).css('script[type="application/ld+json"]'):
            raw = (block.text() or "").strip()
            try:
                data = json.loads(raw)
            except Exception:
                print(f"  (unparseable, {len(raw)} chars)")
                continue
            print(f"  {json.dumps(data)[:400]}")
    return 0


CONDITIONS = f"{ROOT}/actualites/conditions"
ARCHIVE = f"{ROOT}/montagne/conditions-montagne-archive"


def _list() -> int:
    """Shape of the conditions listing: how many items, where the links and
    dates live, and what one article is built from."""
    for label, url in (("LISTING", CONDITIONS), ("ARCHIVE", ARCHIVE)):
        print("=" * 70 + f"\n{label}: {url}\n" + "=" * 70)
        response = _get(url)
        if response is None:
            continue
        tree = HTMLParser(response.text)

        print("\n  one .articont, structure:")
        first = tree.css_first(".articont")
        if first is not None:
            for child in first.iter():
                text = " ".join(child.text(separator=" ", strip=True).split())
                print(f"    <{child.tag} class={child.attributes.get('class')!r}> {text[:70]!r}")
                for sub in child.iter():
                    stext = " ".join(sub.text(separator=" ", strip=True).split())
                    print(f"      <{sub.tag} class={sub.attributes.get('class')!r}> {stext[:60]!r}")

        print("\n  every article link + nearby date:")
        seen = set()
        for node in tree.css("a[href]"):
            href = node.attributes.get("href") or ""
            if "/actualites/" not in href or href.rstrip("/").endswith("conditions"):
                continue
            full = urljoin(ROOT, href)
            if full in seen:
                continue
            seen.add(full)
            text = " ".join(node.text(separator=" ", strip=True).split())
            date = DATEISH.search(text)
            print(f"    {(date.group(0) if date else '—'):<14} {text[:60]!r}")
            print(f"       {full}")
        print(f"\n  {len(seen)} distinct articles\n")

    print("=" * 70 + "\nONE ARTICLE IN FULL\n" + "=" * 70)
    url = f"{ROOT}/actualites/general/fortes-chaleurs-en-haute-montagne"
    response = _get(url)
    if response is not None:
        tree = HTMLParser(response.text)
        heading = tree.css_first("h1")
        print(f"  h1: {heading.text(strip=True) if heading else None!r}")
        for selector in (".artitext", ".articontexte", "article", ".tag", "time", "[class*='date']"):
            nodes = tree.css(selector)
            if not nodes:
                continue
            print(f"\n  {selector} -> {len(nodes)} nodes")
            for node in nodes[:2]:
                text = " ".join(node.text(separator=" ", strip=True).split())
                print(f"    {text[:400]!r}")
    return 0


def _article() -> int:
    """Find the body container by looking for the text, not by guessing.

    .articontexte turned out to be the related-article boxes and h1 is absent,
    so locate a phrase we know is in the body and walk up from it.
    """
    urls = [
        f"{ROOT}/actualites/general/fortes-chaleurs-en-haute-montagne",
        f"{ROOT}/actualites/a-la-une/reouverture-des-refuges-de-tete-rousse-et-du-gouter",
    ]
    needles = ("rimaye", "goutter", "goûter", "refuge", "chaleur", "conditions")

    for url in urls:
        print("=" * 70 + f"\n{url}\n" + "=" * 70)
        response = _get(url)
        if response is None:
            continue
        tree = HTMLParser(response.text)

        # every heading tag, since h1 was absent
        print("\n  headings of any level:")
        for node in tree.css("h1, h2, h3, h4, h5"):
            text = " ".join(node.text(separator=" ", strip=True).split())
            if text and len(text) < 120:
                print(f"    <{node.tag} class={node.attributes.get('class')!r}> {text[:80]!r}")

        # the deepest element that still holds a lot of prose is the body
        print("\n  text-heavy leaf-ish containers:")
        best = []
        for node in tree.css("div, section, article, p"):
            text = " ".join(node.text(separator=" ", strip=True).split())
            if len(text) < 200:
                continue
            child_divs = len(node.css("div"))
            best.append((len(text), child_divs, node))
        best.sort(key=lambda t: (t[1], -t[0]))
        for length, kids, node in best[:6]:
            cls = node.attributes.get("class")
            text = " ".join(node.text(separator=" ", strip=True).split())
            print(f"    <{node.tag} class={cls!r}> {length} chars, {kids} child divs")
            print(f"      {text[:220]!r}")

        # where do our needles actually sit?
        print("\n  elements containing body vocabulary:")
        shown = 0
        for node in tree.css("p, div, span"):
            text = " ".join(node.text(separator=" ", strip=True).split())
            if not (40 < len(text) < 700):
                continue
            low = text.lower()
            if not any(n in low for n in needles):
                continue
            print(f"    <{node.tag} class={node.attributes.get('class')!r}>")
            print(f"      {text[:200]!r}")
            shown += 1
            if shown >= 6:
                break

        print("\n  date-ish strings on the page:")
        flat = " ".join(tree.text(separator=" ", strip=True).split())
        print(f"    {DATEISH.findall(flat)[:8]}")
        idx = flat.lower().find("posté")
        if idx >= 0:
            print(f"    'Posté' context: {flat[idx:idx+60]!r}")
        print()
    return 0


def _probe() -> int:
    print(f"robots_allows({PAGES[0]}) -> {robots_allows(PAGES[0])}\n")

    candidates: set[str] = set()

    for page in PAGES:
        print("=" * 70)
        print(page)
        print("=" * 70)
        response = _get(page)
        if response is None:
            continue
        html = response.text

        print("\n  frameworks detected:")
        found_any = False
        for label, marker in FRAMEWORKS.items():
            if marker in html:
                print(f"    {label}  (marker: {marker})")
                found_any = True
        if not found_any:
            print("    none — likely plain server-rendered HTML")

        print("\n  script sources:")
        tree = HTMLParser(html)
        for node in tree.css("script[src]")[:12]:
            print(f"    {node.attributes.get('src')}")

        print("\n  endpoint-shaped strings in the markup:")
        hits = set(ENDPOINT.findall(html)) | set(ABSOLUTE.findall(html))
        for hit in sorted(hits)[:25]:
            print(f"    {hit}")
            candidates.add(urljoin(ROOT, hit))
        if not hits:
            print("    none found inline — they may live in a bundled JS file")

        # if the content IS server-rendered, say so and save the trouble
        text = " ".join(tree.text(separator=" ", strip=True).split())
        print(f"\n  visible text: {len(text)} chars")
        for probe_word in ("conditions", "course", "neige", "rocher", "glacier"):
            if probe_word in text.lower():
                index = text.lower().find(probe_word)
                print(f"    contains {probe_word!r}: ...{text[max(0,index-60):index+90]}...")
                break
        else:
            print("    no condition vocabulary in the rendered HTML "
                  "— confirms client-side rendering")
        print()

    if candidates:
        print("=" * 70 + "\nPROBING DISCOVERED ENDPOINTS\n" + "=" * 70)
        for url in sorted(candidates)[:10]:
            print(f"\n  {url}")
            response = _get(url)
            if response is None:
                continue
            try:
                data = response.json()
            except Exception:
                print("    (not JSON)")
                continue
            if isinstance(data, dict):
                print(f"    keys: {list(data)[:15]}")
            elif isinstance(data, list):
                print(f"    list of {len(data)}")
                if data:
                    print(f"    first: {json.dumps(data[0])[:300]}")

    print("\nIf nothing above is a data endpoint, the next step is the browser's")
    print("network tab on the route-reports page: watch what the page requests")
    print("when the category filters are used. That request is the source.")
    return 0


# ---------------------------------------------------------------- scraper ---

LISTING = f"{ROOT}/actualites/conditions"

# How long an OHM advisory is treated as current. The articles state when they
# were posted and never when they expire, so this window is OURS, not theirs —
# hence window_inferred in the payload. Unbounded validity is not an option:
# recompute_feature treats null bounds as permanently current, which would
# leave a heatwave advisory live in February.
ADVISORY_TTL_DAYS = 21

POSTED = re.compile(r"post[ée]\s+le\s+(\d{1,2})/(\d{1,2})/(\d{4})", re.I)

# Advisory language. The OHM says a route is not in condition; it never closes
# one. CLOSURE is not in this source's vocabulary at all: an earlier version
# emitted it whenever an article mentioned an arrêté, which turned weekly
# conditions digests into closures for every route they named. If a route is
# legally shut, the mairie is the authority and we take it from there.
NOT_IN_CONDITION = re.compile(
    r"pas en condition|hors condition|"
    r"deconseill|impraticable|differer (son|votre) projet|"
    r"tres degrade|fortement degrade|non recommand|a proscrire|"
    r"impossible|infaisable|tres delicat|purge|chute de pierre",
)
REOPENING = re.compile(r"reouvertur|rouvre|reouvert|de nouveau accessible")

# Sentences, roughly. Good enough: the point is to stop one verdict in a
# 1600-character digest from being applied to every route the digest names.
SENTENCE = re.compile(r"[^.!?\n•;]+[.!?\n•;]?")


def _verdict(sentence: str):
    """(type, status, severity) for ONE sentence, or None."""
    if NOT_IN_CONDITION.search(sentence):
        return StatementType.RESTRICTION, StatusValue.RESTRICTED, 2
    if REOPENING.search(sentence):
        return StatementType.OPENING, StatusValue.OPEN, 0
    return None


def parse_article(html: str) -> dict | None:
    """title, posted date, body. None when the page is not an article."""
    tree = HTMLParser(html)

    heading = None
    for node in tree.css("h2"):
        text = " ".join(node.text(separator=" ", strip=True).split())
        if POSTED.search(text):
            heading = text
            break
    if heading is None:
        return None

    match = POSTED.search(heading)
    day, month, year = (int(g) for g in match.groups())
    title = heading[: match.start()].strip(" -–—")

    body_node = tree.css_first("div.txtblc")
    body = (
        " ".join(body_node.text(separator=" ", strip=True).split())
        if body_node
        else ""
    )
    return {
        "title": title,
        "posted": datetime(year, month, day, tzinfo=UTC),
        "body": body,
    }


def statements_for(
    article: dict, url: str, observed_at: datetime
) -> list[ExtractedStatement]:
    """One verdict per SENTENCE, not per article.

    These articles are weekly digests covering the whole massif. Reading a
    verdict from the article and applying it to every feature named anywhere
    in it produced restrictions on the Grand Couloir, the Cosmiques, the
    Vallée Blanche and the Dent du Géant from a single digest — and marked the
    Tête Rousse and Goûter refuges "restricted" in the very article announcing
    they had reopened, because advisory language about other routes appeared
    further down.

    A feature is only spoken about by the sentence that names it.
    """
    posted = article["posted"]
    valid_to = posted + timedelta(days=ADVISORY_TTL_DAYS)

    # title first: it carries the headline act and scopes what it names
    chunks = [article["title"], *(m.group(0) for m in SENTENCE.finditer(article["body"]))]

    out: list[ExtractedStatement] = []
    # (slug, verdict) rather than slug alone. An article can legitimately say
    # two different things about one feature — the refuges reopen AND the
    # conditions are poor — and collapsing to the first sentence silently
    # discards the warning. Both are emitted; the advisory surfaces alongside
    # the opening rather than replacing or being replaced by it.
    claimed: set[tuple[str, str]] = set()

    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 12:
            continue
        flat = norm(chunk)
        verdict = _verdict(flat)
        if verdict is None:
            continue
        slugs = features_mentioned(chunk)
        if not slugs:
            continue

        statement_type, status, severity = verdict
        for slug in slugs:
            key = (slug, statement_type.value)
            if key in claimed:
                continue
            claimed.add(key)

            out.append(
                ExtractedStatement(
                    feature_mention=slug,
                    feature_slug=slug,
                    statement_type=statement_type,
                    status=status,
                    severity=severity,
                    observed_at=posted,
                    valid_from=posted,
                    valid_to=valid_to,
                    summary_en=chunk[:300],
                    original_text=chunk[:2000],
                    original_language="fr",
                    payload={
                        "url": url,
                        "article_title": article["title"][:200],
                        "posted": posted.date().isoformat(),
                        "advisory": statement_type is StatementType.RESTRICTION,
                        # The article says when it was posted, never when it
                        # expires. This window is ours; say so rather than
                        # implying the OHM set it.
                        "window_inferred": True,
                        "window_days": ADVISORY_TTL_DAYS,
                        "authority": (
                            "institutional — the OHM advises, it cannot close"
                        ),
                    },
                    extraction_method=ExtractionMethod.RULE,
                    extraction_confidence=0.8,
                    context=f"OHM notice: {url}",
                )
            )
    return out


def article_links(html: str) -> list[str]:
    tree = HTMLParser(html)
    out: list[str] = []
    seen: set[str] = set()
    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        if "/actualites/" not in href:
            continue
        url = urljoin(ROOT, href).split("?")[0].split("#")[0]
        # section indexes, not articles
        if url.rstrip("/").count("/") <= 4 or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


class ChamoniardeScraper(Scraper):
    slug = "chamoniarde-ohm"

    def collect(
        self, session, source
    ):
        listing = fetch(LISTING)
        store_document(session, source, LISTING, listing)

        observed_at = datetime.now(UTC)
        results = []

        for url in article_links(listing.text)[:30]:
            try:
                response = fetch(url)
            except Exception as exc:
                print(f"  {url} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue

            article = parse_article(response.text)
            document, is_new = store_document(
                session, source, url, response,
                published_at=article["posted"] if article else None,
            )
            if not is_new or article is None:
                continue
            results.append((document, statements_for(article, url, observed_at)))

        return results


def _dump() -> int:
    """Parse the live feed without touching the database."""
    listing = fetch(LISTING)
    links = article_links(listing.text)
    print(f"{len(links)} articles\n")

    observed_at = datetime.now(UTC)
    for url in links[:30]:
        response = fetch(url)
        article = parse_article(response.text)
        if article is None:
            print(f"  ----   {url.rsplit('/', 1)[-1][:60]}  (not an article)")
            continue
        statements = statements_for(article, url, observed_at)
        if not statements:
            slugs = features_mentioned(f"{article['title']} {article['body']}")
            why = "no feature named" if not slugs else "no advisory language"
            print(f"  ----   {article['posted']:%Y-%m-%d}  {article['title'][:52]:<54} ({why})")
            continue
        for statement in statements:
            print(
                f"  HIT    {statement.payload['posted']}  "
                f"{statement.feature_slug:<22} {statement.statement_type.value:<12}"
                f" sev{statement.severity}"
            )
            print(f"         {statement.summary_en[:76]}")
    return 0


if __name__ == "__main__":
    if "--dump" in sys.argv:
        raise SystemExit(_dump())
    if "--article" in sys.argv:
        raise SystemExit(_article())
    if "--list" in sys.argv:
        raise SystemExit(_list())
    if "--content" in sys.argv:
        raise SystemExit(_content())
    if "--probe" in sys.argv:
        raise SystemExit(_probe())
    print(__doc__)
