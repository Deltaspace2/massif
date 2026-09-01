"""FFCAM warden seasons — and the four things this parser must refuse to say.

FFCAM is the first source that makes a dated claim a hut is open, which is what
finally moves huts off "unknown". That is exactly why the interesting tests
here are the negative ones: a parser that is eager with a season paints a hut
green on prose, or on last year's dates, or keeps painting it green in November
when the warden has gone home and only the winter room is left.
"""

from datetime import UTC, datetime
from pathlib import Path

from massif.enums import StatementType, StatusValue
from massif.ingest.sources.ffcam import EXCLUDED, FfcamScraper, _windows, extract

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED = datetime(2026, 9, 1, 12, tzinfo=UTC)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def portal() -> str:
    return fixture("ffcam_portal_montblanc.html")


def by_name(statements):
    out: dict[str, list] = {}
    for statement in statements:
        out.setdefault(statement.feature_mention, []).append(statement)
    return out


# ---------------------------------------------------------------- what it says


def test_the_portal_yields_a_dated_season_for_each_managed_hut():
    found = by_name(extract(portal(), FETCHED))
    assert set(found) == {"REFUGE DU GOÛTER", "REFUGE DE TÊTE ROUSSE"}

    gouter = found["REFUGE DU GOÛTER"][0]
    assert gouter.valid_from == datetime(2026, 5, 30, tzinfo=UTC)
    assert gouter.valid_to.date() == datetime(2026, 10, 4).date()
    assert gouter.statement_type == StatementType.OPENING
    assert gouter.status == StatusValue.OPEN
    assert gouter.payload["altitude_m"] == 3815


def test_altitude_comes_from_each_block_not_the_first_number_on_the_page():
    """Three huts share one page. Reading the page instead of the block would
    give all three the Goûter's 3815 m, and the altitude check that stops a
    name matching the wrong mountain would then be checking nothing."""
    found = by_name(extract(portal(), FETCHED))
    assert found["REFUGE DU GOÛTER"][0].payload["altitude_m"] == 3815
    assert found["REFUGE DE TÊTE ROUSSE"][0].payload["altitude_m"] == 3165


def test_a_hut_with_two_seasons_gets_two_statements():
    """Albert 1er is wardened in spring and again in summer, with seven weeks
    shut between. One span from 14 March to 13 September would assert the hut
    is staffed through a gap its own page says it is not."""
    seasons = extract(fixture("ffcam_albert1er.html"), FETCHED)
    assert len(seasons) == 2
    spring, summer = sorted(seasons, key=lambda s: s.valid_from)
    assert (spring.valid_from.date(), spring.valid_to.date()) == (
        datetime(2026, 3, 14).date(),
        datetime(2026, 5, 3).date(),
    )
    assert (summer.valid_from.date(), summer.valid_to.date()) == (
        datetime(2026, 5, 23).date(),
        datetime(2026, 9, 13).date(),
    )


# ------------------------------------------------------- what it must not say


def test_the_couvercle_s_worded_season_is_read_rather_than_skipped():
    """It publishes "De début avril à fin septembre" and nothing else.

    This used to assert the opposite — that it emitted nothing — on the
    reading that an undated notice must never claim a present-tense status
    (CLAUDE.md rule 3). That rule is about a notice with NO bounds. This one is
    bounded, just bounded in words, and refusing it left the hut blank while
    its own operator said when it is wardened. It is read, and narrowed to the
    days the words certainly cover.
    """
    found = extract(fixture("ffcam_couvercle.html"), FETCHED)
    assert len(found) == 1
    assert found[0].valid_from.date() == datetime(2026, 4, 10).date()
    assert found[0].valid_to.date() == datetime(2026, 9, 21).date()
    assert found[0].original_text.startswith("Période de gardiennage")


def test_the_date_parser_still_decides_what_counts_as_a_DATE():
    """Both sides of that decision point, which is unchanged.

    A local "must contain a four-digit year" screen used to sit in front of
    parse_range. It was removed because it rejected nothing parse_range does
    not already reject, while silently dropping the `30/05/26` form — so the
    second assertion is what stops it being reintroduced. What changed is only
    that a phrase parse_range refuses now gets a second reading as a worded
    season; a phrase that is neither still says nothing.
    """
    assert _windows("Printemps : 14 mars au 3 mai 2026", 2026) != []
    assert _windows("Ouverture le 30/05/26\nFermeture le 04/10/26", 2026) != []
    assert _windows("Ouvert selon conditions", 2026) == []
    assert _windows("Ouverture au printemps\nFermeture à l'automne", 2026) == []


def page_publishing_a_season_for(name: str) -> str:
    """A minisite for `name` carrying a season this parser can read.

    The real Nid d'Aigle block contains prose, so testing the exclusion against
    the live fixture proves nothing — it would pass with the exclusion list
    emptied. This is the page FFCAM would serve if they printed dates for a hut
    they should not be speaking for.
    """
    return (
        f"<html><body><h1>{name}</h1>"
        '<div class="ouverture"><strong>Période de gardiennage</strong><br>'
        "2372 m<br>Ouverture du refuge au public le 30 mai 2026<br>"
        "Fermeture du refuge au public le 4 octobre 2026</div></body></html>"
    )


def test_the_exclusion_holds_even_when_the_hut_does_publish_dates():
    """FFCAM's own portal says it no longer manages the Nid d'Aigle. They are
    not the authority on its season, so a season from them is not one we carry
    — and that has to be true of a page that HAS dates, not just of the prose
    they happen to print today."""
    assert extract(page_publishing_a_season_for("REFUGE DU NID D'AIGLE"), FETCHED) == []
    # The same page under any other name is read normally: this is an exclusion
    # by identity, not a parser that has quietly stopped working.
    assert extract(page_publishing_a_season_for("REFUGE DU REQUIN"), FETCHED) != []


def test_the_tete_rousse_base_camp_can_never_take_the_refuge_s_status_slot():
    """Two directory rows two metres apart in altitude: the refuge (3165 m) and
    its base camp (3167 m). No altitude tolerance can separate them, so the
    annexe is excluded by name instead of being left to a fuzzy score."""
    assert "tete rousse- camp de base" in EXCLUDED
    assert extract(page_publishing_a_season_for("TETE ROUSSE- CAMP DE BASE"), FETCHED) == []


def test_nothing_is_emitted_outside_the_wardened_window():
    """ "Période de gardiennage" is the WARDEN season, not the access season.
    These huts have winter rooms — FFCAM sells "hors gardiennage" bookings for
    them — so turning the end of the season into a closure would invent a shut
    hut out of an unstaffed one."""
    for name in ("ffcam_portal_montblanc.html", "ffcam_albert1er.html"):
        for statement in extract(fixture(name), FETCHED):
            assert statement.status == StatusValue.OPEN
            assert statement.statement_type == StatementType.OPENING
            assert statement.valid_from is not None
            assert statement.valid_to is not None
            assert statement.payload["wardened"] is True


def test_re_extraction_dates_from_the_document_not_from_now():
    """A re-extraction is not a new observation. Dating it today would hand a
    season the ranking win over anything published since."""

    class StoredDocument:
        raw_text = None
        raw_content = portal().encode("utf-8")
        published_at = None
        fetched_at = datetime(2026, 6, 1, 9, tzinfo=UTC)

    found = FfcamScraper().extract_stored(StoredDocument())
    assert found
    assert all(s.observed_at == StoredDocument.fetched_at for s in found)


# ------------------------------------------------------------ the altitude gate


class _Feature:
    def __init__(self, slug, alt):
        self.id = "f1"
        self.slug = slug
        self.alt_min = self.alt_max = alt


class _Session:
    def __init__(self, feature):
        self.feature = feature

    def get(self, _model, _id):
        return self.feature

    def scalar(self, _query):
        return self.feature


class _Match:
    def __init__(self, score):
        self.feature_id = "f1"
        self.score = score
        self.name = "x"


class _Resolver:
    def __init__(self, match=None):
        self.match = match
        self.queued = []
        self.resolve_calls = 0

    def resolve(self, _mention):
        self.resolve_calls += 1
        return self.match, []

    def queue_unresolved(self, mention, _candidates, **kwargs):
        self.queued.append((mention, kwargs.get("context")))


def _scraper(hut_resolver):
    """A scraper with its hut-scoped resolver already supplied.

    Injected rather than built, because building one needs a database and the
    suite runs without one.
    """
    scraper = FfcamScraper()
    scraper._huts = hut_resolver
    return scraper


class _Source:
    id = "s1"
    language = "fr"


class _Document:
    id = "d1"


def _item(altitude):
    return extract(portal(), FETCHED)[0].__class__(
        feature_mention="REFUGE DU GOÛTER",
        statement_type=StatementType.OPENING,
        status=StatusValue.OPEN,
        observed_at=FETCHED,
        payload={"altitude_m": altitude},
    )


def test_a_good_name_on_the_wrong_mountain_is_refused_and_queued():
    """A name score cannot tell you which mountain something is on (rule 8).
    Vallot and the Goûter sit on one route with similar names 500 m apart."""
    huts = _Resolver(_Match(96.0))
    shared = _Resolver()
    session = _Session(_Feature("refuge-vallot", 4322))
    built = _scraper(huts).resolve_and_build(session, _Source(), _Document(), _item(3815), shared)
    assert built is None
    assert shared.queued
    assert "4322 m" in shared.queued[0][1]


def test_an_altitude_that_agrees_is_allowed_through():
    """The same call, with the altitudes matching, must NOT be queued — proving
    the test above fails on the altitude and not on the plumbing."""
    huts = _Resolver(_Match(96.0))
    shared = _Resolver()
    session = _Session(_Feature("refuge-du-gouter", 3835))
    item = _item(3815)
    built = _scraper(huts).resolve_and_build(session, _Source(), _Document(), item, shared)
    assert shared.queued == []
    assert item.feature_slug == "refuge-du-gouter"
    assert built is not None
    assert built.status == StatusValue.OPEN


def test_matching_goes_through_the_hut_scoped_index_not_the_shared_one():
    """The bug this scope exists for, pinned.

    `normalise` drops "refuge" and "du", so "REFUGE DU GOÛTER" and the Goûter
    Route's alias "Goûter" collide on one key, and the route is indexed first.
    On the first live run the shared resolver handed this source's hut season
    to a 4808 m mountaineering route at a score of 100. Resolution here must
    never consult that index.
    """
    huts = _Resolver(_Match(96.0))
    shared = _Resolver(_Match(100.0))
    session = _Session(_Feature("refuge-du-gouter", 3835))
    _scraper(huts).resolve_and_build(session, _Source(), _Document(), _item(3815), shared)
    assert huts.resolve_calls == 1
    assert shared.resolve_calls == 0


def test_a_name_no_hut_matches_is_queued_and_never_tried_on_the_shared_index():
    """The failure path is the one that needed the scope.

    Applying the hut scope only when a hut already matched leaves the case it
    was written for wide open: with no hut match this used to fall through to
    the base resolver, which resolves against the SHARED index — the one that
    handed "REFUGE DU GOÛTER" to a 4808 m route at a score of 100. The first
    time FFCAM renames a hut or lists one we do not carry, its season would go
    looking for a home among the routes and lifts.
    """
    huts = _Resolver(None)
    shared = _Resolver(_Match(100.0))
    built = _scraper(huts).resolve_and_build(
        _Session(None), _Source(), _Document(), _item(3815), shared
    )
    assert built is None
    assert shared.resolve_calls == 0
    assert shared.queued


def test_a_season_with_no_altitude_to_check_is_queued_not_guessed():
    """One screen is not two. If FFCAM prints no altitude beside a season, the
    name is standing on its own — which is exactly how a hut season reached a
    mountaineering route."""
    huts = _Resolver(_Match(96.0))
    shared = _Resolver()
    built = _scraper(huts).resolve_and_build(
        _Session(_Feature("refuge-du-gouter", 3835)),
        _Source(),
        _Document(),
        _item(None),
        shared,
    )
    assert built is None
    assert "no altitude" in shared.queued[0][1]


# ------------------------------------------------- seasons written in words


def test_a_season_in_words_is_read_and_narrowed_to_what_it_certainly_covers():
    """Four of the fifteen FFCAM huts publish only words — Argentière,
    Couvercle, Leschaux, Durier — and skipping them left every one of them
    with no status while their own operator was saying when it is wardened.

    Read CONSERVATIVELY: the LAST day a start could mean, the FIRST day an end
    could mean. "Début avril to fin septembre" is 10 Apr – 21 Sep, never
    1 Apr – 30 Sep. The window is always a subset of what the words allow, so
    this can fail to speak on a day the hut is open and can never claim it is
    open on a day the words do not cover.
    """
    ((label, window),) = _windows("De début avril à fin septembre", 2026)
    assert window.start.date() == datetime(2026, 4, 10).date()
    assert window.end.date() == datetime(2026, 9, 21).date()
    assert window.rule == "ffcam_coarse"


def test_the_narrowing_goes_inwards_at_both_ends():
    """Pinned as its own fact, because the direction is the whole safety of
    it and an off-by-one here widens a claim instead of tightening it."""
    ((_, mid),) = _windows("De mi juin a mi septembre", 2026)
    assert mid.start.date() == datetime(2026, 6, 20).date()  # latest "mi juin"
    assert mid.end.date() == datetime(2026, 9, 11).date()  # earliest "mi sept"


def test_one_end_in_words_and_one_in_dates():
    """Refuge Durier publishes "De début juin au 24 août 2026" — one of each.
    Requiring both ends to be worded lost the hut entirely."""
    ((_, window),) = _windows("De début juin au 24 août 2026", 2026)
    assert window.start.date() == datetime(2026, 6, 10).date()
    assert window.end.date() == datetime(2026, 8, 24).date()


def test_the_heading_is_skipped_only_when_it_is_the_whole_line():
    """Leschaux repeats it inline: "Période de gardiennage : De mi juin a mi
    septembre". Skipping on a prefix match threw that hut's only season away."""
    assert _windows("Période de gardiennage", 2026) == []
    assert _windows("Période de gardiennage : De mi juin a mi septembre", 2026)


def test_words_that_are_not_a_season_still_say_nothing():
    """Refuge Vallot's "Refuge bivouac non gardé", and any phrase with only one
    end. A bare month name is not a date."""
    assert _windows("Refuge bivouac non gardé", 2026) == []
    assert _windows("De début juin", 2026) == []
    assert _windows("D'avril à septembre", 2026) == []
    assert _windows("Ouvert l'été", 2026) == []


def test_a_season_the_narrowing_turns_inside_out_says_nothing():
    """Pulling both ends inward can cross them over.

    "De fin août à mi août" narrows to 31 Aug – 11 Aug, which is not a window.
    Silence is the answer: a backwards range would either be dropped further
    down or, worse, be stored and treated as valid at both ends. The same
    guard is what keeps a season written within a single month honest.
    """
    assert _windows("De fin août à mi août", 2026) == []
    # ...while a short season that survives the narrowing is still carried.
    ((_, july),) = _windows("De début juillet à fin juillet", 2026)
    assert july.start.date() == datetime(2026, 7, 10).date()
    assert july.end.date() == datetime(2026, 7, 21).date()
