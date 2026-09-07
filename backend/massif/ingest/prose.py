"""Turning a fetched page into the prose a human or a model should read.

SPLIT OUT OF `llm.py`, and not for tidiness. `massif/main.py` imports
`massif/admin.py`, which needs `readable_text` to show a reviewer the page a
statement came from. `llm.py` imports `massif.ingest.base` for
`ExtractedStatement`, and `base` imports **httpx** — so the read API could not
start without an HTTP client, which quietly retracted the guarantee written at
the top of `backend/requirements.txt`: that the API cannot fetch anyone's
website from a page request.

Nothing failed when that happened. Vercel installs more than requirements.txt
asks for, so the deployed function booted and the promise became fiction
instead of a build error. `tests/test_cold_start.py` now holds the line.

So this module imports selectolax and the standard library, and nothing else,
for ever. selectolax parses; it cannot fetch. If something here ever needs a
statement type or a date parser, it belongs in `llm.py` instead.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

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
