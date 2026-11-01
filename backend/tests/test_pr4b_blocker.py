"""PR 4b, step 3: "No file has been read yet" shows only when no file of the audit has the status read."""
import asyncio

import pytest

pytest.importorskip("fastapi")

import test_llm_gateway as t  # noqa: E402
from app import readings  # noqa: E402

AUDIT_ID = "a1"
NOT_READ_TEXT = "No file has been read yet: upload a file and run the audit."


def blockers(checks):
    import server
    db = t.FakeDB()
    db["audits"].docs.append({"id": AUDIT_ID, "company_name": "TestCo", "results": None})
    for n, status in enumerate(checks):
        db[readings.CHECKS].docs.append({"audit_id": AUDIT_ID, "file_hash": f"h{n}", "status": status})
    saved, server.db = server.db, db
    try:
        return asyncio.run(server._blocker_list(AUDIT_ID, db["audits"].docs[0]))
    finally:
        server.db = saved


@pytest.mark.parametrize("checks, shown", [
    ([], True),                                     # nothing uploaded
    (["not_read"], True),                           # the only file was not read
    (["none", "not_read"], True),
    (["read"], False),                              # one file read
    (["not_read", "read"], False),                  # a second file that was not read does not bring the line back
    (["read", "none", "read"], False),
])
def test_the_no_file_read_line_shows_only_when_no_file_has_status_read(checks, shown):
    texts = [b["text"] for b in blockers(checks) if b["kind"] == "revenue_file_missing"]
    assert (texts == [NOT_READ_TEXT]) is shown and (not texts) is (not shown)
