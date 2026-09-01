"""The live end of LLM extraction, tested without a key and without a network.

Everything interesting about a model's answer is checked in llm.py and tested
against cassettes. What is left here is small and dull, and the tests are about
the two ways it could quietly cost money or quietly lose a notice: asking twice
for the same text, and turning a broken response into "nothing published".
"""

import hashlib
import json

import pytest

from massif.ingest.llm import PROMPT_VERSION
from massif.ingest.llm_client import (
    DEFAULT_MODEL,
    PROMPT,
    AnthropicExtractor,
    CachedExtractor,
    ModelReturnedNoJson,
    build_extractor,
    cache_key,
    parse_array,
)

ITEM = {"statement_type": "closure", "status": "unknown", "evidence": "x"}


# ------------------------------------------------------------------- parsing


def test_a_plain_array_is_read():
    assert parse_array(json.dumps([ITEM])) == [ITEM]


def test_a_fenced_or_prefaced_array_is_still_read():
    """Models add code fences and a sentence of preamble. Refusing on that
    would be brittle for no safety gained — every span is checked downstream
    regardless of how it arrived."""
    body = "Here is what I found:\n```json\n" + json.dumps([ITEM]) + "\n```"
    assert parse_array(body) == [ITEM]


def test_an_empty_array_is_a_real_answer():
    """Most documents contain no notice at all. That has to be expressible."""
    assert parse_array("[]") == []


@pytest.mark.parametrize(
    "body", ["", "I could not find any notices.", "[{oh no}]", '{"statement_type": "closure"}']
)
def test_a_response_that_is_not_an_array_raises_rather_than_returning_nothing(body):
    """THE important test in this file.

    [] means "this document contains no notice", which is a real and common
    answer. A parse failure that disguised itself as one would read as clean
    coverage — the site would be quietly certain about a document nobody
    managed to read.
    """
    with pytest.raises(ModelReturnedNoJson):
        parse_array(body)


def test_non_dict_elements_are_dropped_not_passed_on():
    assert parse_array('[{"a": 1}, "nonsense", 3]') == [{"a": 1}]


# --------------------------------------------------------------------- keying


def test_the_key_changes_with_the_text_the_prompt_and_the_model():
    """All three, or the cache lies. A new prompt asks a different question and
    must MISS rather than quietly return the old answer — which is the whole
    reason PROMPT_VERSION exists."""
    base = cache_key("some prose", "1", "claude-sonnet-5")
    assert base != cache_key("other prose", "1", "claude-sonnet-5")
    assert base != cache_key("some prose", "2", "claude-sonnet-5")
    assert base != cache_key("some prose", "1", "claude-opus-5")
    assert base == cache_key("some prose", "1", "claude-sonnet-5")


def test_the_same_text_from_two_documents_is_one_reading():
    """Content, not document id: the same notice fetched twice or republished
    at a second URL is one question and should be paid for once."""
    assert cache_key("identical", "1", "m") == cache_key("identical", "1", "m")


# ---------------------------------------------------------------- the cache


class _Session:
    """Just enough of a Session: one dict standing in for the table."""

    def __init__(self):
        self.rows = {}
        self.selects = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        if sql.startswith("SELECT"):
            self.selects += 1
            row = self.rows.get(params["key"])
            return _Result([(row,)] if row is not None else [])
        self.rows.setdefault(params["key"], json.loads(params["response"]))
        return _Result([])


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Counting:
    model = "test-model"
    last_usage = (11, 22)

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def extract(self, text):
        self.calls += 1
        return self.answer


def test_the_same_document_is_never_paid_for_twice():
    inner = _Counting([ITEM])
    cached = CachedExtractor(inner, _Session())
    assert cached.extract("prose") == [ITEM]
    assert cached.extract("prose") == [ITEM]
    assert inner.calls == 1
    assert (cached.hits, cached.misses) == (1, 1)


def test_different_prose_is_a_different_question():
    inner = _Counting([ITEM])
    cached = CachedExtractor(inner, _Session())
    cached.extract("one")
    cached.extract("two")
    assert inner.calls == 2


def test_a_new_prompt_version_misses_the_cache():
    """Otherwise improving the prompt would appear to change nothing, which is
    the most expensive kind of silence."""
    session = _Session()
    inner = _Counting([ITEM])
    CachedExtractor(inner, session, prompt_version="1").extract("prose")
    CachedExtractor(inner, session, prompt_version="2").extract("prose")
    assert inner.calls == 2


def test_an_empty_reading_is_cached_like_any_other():
    """ "No notices in this document" is an answer, and re-asking for it every
    week across 25 sites is how a cache quietly fails to be one."""
    inner = _Counting([])
    cached = CachedExtractor(inner, _Session())
    assert cached.extract("prose") == []
    assert cached.extract("prose") == []
    assert inner.calls == 1


# ------------------------------------------------------- key, prompt, wiring


def test_no_key_means_no_extractor_rather_than_an_error(monkeypatch):
    """A run on a machine with no key has to complete, not half-complete —
    the same way registry.py skips a source with no scraper."""
    from massif import config

    monkeypatch.setattr(config.settings, "anthropic_api_key", "")
    assert build_extractor() is None


def test_a_key_gives_a_client_that_defaults_to_sonnet(monkeypatch):
    from massif import config

    monkeypatch.setattr(config.settings, "anthropic_api_key", "not-a-real-key")
    built = build_extractor()
    assert isinstance(built, AnthropicExtractor)
    assert built.model == DEFAULT_MODEL == "claude-sonnet-5"


PROMPT_FINGERPRINT = "63ab9664022d48e5"


def test_changing_the_prompt_forces_a_version_bump():
    """The prompt and PROMPT_VERSION are one design.

    Every instruction in that prompt exists because a guard in llm.py checks
    it, and the cache is keyed on the version. Editing the wording without
    bumping the version would serve answers to the old question forever, and
    nothing else would notice. Change both, then update this fingerprint.
    """
    digest = hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()[:16]
    assert digest == PROMPT_FINGERPRINT, (
        f"the prompt changed (now {digest}). Bump PROMPT_VERSION in llm.py "
        f"— currently {PROMPT_VERSION!r} — and update PROMPT_FINGERPRINT here."
    )


def test_the_prompt_asks_for_exactly_what_the_guards_check():
    """A prompt that stopped asking for verbatim spans would not fail loudly:
    every reading would simply be rejected downstream and the source would look
    like a lot of documents with nothing in them."""
    lowered = PROMPT.lower()
    assert "json array" in lowered
    assert "copied exactly" in lowered
    assert "own words" in lowered
    assert "empty array" in lowered
    for name in ("closure", "restriction", "opening", "unknown"):
        assert name in lowered


# ------------------------------------- the shape of a real SDK response


class _Block:
    def __init__(self, text, type_="text"):
        self.text = text
        self.type = type_


class _Usage:
    input_tokens = 1234
    output_tokens = 56


class _Response:
    def __init__(self, blocks):
        self.content = blocks
        self.usage = _Usage()


class _FakeAnthropic:
    def __init__(self, response):
        self._response = response
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _wired(extractor, response):
    """Stand in for the SDK client, which is not installed here."""
    fake = _FakeAnthropic(response)
    extractor._client = fake
    return fake


def test_the_text_blocks_of_a_response_are_joined_and_parsed():
    """This is the seam that cannot be checked without a key, so it is pinned
    against the SDK's shape instead: content is a LIST of blocks, and a reply
    split across two of them is one JSON array."""
    payload = json.dumps([ITEM])
    extractor = AnthropicExtractor("k", model="m")
    _wired(extractor, _Response([_Block(payload[:8]), _Block(payload[8:])]))
    assert extractor.extract("prose") == [ITEM]


def test_non_text_blocks_are_ignored():
    extractor = AnthropicExtractor("k", model="m")
    _wired(
        extractor,
        _Response([_Block("ignore me", "thinking"), _Block(json.dumps([ITEM]))]),
    )
    assert extractor.extract("prose") == [ITEM]


def test_usage_is_captured_so_the_cost_of_a_source_can_be_seen_before_scaling():
    extractor = AnthropicExtractor("k", model="m")
    _wired(extractor, _Response([_Block("[]")]))
    extractor.extract("prose")
    assert extractor.last_usage == (1234, 56)


def test_the_prompt_is_sent_as_a_system_prompt_with_the_document_as_the_message():
    """The document is untrusted text from someone else's website. It goes in
    the user turn, never interpolated into the instructions."""
    extractor = AnthropicExtractor("k", model="m")
    fake = _wired(extractor, _Response([_Block("[]")]))
    extractor.extract("DOCUMENT TEXT")
    sent = fake.calls[0]
    assert sent["system"] == PROMPT
    assert sent["messages"] == [{"role": "user", "content": "DOCUMENT TEXT"}]
    assert sent["model"] == "m"
