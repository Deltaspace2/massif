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
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from massif.config import settings
from massif.db import get_session
from massif.enums import TRANSIENT_STATUSES, ExtractionMethod, StatementType, StatusValue
from massif.ingest.fr_dates import published_date
from massif.ingest.prose import normalise_space, readable_text
from massif.models import Document, Feature, Source, Statement
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
        select(Statement, Feature, Source, Document)
        .join(Feature, Feature.id == Statement.feature_id)
        .join(Source, Source.id == Statement.source_id)
        .outerjoin(Document, Document.id == Statement.document_id)
        .where(
            Statement.payload["needs_review"].as_boolean().is_(True),
            Statement.reviewed_at.is_(None),
            Statement.superseded_at.is_(None),
            # A deactivated feature is one somebody already decided about —
            # the Bivacco della Fourche was taken off the map after the
            # rockfall, and its statements were still queueing for a verdict
            # nobody can act on.
            Feature.active.is_(True),
        )
        .order_by(Statement.observed_at.desc())
    ).all()


def _window(statement: Statement) -> str:
    if not (statement.valid_from or statement.valid_to):
        return "no dates stated"
    start = f"{published_date(statement.valid_from):%d %b %Y}" if statement.valid_from else "—"
    end = f"{published_date(statement.valid_to):%d %b %Y}" if statement.valid_to else "—"
    # These dates are OUR reading, not a date the source printed — and which
    # part is ours varies. "du 15 mars au 15 octobre" gives us the year;
    # "jusqu'à la fin septembre 2026" states its year and leaves us the day,
    # narrowed to the 21st. Saying "the year is ours" named the wrong half for
    # the second, and the reviewer is being told which part to go and check.
    tail = " (OUR reading, not their dates)" if (statement.payload or {}).get("approximate") else ""
    # A window that has already ended cannot change what the site says today:
    # recompute only considers statements valid NOW. Without this a reviewer
    # accepts a season that closed last week and sees nothing happen — the
    # Requin's "staffed until 30/08" was still on the queue on 1 September.
    if statement.valid_to is not None and statement.valid_to < datetime.now(UTC):
        tail += " — ALREADY PAST, accepting it will not change today"
    elif statement.valid_from is not None and statement.valid_from > datetime.now(UTC):
        tail += " — not yet in force"
    return f"{start} to {end}{tail}"


def _would_say(statement: Statement) -> str:
    """Exactly what the site would print if this were accepted.

    Read off the same function the feature page uses, rather than described,
    because a preview that is written separately from the renderer drifts from
    it — and the whole reason to preview is to be shown the real thing.
    """
    # Imported here, not at module scope: main.py imports this module to mount
    # the router, so a top-level import back into it is circular.
    from massif.main import phrase_for_now

    return phrase_for_now(statement, datetime.now(UTC)) or statement.summary_en or ""


def _parsed_day(value: str, *, end: bool) -> datetime | None:
    """A YYYY-MM-DD from a form field, as this codebase encodes a day.

    Midnight to 23:59:59 UTC, matching `fr_dates._at`, so a hand-written date
    and a parsed one mean the same thing and `published_date` reads both back
    the same way. Getting this wrong is how "until 26 septembre" printed as the
    27th, twice.
    """
    if not value:
        return None
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="dates must be YYYY-MM-DD") from None
    if end:
        return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=UTC)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def new_statement(feature, source, fields: dict[str, str], *, now: datetime) -> Statement:
    """A notice a person wrote, against the `manual` source.

    THE SOURCE ALREADY EXISTED. `seeds/sources.yaml` has carried an active
    `manual` entry with no scraper from the beginning — "admin-entered
    statements: hut closures phoned in, things seen in person" — so this was
    always meant to be a real source with a trust weight (0.7, below every
    operator) and the same audit trail as a scraper, rather than an
    untraceable edit to somebody else's row.

    IT IS ALREADY REVIEWED. The review gate exists because a model read a page
    and nobody checked it. A person typing the sentence IS the check, and
    routing it through the queue would ask them to approve their own words —
    and leave it invisible until they did, because the gate keeps unreviewed
    statements out of the status slot.

    RULE 3 IS NOT RELAXED FOR HUMANS. An undated `closed` sits on the map for
    ever whoever typed it, so the same `TRANSIENT_STATUSES` check the review
    card uses applies here, from the same frozenset so the two cannot drift.
    """
    raw_status = (fields.get("status") or "").strip()
    raw_type = (fields.get("statement_type") or "").strip()
    summary = (fields.get("summary") or "").strip()

    if raw_status not in {v.value for v in StatusValue}:
        raise HTTPException(status_code=400, detail=f"unknown status {raw_status!r}")
    if raw_type not in {v.value for v in StatementType}:
        raise HTTPException(status_code=400, detail=f"unknown statement type {raw_type!r}")
    if not summary:
        # The summary is what the site prints. Without it this publishes a
        # coloured status with nothing underneath explaining it.
        raise HTTPException(status_code=400, detail="say what the site should tell a reader")

    valid_from = _parsed_day(fields.get("valid_from") or "", end=False)
    valid_to = _parsed_day(fields.get("valid_to") or "", end=True)
    status = StatusValue(raw_status)
    if status in TRANSIENT_STATUSES and not (valid_from or valid_to):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{raw_status!r} says something about right now, so it needs a "
                "window it is the now of — set at least one date. 'unstaffed' "
                "and 'unknown' are standing states and need none."
            ),
        )

    return Statement(
        feature_id=feature.id,
        source_id=source.id,
        statement_type=StatementType(raw_type),
        status=status,
        severity=int(fields.get("severity") or 0),
        # Rule 10. A person saying it now is both the publication and the
        # confirmation, so the two clocks genuinely coincide here — which is
        # not true of any other source and is worth stating rather than
        # leaving as an accident.
        observed_at=now,
        last_seen_at=now,
        valid_from=valid_from,
        valid_to=valid_to,
        summary_en=summary,
        original_text=summary,
        original_language="en",
        extraction_method=ExtractionMethod.MANUAL,
        reviewed_at=now,
        review_note=(fields.get("note") or "").strip() or None,
        payload={"hand_written": True},
    )


def apply_override(statement: Statement, fields: dict[str, str]) -> str | None:
    """Let a person correct a reading before accepting it.

    The point of the escape hatch: the Cabane de Saleinaz says "depuis le 8
    août et jusqu'à la fin de la saison 2026", which our parser cannot read and
    a person can. Rather than lose the notice or teach the parser every French
    idiom first, the reviewer states the window and it is recorded AS THEIRS.

    RULE 3 STILL HOLDS, FOR THE STATUSES IT IS ABOUT. A hand-set `closed`
    with no dates would sit on the map for ever exactly as a model-set one
    would, so open, closed and restricted all need a window.

    `unstaffed` does not, and requiring it was simply wrong: it is a STANDING
    state, not a claim about the present. refuges.info emits it undated by
    design — "this is an unguarded cabin" has no end — and 54 such statements
    were already live while this form refused to let a person write one.
    `unknown` is exempt for the same reason: it asserts nothing to expire.
    """
    status = fields.get("status") or ""
    start, end = fields.get("valid_from") or "", fields.get("valid_to") or ""
    summary = fields.get("summary") or ""
    if not (status or start or end or summary):
        return None

    changed: dict = {}
    if start or end:
        try:
            if start:
                parsed = date.fromisoformat(start)
                statement.valid_from = datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)
                changed["valid_from"] = start
            if end:
                parsed = date.fromisoformat(end)
                statement.valid_to = datetime(
                    parsed.year, parsed.month, parsed.day, 23, 59, 59, tzinfo=UTC
                )
                changed["valid_to"] = end
        except ValueError:
            raise HTTPException(status_code=400, detail="dates must be YYYY-MM-DD") from None

    if status:
        if status not in {v.value for v in StatusValue}:
            raise HTTPException(status_code=400, detail=f"unknown status {status!r}")
        if StatusValue(status) in TRANSIENT_STATUSES and not (
            statement.valid_from or statement.valid_to
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{status!r} says something about right now, so it needs a "
                    "window it is the now of — set at least one date. "
                    "'unstaffed' and 'unknown' are standing states and need none."
                ),
            )
        statement.status = StatusValue(status)
        changed["status"] = status

    payload = dict(statement.payload or {})

    if summary:
        # What the SITE will say, not a note to ourselves. A reviewer who moves
        # a hut to restricted has to be able to say why in the words a reader
        # sees — otherwise the badge changes and the sentence under it still
        # describes whatever the model made of the page.
        #
        # The model's wording is kept alongside, captured BEFORE the
        # replacement: it is the record of what was read, and the reviewer's
        # sentence is a different claim by a different author. Only the first
        # override captures it, so re-editing does not overwrite the original
        # with the previous edit.
        payload.setdefault("model_summary", statement.summary_en)
        statement.summary_en = summary
        changed["summary"] = summary

    payload["reviewer_override"] = changed
    statement.payload = payload
    return ", ".join(f"{k}={v}" for k, v in changed.items())


# How much of the page to show around the quoted sentence. Whole pages here
# are 1-4k characters of prose, so this is usually all of it.
CONTEXT_CHARS = 6000


def _source_prose(
    document: Document | None,
    evidence: str,
    lang: str = "fr",
    also: list[str] | None = None,
) -> tuple[str, str]:
    """The page as the model read it, with the quoted sentence marked.

    A card used to show one sentence and ask whether to publish it, which is
    the wrong question to be able to answer: the Refuge du Requin states
    "Le Refuge sera gardé jusqu'au 30/08 puis les WE début septembre" at the
    top of its page, and the card in front of the reviewer quoted only a
    secondary line about the winter room. Judging an extract in isolation
    cannot catch what the extraction MISSED, and missing is the failure mode
    this queue exists to catch.

    Marked rather than merely shown, so the reviewer can see at a glance which
    sentence became the statement and read what surrounds it.
    """
    if document is None:
        return "", ""
    raw = document.raw_text or (document.raw_content or b"").decode("utf-8", "replace")
    prose = readable_text(raw)[:CONTEXT_CHARS]
    if not prose:
        return "", ""
    marked = html.escape(prose)
    quoted = html.escape(normalise_space(evidence or ""))
    if quoted and quoted in marked:
        marked = marked.replace(quoted, f"<mark>{quoted}</mark>", 1)
    # Every OTHER sentence the extraction took off this page, marked faintly.
    #
    # Steven, looking at Plan Glacier: why did it not highlight both facts? It
    # had read both — "ouverture du 12 juin au 8 septembre" and "Automne /
    # Hiver / Printemps : ouvert mais non gardé" — as two separate cards, and
    # each card marked only its own sentence. So the panel looked as though
    # the second fact had been missed.
    #
    # With the others marked too, what is left UNMARKED is what nothing read,
    # which is the question this panel exists to answer.
    for other in also or []:
        span = html.escape(normalise_space(other))
        if span and span in marked and f"<mark>{span}</mark>" not in marked:
            marked = marked.replace(span, f"<mark class=other>{span}</mark>", 1)
    return marked, prose


def _document_statements(session: Session | None, statement: Statement) -> list:
    """Everything ever taken off this page, whatever became of it.

    The queue holds only what is still WAITING, so a page whose other notice
    was accepted last week showed no siblings at all — and looked identical to
    a page that produced one statement. A reviewer needs the whole set.
    """
    if session is None or statement.document_id is None:
        return []
    return list(
        session.scalars(
            select(Statement)
            .where(
                Statement.document_id == statement.document_id,
                Statement.id != statement.id,
                # LIVE only. Every re-extraction supersedes the previous set
                # and writes a fresh one, so a document that has been re-read
                # six times carries six retired copies of every statement —
                # the Abri Simond listed twenty siblings, nearly all of them
                # its own history.
                Statement.superseded_at.is_(None),
            )
            .order_by(Statement.observed_at)
        )
    )


def _siblings(others: list) -> str:
    """The other statements taken from the same page, and where each stands.

    A reviewer deciding on one sentence needs to know what else the page
    produced — two cards that split one notice look like two notices, and an
    already-accepted sibling explains why this card seems to ignore half the
    page.
    """
    if not others:
        return ""
    items = ""
    for other in others:
        # Only two states can appear: a superseded statement is filtered out
        # above. Calling those "rejected" was wrong anyway — supersession is
        # what re-extraction does, not a verdict anybody reached.
        state = "accepted" if other.reviewed_at is not None else "waiting"
        items += (
            f"<li><b>{html.escape(state)}</b> · "
            f"{html.escape(other.status.value)} — "
            f"{html.escape((other.summary_en or '')[:110])}</li>"
        )
    return f"<p class=w>Also taken from this page:</p><ul class=sib>{items}</ul>"


def _translated(prose: str, session) -> str | None:
    """The page in English, or None when we cannot ask.

    Imported HERE rather than at module scope, and that is not a style choice.
    `llm_client` reaches `massif.ingest.base`, which imports httpx — so a
    module-level import would mean the read API could not start without an HTTP
    client, retracting the guarantee at the top of `backend/requirements.txt`
    that it cannot fetch anyone's website from a page request. The API is
    deployed without httpx; only the admin project needs it, and only when a
    reviewer opens a card.

    ImportError therefore joins "no API key" as a normal outcome rather than an
    error: both mean no translation, the original is always on the page
    already, and `_card` already renders that case.
    """
    if not prose or session is None:
        return None
    try:
        from massif.ingest.llm_client import translate
    except ImportError:
        return None
    return translate(prose, session)


def _card(
    statement: Statement,
    feature: Feature,
    source: Source,
    document: Document | None = None,
    rows: list | None = None,
    session: Session | None = None,
) -> str:
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
    # "keep" first and selected, so submitting the form untouched changes
    # nothing — an override must be a deliberate act, never a default.
    options = '<option value="">keep</option>' + "".join(
        f'<option value="{v.value}">{v.value}</option>' for v in StatusValue
    )
    from_value = f"{published_date(statement.valid_from):%Y-%m-%d}" if statement.valid_from else ""
    to_value = f"{published_date(statement.valid_to):%Y-%m-%d}" if statement.valid_to else ""
    # The source's own language, so a browser knows this is not English and —
    # with translate="no" below — leaves it alone.
    lang = statement.original_language or "fr"
    others = _document_statements(session, statement)
    siblings = _siblings(others)
    marked, plain = _source_prose(
        document,
        statement.original_text or "",
        lang,
        [o.original_text or "" for o in others],
    )
    # Asked for once per page and then cached on content, so opening the queue
    # again costs nothing. None when there is no key, which is not an error:
    # the original is always there and the translation is the extra.
    english = _translated(plain, session)
    context = ""
    if marked:
        english_block = (
            f"<div class=en>{html.escape(english)}</div>"
            if english
            else "<div class=en><i>no translation available — no API key</i></div>"
        )
        context = (
            # Collapsed by default; English first inside it, because a reviewer
            # who does not read French cannot use the panel at all otherwise.
            # The original is one button away and is what the guards checked
            # and what the decision is finally about — a translation is OURS,
            # and is labelled as such.
            "<details class=prose><summary>the whole page we read "
            f"({len(plain)} characters) — check what is NOT here</summary>"
            "<div class=swap>"
            "<button type=button class=swapbtn>show the original</button>"
            " <span class=note>machine translation; the original is what counts</span>"
            "</div>"
            f"{english_block}"
            f'<div class=fr hidden lang="{lang}" translate="no" '
            f'class="notranslate">{marked}</div>'
            "</details>"
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
  <blockquote lang="{lang}" translate="no" class="notranslate">
    {e(statement.original_text or "")}</blockquote>
  {page}
  {siblings}
  {context}
  <p class=pre>If accepted the site says:
     <b>{e(statement.status.value)}</b> — {e(_would_say(statement))}</p>
  <form method="post" action="/admin/review/{statement.id}/accept">
    <fieldset>
      <legend>override (optional — your reading, recorded as yours)</legend>
      <label>status
        <select name="status">{options}</select></label>
      <label>from <input type="date" name="valid_from" value="{from_value}"></label>
      <label>to <input type="date" name="valid_to" value="{to_value}"></label>
      <label class=wide>what the site should say
        <textarea name="summary" rows="3"
          placeholder="leave blank to keep the reading above &#10;\
Enter accepts · Shift+Enter starts a new line"></textarea></label>
    </fieldset>
    <input name="note" placeholder="why (optional)">
    <button class=ok>Accept</button>
  </form>
  <form method="post" action="/admin/review/{statement.id}/reject">
    <button class=no>Reject</button>
  </form>
</article>"""


PAGE = """<!doctype html><html lang=en><meta charset=utf-8>
<!-- Vercel Web Analytics, the framework-agnostic way: this app is
     FastAPI, so the @vercel/analytics React component the dashboard
     suggests cannot apply here. The script 404s harmlessly anywhere but
     the Vercel deployment, and counts nothing beyond page views. -->
<script defer src="/_vercel/insights/script.js"></script>
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
 input,textarea{{padding:.3rem .5rem;border:1px solid #c6ccd2;border-radius:6px;
   width:16rem;font:inherit}}
 textarea{{resize:vertical;min-height:3.4rem}}
 label.wide textarea{{width:100%}}
 button{{padding:.35rem .9rem;border-radius:999px;border:1px solid #c6ccd2;
   background:#fff;cursor:pointer}}
 .ok{{border-color:#3d8f63;color:#3d8f63}}
 .no{{border-color:#b23c31;color:#b23c31;margin-left:.4rem}}
 .none{{color:#6d7681}}
 details.prose{{margin:.6rem 0;font-size:13px}}
 details.prose summary{{cursor:pointer;color:#6d7681;font-size:12.5px}}
 details.prose div{{margin-top:.5rem;padding:.7rem .9rem;background:#f4f6f8;
   border-radius:8px;white-space:pre-wrap;color:#4d545c;max-height:22rem;
   overflow:auto}}
 mark{{background:#f4f0e4;color:#22282e;padding:0 .1rem}}
 .swap{{margin:.5rem 0 .2rem}}
 .swapbtn{{padding:.2rem .6rem;font-size:12px;border-radius:999px;
   border:1px solid #c6ccd2;background:#fff;cursor:pointer}}
 .note{{font-size:11.5px;color:#9aa2ab}}
 .en,.fr{{margin-top:.4rem;padding:.7rem .9rem;background:#f4f6f8;
   border-radius:8px;white-space:pre-wrap;color:#4d545c;max-height:22rem;
   overflow:auto}}
 [hidden]{{display:none}}
 ul.sib{{margin:.2rem 0 .6rem;padding-left:1.1rem;font-size:12.5px;
   color:#6d7681}}
 mark.other{{background:#eef1f3;color:#6d7681}}
 .pre{{background:#f4f6f8;border-radius:6px;padding:.5rem .7rem;font-size:13.5px;
   margin:.7rem 0}}
 fieldset{{border:1px dashed #c6ccd2;border-radius:8px;padding:.5rem .7rem;
   margin:.6rem 0;display:inline-block}}
 legend{{font-size:11.5px;color:#9aa2ab;padding:0 .3rem}}
 label{{font-size:12.5px;color:#6d7681;margin-right:.7rem}}
 label.wide{{display:block;margin-top:.5rem}}
 label.wide input{{width:26rem;display:block;margin-top:.2rem}}
 select,input[type=date]{{padding:.25rem .4rem;border:1px solid #c6ccd2;
   border-radius:6px;width:auto;font:inherit;font-size:12.5px}}
</style>
<h1>Statements waiting for a person</h1>
<script>
/* One button per card, swapping the English for the original. Inline and
   five lines because this page has no build step and does not want one. */
addEventListener("click", function (event) {{
  var button = event.target.closest(".swapbtn");
  if (!button) return;
  var box = button.closest("details");
  var en = box.querySelector(".en");
  var fr = box.querySelector(".fr");
  var showingEnglish = !en.hidden;
  en.hidden = showingEnglish;
  fr.hidden = !showingEnglish;
  button.textContent = showingEnglish
    ? "show the English translation"
    : "show the original";
}});

/* "What the site should say" is a textarea so a reviewer can write more than
   one line — Steven asked for shift+enter. It was an <input>, where Enter
   accepted the card, and turning it into a plain textarea would have quietly
   taken that away: Enter would insert a newline and the reviewer would be
   hunting for the button. So both are kept, the way every chat box does it. */
addEventListener("keydown", function (event) {{
  if (event.key !== "Enter" || event.shiftKey) return;
  var box = event.target;
  if (box.tagName !== "TEXTAREA" || box.name !== "summary") return;
  event.preventDefault();
  box.form.requestSubmit();
}});
</script>
<p class=meta><a href="/admin/edit">write or correct a statement &rarr;</a></p>
<p class=meta>{count} waiting. A machine read these out of prose; none can take a
status slot until you accept it. Read the quoted evidence, not the summary —
the summary is the only field the model wrote rather than copied.</p>
{cards}"""


@router.get("/review", response_class=HTMLResponse, dependencies=[Depends(require_token)])
def review_page(session: Session = Depends(get_session)) -> HTMLResponse:
    rows = _waiting(session)
    cards = "".join(_card(s, f, src, d, rows, session) for s, f, src, d in rows) or (
        "<p class=none>Nothing waiting.</p>"
    )
    return HTMLResponse(PAGE.format(count=len(rows), cards=cards), headers=NO_INDEX)


async def _fields(request: Request) -> dict[str, str]:
    """The submitted form, url-encoded, parsed by hand.

    Parsed this way rather than with fastapi.Form or request.form(), both of
    which require python-multipart — and adding a dependency to the deployed
    function for a page that is usually not even mounted is the wrong trade.

    request.form() was tried first and raised in production while every test
    passed, because every test stopped at a 401, 403 or 405 and none of them
    ever completed an accept.
    """
    raw = (await request.body()).decode("utf-8", "replace")
    # A browser sends every textarea line break as CRLF, per the URL-encoded
    # form spec. Left alone, the carriage returns ride into `summary_en`, the
    # API and the rendered page, where they are invisible until something
    # splits on "\n" and finds a trailing "\r" on every line.
    return {k: v[0].replace("\r\n", "\n").strip() for k, v in parse_qs(raw).items() if v}


ERROR_PAGE = """<!doctype html><html lang=en><meta charset=utf-8>
<script defer src="/_vercel/insights/script.js"></script>
<meta name=robots content="noindex, nofollow">
<title>massif · review</title>
<style>
 body{{font:15px/1.6 system-ui,sans-serif;max-width:38rem;margin:4rem auto;
   padding:0 1rem;color:#22282e}}
 p.msg{{background:#fdf9ef;border:1px solid #d8bd7a;border-radius:8px;
   padding:.8rem 1rem}}
</style>
<h1>That change was not applied</h1>
<p class=msg>{message}</p>
<p><a href="/admin/review">← back to the queue</a></p>"""


def _error(message: str) -> HTMLResponse:
    """A refusal a person can read, with a way back.

    A raw JSON body is fine for the API and useless here: a reviewer who set a
    status the guard would not take was dropped on a page of JSON with no link
    back to the queue and no way to tell what to do instead.
    """
    return HTMLResponse(
        ERROR_PAGE.format(message=html.escape(message)), status_code=400, headers=NO_INDEX
    )


def _decide(
    session: Session,
    statement_id: str,
    *,
    accept: bool,
    note: str | None,
    fields: dict[str, str] | None = None,
):
    statement = session.get(Statement, statement_id)
    if statement is None:
        raise HTTPException(status_code=404, detail="no such statement")
    now = datetime.now(UTC)
    if accept:
        try:
            overridden = apply_override(statement, fields or {})
        except HTTPException as refusal:
            return _error(str(refusal.detail))
        if overridden:
            # Said in the note as well as the payload, so the decision reads as
            # a decision in the one place a person will look at it again.
            note = f"[override {overridden}] {note or ''}".strip()
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
    fields = await _fields(request)
    return _decide(
        session,
        statement_id,
        accept=True,
        note=fields.get("note") or None,
        fields=fields,
    )


@router.post(
    "/review/{statement_id}/reject",
    dependencies=[Depends(require_token), Depends(same_origin)],
)
async def reject(statement_id: str, request: Request, session: Session = Depends(get_session)):
    fields = await _fields(request)
    return _decide(session, statement_id, accept=False, note=fields.get("note") or None)


# ---------------------------------------------------------------- writing


EDIT_PAGE = """<!doctype html><html lang=en><meta charset=utf-8>
<script defer src="/_vercel/insights/script.js"></script>
<meta name=robots content="noindex, nofollow">
<title>massif · write</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:52rem;margin:2rem auto;
   padding:0 1rem;color:#22282e}}
 h1{{font-size:19px;margin:0 0 .2rem}}
 h2{{font-size:13px;letter-spacing:.14em;text-transform:uppercase;
   color:#6d7681;margin:2rem 0 .6rem}}
 article{{border:1px solid #e3e7ea;border-radius:10px;padding:1rem 1.2rem;
   margin:.7rem 0}}
 .meta{{color:#6d7681;font-size:13px;margin:.2rem 0}}
 .warn{{background:#f4f0e4;border-radius:8px;padding:.7rem .9rem;
   font-size:13px;color:#4d545c;margin:.6rem 0}}
 label{{display:inline-block;margin:.3rem .8rem .3rem 0;font-size:12.5px;
   color:#6d7681}}
 label.wide{{display:block}}
 input,select,textarea{{display:block;padding:.3rem .5rem;border:1px solid #c6ccd2;
   border-radius:6px;font:inherit;width:16rem}}
 label.wide textarea,label.wide input{{width:100%}}
 textarea{{resize:vertical;min-height:3.2rem}}
 fieldset{{border:1px dashed #c6ccd2;border-radius:8px;padding:.5rem .9rem}}
 button{{padding:.35rem .9rem;border-radius:999px;border:1px solid #3d8f63;
   background:#fff;color:#3d8f63;cursor:pointer;margin-top:.6rem}}
 .said{{font-size:14px;margin:.3rem 0}}
 .src{{font-size:11.5px;color:#9aa2ab;letter-spacing:.04em}}
 a{{color:#22282e}}
</style>
<h1>Write or correct a statement</h1>
<p class=meta><a href="/admin/review">&larr; back to the review queue</a></p>
{write}
<h2>Currently in force &mdash; {live} statements</h2>
<p class=meta>Editing one of these changes what the site says now. Rule 3 still
applies: open, closed and restricted need a window; unstaffed and unknown do
not.</p>
{cards}"""


def _feature_choices(session: Session) -> str:
    rows = session.scalars(
        select(Feature).where(Feature.active.is_(True)).order_by(Feature.slug)
    ).all()
    return "".join(
        f'<option value="{html.escape(f.slug)}">{html.escape(f.name_default)}</option>'
        for f in rows
    )


def _options(values, selected: str = "") -> str:
    return "".join(
        f'<option value="{v}"{" selected" if v == selected else ""}>{v}</option>'
        for v in values
    )


def _write_form(session: Session) -> str:
    """The form for a notice no source publishes.

    Against the `manual` source, which has existed in seeds/sources.yaml from
    the beginning and never had a way to write to it: "admin-entered
    statements: hut closures phoned in, things seen in person". Trust 0.7, so
    it sits below every operator and mairie — a phoned-in note should lose to
    the commune's own decree, not overwrite it.
    """
    return f"""<article>
  <h2 style="margin-top:0">New statement</h2>
  <p class=meta>Goes in as <b>manual</b> &mdash; trust 0.7, below every operator
     and mairie, so it never overwrites what a commune published. It is live
     immediately: you writing it is the review.</p>
  <form method="post" action="/admin/write">
    <fieldset>
      <label class=wide>feature
        <select name="feature" required>{_feature_choices(session)}</select></label>
      <label>kind
        <select name="statement_type">{_options(v.value for v in StatementType)}</select></label>
      <label>status
        <select name="status">{_options(v.value for v in StatusValue)}</select></label>
      <label>from <input type="date" name="valid_from"></label>
      <label>to <input type="date" name="valid_to"></label>
      <label class=wide>what the site should say
        <textarea name="summary" rows="2"
          placeholder="Enter saves &middot; Shift+Enter starts a new line"></textarea></label>
      <label class=wide>why you know this (optional, kept with the statement)
        <input name="note"></label>
    </fieldset>
    <button>Publish it</button>
  </form>
</article>"""


def _live_statements(session: Session):
    """Everything currently in force, newest first.

    Not the review queue: these are already published, and correcting one
    changes what the site says right now.
    """
    now = datetime.now(UTC)
    return session.execute(
        select(Statement, Feature, Source)
        .join(Feature, Feature.id == Statement.feature_id)
        .join(Source, Source.id == Statement.source_id)
        .where(
            Statement.superseded_at.is_(None),
            Feature.active.is_(True),
            (Statement.valid_from.is_(None)) | (Statement.valid_from <= now),
            (Statement.valid_to.is_(None)) | (Statement.valid_to >= now),
        )
        .order_by(desc(Statement.observed_at))
        .limit(200)
    ).all()


def _edit_card(statement: Statement, feature: Feature, source: Source) -> str:
    e = html.escape
    hand = (statement.payload or {}).get("hand_written")
    start = f"{published_date(statement.valid_from):%Y-%m-%d}" if statement.valid_from else ""
    end = f"{published_date(statement.valid_to):%Y-%m-%d}" if statement.valid_to else ""
    # A correction to a scraped statement is not permanent: reextract retires
    # every statement of a document and writes the parser's version again.
    # Saying so beats letting someone discover it when their wording vanishes.
    fragile = (
        ""
        if hand
        else (
            "<p class=warn>This came from a scraper. Re-extracting "
            f"<b>{e(source.slug)}</b> retires every statement of its document and "
            "writes the parser's version again, so a correction here can be "
            "overwritten. For something that must stick, publish a "
            "<b>manual</b> statement above instead.</p>"
        )
    )
    return f"""<article>
  <div class=src>{e(source.slug)}{" &middot; hand-written" if hand else ""}</div>
  <b>{e(feature.name_default)}</b>
  <p class=meta>says <b>{e(statement.status.value)}</b> &middot;
     {e(str(statement.statement_type))} &middot; {e(_window(statement))}</p>
  <p class=said>{e(statement.summary_en or "")}</p>
  {fragile}
  <form method="post" action="/admin/edit/{statement.id}">
    <fieldset>
      <legend style="font-size:11.5px;color:#6d7681">correct it</legend>
      <label>status
        <select name="status"><option value="">keep</option>
          {_options(v.value for v in StatusValue)}</select></label>
      <label>from <input type="date" name="valid_from" value="{start}"></label>
      <label>to <input type="date" name="valid_to" value="{end}"></label>
      <label class=wide>what the site should say
        <textarea name="summary" rows="2"
          placeholder="leave blank to keep the wording above"></textarea></label>
    </fieldset>
    <input name="note" placeholder="why (optional)" style="width:100%;margin-top:.4rem">
    <button>Save</button>
  </form>
</article>"""


@router.get("/edit", response_class=HTMLResponse, dependencies=[Depends(require_token)])
def edit_page(session: Session = Depends(get_session)) -> HTMLResponse:
    rows = _live_statements(session)
    cards = "".join(_edit_card(st, f, src) for st, f, src in rows) or (
        "<p class=meta>Nothing in force.</p>"
    )
    return HTMLResponse(
        EDIT_PAGE.format(write=_write_form(session), live=len(rows), cards=cards),
        headers=NO_INDEX,
    )


@router.post("/write", dependencies=[Depends(require_token), Depends(same_origin)])
async def write(request: Request, session: Session = Depends(get_session)):
    fields = await _fields(request)
    feature = session.scalar(select(Feature).where(Feature.slug == fields.get("feature", "")))
    if feature is None:
        return _error("no such feature")
    source = session.scalar(select(Source).where(Source.slug == "manual"))
    if source is None:
        # Seeded from sources.yaml. If it is missing the seed has not been run
        # against this database, and inventing the row here would create a
        # source with no trust weight and no notes.
        return _error("the 'manual' source is not seeded in this database")
    try:
        statement = new_statement(feature, source, fields, now=datetime.now(UTC))
    except HTTPException as refusal:
        return _error(str(refusal.detail))
    # Imported here, not at module scope. `massif.ingest.base` imports httpx,
    # and the read API is deployed without it — a module-level import would
    # retract the guarantee in requirements.txt that it cannot fetch from a
    # page request. tests/test_cold_start.py caught this one commit after it
    # was written to catch exactly this.
    from massif.ingest.base import retire_replaced

    # The same rule every ingest run applies: one source does not accumulate
    # opinions about a feature, it updates its own.
    retire_replaced(session, statement)
    session.add(statement)
    session.flush()
    recompute_feature(session, feature.id)
    return RedirectResponse("/admin/edit", status_code=303, headers=NO_INDEX)


@router.post("/edit/{statement_id}", dependencies=[Depends(require_token), Depends(same_origin)])
async def edit(statement_id: str, request: Request, session: Session = Depends(get_session)):
    fields = await _fields(request)
    statement = session.get(Statement, statement_id)
    if statement is None:
        raise HTTPException(status_code=404, detail="no such statement")
    try:
        changed = apply_override(statement, fields)
    except HTTPException as refusal:
        return _error(str(refusal.detail))
    if changed:
        note = (fields.get("note") or "").strip()
        statement.review_note = f"[edited {changed}] {note}".strip()
    session.flush()
    recompute_feature(session, statement.feature_id)
    return RedirectResponse("/admin/edit", status_code=303, headers=NO_INDEX)


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
