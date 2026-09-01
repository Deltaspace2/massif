"""Turning a language model's reading of French prose into statements — safely.

Rule parsers handle the structured sources and always will: the lift feed is a
DOM with stable element ids, the calendar is a JSON payload with ISO dates in
it, and asking a model to interpret those would be slower, dearer and less
reliable for no gain. Prose is the other half. Municipal arrêtés and the
Chamoniarde bulletins carry the closures that make this site worth visiting,
and no regex is ever going to read them well.

The risk is specific and it is the one this whole project is organised against:
a model does not fail loudly. It produces a plausible, well-formed, wrong
statement — the same shape as every bug that has shipped here. So almost
nothing in this module is about prompting. It is about what happens to the
output afterwards.

Four guards, in order of how much they buy:

1.  EVIDENCE. Every statement must carry the verbatim span of the document it
    was drawn from, and that span must actually be in the document. This is
    the one that turns fabrication from a silent wrong answer into a caught
    error, and it is cheap: normalised substring containment, nothing clever.

2.  DATES READ TWICE. The model returns the French phrase, never a parsed
    range. We parse that phrase ourselves with fr_dates.parse_range — eight
    ordered patterns with tests that already caught a range crossing new year
    ending six days early. Two independent readings of one substring have to
    agree. Where they do not, the statement survives and the dates do not,
    which the site renders honestly as "no dates stated".

3.  NO FEATURE PICKING. The model returns a mention string. FeatureResolver
    matches it, with the same 88-point floor and the same review queue as
    every other source. Unscoped fuzzy matching once resolved "TC MER DE
    GLACE" to the Mer de Glace *glacier* at a score of 95; that door stays
    shut rather than being reopened for a new caller.

4.  THE GATE. Everything from here is written with needs_review, and the API
    keeps such statements out of the status slot until a human clears them.
    The site gains the information immediately and the claim later.

What none of this catches is misinterpretation — a real span read to mean the
opposite. The accent bug in classify() did exactly that, publishing a reopening
as a closure on the morning the refuges reopened, and a rule-based parser is
what made it. Guard 4 is the answer to that, and it is a process answer, not a
technical one. Be honest about which is which.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from selectolax.parser import HTMLParser

from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.ingest.base import ExtractedStatement
from massif.ingest.fr_dates import DateRange, parse_range

# Bump when the prompt or the schema changes. It is part of the cache key, so
# an edit here re-extracts rather than silently mixing two vintages of output
# in one table.
PROMPT_VERSION = "2"


@dataclass
class Rejection:
    """A statement the guards refused, kept rather than dropped.

    A silent rejection is indistinguishable from a source that said nothing,
    and this project has been bitten by that shape before. These are counted,
    logged, and written to the document's extraction_error.
    """

    reason: str
    detail: str
    raw: dict


@dataclass
class Reading:
    """The result of reading one document: what survived, and what did not."""

    statements: list[ExtractedStatement] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected


class Extractor(Protocol):
    """Where the model output comes from.

    Two implementations: a live API client, and a cassette that replays
    recorded responses from disk. Tests only ever use the cassette, so the
    suite stays offline and deterministic and every guard above is ordinary
    pure-function testing.
    """

    model: str

    def extract(self, text: str) -> list[dict]: ...


# ------------------------------------------------------------------ the text


# Furniture: present on every page, never the notice, and expensive.
_FURNITURE = "script, style, noscript, nav, header, footer, aside, form, svg"

# Where the prose lives, best first. The same ladder saint_gervais.py already
# climbs for its own body extraction.
_CONTENT = ("article", "main", "[class*='content']")


def readable_text(html: str) -> str:
    """The prose of a page, without the furniture.

    THIS IS A COST AND A CORRECTNESS FIX, in that order of how it was found.
    `documents.raw_text` is the raw HTML we fetched — importmaps, menus, cookie
    banners and all. Sending that verbatim cost 77,898 input tokens for ONE
    Saint-Gervais notice, and one pass over that source would have been about
    1.5 million tokens. The article bodies are 82,000 characters in total: a
    99% reduction, and 74x the price for the privilege of hiding the notice in
    markup.

    The correctness half matters more. `read_document` verifies every evidence
    span against the text it was given, so the model must be asked about
    EXACTLY the string we later check against — otherwise a perfectly good span
    copied out of the HTML fails a check made against the prose, and the
    failure looks like a document with nothing in it. One function, both jobs.
    """
    tree = HTMLParser(html or "")
    for node in tree.css(_FURNITURE):
        node.decompose()
    container = None
    for selector in _CONTENT:
        container = tree.css_first(selector)
        if container is not None:
            break
    if container is None:
        container = tree.body
    if container is None:
        return ""
    return normalise_space(container.text(separator=" ", strip=True))


# --------------------------------------------------------------- normalising


def normalise_space(text: str) -> str:
    """Collapse whitespace, keeping everything else — accents included.

    Verbatim has to mean verbatim or the evidence check is theatre. The only
    thing forgiven is whitespace, because HTML-to-text extraction moves line
    breaks around and a model retyping a span will not reproduce them.
    """
    return re.sub(r"\s+", " ", (text or "")).strip()


def _fold(text: str) -> str:
    """Whitespace-collapsed, accent-stripped, casefolded — for the LAST-RESORT
    comparison only. Never used for the evidence check itself: an accent
    difference between the model's span and the document is exactly the kind of
    discrepancy worth failing on, in a codebase where four separate bugs came
    from accents."""
    text = unicodedata.normalize("NFKD", normalise_space(text))
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


# ------------------------------------------------------------------- guard 1


def verify_span(evidence: str, document_text: str) -> bool:
    """Is this span actually in the document?

    Whitespace-normalised containment. Deliberately strict about everything
    else — if the model paraphrased, rounded a number, or corrected the
    mairie's typo, that is not the source's words and must not be stored as
    though it were.
    """
    if not evidence or not evidence.strip():
        return False
    return normalise_space(evidence) in normalise_space(document_text)


# ------------------------------------------------------------------- guard 2


ASSUMED = "+assumed_year"


def with_assumed_year(dates_text: str, year: int) -> DateRange | None:
    """A recurring season bound to one year, or None.

    Hut websites state the season without a year because it recurs: Refuge de
    Tré la Tête says "du 15 mars au 15 octobre" and means every year. Municipal
    arrêtés never do this — they are about one occasion — which is why this is
    offered to a caller rather than built into parse_range.

    A season that runs backwards once bound is a WINTER one: "du 15 décembre au
    15 avril" is December to the following April, and the alternative reading
    is a window that ends before it starts. Rolled forward rather than
    rejected, because a hut with a winter season is not an error.

    The rule is stamped so the caller can mark the dates as ours. They are an
    inference — a true one about how these pages are written, and still not
    something the source published.
    """
    bound = parse_range(f"{dates_text} {year}")
    if bound is None or bound.start is None or bound.end is None:
        return None
    if bound.start > bound.end:
        rolled = parse_range(f"{dates_text} {year + 1}")
        if rolled is None or rolled.end is None:
            return None
        bound = DateRange(bound.start, rolled.end, bound.rule)
    return DateRange(bound.start, bound.end, bound.rule + ASSUMED)


def cross_check_dates(
    dates_text: str | None,
    claimed_start: str | None,
    claimed_end: str | None,
    assume_year: int | None = None,
) -> tuple[DateRange | None, str | None]:
    """Parse the French phrase ourselves and require agreement.

    Returns (range, complaint). A complaint means the dates are dropped, not
    that the statement is. An undated notice is a normal, well-handled outcome
    here; a wrongly dated one is a wrong answer with a validity window, which
    is far worse — it would claim the present.
    """
    if not dates_text:
        return None, None

    ours = parse_range(dates_text)
    if ours is None and assume_year is not None:
        ours = with_assumed_year(dates_text, assume_year)
    if ours is None:
        return None, f"we cannot parse {dates_text!r} as a date range"

    # The model may also offer ISO dates. It does not have to, but if it does
    # they must match what the phrase actually says.
    for label, claimed, mine in (
        ("start", claimed_start, ours.start),
        ("end", claimed_end, ours.end),
    ):
        if not claimed:
            continue
        try:
            parsed = datetime.fromisoformat(claimed)
        except ValueError:
            return None, f"claimed {label} {claimed!r} is not an ISO date"
        if mine is None:
            return None, f"claimed a {label} the phrase does not contain"
        if parsed.date() != mine.date():
            return None, (
                f"claimed {label} {parsed.date()} but {dates_text!r} parses to {mine.date()}"
            )
    return ours, None


# ------------------------------------------------------------------ assembly

_TYPES = {t.value: t for t in StatementType}
_STATUSES = {s.value: s for s in StatusValue}


def read_document(
    raw: list[dict],
    document_text: str,
    observed_at: datetime,
    *,
    model: str,
    source_url: str | None = None,
    assume_year: int | None = None,
) -> Reading:
    """Apply every guard to one document's worth of model output."""
    reading = Reading()

    for item in raw:
        # Bound explicitly rather than closed over: a closure here captures the
        # loop variable by reference, so it happens to be correct only because
        # every call site is followed by `continue`. That is a trap for whoever
        # adds a branch that is not.
        def reject(reason: str, detail: str, _item: dict = item) -> None:
            reading.rejected.append(Rejection(reason, detail, _item))

        evidence = item.get("evidence") or ""
        if not verify_span(evidence, document_text):
            reject(
                "evidence-not-in-document",
                f"{evidence[:120]!r} does not appear in the stored document",
            )
            continue

        statement_type = _TYPES.get(str(item.get("statement_type", "")).lower())
        if statement_type is None:
            reject("unknown-type", f"{item.get('statement_type')!r}")
            continue

        status = _STATUSES.get(str(item.get("status", "")).lower())
        if status is None:
            reject("unknown-status", f"{item.get('status')!r}")
            continue

        mention = normalise_space(item.get("feature_mention") or "")
        if not mention:
            reject("no-feature-mention", "the statement names nothing")
            continue
        # The mention has to be the document's word for the thing, not the
        # model's. Otherwise a tidied-up name walks into the fuzzy resolver
        # carrying more confidence than the source ever gave it.
        if _fold(mention) not in _fold(document_text):
            reject(
                "mention-not-in-document",
                f"{mention!r} does not appear in the stored document",
            )
            continue

        dates_text = item.get("dates_text")
        if dates_text and not verify_span(dates_text, evidence):
            reject(
                "dates-not-in-evidence",
                f"{dates_text!r} is not inside the span it was drawn from",
            )
            continue

        demoted = None
        dates, complaint = cross_check_dates(
            dates_text,
            item.get("valid_from"),
            item.get("valid_to"),
            assume_year=assume_year,
        )

        severity = item.get("severity", 0)
        if not isinstance(severity, int) or not 0 <= severity <= 3:
            reject("bad-severity", f"{severity!r} is not 0-3")
            continue

        # RULE 3, ENFORCED HERE RATHER THAN ASKED FOR.
        #
        # The prompt tells the model that an undated closure must be "unknown".
        # Pointing it at hut websites showed how little that is worth: the
        # Rifugio Torino's own page says it closes on 11 October and the model
        # returned `closed` with no parseable dates, which would have painted a
        # hut that is open today red — and the Cosmiques returned `open` with
        # no dates, which recompute_feature treats as valid forever.
        #
        # A claim about the present needs a window it is the present of. This
        # is the one guard the model cannot talk its way past, and unlike the
        # other three it is about misreading rather than fabrication: every
        # span above was real and correctly quoted.
        if dates is None and status is not StatusValue.UNKNOWN:
            demoted, status = status, StatusValue.UNKNOWN

        payload: dict = {
            # The gate. Set here rather than by the caller so no future source
            # can quietly opt out of it by forgetting.
            "needs_review": True,
            "evidence": normalise_space(evidence),
            "llm_model": model,
            "prompt_version": PROMPT_VERSION,
        }
        if source_url:
            payload["url"] = source_url
        if dates is None and demoted is not None:
            # Say what it wanted to claim, so a reviewer can see the reading
            # rather than a bare "unknown" with no explanation.
            payload["undated_status"] = demoted.value
        if complaint:
            # An undated statement whose dates we threw away is not the same as
            # one that never had any. Say which, in the row itself.
            payload["dates_rejected"] = complaint
            payload["dates_text"] = dates_text
        elif dates:
            payload["date_rule"] = dates.rule
            if dates.rule.endswith(ASSUMED):
                # The year is ours, not theirs. Nothing may present these as
                # dates the source published — the same flag ffcam-refuges
                # sets on a season it narrowed out of words.
                payload["approximate"] = True
        payload["dates_found"] = bool(dates)

        confidence = item.get("confidence")
        reading.statements.append(
            ExtractedStatement(
                feature_mention=mention,
                statement_type=statement_type,
                status=status,
                severity=severity,
                observed_at=observed_at,
                valid_from=dates.start if dates else None,
                valid_to=dates.end if dates else None,
                summary_en=item.get("summary_en"),
                original_text=normalise_space(evidence)[:2000],
                original_language=item.get("language") or "fr",
                payload=payload,
                extraction_method=ExtractionMethod.LLM,
                extraction_confidence=(
                    float(confidence) if isinstance(confidence, int | float) else None
                ),
                context=normalise_space(evidence)[:400],
            )
        )

    return reading


# ------------------------------------------------------------------ cassette


class CassetteExtractor:
    """Replays recorded model output from disk. The only Extractor tests use.

    Keyed on a content hash so a cassette is tied to the document it was
    recorded against — swap the document and the test fails loudly rather than
    replaying an answer about different text.
    """

    def __init__(self, directory: Path | str, model: str = "cassette") -> None:
        self.directory = Path(directory)
        self.model = model

    def path_for(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def extract(self, text: str) -> list[dict]:  # noqa: ARG002 - keyed by caller
        raise NotImplementedError("use extract_keyed(); cassettes are keyed")

    def extract_keyed(self, key: str) -> list[dict]:
        path = self.path_for(key)
        if not path.exists():
            raise FileNotFoundError(
                f"no cassette {key!r} in {self.directory} — record one before "
                "asserting anything about it"
            )
        return json.loads(path.read_text(encoding="utf-8"))
