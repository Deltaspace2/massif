"""Guards on model-extracted statements.

The suite is offline by construction: every model response is a cassette read
from disk, so these tests are as deterministic as any other in this project and
the thing under test is the pipeline, not the model.

Most of what follows is deliberately about WRONG readings. A test suite made
only of correct answers proves nothing about a component whose entire job is
catching incorrect ones.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.ingest.llm import (
    ASSUMED,
    PROMPT_VERSION,
    CassetteExtractor,
    cross_check_dates,
    normalise_space,
    read_document,
    verify_span,
    with_assumed_year,
)

CASSETTES = Path(__file__).parent / "cassettes"
NOW = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)

# The documents the cassettes were recorded against. Kept beside them, because
# a cassette divorced from its document replays an answer about text nobody has.
MAY_CLOSURE_DOC = (
    "Fermeture temporaire de la voie normale du Mont-Blanc du 26 au 29 mai 2026 "
    "— La commune de Saint-Gervais-les-Bains informe les alpinistes que "
    "l'itinéraire sera fermé pendant les opérations d'héliportage."
)

ROCKFALL_DOC = (
    "Accès au Mont-Blanc : danger mortel de chutes de pierres "
    "Fermeture des refuges de Tête Rousse et du Goûter — La période de "
    "sécheresse que nous traversons fait que la pratique de l'alpinisme "
    "nécessite une vigilance toute particulière."
)


def read(cassette: str, document: str):
    raw = CassetteExtractor(CASSETTES).extract_keyed(cassette)
    return read_document(raw, document, NOW, model="cassette")


# ------------------------------------------------------- a correct reading --


def test_a_good_reading_survives_every_guard():
    reading = read("real-may-closure", MAY_CLOSURE_DOC)
    assert reading.ok, [r.reason for r in reading.rejected]
    (statement,) = reading.statements

    assert statement.statement_type is StatementType.CLOSURE
    assert statement.status is StatusValue.CLOSED
    assert statement.feature_mention == "voie normale du Mont-Blanc"
    # Dates were re-derived by our own parser, not taken from the model.
    assert statement.valid_from.date().isoformat() == "2026-05-26"
    assert statement.extraction_method is ExtractionMethod.LLM
    assert statement.extraction_confidence == pytest.approx(0.94)


def test_everything_it_writes_is_gated():
    """The gate is set here, not by the caller.

    A future source must not be able to opt out of review by forgetting to ask
    for it — that is the kind of omission nobody notices until it is on the
    front page.
    """
    reading = read("real-may-closure", MAY_CLOSURE_DOC)
    (statement,) = reading.statements
    assert statement.payload["needs_review"] is True
    assert statement.payload["llm_model"] == "cassette"
    assert statement.payload["prompt_version"] == PROMPT_VERSION


def test_an_undated_notice_is_a_normal_outcome():
    """Most municipal prose has no dates. That is not a failure."""
    reading = read("real-rockfall", ROCKFALL_DOC)
    assert reading.ok, [r.reason for r in reading.rejected]
    (statement,) = reading.statements
    assert statement.valid_from is None and statement.valid_to is None
    # And it must not claim the present.
    assert statement.status is StatusValue.UNKNOWN
    assert statement.payload["dates_found"] is False


# ----------------------------------------------------------- wrong readings --


def test_an_invented_notice_is_refused():
    """The guard that matters most: a well-formed closure for a route the
    document never mentions."""
    reading = read("bad-invented-notice", MAY_CLOSURE_DOC)
    assert reading.statements == []
    assert [r.reason for r in reading.rejected] == ["evidence-not-in-document"]


def test_paraphrased_evidence_is_refused():
    """'Fermeture de la voie normale' for a document saying 'Fermeture
    temporaire de la voie normale'. Close enough to read past, which is exactly
    why the check is exact: a tidied quotation is not the source's words."""
    reading = read("bad-paraphrased-evidence", MAY_CLOSURE_DOC)
    assert reading.statements == []
    assert reading.rejected[0].reason == "evidence-not-in-document"


def test_invented_dates_lose_the_dates_not_the_statement():
    """The model quoted the phrase correctly and then claimed 29 JUNE.

    The statement is real and survives; the window does not. A wrongly dated
    statement is worse than an undated one, because a validity window is a
    claim about the present.
    """
    reading = read("bad-invented-dates", MAY_CLOSURE_DOC)
    assert reading.ok
    (statement,) = reading.statements
    assert statement.valid_from is None and statement.valid_to is None
    assert "2026-06-29" in statement.payload["dates_rejected"]
    assert statement.payload["dates_found"] is False


def test_dates_drawn_from_outside_the_quoted_span_are_refused():
    reading = read("bad-dates-outside-evidence", MAY_CLOSURE_DOC)
    assert reading.statements == []
    assert reading.rejected[0].reason == "dates-not-in-evidence"


def test_a_tidied_up_feature_name_is_refused():
    """ "Goûter Route" is our name for it. The document says "voie normale du
    Mont-Blanc". Letting the model hand a canonical name straight to the fuzzy
    resolver gives it more confidence than the source ever expressed — and
    unscoped fuzzy matching is what once resolved TC MER DE GLACE to the
    glacier at a score of 95."""
    reading = read("bad-tidied-mention", MAY_CLOSURE_DOC)
    assert reading.statements == []
    assert reading.rejected[0].reason == "mention-not-in-document"


def test_values_outside_the_schema_are_refused_individually():
    reading = read("bad-enum-and-severity", MAY_CLOSURE_DOC)
    assert reading.statements == []
    assert [r.reason for r in reading.rejected] == [
        "unknown-type",
        "unknown-status",
        "bad-severity",
    ]


def test_a_rejection_keeps_the_offending_output():
    """Counted and kept, never silently dropped. A silent rejection is
    indistinguishable from a source that said nothing."""
    reading = read("bad-invented-notice", MAY_CLOSURE_DOC)
    assert reading.rejected[0].raw["feature_mention"] == "Arête des Cosmiques"
    assert "Cosmiques" in reading.rejected[0].detail


# ------------------------------------------------------------- unit guards --


def test_span_check_forgives_whitespace_and_nothing_else():
    document = "Fermeture\n  temporaire   de la voie normale"
    assert verify_span("Fermeture temporaire de la voie normale", document)
    # An accent difference fails. Four separate bugs in this codebase came from
    # accents; a span check that shrugs at them is not a check.
    assert not verify_span("Fermeture temporaire de la voie normalé", document)
    assert not verify_span("", document)


def test_dates_that_do_not_parse_are_reported_not_guessed():
    dates, complaint = cross_check_dates("un de ces jours", None, None)
    assert dates is None
    assert "cannot parse" in complaint


def test_no_date_phrase_is_silence_not_a_complaint():
    assert cross_check_dates(None, None, None) == (None, None)


def test_a_claimed_iso_date_must_match_the_phrase():
    _, complaint = cross_check_dates("du 26 au 29 mai 2026", "2026-05-26", "2026-06-29")
    assert complaint and "2026-06-29" in complaint

    dates, complaint = cross_check_dates("du 26 au 29 mai 2026", "2026-05-26", "2026-05-29")
    assert complaint is None and dates is not None


def test_normalise_space_keeps_accents():
    assert normalise_space("  Goûter   Route \n") == "Goûter Route"


def test_a_missing_cassette_fails_loudly():
    with pytest.raises(FileNotFoundError, match="record one"):
        CassetteExtractor(CASSETTES).extract_keyed("no-such-cassette")


# ------------------------------------------- rule 3, enforced not requested


def test_an_undated_claim_cannot_be_about_the_present():
    """Found by pointing the model at hut websites.

    The Rifugio Torino's own page says it closes on 11 October; the model
    returned `closed` with no parseable dates, which would have painted a hut
    that is open today red. The Refuge des Cosmiques returned `open` with no
    dates, which `recompute_feature` treats as valid forever.

    The prompt already asks for this. Asking is not enough — and unlike the
    other three guards this one is about MISREADING rather than fabrication:
    every evidence span in both cases was real and correctly quoted.
    """
    reading = read_document(
        [
            {
                "statement_type": "closure",
                "status": "closed",
                "severity": 2,
                "feature_mention": "il rifugio",
                "evidence": "il rifugio chiude",
                "summary_en": "Closing on 11 October",
            }
        ],
        "Comunichiamo che il rifugio chiude per la stagione 2026.",
        NOW,
        model="test",
    )
    assert len(reading.statements) == 1
    assert reading.statements[0].status is StatusValue.UNKNOWN
    # The reading is kept, not thrown away — a reviewer needs to see what it
    # wanted to say, not a bare "unknown".
    assert reading.statements[0].payload["undated_status"] == "closed"


def test_a_dated_claim_keeps_the_status_it_came_with():
    """The guard must bite on the missing window, not on the status."""
    reading = read_document(
        [
            {
                "statement_type": "closure",
                "status": "closed",
                "severity": 2,
                "feature_mention": "La voie normale",
                "evidence": "La voie normale sera fermée du 26 mai 2026 au 29 mai 2026",
                "dates_text": "du 26 mai 2026 au 29 mai 2026",
                "summary_en": "Closed 26-29 May",
            }
        ],
        "La voie normale sera fermée du 26 mai 2026 au 29 mai 2026.",
        NOW,
        model="test",
    )
    assert reading.statements[0].status is StatusValue.CLOSED
    assert "undated_status" not in reading.statements[0].payload


def test_an_unknown_with_no_dates_is_left_alone():
    """Already honest; there is nothing to demote."""
    reading = read_document(
        [
            {
                "statement_type": "closure",
                "status": "unknown",
                "severity": 3,
                "feature_mention": "refuges",
                "evidence": "Fermeture des refuges",
                "summary_en": "Closed, no end date",
            }
        ],
        "Fermeture des refuges de Tête Rousse.",
        NOW,
        model="test",
    )
    assert reading.statements[0].status is StatusValue.UNKNOWN
    assert "undated_status" not in reading.statements[0].payload


# ------------------------------------------- a season stated without a year


def test_a_recurring_season_can_be_bound_to_the_document_s_year():
    """Hut websites state the season without a year because it recurs: Refuge
    de Tré la Tête says "du 15 mars au 15 octobre" and means every year. Guard
    2 drops those dates, and the rule-3 guard then demotes the statement to
    unknown — so most hut homepages produce nothing at all without this."""
    found = with_assumed_year("du 15 mars au 15 octobre", 2026)
    assert found.start.date() == date(2026, 3, 15)
    assert found.end.date() == date(2026, 10, 15)
    assert found.rule.endswith(ASSUMED)


def test_a_winter_season_rolls_into_the_following_year():
    """ "du 15 décembre au 15 avril" bound to one year runs backwards, and the
    only other reading is a window that ends before it starts. A hut with a
    winter season is not an error."""
    found = with_assumed_year("du 15 décembre au 15 avril", 2026)
    assert found.start.date() == date(2026, 12, 15)
    assert found.end.date() == date(2027, 4, 15)


def test_assuming_a_year_does_not_make_prose_into_a_date():
    assert with_assumed_year("de mi-juin à mi-septembre", 2026) is None
    assert with_assumed_year("l'été", 2026) is None


def test_a_phrase_that_states_its_own_year_is_never_second_guessed():
    """The assumption is only ever a fallback. An arrêté is about one occasion
    and says which — overriding that with the document's year would be this
    guard inventing a date instead of checking one."""
    stated, complaint = cross_check_dates(
        "du 26 mai 2025 au 29 mai 2025", None, None, assume_year=2026
    )
    assert stated.start.date() == date(2025, 5, 26)
    assert not stated.rule.endswith(ASSUMED)
    assert complaint is None


def test_an_assumed_year_is_marked_as_ours_in_the_payload():
    """ffcam-refuges sets the same flag on a season it narrowed out of words.
    Nothing may print these as dates the source published."""
    reading = read_document(
        [
            {
                "statement_type": "opening",
                "status": "open",
                "severity": 0,
                "feature_mention": "Le refuge",
                "evidence": "Le refuge est ouvert du 15 mars au 15 octobre",
                "dates_text": "du 15 mars au 15 octobre",
                "summary_en": "Open for the season",
            }
        ],
        "Le refuge est ouvert du 15 mars au 15 octobre.",
        NOW,
        model="test",
        assume_year=2026,
    )
    assert len(reading.statements) == 1
    assert reading.statements[0].payload["approximate"] is True
    assert reading.statements[0].valid_from.date() == date(2026, 3, 15)


def test_without_an_assumed_year_the_same_reading_is_demoted():
    """The default is unchanged: a caller that does not opt in still gets
    rule 3 applied to a yearless season."""
    reading = read_document(
        [
            {
                "statement_type": "opening",
                "status": "open",
                "severity": 0,
                "feature_mention": "Le refuge",
                "evidence": "Le refuge est ouvert du 15 mars au 15 octobre",
                "dates_text": "du 15 mars au 15 octobre",
                "summary_en": "Open for the season",
            }
        ],
        "Le refuge est ouvert du 15 mars au 15 octobre.",
        NOW,
        model="test",
    )
    assert reading.statements[0].status is StatusValue.UNKNOWN
    assert reading.statements[0].payload["undated_status"] == "open"
