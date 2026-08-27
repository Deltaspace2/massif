"""Saint-Gervais notice parsing.

Every title below is verbatim from the live feed. This source regulates the
Goûter route, so an inverted verdict here is the difference between telling
someone Mont Blanc's normal route is open and telling them it is shut.
"""

from datetime import UTC, datetime

import pytest

from massif.enums import StatementType, StatusValue
from massif.models import Document
from massif.ingest.sources.saint_gervais import (
    GATE,
    SaintGervaisScraper,
    classify,
    extract_published_at,
    features_mentioned,
    norm,
    statements_for,
)

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)

REOPENING = "Accès au Mont-Blanc Réouverture des refuges de Tête Rousse et du Goûter le 26/08/26"
MAY_CLOSURE = "Fermeture temporaire de la voie normale du Mont-Blanc du 26 au 29 mai 2026"
OPINION = "Ascension du Mont-Blanc Situation ubuesque au refuge du Goûter"
DEMOLITION = (
    "Démontage de l'ancien refuge du Goûter et interdiction temporaire "
    "d'accès à la voie normale du Mont-Blanc"
)
TOWN_NEWS = "L'Ambassade d'Inde en visite à Saint-Gervais"


# ---------------------------------------------------------------- classify --

def test_accented_reouverture_is_an_opening():
    """The bug this exists for: 'Réouverture' did not match 'reouverture',
    so a reopening was published as a closure on the morning the refuges
    actually reopened."""
    verdict = classify(REOPENING, body="... après la fermeture de juillet ...")
    assert verdict is not None
    assert verdict[0] is StatementType.OPENING
    assert verdict[1] is StatusValue.OPEN


def test_closure_title_is_a_closure():
    assert classify(MAY_CLOSURE)[0] is StatementType.CLOSURE
    assert classify(MAY_CLOSURE)[1] is StatusValue.CLOSED


def test_interdiction_counts_as_closure():
    assert classify(DEMOLITION)[0] is StatementType.CLOSURE


def test_body_gets_no_vote():
    """An article ABOUT closures is not a closure. This opinion piece produced
    three false closure statements when the body was consulted."""
    assert classify(OPINION, body="les refuges sont fermés, interdiction totale") is None


def test_town_news_classifies_as_nothing():
    assert classify(TOWN_NEWS) is None


def test_earlier_word_wins_when_a_title_has_both():
    assert classify("Réouverture après la fermeture du 3 juin")[0] is StatementType.OPENING
    assert classify("Fermeture puis réouverture prévue")[0] is StatementType.CLOSURE


# ------------------------------------------------------- feature detection --

def test_one_notice_names_several_features():
    """'les refuges de Tête Rousse et du Goûter' is two huts, not one."""
    found = features_mentioned(REOPENING)
    assert "refuge-tete-rousse" in found
    assert "refuge-du-gouter" in found


def test_voie_normale_maps_to_the_gouter_route():
    assert "gouter-route" in features_mentioned(MAY_CLOSURE)


def test_bare_gouter_is_never_guessed():
    """'Goûter' alone is either the hut or the route. Guessing wrong closes
    the wrong thing, on the busiest route on the massif."""
    assert features_mentioned("Le Goûter en 2026") == []


def test_gouter_disambiguated_by_context():
    assert features_mentioned("le refuge du Goûter est complet") == ["refuge-du-gouter"]
    assert features_mentioned("la voie du Goûter est fermée") == ["gouter-route"]


def test_grand_couloir_recognised():
    assert features_mentioned("Traversée du Grand Couloir déconseillée") == [
        "grand-couloir"
    ]


# ------------------------------------------------------------------- gate ---

@pytest.mark.parametrize("title", [REOPENING, MAY_CLOSURE, DEMOLITION])
def test_gate_admits_mountain_notices(title):
    assert GATE.search(norm(title))


@pytest.mark.parametrize(
    "title",
    [TOWN_NEWS, "Exposition « Voyages » de Denise Kehl", "Fête nationale du 14 juillet"],
)
def test_gate_rejects_town_news(title):
    assert not GATE.search(norm(title))


# -------------------------------------------------------------- statements --

def test_dated_closure_asserts_a_status_and_window():
    statements = statements_for(MAY_CLOSURE, "", "http://x", NOW)
    assert len(statements) == 1
    statement = statements[0]
    assert statement.feature_slug == "gouter-route"
    assert statement.status is StatusValue.CLOSED
    assert statement.severity == 2
    assert statement.valid_from.date().isoformat() == "2026-05-26"
    assert statement.valid_to.date().isoformat() == "2026-05-29"
    assert statement.payload["open_ended"] is False


def test_undated_notice_does_not_claim_a_present_status():
    """recompute_feature treats unbounded validity as currently valid, so an
    undated closure from a past season would sit on the map as live forever."""
    statements = statements_for(
        "Fermeture des refuges de Tête Rousse et du Goûter", "", "http://x", NOW
    )
    assert statements
    for statement in statements:
        assert statement.status is StatusValue.UNKNOWN
        assert statement.severity == 0
        assert statement.payload["open_ended"] is True
        assert statement.payload["undated_reason"]


def test_reopening_emits_openings_for_both_huts():
    statements = statements_for(REOPENING, "", "http://x", NOW)
    slugs = {s.feature_slug for s in statements}
    assert {"refuge-tete-rousse", "refuge-du-gouter"} <= slugs
    for statement in statements:
        assert statement.statement_type is StatementType.OPENING


def test_opinion_piece_produces_nothing():
    assert statements_for(OPINION, "les refuges sont fermés", "http://x", NOW) == []


def test_every_statement_keeps_its_source_url():
    """Never present an aggregation as our own authority."""
    statements = statements_for(MAY_CLOSURE, "", "http://example/notice", NOW)
    assert all(s.payload["url"] == "http://example/notice" for s in statements)
    assert all(s.original_language == "fr" for s in statements)


# --------------------------------------------------------- published_at ----

JSON_LD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https:\\/\\/schema.org","@graph":[
  {"@type":"WebSite","url":"https:\\/\\/www.saintgervais.com"},
  {"@type":"WebPage","url":"https:\\/\\/www.saintgervais.com\\/x\\/",
   "datePublished":"2026-08-24 20:12:25","dateModified":"2026-08-24 20:12:25"}
]}
</script>
</head><body></body></html>
"""


def test_extract_published_at_reads_resort_local_time():
    """The mairie's JSON-LD carries no UTC offset — it is Europe/Paris wall
    clock time, so 20:12 in August (CEST, UTC+2) must land on 18:12 UTC."""
    result = extract_published_at(JSON_LD_PAGE)
    assert result is not None
    assert result.isoformat() == "2026-08-24T18:12:25+00:00"


def test_extract_published_at_missing_returns_none():
    """No article:published_time meta tag exists on this site (og:type is
    'website', not 'article'), and no JSON-LD datePublished means we have no
    honest publish date — never invent one."""
    assert extract_published_at("<html><head></head><body>no ld+json here</body></html>") is None


def test_extract_published_at_tolerates_malformed_json():
    html = '<script type="application/ld+json">{not valid json</script>'
    assert extract_published_at(html) is None


# ------------------------------------------------- expiry, end to end -------

CLOSURE_UNDATED = "Accès au Mont-Blanc : danger mortel de chutes de pierres Fermeture des refuges de Tête Rousse et du Goûter"

# (title, body, published_at) for the four real gouter-route notices of 2026,
# in the order the mairie published them. Bodies are trimmed from the live
# pages; the reopening names the route only in its body, so an empty body
# here would quietly test the wrong thing.
REOPENING_BODY = (
    "Les conditions d'accès au Mont-Blanc par la voie royale de l'aiguille "
    "du Goûter sont à nouveau conformes aux normales de saison."
)
FEED_2026 = [
    (DEMOLITION, "", datetime(2026, 4, 10, 9, 0, tzinfo=UTC)),
    (MAY_CLOSURE, "", datetime(2026, 5, 26, 9, 0, tzinfo=UTC)),
    (CLOSURE_UNDATED, "", datetime(2026, 8, 11, 13, 59, tzinfo=UTC)),
    (REOPENING, REOPENING_BODY, datetime(2026, 8, 24, 18, 12, tzinfo=UTC)),
]


def winning_status(slug, at):
    """Mirror of massif.status.recompute_feature for one feature and one
    source: filter to statements whose validity window contains `at`, then
    rank by (trust, observed_at, severity). Trust is constant here — every
    notice comes from mairie-saint-gervais — so observed_at decides, which
    is exactly why observed_at must be the publication date."""
    live = []
    for title, body, published in FEED_2026:
        for statement in statements_for(title, body, "http://x", published):
            if statement.feature_slug != slug:
                continue
            if statement.valid_from is not None and statement.valid_from > at:
                continue
            if statement.valid_to is not None and statement.valid_to < at:
                continue
            live.append(statement)
    if not live:
        return None
    return max(live, key=lambda s: (s.observed_at, s.severity))


def test_gouter_route_reads_open_the_day_after_the_reopening():
    """The bug this exists for. 'Réouverture ... le 26/08/26' parsed to a
    one-day window, so on 27/08 the reopening had already lapsed and the
    newest thing left standing was the undated August closure. The normal
    route up Mont Blanc read shut the day after the mairie reopened it."""
    winner = winning_status("gouter-route", datetime(2026, 8, 27, 9, 0, tzinfo=UTC))
    assert winner is not None
    assert winner.status is StatusValue.OPEN
    assert winner.statement_type is StatementType.OPENING


def test_reopening_still_expires_eventually():
    """Honest expiry, not permanent OPEN: a reopening speaks for STALE_DAYS,
    then stops. Two months on, nothing from this feed claims the route is
    open — and the undated closure still refuses to claim it is shut."""
    winner = winning_status("gouter-route", datetime(2026, 10, 27, 9, 0, tzinfo=UTC))
    assert winner is None or winner.status is StatusValue.UNKNOWN


def test_may_closure_end_date_is_not_widened():
    """'du 26 au 29 mai' gave an explicit end. Only a point date is widened."""
    statement = statements_for(MAY_CLOSURE, "", "http://x", NOW)[0]
    assert statement.valid_to.date().isoformat() == "2026-05-29"


def test_expired_closure_does_not_linger():
    """The May closure is over. It must not still be shutting the route."""
    winner = winning_status("gouter-route", datetime(2026, 6, 15, 9, 0, tzinfo=UTC))
    assert winner is None or winner.status is not StatusValue.CLOSED


# ----------------------------------------------------- re-extraction --------

def _doc(raw_text, url="https://www.saintgervais.com/mairie/actualites/x/",
         published_at=None, fetched_at=None):
    return Document(
        url=url,
        raw_text=raw_text,
        published_at=published_at,
        fetched_at=fetched_at or datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
        content_hash="x",
        source_id=None,
    )


ARTICLE_HTML = """
<html><head>
<script type="application/ld+json">
{"@graph":[{"@type":"WebPage","datePublished":"2026-05-26 09:00:00"}]}
</script></head>
<body><article><h1>Fermeture temporaire de la voie normale du Mont-Blanc
du 26 au 29 mai 2026</h1><p>Arrêté municipal.</p></article></body></html>
"""


def test_extract_stored_reads_the_stored_html():
    statements = SaintGervaisScraper().extract_stored(_doc(ARTICLE_HTML))
    assert [s.feature_slug for s in statements] == ["gouter-route"]
    assert statements[0].status is StatusValue.CLOSED


def test_extract_stored_dates_from_the_document_not_now():
    """A re-extraction is not a new observation. Dating April's notice today
    would hand it the ranking win over August's reopening — the exact bug
    published_at was introduced to fix, reintroduced invisibly."""
    statements = SaintGervaisScraper().extract_stored(_doc(ARTICLE_HTML))
    assert statements[0].observed_at.date().isoformat() == "2026-05-26"


def test_extract_stored_falls_back_to_fetched_at_never_now():
    """A document stored before published_at existed has no publication date.
    fetched_at is when we saw it, which is still a fact about the past."""
    html = ARTICLE_HTML.replace('"datePublished":"2026-05-26 09:00:00"', '"x":1')
    doc = _doc(html, fetched_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC))
    statements = SaintGervaisScraper().extract_stored(doc)
    assert statements
    assert statements[0].observed_at == datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


def test_extract_stored_skips_the_listing_page():
    """The listing is stored for provenance but is not a notice. Extracting
    it would double-count every headline it links to."""
    listing = "<html><body><h1>Actualités</h1>Fermeture des refuges</body></html>"
    doc = _doc(listing, url="https://www.saintgervais.com/mairie/actualites/")
    assert SaintGervaisScraper().extract_stored(doc) == []


def test_extract_stored_handles_a_document_with_no_text():
    assert SaintGervaisScraper().extract_stored(_doc(None)) == []



# --------------------------------------------------------- english summary --

def test_summary_is_composed_english_not_french():
    """Cards were showing the French notice title verbatim. We already know
    the act and the dates structurally, so state them exactly in English —
    the French stays in original_text as the source's own words."""
    statement = statements_for(MAY_CLOSURE, "", "http://x", NOW)[0]
    assert statement.summary_en == "Closed 26–29 May 2026"
    assert "Fermeture" in statement.original_text
    assert statement.original_language == "fr"


def test_reopening_reads_as_a_reopening():
    statements = statements_for(REOPENING, "", "http://x", NOW)
    assert all(s.summary_en == "Reopening 26 Aug 2026" for s in statements)


def test_undated_notice_says_so_plainly():
    statements = statements_for(
        "Fermeture des refuges de Tête Rousse et du Goûter", "", "http://x", NOW
    )
    assert all(s.summary_en == "Closure notice — no dates stated" for s in statements)
