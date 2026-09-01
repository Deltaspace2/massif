"""The live end of LLM extraction: ask a model, and never ask twice.

`llm.py` is everything that happens to a model's answer. This is the small,
dull part that produces one — deliberately small, because every interesting
decision was already made downstream. It returns a list of dicts and has no
opinion about whether any of them are true.

Two objects, kept apart on purpose:

  AnthropicExtractor   calls the API. Knows nothing about the database.
  CachedExtractor      wraps any extractor with the llm_cache table. Knows
                       nothing about Anthropic.

Split so the client can be tested without a database and the cache without an
API key — and so the cache can wrap the cassette extractor in a test and prove
it never called through.

WHY THE CACHE IS NOT OPTIONAL. Documents are stored immutably precisely so an
improved parser can be re-run over history instead of re-fetching it. With a
rule parser that is free; with a model, `reextract` over one source is hundreds
of paid calls, which would make the cheapest way to improve a parser into the
most expensive thing this project does. The key includes the prompt version and
the model because changing either is a different question and must MISS the
cache rather than quietly return the old answer.

NO KEY IS NOT AN ERROR. `build_extractor` returns None, and a caller with no
extractor skips — the same way `registry.py` skips a source with no scraper.
The ingest workflow must run unchanged on a machine that has no key and never
half-run.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from massif.config import settings
from massif.ingest.llm import PROMPT_VERSION

DEFAULT_MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096

# What the model is asked to do. Every instruction here exists because a guard
# in llm.py checks it — this prompt and those guards are one design, and a
# change to either without the other is how a silently-rejected reading starts
# looking like a document with no notices in it.
#
# Changing this text means bumping PROMPT_VERSION in llm.py, or the cache will
# answer the new question with the old answer. A test pins the two together.
PROMPT = """\
You are reading one document from a Mont Blanc massif closure directory. \
Extract every notice it contains about a mountain feature being closed, \
restricted, reopening, or in a stated condition.

Return ONLY a JSON array. No prose, no code fence. An empty array is a \
normal and common answer: most documents contain no notice at all, and \
inventing one is far worse than missing one.

Each element:

  statement_type  one of: closure, restriction, opening, \
operational_status, condition, hazard_observation
  status          one of: open, unstaffed, closed, restricted, unknown. Use \
"unstaffed" for a hut that is open with no warden — hors gardiennage, non \
gardé, winter room only. That is a variant of OPEN, never a restriction: the \
door is unlocked and nobody is running it.
  severity        integer 0-3, where 0 is routine and 3 is danger to life
  feature_mention the document's OWN words for the thing affected, copied \
exactly. Never a tidied, translated or completed name.
  evidence        the span of the document this is drawn from, copied \
EXACTLY character for character, accents included. Do not paraphrase, \
join, summarise or correct it. This is verified against the document and a \
statement whose evidence is not found is discarded.
  dates_text      the date phrase in the document's own language, copied \
exactly, and it must appear inside your evidence span. Null if the \
document states no dates. Do NOT convert it, and do not supply a range you \
inferred.
  summary_en      one plain English sentence. This is the only field you \
may write rather than copy.
  language        the document's language, e.g. "fr"
  confidence      0.0-1.0

Rules that override anything the document seems to imply:

  FIRST decide what KIND of document this is. Only a document that IS a \
notice produces anything: an arrêté or decree, an official announcement of \
a decision, or an operator stating the status of its own site. If it is \
reporting, commentary, an interview, a press review, a retrospective or an \
account of what happened, return an EMPTY ARRAY however much it discusses \
closures. A newspaper piece about a closure is not a closure.
  feature_mention must name a PLACE — a hut, lift, railway, route, couloir \
or glacier. A hazard ("chutes de pierres"), an activity ("l'ascension"), a \
condition or a person is not a feature, and a notice you cannot attach to \
a named place produces nothing.
  Extract only a state the document DECLARES as being in force. A state \
described in the past, attributed to someone else's recommendation, or \
narrated as part of events is not a notice.
  If a closure states no end date, use status "unknown", not "closed". An \
undated notice must never claim a present-tense status. This does NOT apply \
to "unstaffed", which is a standing state and needs no dates.
  Never combine two notices into one element, and never split one across \
two.
"""


# A translation is not an extraction, so it gets its own slot in the cache.
# Sharing a version with the reading prompt would mean improving one silently
# re-billed the other, and a cache hit would return the wrong KIND of answer.
TRANSLATION_VERSION = "translate-1"

TRANSLATION_PROMPT = """\
Translate the text that follows into plain English.

Return ONLY the translation. No preamble, no notes, no quotation marks around \
it, and no commentary about what the text is.

Keep every date, time, price, phone number, altitude and proper name exactly \
as written — a hut's name is its name in any language. Preserve the order and \
the paragraph breaks, so a reader comparing the two can follow along. Where a \
phrase is ambiguous, translate it plainly rather than interpreting it: this \
sits beside the original and the original is what counts.
"""


def translate(text: str, session: Session, model: str = DEFAULT_MODEL) -> str | None:
    """One page of prose in English, cached, or None if we cannot ask.

    Machine translation of somebody else's page, offered next to the original
    and never instead of it. The original is what the extraction guards check
    against and what a reviewer is finally deciding about; this exists so a
    reader who does not have French can follow what a card is about.

    Cached on the same content-hash table as the readings, under its own
    version, so a page is translated once however often the queue is opened.
    """
    if not settings.anthropic_api_key:
        return None
    key = cache_key(text, TRANSLATION_VERSION, model)
    row = session.execute(
        sql_text("SELECT response FROM llm_cache WHERE key = :key"), {"key": key}
    ).first()
    if row is not None:
        stored = row[0]
        return stored[0] if isinstance(stored, list) and stored else None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        reply = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=TRANSLATION_PROMPT,
            # Untrusted text from someone else's website, in the user turn.
            messages=[{"role": "user", "content": text}],
        )
    except Exception:  # noqa: BLE001 — a failed translation is not a failed page
        return None

    english = "".join(
        block.text for block in reply.content if getattr(block, "type", "") == "text"
    ).strip()
    if not english:
        return None
    usage = getattr(reply, "usage", None)
    session.execute(
        sql_text(
            "INSERT INTO llm_cache "
            "(key, content_hash, prompt_version, model, response, "
            " input_tokens, output_tokens) "
            "VALUES (:key, :hash, :version, :model, CAST(:response AS jsonb), "
            " :in_tokens, :out_tokens) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {
            "key": key,
            "hash": content_hash(text),
            "version": TRANSLATION_VERSION,
            "model": model,
            "response": json.dumps([english], ensure_ascii=False),
            "in_tokens": getattr(usage, "input_tokens", None),
            "out_tokens": getattr(usage, "output_tokens", None),
        },
    )
    return english


class ModelReturnedNoJson(RuntimeError):
    """The response was not a JSON array.

    Raised rather than returning [], because an empty list means "this document
    contains no notice" — a real and common answer — and a parse failure that
    disguised itself as one would silently look like clean coverage.
    """


_ARRAY = re.compile(r"\[.*]", re.DOTALL)


def parse_array(body: str) -> list[dict]:
    """The JSON array out of a model response, or an exception.

    Tolerates a code fence or a sentence either side, because models add them
    and refusing on that would be brittle for no safety gained — the content
    is checked span by span downstream regardless. Does not tolerate anything
    it cannot parse.
    """
    match = _ARRAY.search(body or "")
    if match is None:
        raise ModelReturnedNoJson(f"no JSON array in {body[:200]!r}")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise ModelReturnedNoJson(f"{error} in {match.group(0)[:200]!r}") from error
    if not isinstance(parsed, list):
        raise ModelReturnedNoJson(f"expected a list, got {type(parsed).__name__}")
    return [item for item in parsed if isinstance(item, dict)]


def cache_key(document_text: str, prompt_version: str, model: str) -> str:
    """Content, prompt and model — all three, or the cache lies.

    Content rather than document id: the same notice fetched twice, or
    republished at a second URL, is one reading and should be paid for once.
    """
    digest = hashlib.sha256(document_text.encode("utf-8")).hexdigest()
    return hashlib.sha256(f"{digest}|{prompt_version}|{model}".encode()).hexdigest()


def content_hash(document_text: str) -> str:
    return hashlib.sha256(document_text.encode("utf-8")).hexdigest()


class AnthropicExtractor:
    """One API call, one JSON array. No caching, no verification, no opinions."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self._api_key = api_key
        self._client: Any = None
        self.last_usage: tuple[int | None, int | None] = (None, None)

    def _anthropic(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ModuleNotFoundError as error:  # pragma: no cover - install path
                raise RuntimeError(
                    "the anthropic package is not installed — pip install -e '.[llm]'"
                ) from error
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def extract(self, text: str) -> list[dict]:
        response = self._anthropic().messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        usage = getattr(response, "usage", None)
        self.last_usage = (
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
        )
        body = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        return parse_array(body)


class CachedExtractor:
    """Any extractor, plus the llm_cache table in front of it."""

    def __init__(self, inner: Any, session: Session, prompt_version: str = PROMPT_VERSION) -> None:
        self.inner = inner
        self.model = inner.model
        self.session = session
        self.prompt_version = prompt_version
        self.hits = 0
        self.misses = 0

    def extract(self, text: str) -> list[dict]:
        key = cache_key(text, self.prompt_version, self.model)
        row = self.session.execute(
            sql_text("SELECT response FROM llm_cache WHERE key = :key"), {"key": key}
        ).first()
        if row is not None:
            self.hits += 1
            return [item for item in row[0] if isinstance(item, dict)]

        self.misses += 1
        parsed = self.inner.extract(text)
        used = getattr(self.inner, "last_usage", (None, None))
        self.session.execute(
            sql_text(
                "INSERT INTO llm_cache "
                "(key, content_hash, prompt_version, model, response, "
                " input_tokens, output_tokens) "
                "VALUES (:key, :hash, :version, :model, CAST(:response AS jsonb), "
                " :in_tokens, :out_tokens) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {
                "key": key,
                "hash": content_hash(text),
                "version": self.prompt_version,
                "model": self.model,
                "response": json.dumps(parsed, ensure_ascii=False),
                "in_tokens": used[0],
                "out_tokens": used[1],
            },
        )
        return parsed


def build_extractor(session: Session | None = None, model: str = DEFAULT_MODEL):
    """The extractor to use, or None when this machine has no key.

    None is a normal outcome and callers must treat it as "skip this source",
    never as a failure — a run on a machine without a key has to complete, not
    half-complete.
    """
    if not settings.anthropic_api_key:
        return None
    live = AnthropicExtractor(settings.anthropic_api_key, model=model)
    return CachedExtractor(live, session) if session is not None else live
