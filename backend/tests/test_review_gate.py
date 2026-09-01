"""A statement a model produced must not take a status slot on its own.

llm.py calls this the fourth guard and describes it as the answer to
MISREADING — the failure the other three cannot catch, because a misread
statement fabricates nothing and quotes the document correctly. Its docstring
said the API kept such statements out of the status slot.

Nothing checked it. `needs_review` was written into every model-produced
payload and read by no query in the project, so a reading that survived the
other three guards would have taken a status slot on the same terms as an
arrêté. It was found by wiring up the first source that produces them.

Asserted against the compiled query because this suite has no database — and a
filter nobody can test is how this one came to be missing.
"""

import uuid
from datetime import UTC, datetime

from massif.status import current_statements

# literal_binds because the JSON key is otherwise a bound parameter and the
# word "needs_review" never appears in the compiled string — which is exactly
# how a missing filter would look like a present one.
SQL = str(
    current_statements(uuid.uuid4(), datetime.now(UTC)).compile(
        compile_kwargs={"literal_binds": True}
    )
)


def test_the_winner_query_excludes_statements_awaiting_review():
    assert "payload['needs_review'] IS NOT true" in SQL


def test_it_still_filters_on_validity_and_supersession():
    """The gate is an addition, not a replacement — a query that only checked
    needs_review would let an expired arrêté win."""
    # The PREDICATES, not the column names — every one of these also appears
    # in the SELECT list, so `"valid_from" in SQL` passes with the filter
    # deleted. That version of this test did.
    assert "superseded_by IS NULL" in SQL
    assert "superseded_at IS NULL" in SQL
    assert "valid_from IS NULL OR" in SQL
    assert "valid_to IS NULL OR" in SQL


def test_the_gate_is_on_the_status_winner_and_not_a_blanket_filter():
    """These statements must still be visible as notices and history. The
    point of the gate is that the site gains the information immediately and
    the verdict later, so nothing here may make them disappear."""
    from pathlib import Path

    from massif import main

    # The notices and history queries live in main.py and must NOT grow a
    # needs_review filter of their own.
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "needs_review" not in source
