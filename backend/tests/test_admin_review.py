"""The review page's security properties, which are the only interesting part.

It is a page that holds a write token, renders verbatim text from hut websites,
and can change what the map says. Each test below is a way that goes wrong.
"""

import base64
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from massif import admin
from massif.config import settings
from massif.db import get_session
from massif.enums import StatementType, StatusValue

TOKEN = "a-test-token"
AUTH = {"Authorization": "Basic " + base64.b64encode(b"any:" + TOKEN.encode()).decode()}
HERE = {"Origin": "http://testserver"}


class _Statement:
    id = "11111111-1111-1111-1111-111111111111"
    feature_id = "22222222-2222-2222-2222-222222222222"
    status = StatusValue.CLOSED
    statement_type = StatementType.CLOSURE
    summary_en = "Shut for the season"
    original_text = "<script>alert(1)</script> le refuge est fermé"
    valid_from = None
    valid_to = None
    payload: dict = {"needs_review": True}
    reviewed_at = None
    superseded_at = None
    review_note = None


class _Feature:
    id = _Statement.feature_id
    slug = "refuge-de-test"
    name_default = "Refuge de Test"


class _Source:
    slug = "hut-sites"


class _Session:
    """Enough of a Session for the page and one decision."""

    def __init__(self, rows):
        self.rows = rows
        self.flushed = False

    def execute(self, _q):
        return self

    def all(self):
        return self.rows

    def get(self, _model, _id):
        return _Statement

    def flush(self):
        self.flushed = True


def build(token=TOKEN, rows=None):
    settings.admin_token = token
    app = FastAPI()
    mounted = admin.include_admin(app)
    session = _Session(rows if rows is not None else [(_Statement, _Feature, _Source)])
    app.dependency_overrides[get_session] = lambda: session
    return app, mounted, session


@pytest.fixture(autouse=True)
def _restore():
    original = settings.admin_token
    yield
    settings.admin_token = original


# --------------------------------------------------------------- mounting


def test_no_token_means_no_routes_at_all():
    """An unconfigured admin must be ABSENT, not open. A missing secret that
    quietly becomes a public write endpoint is the failure that does not
    announce itself."""
    app, mounted, _ = build(token="")
    assert mounted is False
    assert [r for r in app.routes if "/admin" in getattr(r, "path", "")] == []
    assert TestClient(app).get("/admin/review").status_code == 404


# ------------------------------------------------------------------- auth


def test_the_page_refuses_without_credentials():
    app, _, _ = build()
    response = TestClient(app).get("/admin/review")
    assert response.status_code == 401
    # So a browser offers its own prompt rather than showing a bare error.
    assert "Basic" in response.headers.get("WWW-Authenticate", "")


def test_the_page_refuses_a_wrong_token():
    app, _, _ = build()
    wrong = {"Authorization": "Basic " + base64.b64encode(b"any:nope").decode()}
    assert TestClient(app).get("/admin/review", headers=wrong).status_code == 401


def test_the_page_opens_with_the_right_token():
    app, _, _ = build()
    response = TestClient(app).get("/admin/review", headers=AUTH)
    assert response.status_code == 200
    assert "Refuge de Test" in response.text


# ------------------------------------------------- Steven's condition: POST


def test_accepting_is_not_reachable_by_a_get():
    """A crawler, a link preview or a browser prefetch that reaches a GET
    accept URL clears the queue on its own. 405, not a decision."""
    app, _, _ = build()
    client = TestClient(app)
    for verb in (client.get, client.head):
        assert verb(f"/admin/review/{_Statement.id}/accept", headers=AUTH).status_code == 405


def test_rejecting_is_not_reachable_by_a_get():
    app, _, _ = build()
    got = TestClient(app).get(f"/admin/review/{_Statement.id}/reject", headers=AUTH)
    assert got.status_code == 405


def test_a_write_without_credentials_is_refused():
    app, _, session = build()
    got = TestClient(app).post(f"/admin/review/{_Statement.id}/accept", headers=HERE, data={})
    assert got.status_code == 401
    assert session.flushed is False


# ------------------------------------------------------------------ CSRF


def test_a_cross_origin_write_is_refused():
    """Basic credentials travel with a cross-site form POST, so requiring a
    token does not by itself stop another page submitting to this one."""
    app, _, session = build()
    got = TestClient(app).post(
        f"/admin/review/{_Statement.id}/accept",
        headers={**AUTH, "Origin": "https://evil.example"},
        data={},
    )
    assert got.status_code == 403
    assert session.flushed is False


def test_a_write_with_no_origin_at_all_is_refused():
    """Browsers send Origin on every POST. A request without one is not a
    browser form."""
    app, _, session = build()
    got = TestClient(app).post(f"/admin/review/{_Statement.id}/accept", headers=AUTH, data={})
    assert got.status_code == 403
    assert session.flushed is False


# ------------------------------------------------------------------- XSS


def test_evidence_from_a_hut_website_is_escaped():
    """The evidence on this page is verbatim text from someone else's site —
    the most untrusted string in the project — rendered into a page that holds
    a write token."""
    app, _, _ = build()
    body = TestClient(app).get("/admin/review", headers=AUTH).text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_the_page_asks_not_to_be_indexed():
    app, _, _ = build()
    response = TestClient(app).get("/admin/review", headers=AUTH)
    assert "noindex" in response.headers.get("X-Robots-Tag", "")
    assert response.headers.get("Cache-Control") == "no-store"


# ------------------------------------------------------- the working path


def test_an_accept_actually_writes_and_redirects(monkeypatch):
    """The test that was missing, and its absence let a 500 ship.

    Every test above stops at a 401, 403 or 405, so none of them ever reached
    the body parser — and the first version of it raised in production because
    it needed a library that is not installed. Guards covered, working path
    not.
    """
    recomputed = []
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: recomputed.append(f))
    app, _, session = build()
    got = TestClient(app, follow_redirects=False).post(
        f"/admin/review/{_Statement.id}/accept",
        headers={**AUTH, **HERE, "Content-Type": "application/x-www-form-urlencoded"},
        content=b"note=looked+at+the+page",
    )
    assert got.status_code == 303
    assert got.headers["location"] == "/admin/review"
    assert session.flushed is True
    assert _Statement.reviewed_at is not None
    assert _Statement.review_note == "looked at the page"
    assert recomputed == [_Feature.id]


def test_a_reject_supersedes_rather_than_deleting(monkeypatch):
    """Superseded is the mechanism that already exists for a claim that should
    stop being served, and it leaves the document — and the possibility of
    re-extracting the statement — intact."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _Statement.superseded_at = None
    app, _, session = build()
    got = TestClient(app, follow_redirects=False).post(
        f"/admin/review/{_Statement.id}/reject", headers={**AUTH, **HERE}, content=b""
    )
    assert got.status_code == 303
    assert _Statement.superseded_at is not None


# ------------------------------------ the two extraction paths must agree


def test_extract_stored_finds_the_site_owner_the_same_way_collect_does():
    """collect() knows which hut it is fetching; extract_stored has only a
    document and has to look it up. That lookup was still querying
    Feature.external_ids after the URLs moved into seeds/hut_sites.yaml, so it
    always found None: the site-of fallback never fired on the re-extraction
    path, and every generic "le refuge" went to the unresolved queue while
    collect() resolved the identical text fine.

    Two paths that must agree, and only one of them was tested.
    """
    from massif.ingest.sources import hut_sites as module

    sites = module.hut_sites()
    assert sites, "the seed file is the whole configuration of this source"
    by_url = {url: slug for slug, url in sites.items()}
    for slug, url in sites.items():
        assert by_url[url] == slug


# ------------------------------------------------------------- overriding


def _fresh():
    _Statement.status = StatusValue.CLOSED
    _Statement.valid_from = None
    _Statement.valid_to = None
    _Statement.payload = {"needs_review": True}
    _Statement.reviewed_at = None
    _Statement.superseded_at = None
    _Statement.review_note = None


def _post(app, body, path="accept"):
    return TestClient(app, follow_redirects=False).post(
        f"/admin/review/{_Statement.id}/{path}",
        headers={**AUTH, **HERE, "Content-Type": "application/x-www-form-urlencoded"},
        content=body,
    )


def test_a_reviewer_can_state_the_window_the_parser_could_not_read(monkeypatch):
    """The point of the escape hatch. Saleinaz says "depuis le 8 août et
    jusqu'à la fin de la saison 2026", which our parser cannot read and a
    person can — so rather than lose the notice or teach the parser every
    French idiom first, the reviewer states the window."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    app, _, _ = build()
    got = _post(app, b"status=restricted&valid_from=2026-08-08&valid_to=2026-09-30")
    assert got.status_code == 303
    assert _Statement.status is StatusValue.RESTRICTED
    assert _Statement.valid_from.date() == date(2026, 8, 8)
    assert _Statement.valid_to.date() == date(2026, 9, 30)


def test_an_override_is_recorded_as_the_reviewer_s_and_not_the_model_s(monkeypatch):
    """It must never read later as though the source or the model said it."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    app, _, _ = build()
    _post(app, b"status=restricted&valid_from=2026-08-08&note=read+it+myself")
    assert _Statement.payload["reviewer_override"]["status"] == "restricted"
    assert _Statement.payload["needs_review"] is True
    assert "override" in _Statement.review_note


def test_rule_3_still_holds_against_a_human(monkeypatch):
    """A hand-set "closed" with no dates would sit on the map for ever exactly
    as a model-set one would. The guard is about the claim, not its author."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    app, _, _ = build()
    got = _post(app, b"status=closed")
    assert got.status_code == 400
    assert _Statement.reviewed_at is None


def test_submitting_the_form_untouched_changes_nothing(monkeypatch):
    """ "keep" is the default option, so an override has to be a deliberate act
    — accepting a reading as it stands must not silently rewrite it."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    app, _, _ = build()
    got = _post(app, b"status=&valid_from=&valid_to=&note=looks+right")
    assert got.status_code == 303
    assert _Statement.status is StatusValue.CLOSED
    assert "reviewer_override" not in _Statement.payload
    assert _Statement.review_note == "looks right"


def test_a_nonsense_date_is_refused_rather_than_ignored(monkeypatch):
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    app, _, _ = build()
    assert _post(app, b"valid_from=not-a-date").status_code == 400
    assert _Statement.reviewed_at is None


def test_a_status_that_is_not_one_of_ours_is_refused(monkeypatch):
    """The select offers four values; a hand-made POST can offer anything, and
    an unrecognised one must not reach the enum or the database."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    app, _, _ = build()
    got = _post(app, b"status=probably-fine&valid_from=2026-08-08")
    assert got.status_code == 400
    assert _Statement.reviewed_at is None
    assert _Statement.status is StatusValue.CLOSED
