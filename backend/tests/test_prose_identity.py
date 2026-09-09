"""A page whose words did not change must not be re-decided.

Everything `hut-sites` produces is written `needs_review`: a person clears each
statement before it can take a status slot. That gate is right — a model read
prose and a human should agree before the site repeats it — but it is only
affordable if each sentence is decided ONCE.

It was not. Measured 9 Sep 2026 across the stored documents:

    trelatete.com   two fetches, HTML of identical length, different checksum
    aneuve.ch       two fetches, two bytes apart
    montourdumontblanc.com  187 bytes apart on an 867 KB page

Extracted, every one of those pairs was character-for-character identical
prose. A token or a timestamp rotates in the markup, `store_document` hashed
the markup, so every weekly run wrote a new document, re-read the same
sentences, produced the same statement, superseded the one the reviewer had
cleared, and put it back in the queue. The model was never re-called —
`llm_cache` keys on the prose — so the only thing being spent was the
reviewer's attention, which is the part that does not scale.

The fix is to say what makes a document THE SAME DOCUMENT. For a source read
as prose, that is the prose.
"""

from __future__ import annotations

import hashlib

from massif.ingest.base import store_document


class _Response:
    def __init__(self, content: bytes, text: str | None = None) -> None:
        self.content = content
        self.text = text if text is not None else content.decode("utf-8", "replace")
        self.headers = {"content-type": "text/html"}
        self.status_code = 200


class _Source:
    id = "11111111-1111-1111-1111-111111111111"
    language = "fr"


class _Session:
    """Remembers documents by (source, hash), like the real uniqueness does."""

    def __init__(self) -> None:
        self.docs: list = []
        self.by_hash: dict[str, object] = {}
        self.lookup: str | None = None

    def scalar(self, query):
        # store_document looks for an existing document by content_hash; the
        # value is in the compiled parameters.
        params = query.compile().params
        wanted = next((v for v in params.values() if isinstance(v, str) and len(v) == 64), None)
        self.lookup = wanted
        return self.by_hash.get(wanted)

    def add(self, obj):
        self.docs.append(obj)
        self.by_hash[obj.content_hash] = obj

    def flush(self):
        pass


PROSE = "Il rifugio è aperto dal 20 giugno al 20 settembre"


def _html(token: str) -> bytes:
    """The same words, with a rotating token in the markup around them."""
    return (
        f"<html><head><meta name='t' content='{token}'></head>"
        f"<body><p>{PROSE}</p></body></html>"
    ).encode()


# ------------------------------------------------------- identity is content


def test_by_default_a_document_is_its_bytes():
    """Unchanged for every source that reads markup. Only a source that reads
    prose should ask for anything else."""
    session = _Session()
    body = b"<html><body>same</body></html>"
    first, new1 = store_document(session, _Source, "https://x.invalid/", _Response(body))
    second, new2 = store_document(session, _Source, "https://x.invalid/", _Response(body))
    assert new1 is True and new2 is False
    assert first is second
    assert first.content_hash == hashlib.sha256(body).hexdigest()


def test_different_bytes_are_a_different_document_by_default():
    session = _Session()
    store_document(session, _Source, "https://x.invalid/", _Response(_html("a")))
    _doc, is_new = store_document(session, _Source, "https://x.invalid/", _Response(_html("b")))
    assert is_new is True, "without an identity, a rotating token makes a new document"


# ------------------------------------------------ identity can be the prose


def test_the_same_prose_in_different_markup_is_the_same_document():
    """The whole point. Two fetches, two checksums, one reading — so one
    decision for the reviewer, not one per week."""
    session = _Session()
    first, new1 = store_document(
        session, _Source, "https://x.invalid/", _Response(_html("a")), identity=PROSE
    )
    second, new2 = store_document(
        session, _Source, "https://x.invalid/", _Response(_html("b")), identity=PROSE
    )
    assert new1 is True
    assert new2 is False, "the words did not change, so this is not a new document"
    assert first is second


def test_changed_prose_is_still_a_new_document():
    """The other half, and the one that must not be lost: when the hut really
    does change its season, that IS a new reading and a person should see it."""
    session = _Session()
    store_document(session, _Source, "https://x.invalid/", _Response(_html("a")), identity=PROSE)
    _doc, is_new = store_document(
        session,
        _Source,
        "https://x.invalid/",
        _Response(_html("a")),
        identity="Il rifugio è chiuso",
    )
    assert is_new is True


def test_the_identity_is_hashed_and_not_stored_raw():
    """`content_hash` is a hash column. Putting prose in it directly would
    both break the uniqueness index and leak page text into a key."""
    session = _Session()
    doc, _ = store_document(
        session, _Source, "https://x.invalid/", _Response(_html("a")), identity=PROSE
    )
    assert doc.content_hash == hashlib.sha256(PROSE.encode("utf-8")).hexdigest()
    assert PROSE not in doc.content_hash


def test_the_raw_bytes_are_still_stored_whatever_the_identity():
    """Identity decides what counts as a change. It does not decide what is
    kept: `documents` is immutable history and re-extraction reads the markup
    back out of it."""
    session = _Session()
    body = _html("a")
    doc, _ = store_document(
        session, _Source, "https://x.invalid/", _Response(body), identity=PROSE
    )
    assert doc.raw_content == body


# ------------------------------- and the source actually uses it that way


class _Feature:
    slug = "refuge-torino"
    feature_type = "hut"
    active = True


class _CollectSession(_Session):
    def scalars(self, _query):
        return [_Feature()]


def test_hut_sites_confirms_instead_of_re_reading_when_the_prose_is_unchanged(monkeypatch):
    """The behaviour the whole change exists for, and it was untested first
    time: deleting the `is_new` check left every other test green.

    Two fetches, different markup, identical words. The first is read; the
    second must come back as None — "unchanged, still standing" — so
    `confirm_still_standing` refreshes the clock and the reviewer's decision
    stays put, instead of a fresh statement superseding it into the queue.
    """
    from massif.ingest.sources import hut_sites as mod

    pages = iter([_Response(_html("a")), _Response(_html("b"))])
    monkeypatch.setattr(mod, "fetch", lambda url: next(pages))
    monkeypatch.setattr(mod, "hut_sites", lambda: {"refuge-torino": "https://x.invalid/"})
    monkeypatch.setattr(mod, "build_extractor", lambda session: object())
    monkeypatch.setattr(
        mod.HutSiteScraper, "_read", lambda self, document, extractor, slug: ["a statement"]
    )

    session = _CollectSession()
    scraper = mod.HutSiteScraper()

    first = scraper.collect(session, _Source)
    assert first[0][1] == ["a statement"], "a page seen for the first time is read"

    second = scraper.collect(session, _Source)
    assert second[0][1] is None, "unchanged prose must confirm, not re-read"
    assert second[0][0] is first[0][0], "and confirm against the document that produced them"
