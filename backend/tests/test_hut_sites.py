"""What a hut's own website is allowed to say about the hut.

The site-of fallback exists because a one-hut page calling itself "la cabane"
means that hut. The danger is the same rule applied to everything else on the
page, and Saleinaz is the case that showed it: three notices, only one of them
about the building.
"""

import re

from massif.ingest.fr_dates import _norm
from massif.ingest.sources.hut_sites import NAMES_AN_APPROACH, hut_sites


def approach(mention: str) -> bool:
    return bool(NAMES_AN_APPROACH.search(_norm(mention)))


def test_a_notice_about_the_way_there_is_not_about_the_hut():
    """Cabane de Saleinaz publishes "l'accès à la cabane depuis la prise d'eau
    de Saleinaz est toujours fermé" — and the very next sentence says the hut
    is still reachable from La Fouly. Filed on the hut as a closure, accepting
    it would have said the hut was shut on the strength of a page saying it is
    open."""
    assert approach("l'accès à la cabane depuis la prise d'eau de Saleinaz")
    assert approach("le sentier du col des Plines")
    assert approach("l'itinéraire normal")


def test_the_hut_itself_still_falls_back():
    """The fallback has to keep working for what it is for: a one-hut page
    referring to its own hut in the generic."""
    for mention in (
        "la cabane",
        "Le Refuge",
        "le refuge d'hiver",
        "Elle",
        "La cabane de Saleinaz",
        "Refuge",
    ):
        assert not approach(mention), mention


def test_the_words_are_matched_whole():
    """ "accessible" is not "accès" — a hut saying it is accessible is talking
    about itself, and a substring match would refuse that too."""
    assert not approach("la cabane reste accessible")
    assert not approach("cheminée")


def test_every_seeded_site_is_a_url():
    sites = hut_sites()
    assert sites
    for slug, url in sites.items():
        assert re.match(r"^https?://", url), f"{slug} has no scheme"
        assert slug == slug.lower().strip()


# ------------------------------------------------ the guard, where it runs


class _Resolver:
    def __init__(self, match=None):
        self.match = match
        self.queued = []

    def resolve(self, _m):
        return self.match, []

    def queue_unresolved(self, mention, _c, **kw):
        self.queued.append((mention, kw.get("context")))


class _Item:
    def __init__(self, mention):
        self.feature_mention = mention
        self.original_text = "l'accès est fermé"
        self.payload = {"site_of": "cabane-de-saleinaz"}
        self.feature_slug = None


class _Src:
    id = "s"


class _Doc:
    id = "d"


def test_an_approach_is_refused_even_when_it_resolves_to_the_hut():
    """The guard has to run BEFORE resolution, not only in the fallback.

    "l'accès à la cabane depuis la prise d'eau de Saleinaz" carries the hut's
    own name, so the resolver matches it happily and the fallback never runs —
    which is exactly how a closure of the APPROACH was filed on the hut. A
    mutant that disabled this passed every test until this one existed.
    """
    from massif.ingest.sources.hut_sites import HutSiteScraper

    resolver = _Resolver()
    built = HutSiteScraper().resolve_and_build(
        None, _Src(), _Doc(), _Item("l'accès à la cabane depuis la prise d'eau"), resolver
    )
    assert built is None
    assert resolver.queued
    assert "approach" in resolver.queued[0][1]
