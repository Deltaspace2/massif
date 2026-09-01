"""Scraper registry. A source without a registered scraper is simply skipped —
that is how seeds/sources.yaml can list identified-but-not-yet-built sources
without breaking the run."""

from __future__ import annotations

from massif.ingest.base import Scraper
from massif.ingest.sources.camptocamp_outings import CamptocampOutingsScraper
from massif.ingest.sources.ffcam import FfcamScraper
from massif.ingest.sources.mbnr_live import MbnrLiveScraper
from massif.ingest.sources.mbnr_openings import MbnrOpeningsScraper
from massif.ingest.sources.refuges_info import RefugesInfoScraper
from massif.ingest.sources.saint_gervais import SaintGervaisScraper
from massif.ingest.sources.tramway_mont_blanc import TramwayMontBlancScraper

SCRAPERS: dict[str, type[Scraper]] = {
    CamptocampOutingsScraper.slug: CamptocampOutingsScraper,
    FfcamScraper.slug: FfcamScraper,
    MbnrLiveScraper.slug: MbnrLiveScraper,
    MbnrOpeningsScraper.slug: MbnrOpeningsScraper,
    RefugesInfoScraper.slug: RefugesInfoScraper,
    SaintGervaisScraper.slug: SaintGervaisScraper,
    TramwayMontBlancScraper.slug: TramwayMontBlancScraper,
}
