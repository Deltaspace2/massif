"""Scraper registry. A source without a registered scraper is simply skipped —
that is how seeds/sources.yaml can list identified-but-not-yet-built sources
without breaking the run."""

from __future__ import annotations

from massif.ingest.base import Scraper
from massif.ingest.sources.mbnr_live import MbnrLiveScraper
from massif.ingest.sources.mbnr_openings import MbnrOpeningsScraper
from massif.ingest.sources.saint_gervais import SaintGervaisScraper

SCRAPERS: dict[str, type[Scraper]] = {
    MbnrLiveScraper.slug: MbnrLiveScraper,
    MbnrOpeningsScraper.slug: MbnrOpeningsScraper,
    SaintGervaisScraper.slug: SaintGervaisScraper,
}
