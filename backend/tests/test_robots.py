"""robots.txt handling.

Conduct, not correctness: "We are guests on these servers." The bug these
exist for made us a bad guest in both directions at once — the first request
to a host with a flaky robots.txt was allowed through, and every request
after it was refused for the life of the process, so a site that had a bad
minute stayed written off until restart.
"""

import http.server
import threading
from contextlib import contextmanager

import pytest

import massif.ingest.base as base


class _Handler(http.server.BaseHTTPRequestHandler):
    body = b"User-agent: *\nDisallow: /private/\n"
    code = 200
    seen_user_agents: list[str] = []

    def do_GET(self):
        type(self).seen_user_agents.append(self.headers.get("User-Agent", ""))
        self.send_response(self.code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if self.code < 400:
            self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@contextmanager
def serving(code=200, body=b"User-agent: *\nDisallow: /private/\n"):
    _Handler.code = code
    _Handler.body = body
    _Handler.seen_user_agents = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _clear_cache():
    base._robots_cache.clear()
    yield
    base._robots_cache.clear()


def test_disallowed_path_is_refused():
    with serving() as root:
        assert base.robots_allows(f"{root}/public/page") is True
        assert base.robots_allows(f"{root}/private/page") is False


def test_missing_robots_txt_allows_everything():
    """404 means no policy was published, which is not the same as a policy
    that forbids us."""
    with serving(code=404) as root:
        assert base.robots_allows(f"{root}/anything") is True


def test_forbidden_robots_txt_disallows_everything():
    """If we may not even read the policy, we do not get to assume consent."""
    with serving(code=403) as root:
        assert base.robots_allows(f"{root}/anything") is False


def test_server_error_is_a_refusal_not_a_licence():
    """The bug. A 503 meant 'proceed' on the first call — we fetched a page
    from a server that was already failing."""
    with serving(code=503) as root:
        assert base.robots_allows(f"{root}/anything") is False


def test_unreachable_host_is_a_refusal():
    # Nothing is listening on this port.
    assert base.robots_allows("http://127.0.0.1:9/anything") is False


def test_verdict_is_stable_across_calls():
    """The sharpest edge of the old behaviour: allowed once, then refused
    forever, so the answer depended on how many times you had asked."""
    with serving(code=503) as root:
        answers = [base.robots_allows(f"{root}/x") for _ in range(4)]
    assert answers == [False, False, False, False]


def test_a_failure_is_retried_rather_than_cached_forever():
    """A transient 503 must not write the host off until the process
    restarts — which is how Chamonix came to be recorded as 'recon blocked'
    when its robots.txt had long since recovered."""
    with serving(code=503) as root:
        assert base.robots_allows(f"{root}/x") is False
        port = root.rsplit(":", 1)[1]

    # Same host and port, now healthy, with the retry window elapsed.
    base._robots_cache[f"http://127.0.0.1:{port}"] = (
        -base.ROBOTS_RETRY_TTL - 1.0,
        None,
    )
    _Handler.code = 200
    server = http.server.HTTPServer(("127.0.0.1", int(port)), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert base.robots_allows(f"http://127.0.0.1:{port}/x") is True
    finally:
        server.shutdown()
        server.server_close()


def test_robots_fetch_identifies_itself():
    """We promise a real User-Agent with a contact URL. The request that asks
    what we are allowed to do is the one where that matters most; urllib's
    default would have announced us as Python-urllib."""
    with serving() as root:
        base.robots_allows(f"{root}/x")
    assert _Handler.seen_user_agents
    assert all("massif" in ua for ua in _Handler.seen_user_agents)


def test_fetch_raises_rather_than_proceeding_when_refused():
    with serving(code=503) as root, pytest.raises(PermissionError):
        base.fetch(f"{root}/anything")


# ------------------------------------------ saying WHICH refusal it was

def test_a_published_disallow_and_an_unreadable_file_are_reported_differently():
    """Both are refusals; they are not the same event.

    aneuve.ch publishes "User-agent: * / Crawl-delay: 10", which allows
    everything. One failed fetch of that file from a CI runner was logged as
    "robots.txt disallows https://www.aneuve.ch/" — so the site was read as
    having refused us when it had done nothing of the kind. The behaviour was
    right and the sentence was wrong.
    """
    with serving(body=b"User-agent: *\nDisallow: /private/\n") as root:
        allowed, why = base.robots_verdict(f"{root}/private/page")
        assert (allowed, why) == (False, "disallowed")
        allowed, why = base.robots_verdict(f"{root}/public/page")
        assert (allowed, why) == (True, "")

    # Nothing listening at all: the policy could not be read.
    allowed, why = base.robots_verdict("http://127.0.0.1:9/anything")
    assert (allowed, why) == (False, "unreadable")


def test_crawl_delay_on_its_own_allows_everything():
    """Verbatim from aneuve.ch. No Disallow anywhere in it."""
    with serving(body=b"User-agent: *\nCrawl-delay: 10\n") as root:
        assert base.robots_verdict(f"{root}/anything") == (True, "")


def test_the_refusal_message_names_which_kind_it_was():
    import pytest

    with serving(body=b"User-agent: *\nDisallow: /\n") as root:
        with pytest.raises(PermissionError) as refused:
            base.fetch(f"{root}/x")
        assert "disallows" in str(refused.value)
        assert "could not read" not in str(refused.value)

    with pytest.raises(PermissionError) as unread:
        base.fetch("http://127.0.0.1:9/x")
    assert "could not read robots.txt" in str(unread.value)
