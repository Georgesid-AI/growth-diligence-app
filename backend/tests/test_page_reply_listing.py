"""A stored page-read reply that uses the full schema is listed, never a 500 (George, 2026-10-23: GET /decks raised ValueError after a page read).
Also the unexpected-error log line names the exception message and the last traceback frame, never the request or deck content."""
import json
import logging
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("fastapi")
pytest.importorskip("pdfplumber")

import test_llm_gateway as t  # noqa: E402
from pdf_support import pdf_page  # noqa: E402
from test_chat_upload import AUDIT, SAMPLE  # noqa: E402

from app import decks  # noqa: E402
from app.llm import gateway  # noqa: E402

PAGE = [(50, 560, 20, "Plan"), (50, 520, 12, "Revenue 2025 $150,000"), (50, 500, 12, "Customers Q3 800"), (50, 480, 12, "Users H2 900"),
        (50, 460, 12, "Margin April 40%"), (50, 440, 12, "ARR FY2025 $2M"), (50, 420, 12, "Revenue FY2025/26 $3M to $4M"),
        (50, 400, 12, "Launch of the new product in 2025-Q4")]
PERIODS = ["2025", "2025-Q3", "2025-H2", "2025-04", "FY2025", "FY2025/26"]


def full(cell, value, period, metric="revenue", **more):
    return {"metric": metric, "value": value, "value_high": None, "unit": "USD", "unit_other": None, "period": period, "basis": "projection",
            "scenario": "realistic", "value_cell": cell, "label_cell": None, "period_cell": None, **more}


REPLY = {"type": "page_claims", "claims": [
    *[full(f"p1r{i + 2}c1", 150000 + i, p) for i, p in enumerate(PERIODS)],
    full("p1r6c1", 3, "FY2025/26", value_high=4),
    full("p1r8c1", None, "2025-Q4", metric="product", unit=None),            # a date claim: no value, a period, metric product
]}


@pytest.fixture()
def reading(api, monkeypatch):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    api.state["adapter"] = t.FakeAdapter(replies=[json.dumps(REPLY)])
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: api.state["adapter"])
    for name in ("revenue.csv", "pnl.csv"):
        r = api.post(f"/api/audits/{AUDIT}/datasets/upload", files={"file": (name, (SAMPLE / name).read_bytes())})
        assert r.status_code == 200, r.text
    r = api.post(f"/api/audits/{AUDIT}/decks/upload", files={"file": ("deck.pdf", pdf_page(PAGE))})
    assert r.status_code == 200, r.text
    return api


@pytest.mark.parametrize("as_of", [None, "2025-06-30", "2025-06"])
def test_a_stored_page_reply_with_the_full_schema_is_listed(reading, as_of):
    reading.db["audits"].docs[0]["as_of_month"] = as_of         # the audit stores a date (YYYY-MM-DD); the engine's results a month
    assert reading.db[decks.TEXT_COLLECTION].docs[0]["ai_status"] == "read"
    r = reading.get(f"/api/audits/{AUDIT}/decks")
    assert r.status_code == 200, r.text
    rows = r.json()["candidates"]
    assert len(rows) == len(REPLY["claims"])
    assert all(row["basis"] == "projection" and row["scenario"] == "realistic" and "flags" in row for row in rows)


# ---------------------------------------------------------------------------
# Period normalisation before validation (the rejections of the log: fields=period)
# ---------------------------------------------------------------------------
TEXT = "p1r1c1: Revenue H2 2022 $150,000"


def parsed(**more):
    reply = {"type": "page_claims", "claims": [full("p1r1c1", 150000, "2022", **more)]}
    return gateway.parse_page_reply(json.dumps(reply), TEXT)


@pytest.mark.parametrize("written, allowed", [
    ("H2 2022", "2022-H2"), ("Q4 2021", "2021-Q4"), ("April 2022", "2022-04"), ("FY21/22", "FY2021/22"),
    ("2021 Q4", "2021-Q4"), ("Sept 2022", "2022-09"), ("FY21", "FY2021"), ("FY2021/2022", "FY2021/22"), ("Q4'21", "2021-Q4"),
    *[(p, p) for p in PERIODS]])
def test_a_common_page_form_of_a_period_is_mapped_to_the_allowed_one_before_validation(written, allowed):
    reply = {"type": "page_claims", "claims": [full("p1r1c1", 150000, written)]}
    assert gateway.parse_page_reply(json.dumps(reply), TEXT).claims[0].period == allowed


@pytest.mark.parametrize("span", ["Jan-May 2022", "Jan–May 2022", "January to May 2022", "2022-2024", "FY22-24", "Q1-Q3 2022"])
def test_a_span_is_no_period_the_period_is_null_and_the_claim_is_kept(span):
    reply = {"type": "page_claims", "claims": [full("p1r1c1", 150000, span), full("p1r1c1", 7, "2023")]}
    got = gateway.parse_page_reply(json.dumps(reply), TEXT)
    assert [(c.value, c.period) for c in got.claims] == [(150000, None), (7, "2023")]


def test_a_form_that_is_neither_mapped_nor_a_span_drops_that_claim_naming_the_field(caplog):
    for word in ("next year", "H3 2022"):
        reply = {"type": "page_claims", "claims": [full("p1r1c1", 1, word), full("p1r1c1", 2, "2023")]}
        with caplog.at_level(logging.INFO, logger="growth.llm"):
            got = gateway.parse_page_reply(json.dumps(reply), TEXT)
        assert [c.value for c in got.claims] == [2]
        assert "page 1: claim rejected (period)" in caplog.text


def test_the_reply_with_a_page_form_and_a_span_is_read_stored_normalised_and_listed(reading):
    """End to end through process_deck: the stored reply holds the allowed forms, a span's claim is a row with no date."""
    reading.db[decks.TEXT_COLLECTION].docs[0]["ai_status"] = "waiting"
    reading.db[gateway.STRUCTURES_COLLECTION].docs.clear()
    reading.db[decks.CANDIDATES_COLLECTION].docs.clear()
    reading.state["adapter"] = t.FakeAdapter(replies=[json.dumps({"type": "page_claims", "claims": [
        full("p1r2c1", 150000, "H2 2022"), full("p1r3c1", 800, "Jan-May 2022", metric="customers", unit="count")]})])
    from app import structures
    import asyncio
    status = asyncio.run(structures.process_deck(reading.db, AUDIT, reading.db[decks.TEXT_COLLECTION].docs[0]["deck_id"],
                                                 adapter=reading.state["adapter"], sleep=t._noop_sleep))
    assert status == "read"
    stored, = reading.db[gateway.STRUCTURES_COLLECTION].docs
    assert [c["period"] for c in stored["output"]["claims"]] == ["2022-H2", None]
    rows = reading.get(f"/api/audits/{AUDIT}/decks").json()["candidates"]
    assert sorted((r["claim_type"], r["target_date"]) for r in rows) == [("customers", None), ("revenue", "2022-H2")]


# ---------------------------------------------------------------------------
# A schema failure inside one claim drops that claim only (George, 2026-10-23)
# ---------------------------------------------------------------------------
TEXT2 = "p1r1c1: Revenue $1\np2r1c1: Customers 8"


def lines(caplog):
    return [r.getMessage() for r in caplog.records if "claim rejected" in r.getMessage()]


def read(claims, text=TEXT2, **top):
    return gateway.parse_page_reply(json.dumps({"type": "page_claims", "claims": claims, **top}), text)


GOOD = full("p1r1c1", 1, "2023")


@pytest.mark.parametrize("bad, fields", [
    ({"period": "next year"}, "period"),
    ({"metric": "vibes"}, "metric"),
    ({"basis": "hope"}, "basis"),
    ({"value_cell": "A1"}, "value_cell"),
    ({"extra_key": 1}, "extra_key"),
    ({"value": "lots"}, "value"),
    ({"value": None, "value_high": 3.0}, "claim"),            # the model-level validators name no field
    ({"unit": "USD", "unit_other": "XYZ"}, "claim"),
])
def test_one_invalid_claim_is_dropped_the_rest_of_the_reply_is_kept(bad, fields, caplog):
    with caplog.at_level(logging.INFO, logger="growth.llm"):
        got = read([GOOD, {**full("p2r1c1", 8, "2023", metric="customers", unit="count"), **bad}, full("p1r1c1", 5, "2024")])
    assert [c.value for c in got.claims] == [1, 5]
    page = "?" if "value_cell" in bad else "2"          # a claim with no valid cell id has no page
    assert lines(caplog) == [f"page {page}: claim rejected ({fields})"]


def test_two_invalid_claims_are_two_log_lines_with_every_failing_field(caplog):
    with caplog.at_level(logging.INFO, logger="growth.llm"):
        got = read([full("p1r1c1", 1, "soon", basis="hope"), GOOD, "junk"])
    assert [c.value for c in got.claims] == [1]
    assert lines(caplog) == ["page 1: claim rejected (basis, period)", "page ?: claim rejected (claim)"]


def test_a_reply_whose_claims_are_all_invalid_is_an_empty_reply_not_a_failure():
    assert read([full("p1r1c1", 1, "soon")]).claims == []


@pytest.mark.parametrize("top, fields", [
    ({"type": "sheet_structure"}, ["type"]),
    ({"claims": {"a": 1}}, ["claims"]),
    ({"extra": 1}, ["extra"]),
])
def test_an_invalid_top_level_object_rejects_the_whole_reply(top, fields):
    reply = {"type": "page_claims", "claims": [GOOD], **top}
    with pytest.raises(gateway.GatewayError) as e:
        gateway.parse_page_reply(json.dumps(reply), TEXT2)
    assert e.value.reason == "parse_failed" and e.value.fields == fields


@pytest.mark.parametrize("reply", ["not json", "[]", '{"claims": []}', '{"type": "page_claims"}'])
def test_a_reply_that_is_not_the_object_rejects_the_whole_reply(reply):
    with pytest.raises(gateway.GatewayError) as e:
        gateway.parse_page_reply(reply, TEXT2)
    assert e.value.reason == "parse_failed"


def test_a_cell_the_pages_did_not_send_still_rejects_the_whole_reply():
    with pytest.raises(gateway.GatewayError):
        read([GOOD, full("p9r9c9", 1, "2023")])
