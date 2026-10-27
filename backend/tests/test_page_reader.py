"""The page reader after docs/design/page-image.md sections 1, 2, 3 and 6: one PNG of each whole page goes with the page text in the same
request, together with the printed-values-only instruction; the pages go as printed; the model must be on the allow-list (Sonnet and Opus
families only) at startup and before each read; the image tokens and their cost are counted apart. Synthetic pages and images only."""
import asyncio
import json
import logging
import threading
import time

import page_images
import pytest

from app import structures
from app.decks import CANDIDATES_COLLECTION, TEXT_COLLECTION, pages, render
from app.llm import gateway
from app.structures import pages as pipeline
from test_page_pipeline import LINES, TITLE, _page_db, claim, deck
from test_page_reads_speed import EMPTY, Gauge, many_pages, page_of
from test_structure_reading import AUDIT, t


@pytest.fixture(autouse=True)
def page_reader_env(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    monkeypatch.delenv("PAGE_READER_MODEL", raising=False)


def run_deck(db, adapter):
    return asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))


# ---------------------------------------------------------------------------
# Section 1: one image of the whole page, with the text, in the same request
# ---------------------------------------------------------------------------
def test_every_page_goes_with_the_image_of_that_page_and_the_instruction_in_the_same_request():
    parsed = many_pages(5)
    adapter = Gauge(hold=0.0)
    assert run_deck(_page_db(parsed), adapter) == "read"
    assert len(adapter.requests) == 5
    for request, payload in zip(adapter.requests, adapter.payloads):
        page = page_of(payload)
        assert request["images"] == [page_images.png(page)], "one image, the image of the page whose text is in this request"
        assert json.loads(payload)["type"] == "page_claims" and "p%dr1c1" % page in json.loads(payload)["text"]


def test_the_gateway_carries_no_copy_of_the_printed_values_only_instruction():
    assert not hasattr(gateway, "PAGE_IMAGE_RULE"), "the stored deck_reading prompt carries it"


def test_the_adapter_puts_the_images_before_the_text_in_one_user_message():
    content = gateway._user_content("TEXT", [page_images.png(1), page_images.png(2)])
    assert [block["type"] for block in content] == ["image", "image", "text"] and content[-1]["text"] == "TEXT"
    assert content[0]["source"]["media_type"] == "image/png" and content[0]["source"]["type"] == "base64"
    assert gateway._user_content("TEXT", None) == "TEXT", "a step with no image sends the text alone, as before"


def test_a_cached_page_read_does_not_serve_a_read_made_with_another_image_or_none():
    key = gateway.structure_key("p1r1c1: A", "page_claims", "v1", "claude-sonnet-5-5", [page_images.png(1)])
    assert key != gateway.structure_key("p1r1c1: A", "page_claims", "v1", "claude-sonnet-5-5", [page_images.png(2)])
    assert key != gateway.structure_key("p1r1c1: A", "page_claims", "v1", "claude-sonnet-5-5")


def test_the_parallel_read_and_the_timeout_stay_and_no_cap_is_set_on_images():
    assert pipeline.PARALLEL_PAGES == 8 and pipeline.PAGE_TIMEOUT_SECONDS == 60.0
    assert not [name for name in dir(gateway) if name.isupper() and "IMAGE" in name and ("CAP" in name or "MAX" in name or "LIMIT" in name)]


def _text_only_deck(monkeypatch, failure):
    async def cannot_draw(db, audit_id, deck_id, fmt, pages_):
        raise render.PageImageError(failure)
    monkeypatch.setattr(render, "prepare", cannot_draw)
    db, adapter = _page_db(many_pages(3)), Gauge(hold=0.0)
    assert run_deck(db, adapter) == "read"
    return db, adapter


@pytest.mark.parametrize("failure", [render.NOT_RENDERED, render.PAGE_COUNT_DIFFERS, render.NO_FILE])
def test_a_deck_that_cannot_be_drawn_is_read_as_text_alone_never_not_read(monkeypatch, failure):
    """LibreOffice absent (NOT_RENDERED) or a drawn page count that differs: the text goes without an image, as before."""
    db, adapter = _text_only_deck(monkeypatch, failure)
    assert len(adapter.requests) == 3 and all(not r.get("images") for r in adapter.requests)
    doc, = db[TEXT_COLLECTION].docs
    assert [r["status"] for r in doc["page_reads"]] == ["read"] * 3 and doc["unread_pages"] == []
    assert doc["images_unavailable"] is True, "the panel says so"


def test_a_deck_that_is_drawn_does_not_set_the_text_only_note():
    db = _page_db(many_pages(2))
    assert run_deck(db, Gauge(hold=0.0)) == "read"
    assert db[TEXT_COLLECTION].docs[0]["images_unavailable"] is False


def test_a_page_that_fails_to_draw_goes_as_text_alone_and_the_others_keep_their_image(monkeypatch):
    real = render.render_page

    def flaky(pdf, page):
        if page == 2:
            raise render.PageImageError(render.NOT_RENDERED)
        return real(pdf, page)
    monkeypatch.setattr(render, "render_page", flaky)
    db, adapter = _page_db(many_pages(3)), Gauge(hold=0.0)
    assert run_deck(db, adapter) == "read"
    by_page = {page_of(p): bool(r.get("images")) for r, p in zip(adapter.requests, adapter.payloads)}
    assert by_page == {1: True, 2: False, 3: True}
    assert db[TEXT_COLLECTION].docs[0]["images_unavailable"] is True


def _stored_deck(monkeypatch, fmt, pages_):
    db = _page_db(many_pages(pages_))
    db[TEXT_COLLECTION].docs[0].update(format=fmt)
    asyncio.run(render.save(db, AUDIT, "d1", b"stored bytes", fmt))
    return db


@pytest.mark.real_render
def test_a_stored_pptx_reaches_the_converter_with_its_format(monkeypatch):
    """The deck's format is read from its record and handed to render.prepare (conftest's replacement of prepare is off here)."""
    converted = []
    monkeypatch.setattr(render, "to_pdf", lambda content, fmt: converted.append((content, fmt)) or b"pdf")
    monkeypatch.setattr(render, "page_count", lambda pdf: 3)
    monkeypatch.setattr(render, "render_page", lambda pdf, page: page_images.png(page))
    db, adapter = _stored_deck(monkeypatch, "pptx", 3), Gauge(hold=0.0)
    assert run_deck(db, adapter) == "read"
    assert converted == [(b"stored bytes", "pptx")], "a .pptx is converted as a .pptx, not taken for a PDF"
    assert all(r.get("images") for r in adapter.requests) and db[TEXT_COLLECTION].docs[0]["images_unavailable"] is False


class _FakePdfium:
    """A stand-in for pypdfium2 that records how many documents are open at once."""

    def __init__(self):
        self.open = self.peak = 0
        self.lock = threading.Lock()

    def enter(self):
        with self.lock:
            self.open += 1
            self.peak = max(self.peak, self.open)

    def leave(self):
        with self.lock:
            self.open -= 1

    def module(self):
        fake = self
        from PIL import Image

        class Sheet:
            def get_size(self):
                return 800, 450

            def render(self, scale):
                time.sleep(0.02)
                return type("Bitmap", (), {"to_pil": lambda _self: Image.new("RGB", (1568, 882))})()

        class PdfDocument:
            def __init__(self, data):
                fake.enter()

            def __len__(self):
                return 9

            def __getitem__(self, index):
                return Sheet()

            def close(self):
                fake.leave()
        return type("pypdfium2", (), {"PdfDocument": PdfDocument})


@pytest.mark.real_render
def test_two_concurrent_page_reads_never_draw_at_the_same_time(monkeypatch):
    """PDFium is not thread safe: the pages of a deck are drawn one at a time (render.PDFIUM_LOCK) while the model calls stay parallel."""
    import sys
    fake = _FakePdfium()
    monkeypatch.setitem(sys.modules, "pypdfium2", fake.module())

    async def prepared(db, audit_id, deck_id, fmt, pages_):
        return b"pdf"
    monkeypatch.setattr(render, "prepare", prepared)
    db, adapter = _page_db(many_pages(6)), Gauge(hold=0.05)
    assert run_deck(db, adapter) == "read"
    assert len(adapter.requests) == 6 and all(r.get("images") for r in adapter.requests)
    assert fake.peak == 1, "never two pages in PDFium at once"
    assert adapter.peak > 1, "the model calls stay parallel"


# ---------------------------------------------------------------------------
# Section 2: pages go as printed; the pipeline rows keep their printed names
# ---------------------------------------------------------------------------
def test_pipeline_rows_keep_their_printed_names_under_a_customer_header():
    parsed = deck([(50, 560, 20, "Sales pipeline"), (50, 520, 12, "Top customers"), (250, 520, 12, "Deal size"),
                   (50, 500, 12, "Acme Retail"), (250, 500, 12, "EUR 1.2M"), (50, 480, 12, "Globex Corp"), (250, 480, 12, "EUR 0.8M")])
    grid, = pages.page_grids(parsed["blocks"])
    ids = {c["text"]: f"p1r{c['row']}c{c['col']}" for c in grid["cells"]}
    reply = {"type": "page_claims", "claims": [
        claim(ids["EUR 1.2M"], 1200000, metric="pipeline", unit="EUR", label_cell=ids["Acme Retail"]),
        claim(ids["EUR 0.8M"], 800000, metric="pipeline", unit="EUR", label_cell=ids["Globex Corp"])]}
    db, adapter = _page_db(parsed), t.FakeAdapter(replies=[json.dumps(reply)])
    assert run_deck(db, adapter) == "read"
    sent = json.loads(adapter.payloads[0])["text"]
    assert "Acme Retail" in sent and "Globex Corp" in sent and "[redacted]" not in sent
    rows = db[CANDIDATES_COLLECTION].docs
    assert sorted(r["label_from"] for r in rows) == ["Acme Retail", "Globex Corp"], "the printed names, not placeholders"
    assert all("[redacted]" not in json.dumps(r) and "Customer_" not in json.dumps(r) for r in rows)


# ---------------------------------------------------------------------------
# Allow-list of page-reader models (Sonnet and Opus families only)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["claude-sonnet-5-5", "claude-sonnet-5", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-4-5-20250929"])
def test_sonnet_and_opus_models_are_permitted(name, monkeypatch, caplog):
    monkeypatch.setenv("PAGE_READER_MODEL", name)
    with caplog.at_level(logging.ERROR):
        assert gateway.page_reader_problem() is None
    assert not caplog.records


@pytest.mark.parametrize("name", ["claude-haiku-4-5", "claude-fable-5-1", "claude-mythos-1", "claude-sonnet", "claude-sonnet-5-5-evil",
                                  "gpt-5", "sonnet", "claude-opus-"])
def test_any_other_model_is_not_permitted(name, monkeypatch, caplog):
    monkeypatch.setenv("PAGE_READER_MODEL", name)
    with caplog.at_level(logging.ERROR):
        assert gateway.page_reader_problem() == "AI read: blocked – model not permitted"
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR] == [f"page reader model {name} not permitted"]


def test_the_default_page_reader_model_is_on_the_list():
    assert gateway.page_reader_model() == gateway.STRUCTURE_MODEL
    assert gateway.PAGE_READER_MODELS.fullmatch(gateway.STRUCTURE_MODEL)


def test_startup_logs_the_error_for_a_model_not_on_the_list_and_stays_quiet_for_one_that_is(monkeypatch, caplog):
    import server
    assert server.check_page_reader_model in server.app.router.on_startup, "the check is registered to run when the app starts"
    monkeypatch.setenv("PAGE_READER_MODEL", "claude-haiku-4-5")
    with caplog.at_level(logging.ERROR):
        asyncio.run(server.check_page_reader_model())
    assert "page reader model claude-haiku-4-5 not permitted" in [r.getMessage() for r in caplog.records]
    caplog.clear()
    monkeypatch.setenv("PAGE_READER_MODEL", "claude-opus-5-5")
    with caplog.at_level(logging.ERROR):
        asyncio.run(server.check_page_reader_model())
    assert not caplog.records


def test_before_each_page_read_a_model_not_on_the_list_blocks_the_read_and_nothing_is_sent(monkeypatch, caplog):
    monkeypatch.setenv("PAGE_READER_MODEL", "claude-haiku-4-5")
    parsed = many_pages(3)
    db, adapter = _page_db(parsed), Gauge(hold=0.0)
    with caplog.at_level(logging.ERROR):
        status = run_deck(db, adapter)
    assert status == "blocked"
    assert adapter.calls == 0 and getattr(adapter, "counted", 0) == 0, "nothing was counted or sent"
    assert db["llm_calls"].docs == [], "and nothing was billed"
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert errors == ["page reader model claude-haiku-4-5 not permitted"] * 3, "once per page read, the check runs before each"
    doc, = db[TEXT_COLLECTION].docs
    assert (doc["ai_status"], doc["ai_message"]) == ("blocked", "AI read: blocked – model not permitted")
    assert [r["status"] for r in doc["page_reads"]] == ["blocked"] * 3 and doc["retry_pages"] == [1, 2, 3]


def test_a_model_changed_to_a_forbidden_one_between_two_reads_blocks_the_second(monkeypatch):
    parsed = many_pages(2)
    db = _page_db(parsed)
    read = asyncio.run(gateway.read_structure(db, AUDIT, "p1r1c1 title: Traction\np1r2c1: 800 Paying Users", "page_claims",
                                              adapter=t.FakeAdapter(replies=[EMPTY]), sleep=t._noop_sleep, images=[page_images.png(1)]))
    assert read.status == "read"
    monkeypatch.setenv("PAGE_READER_MODEL", "claude-fable-5-1")
    adapter = t.FakeAdapter(replies=[EMPTY])
    read = asyncio.run(gateway.read_structure(db, AUDIT, "p2r1c1 title: Traction\np2r2c1: 800 Paying Users", "page_claims",
                                              adapter=adapter, sleep=t._noop_sleep, images=[page_images.png(2)]))
    assert (read.status, read.reason, adapter.calls) == ("blocked", "AI read: blocked – model not permitted", 0)


def test_a_blocked_deck_is_read_again_by_run_audit_once_the_model_is_permitted(monkeypatch):
    monkeypatch.setenv("PAGE_READER_MODEL", "claude-haiku-4-5")
    parsed = many_pages(2)
    db = _page_db(parsed)
    assert run_deck(db, Gauge(hold=0.0)) == "blocked"
    assert asyncio.run(structures.queue_blocked(db, AUDIT)) == [], "still not permitted: nothing is queued"
    monkeypatch.delenv("PAGE_READER_MODEL")
    assert asyncio.run(structures.queue_blocked(db, AUDIT)) == ["d1"]
    assert db[TEXT_COLLECTION].docs[0]["ai_status"] == "reading"
    assert run_deck(db, Gauge(hold=0.0)) == "read"


def test_the_deck_list_shows_the_blocked_status_and_its_line(api, monkeypatch):
    """The deck panel's line (frontend/src/lib/deckClaims.js): the server sends the status and the message."""
    monkeypatch.setenv("PAGE_READER_MODEL", "claude-haiku-4-5")
    audit_id = api.db["audits"].docs[0]["id"]
    db = _page_db(many_pages(2))
    for name in ("datasets", TEXT_COLLECTION):
        for doc in db[name].docs:
            api.db[name].docs.append({**doc, "audit_id": audit_id})
    api.db["audits"].docs[0]["structure_reading_consent"] = True
    status = asyncio.run(structures.process_deck(api.db, audit_id, "d1", adapter=Gauge(hold=0.0), sleep=t._noop_sleep))
    assert status == "blocked"
    listed = api.get(f"/api/audits/{audit_id}/decks").json()["decks"][0]
    assert (listed["ai_status"], listed["ai_message"]) == ("blocked", "AI read: blocked – model not permitted")


# ---------------------------------------------------------------------------
# Section 6: image tokens and image cost, apart from the text's
# ---------------------------------------------------------------------------
def test_the_image_tokens_and_their_cost_are_counted_apart_from_the_text_and_logged_per_call():
    parsed = many_pages(2)
    db, adapter = _page_db(parsed), Gauge(hold=0.0)
    adapter.image_tokens = 1500                            # what the images add to a call's count and bill
    assert run_deck(db, adapter) == "read"
    calls = [c for c in db["llm_calls"].docs if c["status"] == "ok"]
    assert len(calls) == 2
    price = gateway.MODEL_PRICING_USD[gateway.STRUCTURE_MODEL]["input"]
    for call in calls:
        assert call["input_tokens"] == 1200 + 1500, "the call bills the text and the image"
        assert call["image_tokens"] == 1500 and call["image_cost_usd"] == round(1500 / 1_000_000 * price, 6)
        assert call["estimated_cost_usd"] == round(gateway.estimate_cost_usd(gateway.STRUCTURE_MODEL, 2700, 300), 6)
    usage = asyncio.run(gateway.usage_for_run(db, AUDIT))
    deck_usage = usage.by_deck["d1"]
    assert (deck_usage.image_tokens, deck_usage.input_tokens) == (3000, 5400)
    assert deck_usage.image_cost_usd == round(2 * 1500 / 1_000_000 * price, 6)
    assert usage.by_step["deck_structure"].image_tokens == 3000


def test_a_page_read_with_no_image_tokens_reported_has_none_logged():
    db, adapter = _page_db(many_pages(1)), t.FakeAdapter(replies=[EMPTY])
    assert run_deck(db, adapter) == "read"
    call, = [c for c in db["llm_calls"].docs if c["status"] == "ok"]
    assert (call["image_tokens"], call["image_cost_usd"]) == (0, 0.0)


def test_a_cache_hit_bills_no_image():
    db, adapter = _page_db(many_pages(1)), t.FakeAdapter(replies=[EMPTY])
    adapter.image_tokens = 900
    run_deck(db, adapter)
    db[TEXT_COLLECTION].docs[0].pop("page_reads"), db[TEXT_COLLECTION].docs[0].pop("retry_pages", None)
    run_deck(db, adapter)
    hit = db["llm_calls"].docs[-1]
    assert hit["cache_hit"] is True and (hit["image_tokens"], hit["image_cost_usd"]) == (0, 0.0)
    assert adapter.calls == 1


def test_a_failed_call_still_reports_the_image_tokens_it_billed(monkeypatch):
    err = gateway.GatewayError("truncated", "cut")
    err.tokens = (2700, 4000)
    adapter = t.FakeAdapter(raise_with=err)
    adapter.image_tokens = 1500
    db = _page_db(many_pages(1))
    read = asyncio.run(gateway.read_structure(db, AUDIT, "p1r1c1 title: Traction\np1r2c1: 800 Paying Users", "page_claims", adapter=adapter,
                                              sleep=t._noop_sleep, images=[page_images.png(1)]))
    assert read.status == "truncated" and read.image_tokens == 1500
    assert db["llm_calls"].docs[-1]["image_tokens"] == 1500


def test_the_text_and_title_lines_are_what_the_unchanged_page_text_builder_writes():
    parsed = deck([TITLE, *LINES])
    sent, = pipeline.sendable_pages(pages.page_grids(parsed["blocks"]))
    assert pipeline.batch_text([sent]).startswith("p1r1c1 title: Traction\np1r2c1: 800 Paying Users")


@pytest.mark.real_render
def test_a_model_off_the_allow_list_converts_and_draws_nothing_and_blocks_every_page(monkeypatch, caplog):
    """The allow-list check runs before any conversion or drawing (rule 31): nothing is prepared, nothing is rendered, nothing is sent."""
    monkeypatch.setenv("PAGE_READER_MODEL", "claude-fable-5-1")
    touched = []

    async def prepared(*args):
        touched.append("prepare")
        return b"pdf"
    monkeypatch.setattr(render, "prepare", prepared)
    monkeypatch.setattr(render, "to_pdf", lambda content, fmt: touched.append("to_pdf") or b"pdf")
    monkeypatch.setattr(render, "render_page", lambda pdf, page: touched.append("render_page") or page_images.png(page))
    db, adapter = _stored_deck(monkeypatch, "pptx", 3), Gauge(hold=0.0)
    with caplog.at_level(logging.WARNING):
        assert run_deck(db, adapter) == "blocked"
    doc, = db[TEXT_COLLECTION].docs
    assert touched == [] and adapter.calls == 0
    assert [r["status"] for r in doc["page_reads"]] == ["blocked"] * 3 and doc["images_unavailable"] is False
    assert "page reader model claude-fable-5-1 not permitted" in [r.getMessage() for r in caplog.records]
