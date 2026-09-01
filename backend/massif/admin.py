"""A one-person review page, on the API and not on the public site.

The public frontend exists to be crawled. Putting a login on it would add an
auth surface to the SEO surface, and CLAUDE.md rules user accounts out of v1
anyway. This lives on the API project instead: a separate Vercel project, a
separate origin, already talking to the database, and nothing Google looks at.

FOUR THINGS HOLD IT TOGETHER, and each is here because the obvious version is
wrong:

1.  NO TOKEN, NO ROUTES. `include_admin` refuses to mount anything when
    ADMIN_TOKEN is unset. An unconfigured admin must be ABSENT, never open —
    the failure where a missing secret becomes a public write endpoint is the
    one that does not announce itself.

2.  MUTATIONS ARE POST, NEVER GET. Steven's condition, and he is right: a
    crawler, a link preview or a prefetch that reaches a GET accept URL clears
    the queue on its own. Accept and reject are POST-only, so a GET on them is
    405 rather than a decision.

3.  ORIGIN IS CHECKED ON WRITES. Browsers send credentials with a cross-site
    form POST, so Basic auth alone does not stop another page submitting to
    this one. A mutation whose Origin is not this host is refused.

4.  EVERYTHING INTERPOLATED IS ESCAPED. The evidence on this page is verbatim
    text from hut websites — the most untrusted string in the project. It is
    rendered through html.escape, and it is the one place where a source could
    otherwise put script into a page that holds a write token.

Auth is HTTP Basic with the token as the PASSWORD and any username, because a
browser prompts for it natively and it keeps the secret out of the URL, out of
history and out of referrers — which a `?token=` query parameter would not.
"""

from __future__ import annotations

import base64
import html
import secrets
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from massif.config import settings
from massif.db import get_session
from massif.ingest.fr_dates import published_date
from massif.models import Feature, Source, Statement
from massif.status import recompute_feature

router = APIRouter(prefix="/admin", include_in_schema=False)

# Belt and braces. This is not on the crawled origin, but a page carrying a
# write token should say so itself rather than rely on where it happens to live.
NO_INDEX = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"}


def require_token(authorization: str | None = Header(default=None)) -> None:
    """HTTP Basic, constant-time, token as the password.

    401 with a WWW-Authenticate header so a browser offers the prompt rather
    than showing a bare error.
    """
    unauthorised = HTTPException(
        status_code=401,
        detail="admin token required",
        headers={"WWW-Authenticate": 'Basic realm="massif admin"'},
    )
    if not settings.admin_token or not authorization:
        raise unauthorised
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic":
        raise unauthorised
    try:
        _user, _, password = base64.b64decode(encoded).decode("utf-8").partition(":")
    except Exception as error:  # noqa: BLE001 — a malformed header is a refusal
        raise unauthorised from error
    if not secrets.compare_digest(password, settings.admin_token):
        raise unauthorised


def same_origin(request: Request) -> None:
    """Refuse a write whose Origin is not this host.

    Basic credentials travel with a cross-site form POST, so requiring a token
    does not by itself stop another page submitting to this one. Browsers send
    Origin on every POST; a request without one is not a browser form and is
    refused too.
    """
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(status_code=403, detail="no Origin on a write")
    if urlparse(origin).netloc != request.url.netloc:
        raise HTTPException(status_code=403, detail="cross-origin write refused")


def _waiting(session: Session):
    return session.execute(
        select(Statement, Feature, Source)
        .join(Feature, Feature.id == Statement.feature_id)
        .join(Source, Source.id == Statement.source_id)
        .where(
            Statement.payload["needs_review"].as_boolean().is_(True),
            Statement.reviewed_at.is_(None),
            Statement.superseded_at.is_(None),
        )
        .order_by(Statement.observed_at.desc())
    ).all()


def _window(statement: Statement) -> str:
    if not (statement.valid_from or statement.valid_to):
        return "no dates stated"
    start = f"{published_date(statement.valid_from):%d %b %Y}" if statement.valid_from else "—"
    end = f"{published_date(statement.valid_to):%d %b %Y}" if statement.valid_to else "—"
    tail = " (the year is OURS)" if (statement.payload or {}).get("approximate") else ""
    return f"{start} to {end}{tail}"


def _card(statement: Statement, feature: Feature, source: Source) -> str:
    e = html.escape  # every interpolation below is third-party text
    payload = statement.payload or {}
    demoted = payload.get("undated_status")
    # "gave no dates" was printed even when the source plainly gave them and
    # our parser could not read them — Plan Glacier publishes "du Vendredi 12
    # Juin au soir, jusqu'au Mardi 8 Septembre 2026" and the page blamed the
    # refuge for saying nothing. Those are different facts and only one of them
    # is about the source; the other is a bug report about us.
    if demoted and payload.get("dates_text"):
        note = (
            f"<p class=w>Rule 3 demoted this: it wanted to say "
            f"<b>{e(str(demoted))}</b>. The source DID state dates — "
            f"<q>{e(str(payload['dates_text']))}</q> — and we could not read "
            f"them: {e(str(payload.get('dates_rejected') or 'unparsed'))}. "
            f"That is our parser's limit, not the refuge's silence.</p>"
        )
    elif demoted:
        note = (
            f"<p class=w>Rule 3 demoted this: it wanted to say "
            f"<b>{e(str(demoted))}</b> and the source stated no dates at all.</p>"
        )
    else:
        note = ""
    attributed = (
        f"<p class=w>Attributed by {e(str(payload['attributed_by']))}.</p>"
        if payload.get("attributed_by")
        else ""
    )
    page = (
        f'<p><a href="{e(str(payload["url"]))}" rel="noopener nofollow" '
        f'target="_blank">the page it came from</a></p>'
        if payload.get("url")
        else ""
    )
    return f"""
<article>
  <h2>{e(feature.name_default)} <small>{e(feature.slug)}</small></h2>
  <p class=meta>{e(source.slug)} · says <b>{e(statement.status.value)}</b>
     · {e(str(statement.statement_type))} · {e(_window(statement))}</p>
  {note}{attributed}
  <p class=sum>{e(statement.summary_en or "")}</p>
  <blockquote>{e(statement.original_text or "")}</blockquote>
  {page}
  <form method="post" action="/admin/review/{statement.id}/accept">
    <input name="note" placeholder="why (optional)">
    <button class=ok>Accept</button>
  </form>
  <form method="post" action="/admin/review/{statement.id}/reject">
    <button class=no>Reject</button>
  </form>
</article>"""


PAGE = """<!doctype html><meta charset=utf-8>
<meta name=robots content="noindex, nofollow">
<title>massif · review</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:52rem;margin:2rem auto;
   padding:0 1rem;color:#22282e}}
 article{{border:1px solid #e3e7ea;border-radius:10px;padding:1rem 1.2rem;
   margin:1rem 0}}
 h2{{font-size:17px;margin:0 0 .2rem}}
 h2 small{{font-weight:400;color:#9aa2ab;font-size:12px}}
 .meta{{color:#6d7681;font-size:13px;margin:.2rem 0}}
 .sum{{margin:.6rem 0}}
 .w{{color:#8c6d14;font-size:13px;margin:.3rem 0}}
 blockquote{{margin:.6rem 0;padding:.4rem .8rem;border-left:2px solid #e3e7ea;
   color:#4d545c;font-size:14px}}
 form{{display:inline}}
 input{{padding:.3rem .5rem;border:1px solid #c6ccd2;border-radius:6px;
   width:16rem}}
 button{{padding:.35rem .9rem;border-radius:999px;border:1px solid #c6ccd2;
   background:#fff;cursor:pointer}}
 .ok{{border-color:#3d8f63;color:#3d8f63}}
 .no{{border-color:#b23c31;color:#b23c31;margin-left:.4rem}}
 .none{{color:#6d7681}}
</style>
<h1>Statements waiting for a person</h1>
<p class=meta>{count} waiting. A machine read these out of prose; none can take a
status slot until you accept it. Read the quoted evidence, not the summary —
the summary is the only field the model wrote rather than copied.</p>
{cards}"""


@router.get("/review", response_class=HTMLResponse, dependencies=[Depends(require_token)])
def review_page(session: Session = Depends(get_session)) -> HTMLResponse:
    rows = _waiting(session)
    cards = "".join(_card(s, f, src) for s, f, src in rows) or (
        "<p class=none>Nothing waiting.</p>"
    )
    return HTMLResponse(PAGE.format(count=len(rows), cards=cards), headers=NO_INDEX)


async def _note(request: Request) -> str | None:
    """The reviewer's note, out of a plain url-encoded form.

    Parsed by hand rather than with fastapi.Form or request.form(), both of
    which require python-multipart — and adding a dependency to the deployed
    function for a page that is usually not even mounted is the wrong trade.
    An HTML form posts url-encoded by default, which is three lines to read.

    request.form() was tried first and raised in production while every test
    passed, because every test stopped at a 401, 403 or 405 and none of them
    ever completed an accept. The guards were covered and the working path was
    not.
    """
    raw = (await request.body()).decode("utf-8", "replace")
    values = parse_qs(raw).get("note") or []
    value = values[0].strip() if values else ""
    return value or None


def _decide(session: Session, statement_id: str, *, accept: bool, note: str | None):
    statement = session.get(Statement, statement_id)
    if statement is None:
        raise HTTPException(status_code=404, detail="no such statement")
    now = datetime.now(UTC)
    if accept:
        statement.reviewed_at = now
    else:
        # Superseded rather than deleted: the document still holds the page and
        # a better parser can produce the statement again.
        statement.superseded_at = now
    statement.review_note = note or None
    session.flush()
    recompute_feature(session, statement.feature_id)
    return RedirectResponse("/admin/review", status_code=303, headers=NO_INDEX)


@router.post(
    "/review/{statement_id}/accept",
    dependencies=[Depends(require_token), Depends(same_origin)],
)
async def accept(statement_id: str, request: Request, session: Session = Depends(get_session)):
    return _decide(session, statement_id, accept=True, note=await _note(request))


@router.post(
    "/review/{statement_id}/reject",
    dependencies=[Depends(require_token), Depends(same_origin)],
)
async def reject(statement_id: str, request: Request, session: Session = Depends(get_session)):
    return _decide(session, statement_id, accept=False, note=await _note(request))


def include_admin(app) -> bool:
    """Mount the admin routes, but only when there is a token to guard them.

    Returns whether it mounted, so a caller can say so out loud. An
    unconfigured admin is ABSENT, not open: a missing secret must never become
    a public write endpoint.
    """
    if not settings.admin_token:
        return False
    app.include_router(router)
    return True
