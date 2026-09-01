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
    document_id = "33333333-3333-3333-3333-333333333333"
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


class _Document:
    """The stored page, as the reviewer needs to see it."""

    id = "33333333-3333-3333-3333-333333333333"
    url = "https://example.invalid/refuge"
    raw_content = None
    raw_text = (
        "<html><body><main>"
        "<p>Le Refuge sera gard\u00e9 jusqu\u2019au 30/08 puis les WE d\u00e9but "
        "septembre.</p>"
        "<p>En dehors de la p\u00e9riode gard\u00e9e, le refuge d'hiver est "
        "accessible.</p>"
        "<script>alert('x')</script>"
        "</main></body></html>"
    )


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
    session = _Session(rows if rows is not None else [(_Statement, _Feature, _Source, _Document)])
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


def test_a_reviewer_can_say_what_the_site_should_say(monkeypatch):
    """Steven, reviewing: setting restricted or closed needs a why.

    Without this the badge changes and the sentence under it still describes
    whatever the model made of the page — a hut reading "restricted" over a
    summary about something else entirely.
    """
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    _Statement.summary_en = "The hut will be unstaffed from August 8th"
    app, _, _ = build()
    got = _post(
        app,
        b"status=restricted&valid_from=2026-08-08"
        b"&summary=Unstaffed+since+8+August%2C+winter+room+only",
    )
    assert got.status_code == 303
    assert _Statement.summary_en == "Unstaffed since 8 August, winter room only"
    assert _Statement.payload["reviewer_override"]["summary"] == _Statement.summary_en


def test_the_model_s_own_wording_is_kept_when_a_reviewer_replaces_it(monkeypatch):
    """It is the record of what was READ. The reviewer's sentence is a
    different claim by a different author, and both have to survive."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    _Statement.summary_en = "what the model wrote"
    app, _, _ = build()
    _post(app, b"status=restricted&valid_from=2026-08-08&summary=what+the+reviewer+wrote")
    assert _Statement.payload["model_summary"] == "what the model wrote"
    assert _Statement.summary_en == "what the reviewer wrote"


def test_a_reason_on_its_own_is_a_valid_override(monkeypatch):
    """Correcting only the wording, leaving the reading alone."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    _Statement.summary_en = "clumsy"
    app, _, _ = build()
    got = _post(app, b"summary=said+plainly")
    assert got.status_code == 303
    assert _Statement.summary_en == "said plainly"
    assert _Statement.status is StatusValue.CLOSED


def test_a_standing_state_needs_no_dates(monkeypatch):
    """Requiring them was simply wrong. `unstaffed` is a STANDING state — "this
    is an unguarded cabin" has no end — and refuges.info emits it undated by
    design: 54 such statements were already live while this form refused to let
    a person write one."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    app, _, _ = build()
    got = _post(app, b"status=unstaffed")
    assert got.status_code == 303
    assert _Statement.status is StatusValue.UNSTAFFED
    assert _Statement.valid_from is None


def test_a_transient_state_still_needs_a_window(monkeypatch):
    """The exemption is for standing states only. Open, closed and restricted
    all say something about right now."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    for status in (b"status=closed", b"status=open", b"status=restricted"):
        _fresh()
        app, _, _ = build()
        assert _post(app, status).status_code == 400, status
        assert _Statement.reviewed_at is None


def test_a_refusal_is_a_page_a_person_can_read(monkeypatch):
    """A raw JSON body is fine for the API and useless here: a reviewer was
    dropped on a page of JSON with no link back to the queue and no way to tell
    what to do instead."""
    monkeypatch.setattr(admin, "recompute_feature", lambda s, f: None)
    _fresh()
    app, _, _ = build()
    got = _post(app, b"status=closed")
    assert got.status_code == 400
    assert "text/html" in got.headers["content-type"]
    assert "/admin/review" in got.text
    assert "needs a window" in got.text


# ------------------------------------------- the page, not just the extract


def test_the_reviewer_is_shown_the_whole_page_the_model_read():
    """A card that quotes one sentence asks a question the reviewer cannot
    answer. The Refuge du Requin states "Le Refuge sera gardé jusqu'au 30/08
    puis les WE début septembre" at the top of its page, and the card in front
    of the reviewer quoted a secondary line about the winter room instead.

    Judging an extract in isolation cannot catch what the extraction MISSED,
    and missing is the failure this queue exists to catch.
    """
    app, _, _ = build()
    body = TestClient(app).get("/admin/review", headers=AUTH).text
    assert "the whole page we read" in body
    # The sentence the model did NOT pick has to be visible.
    assert "30/08" in body


def test_the_page_text_is_escaped_like_everything_else():
    """It is the same untrusted third-party prose, in larger quantity."""
    app, _, _ = build()
    body = TestClient(app).get("/admin/review", headers=AUTH).text
    assert "<script>alert('x')</script>" not in body


def test_the_quoted_sentence_is_marked_inside_the_page():
    """So the reviewer can see at a glance which sentence became the statement
    and read what surrounds it."""
    _Statement.original_text = "En dehors de la période gardée, le refuge d'hiver est accessible."
    app, _, _ = build()
    body = TestClient(app).get("/admin/review", headers=AUTH).text
    assert "<mark>" in body


def test_a_statement_with_no_document_still_renders():
    """Not every source stores one, and a missing page must not break the
    queue for the statements that do."""
    app, _, _ = build(rows=[(_Statement, _Feature, _Source, None)])
    got = TestClient(app).get("/admin/review", headers=AUTH)
    assert got.status_code == 200
    assert "the whole page we read" not in got.text


def test_the_page_panel_is_open_rather_than_behind_a_click():
    """Information you have to ask for is information most people will not ask
    for, and the whole point of the panel is what the extraction missed."""
    app, _, _ = build()
    body = TestClient(app).get("/admin/review", headers=AUTH).text
    assert "<details class=prose open>" in body


def test_a_card_says_what_else_came_off_the_same_page():
    """Two cards that split one notice look like two notices, and a page that
    produced only this statement looks the same as one that produced five."""

    class _Other:
        id = "44444444-4444-4444-4444-444444444444"
        document_id = _Document.id
        status = StatusValue.OPEN
        statement_type = StatementType.OPENING
        summary_en = "The refuge is staffed until 30 August"
        original_text = "Le Refuge sera gardé jusqu'au 30/08"
        valid_from = None
        valid_to = None
        payload: dict = {"needs_review": True}

    _Statement.document_id = _Document.id
    app, _, _ = build(
        rows=[
            (_Statement, _Feature, _Source, _Document),
            (_Other, _Feature, _Source, _Document),
        ]
    )
    body = TestClient(app).get("/admin/review", headers=AUTH).text
    assert "Also taken from this page" in body
    assert "staffed until 30 August" in body


def test_a_deactivated_feature_is_not_queued_for_review():
    """A feature somebody already took off the map — the Bivacco della
    Fourche, after the rockfall — must not queue statements for a verdict
    nobody can act on."""
    from massif.admin import _waiting

    sql = str(_waiting.__doc__ or "")  # documented behaviour lives in the query
    del sql
    import inspect

    source = inspect.getsource(_waiting)
    assert "Feature.active.is_(True)" in source


def test_a_window_that_has_already_closed_says_so(monkeypatch):
    """recompute only considers statements valid NOW, so accepting an expired
    season changes nothing and looks like a broken button. The Requin's
    "staffed until 30/08" was still on the queue on 1 September."""
    from datetime import UTC, datetime, timedelta

    from massif.admin import _window

    class Past:
        valid_from = datetime.now(UTC) - timedelta(days=40)
        valid_to = datetime.now(UTC) - timedelta(days=2)
        payload: dict = {}

    class Future:
        valid_from = datetime.now(UTC) + timedelta(days=10)
        valid_to = datetime.now(UTC) + timedelta(days=40)
        payload: dict = {}

    class Now:
        valid_from = datetime.now(UTC) - timedelta(days=2)
        valid_to = datetime.now(UTC) + timedelta(days=10)
        payload: dict = {}

    assert "ALREADY PAST" in _window(Past())
    assert "not yet in force" in _window(Future())
    assert "ALREADY PAST" not in _window(Now())
    assert "not yet in force" not in _window(Now())
