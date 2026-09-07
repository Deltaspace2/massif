"""What the read API is allowed to import.

`backend/requirements.txt` is the serverless function's dependency list and it
is deliberately a SUBSET of `pyproject.toml`. The point is stated in the file
itself: the API never fetches, parses or resolves anything, it reads rows that
ingest already wrote, and leaving the fetching machinery out makes it
*structurally impossible* to scrape someone's website from a page request.

That property had already been broken by the time this test was written. The
review panel started showing the source page's prose, so `admin.py` imported
`readable_text` from `massif.ingest.llm`, which imports `massif.ingest.base`,
which imports **httpx**. Nothing failed: Vercel installs more than
requirements.txt asks for, so the deployed function booted anyway and the
guarantee was fiction rather than a build error.

The cost of getting this wrong is the whole API, not one endpoint —
`ModuleNotFoundError` at import means every request 500s while the deploy shows
green. DEPLOY.md documents a manual venv check for it; nobody ran it for three
weeks. This runs in the suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# httpx is the one that carries the promise: no HTTP client, no fetching from a
# page request. The others are listed because they are the rest of the ingest
# stack and their absence is what keeps the bundle small — but if one of them
# ever has to be added, that is a judgement call about size, whereas adding
# httpx would retract a stated guarantee.
FETCHING = "httpx"
INGEST_ONLY = ("rapidfuzz", "yaml", "anthropic")

_PROBE = """
import sys, importlib.abc
BLOCK = set(sys.argv[1].split(","))


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCK:
            raise ImportError("BLOCKED: " + name)
        return None


sys.meta_path.insert(0, Blocker())
sys.path.insert(0, ".")
import api.index as m

print("OK", len(m.app.routes))
"""


def _boots_without(*blocked: str) -> subprocess.CompletedProcess:
    """Import the Vercel entry point with those packages made unimportable."""
    return subprocess.run(
        [sys.executable, "-c", _PROBE, ",".join(blocked)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )


def test_the_api_boots_without_an_http_client():
    """The guarantee in requirements.txt, enforced.

    If this fails, `massif.main` has grown a path to the fetching stack — most
    likely by importing something under `massif.ingest` that pulls in
    `massif.ingest.base`. The fix is to move what the API actually needs into a
    module that does not, not to add httpx to requirements.txt: that would
    retract the promise rather than keep it.
    """
    done = _boots_without(FETCHING)
    assert done.returncode == 0, (
        "the read API cannot start without httpx, so it can fetch from a page "
        f"request:\n{done.stderr[-1500:]}"
    )
    assert done.stdout.startswith("OK")


def test_the_api_boots_without_the_rest_of_the_ingest_stack():
    """Cheaper bundle, and the same cold-start failure if it regresses."""
    done = _boots_without(FETCHING, *INGEST_ONLY)
    assert done.returncode == 0, done.stderr[-1500:]


def test_the_probe_can_actually_fail():
    """A test that cannot fail is not a test. Block something `massif.main`
    genuinely needs and confirm the harness reports it."""
    done = _boots_without("sqlalchemy")
    assert done.returncode != 0
    assert "BLOCKED: sqlalchemy" in done.stderr
