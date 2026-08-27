"""Mairie de Saint-Gervais-les-Bains — municipal notices.

https://www.saintgervais.com/mairie/actualites/

The most consequential publisher on this project's list. Saint-Gervais
regulates the Goûter route — the normal way up Mont Blanc — and its notices
are what actually close it:

    "Fermeture temporaire de la voie normale du Mont-Blanc du 26 au 29 mai 2026"
    "Réouverture des refuges de Tête Rousse et du Goûter le 26/08/26"

Recon findings that shaped this:

* Notices are plain HTML articles at /mairie/actualites/<slug>/, NOT the PDFs
  originally assumed. No PDF extraction needed.
* Dates live in the title, in forms fr_dates.py can read by rule. No LLM
  needed to know when something is shut.
* They sit undifferentiated in the general municipal feed, next to
  "L'Ambassade d'Inde en visite à Saint-Gervais". Something must decide what
  is a mountain notice — here, a keyword gate on the listing title, applied
  BEFORE fetching, so we do not pull articles we have no use for.
* No arrêté number, and no *visible* publication date on the page — but the
  JSON-LD carries `datePublished`, which is what `observed_at` uses. There is
  no `article:published_time` meta tag: the SEO plugin sets og:type to
  "website", not "article", so it never emits one.
* A reopening announced "le 26/08/26" names a start, not a one-day window.
  Read literally it went OPEN for a day and lapsed, letting an older undated
  closure become the newest statement standing.

One notice routinely names several features ("les refuges de Tête Rousse et
du Goûter"), so this emits one statement per feature mentioned.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser
from sqlalchemy.orm import Session

from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.ingest.base import ExtractedStatement, Scraper, fetch, store_document
from massif.ingest.fr_dates import parse_range
from massif.ingest.fr_features import features_mentioned, norm
from massif.models import Document, Source
from massif.status import STALE_DAYS

LISTING = "https://www.saintgervais.com/mairie/actualites/"
ARTICLE_PATH = "/mairie/actualites/"

# The mairie's WordPress SEO plugin sets og:type to "website", not "article",
# so it never emits <meta property="article:published_time">. There is no
# meta tag to read. It does emit a WebPage entry in JSON-LD with
# datePublished, in resort-local time with no offset — the only honest
# signal of how old a notice actually is.
RESORT_TZ = ZoneInfo("Europe/Paris")

# How long a reopening announced for a single day keeps speaking. Borrowed
# from status.STALE_DAYS so there is one answer to "how long does an opening
# hold", not two that can drift apart.
STALE_DAYS_OPENING = STALE_DAYS["opening"]

# Fetch at most this many articles per run, newest first. Logged when hit —
# a silent cap reads as "we covered everything" when we did not.
MAX_ARTICLES = 25

# Applied to the listing title before fetching. Cheap, and keeps us off pages
# that are none of our business.
GATE = re.compile(
    r"voie normale|gouter|tete rousse|refuge|fermeture|reouverture|"
    r"interdic|couloir|itineraire|acces|arrete|tramway|nid d'aigle|"
    r"telepherique|montagne|alpinis|mont-blanc|mont blanc",
    re.I,
)

# Feature recognition is shared with the other French sources — see
# massif/ingest/fr_features.py. Kept re-exported here so this module's public
# surface (and its tests) are unchanged.

OPENING_WORDS = re.compile(
    r"reouvert|reouverture|rouvre|levee de l'interdiction|"
    r"levee de l'arrete|retabli|de nouveau accessible|reprise"
)
CLOSURE_WORDS = re.compile(
    r"fermeture|fermes?\b|interdiction|interdit|interdite|suspendu|"
    r"inaccessible|non accessible|demontage"
)




def classify(title: str, body: str = "") -> tuple[StatementType, StatusValue, int] | None:
    """Decide from the TITLE ALONE, on accent-stripped text.

    Two bugs live here, both found against real notices:

    1. Accents. The keyword is "reouverture"; the title says "Réouverture".
       Matching raw text missed it, fell through to the closure words in the
       body, and published a REOPENING as a CLOSURE — on the morning the
       Goûter refuges actually reopened.

    2. Body text. "Situation ubuesque au refuge du Goûter" is the mayor
       complaining about overcrowding; its body mentions closures and the
       article became three closure statements. Municipal notices lead with
       the act in the title, so the body gets no vote.

    Where a title contains both senses, the earlier one wins — French notices
    are written act-first ("Réouverture ... après la fermeture du ...").
    """
    flat = norm(title)
    if not flat:
        return None

    opening = OPENING_WORDS.search(flat)
    closure = CLOSURE_WORDS.search(flat)

    if opening and closure:
        if opening.start() < closure.start():
            return StatementType.OPENING, StatusValue.OPEN, 0
        return StatementType.CLOSURE, StatusValue.CLOSED, 2
    if opening:
        return StatementType.OPENING, StatusValue.OPEN, 0
    if closure:
        return StatementType.CLOSURE, StatusValue.CLOSED, 2
    return None


def article_links(html: str, base: str) -> list[tuple[str, str]]:
    """(url, link text) for each article on the listing, deduped, order kept."""
    tree = HTMLParser(html)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        if ARTICLE_PATH not in href:
            continue
        url = urljoin(base, href).split("?")[0].split("#")[0]
        if url.rstrip("/").endswith("actualites") or url in seen:
            continue
        seen.add(url)
        out.append((url, " ".join(node.text(separator=" ", strip=True).split())))
    return out


def article_text(html: str) -> tuple[str, str]:
    """(title, body). Title from the h1; body from the main content if we can
    find it, else the whole document."""
    tree = HTMLParser(html)
    heading = tree.css_first("h1")
    title = " ".join(heading.text(separator=" ", strip=True).split()) if heading else ""

    container = (
        tree.css_first("article")
        or tree.css_first("main")
        or tree.css_first("[class*='content']")
        or tree.body
    )
    body = (
        " ".join(container.text(separator=" ", strip=True).split())
        if container
        else ""
    )
    return title, body


def extract_published_at(html: str) -> datetime | None:
    """When the mairie actually published this notice, from JSON-LD.

    Without this, `observed_at` defaults to scrape time — so a months-old
    closure looks freshly observed the moment we first read it, and never
    ages out. Worse, a closure and a same-run reopening then share the same
    observed_at, and `recompute_feature` breaks that tie by severity, so the
    closure (severity 2) beats the reopening (severity 0) regardless of
    which one actually came later.
    """
    for match in re.finditer(
        r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S
    ):
        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            continue
        graph = data.get("@graph", [data]) if isinstance(data, dict) else data
        for item in graph if isinstance(graph, list) else [graph]:
            if not isinstance(item, dict):
                continue
            raw = item.get("datePublished")
            if not raw:
                continue
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=RESORT_TZ)
            return parsed.astimezone(UTC)
    return None


def statements_for(
    title: str, body: str, url: str, observed_at: datetime
) -> list[ExtractedStatement]:
    verdict = classify(title, body)
    if verdict is None:
        return []
    statement_type, status, severity = verdict

    slugs = features_mentioned(f"{title} {body}")
    if not slugs:
        return []

    dates = parse_range(title) or parse_range(body)

    # "Réouverture ... le 26/08/26" names the day the thing opens, not the only
    # day it is open. Taken literally it asserted OPEN for 24 hours and then
    # lapsed, leaving an older undated closure as the newest thing still in
    # recompute's window — the Goûter route read shut the day after the mairie
    # reopened it. Only widen a point date: "du 26 au 29 mai" gave an explicit
    # end and means it.
    if (
        statement_type is StatementType.OPENING
        and dates is not None
        and dates.rule.startswith("single")
        and dates.start is not None
    ):
        dates = replace(
            dates, end=dates.start + timedelta(days=STALE_DAYS_OPENING)
        )

    # An undated notice is real but unbounded, and recompute_feature treats
    # unbounded validity as CURRENTLY valid — so a closure from a past season
    # would sit on the map as live forever. We keep the notice for its text
    # and its link, but it does not get to claim a present-tense status.
    if dates is None or not dates.bounded:
        status = StatusValue.UNKNOWN
        severity = 0

    out: list[ExtractedStatement] = []
    for slug in slugs:
        out.append(
            ExtractedStatement(
                feature_mention=slug,
                feature_slug=slug,
                statement_type=statement_type,
                status=status,
                severity=severity,
                observed_at=observed_at,
                valid_from=dates.start if dates else None,
                valid_to=dates.end if dates else None,
                summary_en=title,
                original_text=(title + " — " + body)[:2000],
                original_language="fr",
                payload={
                    "url": url,
                    "date_rule": dates.rule if dates else None,
                    "dates_found": bool(dates),
                    # An undated notice is real but open-ended: we know a thing
                    # was closed, not until when. Surfacing that beats
                    # inventing an end date.
                    "open_ended": not (dates and dates.bounded),
                    # why this notice is not asserting open/closed
                    "undated_reason": (
                        None if (dates and dates.bounded)
                        else "no bounded date range found in the notice"
                    ),
                },
                extraction_method=ExtractionMethod.RULE,
                extraction_confidence=0.9 if dates else 0.6,
                context=f"municipal notice: {url}",
            )
        )
    return out


def extract_page(html: str, url: str, fallback_observed_at: datetime) -> list[ExtractedStatement]:
    """Everything downstream of having the HTML: the extract half, sharable
    between a live fetch and a re-extraction from a stored document."""
    published = extract_published_at(html)
    title, body = article_text(html)
    return statements_for(title, body, url, published or fallback_observed_at)


class SaintGervaisScraper(Scraper):
    slug = "mairie-saint-gervais"

    def extract_stored(self, document: Document) -> list[ExtractedStatement]:
        # The listing page is stored for provenance but carries no notice of
        # its own; extracting it would double-count every headline it links.
        if not document.raw_text or document.url.rstrip("/").endswith("actualites"):
            return []
        # published_at was parsed at store time; fetched_at is the honest
        # fallback for a document stored before that existed. Never now().
        return extract_page(
            document.raw_text,
            document.url,
            document.published_at or document.fetched_at,
        )

    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        listing = fetch(LISTING)
        store_document(session, source, LISTING, listing)

        links = article_links(listing.text, LISTING)
        relevant = [(u, t) for u, t in links if GATE.search(norm(t))]
        skipped = len(links) - len(relevant)

        capped = relevant[:MAX_ARTICLES]
        if len(relevant) > MAX_ARTICLES:
            print(
                f"  capped at {MAX_ARTICLES} of {len(relevant)} relevant articles",
                file=sys.stderr,
            )
        if skipped:
            print(f"  gate skipped {skipped} non-mountain articles", file=sys.stderr)

        observed_at = datetime.now(UTC)
        results: list[tuple[Document, list[ExtractedStatement]]] = []

        for url, _ in capped:
            try:
                response = fetch(url)
            except Exception as exc:
                print(f"  {url} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue

            published = extract_published_at(response.text)
            if published is None:
                print(f"  {url}: no datePublished, falling back to scrape time", file=sys.stderr)

            document, is_new = store_document(
                session, source, url, response, published_at=published
            )
            if not is_new:
                continue
            # Same extraction path re-extraction uses, so the two cannot drift.
            results.append((document, extract_page(response.text, url, observed_at)))

        return results


def _dump() -> int:
    """Parse the live feed without touching the database."""
    listing = fetch(LISTING)
    links = article_links(listing.text, LISTING)
    print(f"{len(links)} articles on the listing\n")

    observed_at = datetime.now(UTC)
    for url, text in links:
        gated = bool(GATE.search(norm(text)))
        if not gated:
            print(f"  skip   {text[:70]}")
            continue
        response = fetch(url)
        published = extract_published_at(response.text)
        title, body = article_text(response.text)
        statements = statements_for(title, body, url, published or observed_at)
        if not statements:
            print(f"  none   {title[:70]}")
            continue
        published_str = f"{published:%Y-%m-%d}" if published else "UNKNOWN (fallback to now)"
        for statement in statements:
            window = (
                f"{statement.valid_from:%Y-%m-%d} → {statement.valid_to:%Y-%m-%d}"
                if statement.valid_from and statement.valid_to
                else "open-ended"
            )
            print(
                f"  HIT    {statement.feature_slug:<20} "
                f"{statement.statement_type.value:<8} {window}   published {published_str}"
            )
            print(f"         {title[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_dump())
