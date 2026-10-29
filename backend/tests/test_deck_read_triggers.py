"""When the page read starts and what the deck panel says about it (docs/specs/chat-upload.md section 28, George 2026-10-23, follow-up
of PR 164): the revenue-file gate stays; the read starts (a) at the deck upload when the audit already has its revenue file, (b) when the
revenue mapping completes, for a deck still waiting, (c) on Run audit, for a deck not yet read. The gate counts the revenue file as the
rest of the app does (the blocker banner): a mapped revenue file of any kind, or a confirmed P&L with two or more periods.
Every test runs on the in-memory Mongo stub and the fake adapter: nothing reaches a provider."""
import json
import sys
from pathlib import Path

import page_images
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("fastapi")
pytest.importorskip("pdfplumber")

import test_llm_gateway as t  # noqa: E402
import test_revenue_recognition as rr  # noqa: E402
from pdf_support import pdf_page  # noqa: E402
from test_chat_upload import AUDIT, SAMPLE  # noqa: E402

from app import decks  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.llm.schemas import PAGE_CLAIMS  # noqa: E402

FIGURE_PAGE = [(50, 560, 20, "Traction"), (50, 500, 12, "800 Paying Users"), (50, 480, 12, "$150,000 annual revenue run rate")]
DECK = pdf_page(FIGURE_PAGE)
EMPTY_REPLY = json.dumps({"type": PAGE_CLAIMS, "claims": []})


def upload_file(client, name, content=None):
    r = client.post(f"/api/audits/{AUDIT}/datasets/upload", files={"file": (name, content or (SAMPLE / name).read_bytes())})
    assert r.status_code == 200, r.text
    return r


def upload_deck(client):
    r = client.post(f"/api/audits/{AUDIT}/decks/upload", files={"file": ("deck.pdf", DECK)})
    assert r.status_code == 200, r.text
    return r


def page_calls(client):
    return [p for p in client.state["adapter"].payloads if json.loads(p)["type"] == PAGE_CLAIMS]


def forget_the_first_read(client):
    """A trigger that never fired: the deck is waiting again and the cached reply of the first read is gone, so a read shows as a call."""
    client.db[decks.TEXT_COLLECTION].docs[0]["ai_status"] = "waiting"
    client.db[decks.TEXT_COLLECTION].docs[0].pop("page_reads", None)       # never read: no page is kept from an earlier run
    client.db[gateway.STRUCTURES_COLLECTION].docs.clear()
    client.state["adapter"].payloads.clear()


def deck_doc(client):
    doc, = client.db[decks.TEXT_COLLECTION].docs
    return doc


def listed(client):
    deck, = client.get(f"/api/audits/{AUDIT}/decks").json()["decks"]
    return deck


def confirmed_pnl(client):
    client.db["audits"].docs[0]["as_of_month"] = "2025-06-30"
    upload_file(client, "pnl_monthly.csv", (rr.FIXTURES / "pnl_monthly.csv").read_bytes())
    r = rr.decide(client, dtype="pnl", action="confirm", part="revenue_row")
    assert r.status_code == 200, r.text


@pytest.fixture()
def reading(api, monkeypatch):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    api.state["adapter"] = t.FakeAdapter(replies=[EMPTY_REPLY])
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: api.state["adapter"])
    return api


# ---------------------------------------------------------------------------
# Item 3: the gate counts the revenue file as the rest of the app does
# ---------------------------------------------------------------------------
def test_item_3_revenue_and_pnl_mapped_through_the_upload_page_then_a_deck_makes_a_page_read_call(reading):
    upload_file(reading, "revenue.csv")
    upload_file(reading, "pnl.csv")
    upload_deck(reading)
    assert len(page_calls(reading)) == 1 and deck_doc(reading)["ai_status"] == "read"


def test_item_3_a_pnl_confirmed_with_two_or_more_periods_is_the_revenue_file_for_the_gate_as_for_the_banner(reading):
    confirmed_pnl(reading)
    assert "revenue_file_missing" not in [b["kind"] for b in reading.get(f"/api/audits/{AUDIT}/blockers").json()["blockers"]]
    upload_deck(reading)
    assert len(page_calls(reading)) == 1 and deck_doc(reading)["ai_status"] == "read"


def test_item_3_a_pnl_with_one_period_is_not_the_revenue_file_and_the_deck_waits(reading):
    upload_file(reading, "pnl_single_period.csv", (rr.FIXTURES / "pnl_single_period.csv").read_bytes())
    upload_deck(reading)
    assert page_calls(reading) == [] and deck_doc(reading)["ai_status"] == "waiting"


def test_item_3_a_revenue_file_the_analyst_has_not_mapped_does_not_open_the_gate(reading):
    upload_file(reading, "revenue.csv")
    reading.db["datasets"].docs[0]["mapped_at"] = None
    upload_deck(reading)
    assert page_calls(reading) == [] and deck_doc(reading)["ai_status"] == "waiting"


# ---------------------------------------------------------------------------
# Re-triggers (a), (b), (c)
# ---------------------------------------------------------------------------
def test_a_the_read_starts_at_the_deck_upload_when_the_revenue_file_is_already_mapped(reading):
    upload_file(reading, "revenue.csv")
    body = upload_deck(reading).json()
    assert body["ai_status"] == "reading" and len(page_calls(reading)) == 1


def test_b_the_read_starts_when_the_revenue_mapping_completes_for_a_deck_that_waits(reading):
    body = upload_deck(reading).json()
    assert body["ai_status"] == "waiting" and page_calls(reading) == [] and deck_doc(reading)["ai_status"] == "waiting"
    upload_file(reading, "revenue.csv")
    assert len(page_calls(reading)) == 1 and deck_doc(reading)["ai_status"] == "read"


def test_b_the_read_starts_when_the_analyst_confirms_a_pnl_for_a_deck_that_waits(reading):
    upload_deck(reading)
    confirmed_pnl(reading)
    assert len(page_calls(reading)) == 1 and deck_doc(reading)["ai_status"] == "read"


def test_b_the_read_starts_when_a_mapping_is_saved_with_the_mapping_endpoint_for_a_deck_that_waits(reading):
    upload_deck(reading)
    upload_file(reading, "revenue.csv")
    mapping = reading.db["datasets"].docs[0]["mapping"]
    reading.db["datasets"].docs[0].update(mapped_at=None)
    forget_the_first_read(reading)
    r = reading.put(f"/api/audits/{AUDIT}/datasets/revenue/mapping", json={"mapping": mapping})
    assert r.status_code == 200, r.text
    assert len(page_calls(reading)) == 1 and deck_doc(reading)["ai_status"] == "read"


def test_c_run_audit_reads_a_deck_still_waiting_once_the_audit_has_its_revenue_file(reading):
    upload_deck(reading)
    upload_file(reading, "revenue.csv")
    for stage in ("mapping", "engine"):
        assert reading.post(f"/api/audits/{AUDIT}/run/{stage}").json()["status"] == "done"
    forget_the_first_read(reading)
    reading.post(f"/api/audits/{AUDIT}/run/claims")
    assert len(page_calls(reading)) == 1 and deck_doc(reading)["ai_status"] == "read"


def test_c_run_audit_leaves_a_waiting_deck_waiting_while_the_revenue_file_is_missing(reading):
    upload_file(reading, "pnl_single_period.csv", (rr.FIXTURES / "pnl_single_period.csv").read_bytes())
    upload_deck(reading)
    reading.db["audits"].docs[0]["results"] = {"revenue_series": {"data": []}}
    out = reading.post(f"/api/audits/{AUDIT}/run/claims").json()
    assert page_calls(reading) == [] and deck_doc(reading)["ai_status"] == "waiting" and out["status"] == "needs_review"


# ---------------------------------------------------------------------------
# The deck panel's line: what the server sends for each status
# ---------------------------------------------------------------------------
def test_the_upload_answer_counts_the_pages_with_a_figure_and_never_pages_read(reading):
    body = upload_deck(reading).json()
    assert body["pages"] == 1 and body["figure_pages"] == 1 and "candidates" in body
    page_free = reading.post(f"/api/audits/{AUDIT}/decks/upload", files={"file": ("quiet.pdf", pdf_page([(50, 560, 20, "Our mission"), (50, 500, 12, "We help teams")]))})
    assert page_free.json()["pages"] == 1 and page_free.json()["figure_pages"] == 0


def test_status_waiting_queued_page_n_of_n_and_done_are_listed_with_their_counts(reading):
    upload_deck(reading)
    assert (listed(reading)["ai_status"], listed(reading)["figure_pages"]) == ("waiting", 1)
    reading.db[decks.TEXT_COLLECTION].docs[0]["ai_status"] = "reading"                    # queued: reading, no progress yet
    assert listed(reading)["ai_status"] == "reading" and listed(reading).get("read_progress") is None
    reading.db[decks.TEXT_COLLECTION].docs[0]["read_progress"] = {"done": 2, "total": 7}      # page 3 of 7
    assert listed(reading)["read_progress"] == {"done": 2, "total": 7}
    reading.db[decks.TEXT_COLLECTION].docs[0]["ai_status"] = "waiting"
    upload_file(reading, "revenue.csv")
    done = listed(reading)
    assert (done["ai_status"], done["pages_read"], done["pages_rejected"]) == ("read", 1, 0)


def test_the_deck_line_counts_what_masking_took_out_of_the_pages_sent_as_numbers_only(reading, monkeypatch):
    """George, 2026-10-29 (review of PR 204): the deck line ends with the personal items removed and the company names tokenised in the
    page text sent; the page read keeps the two counts, never what was removed."""
    page = FIGURE_PAGE + [(50, 440, 12, "Fixture Target Ltd grew 40% in 2025"), (50, 420, 12, "Jane Doe, jane.roe@example.org")]
    monkeypatch.setattr(sys.modules[__name__], "DECK", pdf_page(page))
    upload_file(reading, "revenue.csv")
    upload_deck(reading)
    sent = json.loads(page_calls(reading)[0])["text"]
    assert "jane.roe" not in sent and "Jane Doe" not in sent and "Fixture Target" not in sent
    stored, = deck_doc(reading)["page_reads"]
    assert stored["masked"] == {"personal": 2, "names": 1}
    done = listed(reading)
    assert (done["ai_status"], done["personal_removed"], done["names_replaced"]) == ("read", 2, 1)


def test_a_reply_the_validator_rejects_is_counted_as_rejected_pages(reading):
    reading.state["adapter"] = t.FakeAdapter(replies=["{not json"])
    upload_file(reading, "revenue.csv")
    upload_deck(reading)
    done = listed(reading)
    assert (done["ai_status"], done["pages_read"], done["pages_rejected"]) == ("not_read", 0, 1)


def test_the_page_read_saves_its_progress_before_and_after_each_batch(reading):
    calls = []
    from app.structures import pages as pipeline

    async def progress(done, total):
        calls.append((done, total))

    upload_file(reading, "revenue.csv")
    upload_deck(reading)
    grids = pipeline.page_grids_mod.page_grids(deck_doc(reading)["blocks"])
    import asyncio
    asyncio.run(pipeline.read_pages(reading.db, AUDIT, "d", grids, page_images.image_for, adapter=reading.state["adapter"],
                                    sleep=t._noop_sleep, progress=progress))
    assert calls == [(0, 1), (1, 1)]


def test_a_new_read_clears_the_old_progress(reading):
    upload_deck(reading)
    reading.db[decks.TEXT_COLLECTION].docs[0]["read_progress"] = {"done": 2, "total": 7}
    upload_file(reading, "revenue.csv")
    assert deck_doc(reading)["read_progress"] == {"done": 1, "total": 1}, "the new read replaced the old progress"


def test_item_3_a_revenue_file_saved_as_a_statement_line_map_has_no_customer_column_and_still_opens_the_gate(reading):
    upload_file(reading, "revenue.csv")
    reading.db["datasets"].docs[0].update(mapping={}, sheet_map={"lines": []}, columns_state=None)
    upload_deck(reading)
    assert len(page_calls(reading)) == 1 and deck_doc(reading)["ai_status"] == "read"


# ---------------------------------------------------------------------------
# The stored file the page images are drawn from (docs/design/page-image.md section 1)
# ---------------------------------------------------------------------------
def stored_files(client):
    return client.db["deck_files"].docs


def test_the_upload_keeps_the_file_for_the_page_images_and_a_new_upload_of_it_replaces_the_stored_one(reading):
    upload_deck(reading)
    first, = stored_files(reading)
    assert first["deck_id"] == deck_doc(reading)["deck_id"] and first["data"] == DECK and first["format"] == "pdf"
    second_deck = pdf_page(FIGURE_PAGE + [(50, 440, 12, "97% margins")])
    reading.post(f"/api/audits/{AUDIT}/decks/upload", files={"file": ("deck.pdf", second_deck)})
    kept, = stored_files(reading)
    assert kept["data"] == second_deck and kept["deck_id"] == deck_doc(reading)["deck_id"], "the earlier upload's file is gone"


def test_removing_the_deck_or_deleting_the_audit_removes_the_stored_file(reading):
    upload_deck(reading)
    other = pdf_page([(50, 560, 20, "Other"), (50, 500, 12, "12 customers")])
    reading.post(f"/api/audits/{AUDIT}/decks/upload", files={"file": ("other.pdf", other)})
    assert len(stored_files(reading)) == 2
    gone = [d["deck_id"] for d in reading.db[decks.TEXT_COLLECTION].docs if d["file"] == "deck.pdf"][0]
    assert reading.delete(f"/api/audits/{AUDIT}/decks/{gone}").status_code == 200
    assert [f["data"] for f in stored_files(reading)] == [other]
    name = reading.db["audits"].docs[0]["company_name"]
    assert reading.request("DELETE", f"/api/audits/{AUDIT}", json={"confirm": name}).status_code == 200
    assert stored_files(reading) == [], "delete audit removes every stored file (rule 22)"


def test_the_file_is_stored_only_when_consent_is_ticked_and_the_page_pipeline_is_on(reading, monkeypatch):
    """Nothing about a deck is kept for page images unless a page read can happen (rule 17 as amended)."""
    reading.db["audits"].docs[0]["structure_reading_consent"] = False
    upload_deck(reading)
    assert stored_files(reading) == [], "consent unticked: no copy of the file"
    reading.db["audits"].docs[0]["structure_reading_consent"] = True
    monkeypatch.setenv("DECK_PIPELINE", "rules")
    upload_deck(reading)
    assert stored_files(reading) == [], "DECK_PIPELINE=rules: no page read, no copy of the file"
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    upload_deck(reading)
    stored, = stored_files(reading)
    assert stored["data"] == DECK


def test_unticking_consent_removes_the_stored_deck_files_and_ticking_again_says_the_images_need_the_file(reading, monkeypatch):
    from app.decks import render

    async def prepared(db, audit_id, deck_id, fmt, pages):          # the real prepare's first step; the suite's stub always finds a file
        if await render._load(db, audit_id, deck_id, "original") is None:
            raise render.PageImageError(render.NO_FILE)
        return b"synthetic pdf"
    monkeypatch.setattr(render, "prepare", prepared)
    upload_file(reading, "revenue.csv")
    upload_deck(reading)
    assert len(stored_files(reading)) == 1 and not listed(reading).get("images_need_file")
    assert reading.put(f"/api/audits/{AUDIT}", json={"structure_reading_consent": False}).status_code == 200
    assert stored_files(reading) == [], "unticked: the stored deck files go with the permission to read"
    assert reading.put(f"/api/audits/{AUDIT}", json={"structure_reading_consent": True}).status_code == 200
    assert listed(reading)["images_need_file"] is True and listed(reading)["images_unavailable"] is True, "ticked again with no file: the panel asks for a re-upload"
    upload_deck(reading)
    assert len(stored_files(reading)) == 1 and not listed(reading).get("images_need_file")


def test_a_save_that_leaves_consent_ticked_keeps_the_stored_deck_files(reading):
    upload_deck(reading)
    reading.put(f"/api/audits/{AUDIT}", json={"structure_reading_consent": True})
    reading.put(f"/api/audits/{AUDIT}", json={"company_name": "Renamed"})
    assert len(stored_files(reading)) == 1


def test_reseeding_the_demo_audits_removes_the_stored_deck_files_of_the_old_ones(monkeypatch):
    import asyncio
    import server
    db = t.FakeDB()
    monkeypatch.setattr(server, "db", db)
    asyncio.run(server.seed_demo())
    old = [a["id"] for a in db["audits"].docs if a.get("demo")]
    assert old
    db["deck_files"].docs.extend([{"audit_id": old[0], "deck_id": "d", "kind": "original", "part": 0, "data": b"x"},
                                  {"audit_id": "someone-elses", "deck_id": "d", "kind": "original", "part": 0, "data": b"y"}])
    for audit in db["audits"].docs:
        audit.pop("seed_version", None)
    asyncio.run(server.seed_demo())
    assert [f["audit_id"] for f in db["deck_files"].docs] == ["someone-elses"]
