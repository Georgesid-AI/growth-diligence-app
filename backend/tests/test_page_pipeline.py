"""The page pipeline behind DECK_PIPELINE (docs/design/ai-reads-rules-check.md, PR A): the page grid gives every line of a page a
cell id; only a page with a figure as digits may go (decision 1b; number-words do not count); the page text comes through one
builder, as printed, in batches of five; a batch too large is split; under the switch "ai" process_deck reads the pages and lists
each claim as "Matched to page" or "AI suggestion, not matched"; under the default "rules" nothing changes."""
import asyncio
import copy
import json
import sys
from pathlib import Path

import page_images
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")

from pdf_support import pdf_page, ruled_table  # noqa: E402
from test_structure_reading import AUDIT, REVENUE_MAPPING, _db, t  # noqa: E402

from app import structures  # noqa: E402
from app.decks import CANDIDATES_COLLECTION, TEXT_COLLECTION, pages  # noqa: E402
from app.decks.parser import parse_deck  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.llm.schemas import PAGE_CLAIMS  # noqa: E402
from app.structures import page_check, redact  # noqa: E402
from app.structures import pages as pipeline  # noqa: E402

TITLE = (50, 560, 20, "Traction")
LINES = [(50, 500, 12, "800 Paying Users"), (50, 480, 12, "$150,000 annual revenue run rate"), (50, 460, 12, "97% margins")]
PROSE = (50, 320, 10, "Our CEO Jane Doe and CTO Max Mustermann met at Northwind Trading in 2019; the team grew.")
LONG = (50, 300, 10, "Our CEO Jane Doe and CTO Max Mustermann met at Northwind Trading in 2019; " * 3 + "the team grew.")
assert len(PROSE[3]) <= 200 < len(LONG[3])
DECKS = BACKEND.parent / "tests" / "fixtures" / "decks" / "decks"


def deck(texts, rects=()):
    return parse_deck(pdf_page(texts, rects), "deck.pdf")


def grid_of(texts, rects=()):
    grids = pages.page_grids(deck(texts, rects)["blocks"])
    assert len(grids) == 1
    return grids[0]


def claim(value_cell, value, metric="revenue", unit="USD", period=None, period_cell=None, label_cell=None):
    return {"metric": metric, "value": value, "value_high": None, "unit": unit, "unit_other": None, "period": period,
            "basis": "actual", "scenario": "none", "value_cell": value_cell, "label_cell": label_cell, "period_cell": period_cell}


# ---------------------------------------------------------------------------
# The page grid
# ---------------------------------------------------------------------------
def test_every_line_of_a_page_is_a_cell_with_an_id_a_box_and_its_neighbours():
    g = grid_of([TITLE, *LINES, PROSE])
    texts = [c["text"] for c in g["cells"]]
    assert texts[:4] == ["Traction", "800 Paying Users", "$150,000 annual revenue run rate", "97% margins"]
    assert any(t.startswith("Our CEO Jane Doe") for t in texts), "prose is a cell too"
    assert all({"row", "col", "text", "box"} <= set(c) for c in g["cells"])
    assert g["cells"][0].get("title") is True and g["figure"] is True and g["page"] == 1
    assert "r2c1" in g["cells"][0]["next_to"], "the title is next to the first value line"


def test_a_table_joins_the_grid_below_the_text_with_its_table_row_and_column():
    texts, rects = ruled_table([["", "FY2025", "FY2026"], ["Revenue", "£1,200", "£1,500"]], col_widths=(200, 200, 200))
    g = grid_of([TITLE, *texts], rects)
    table = [c for c in g["cells"] if c.get("table") == 1]
    assert len(table) == 5 and g["tables"] == [{"table": 1, "header_rows": 1}]
    assert {(c["trow"], c["tcol"]) for c in table} == {(1, 2), (1, 3), (2, 1), (2, 2), (2, 3)}
    text_rows = max(c["row"] for c in g["cells"] if c.get("table") is None)
    assert min(c["row"] for c in table) == text_rows + 1, "table rows come after the text rows"
    cell, = [c for c in table if c["text"] == "£1,200"]
    got = page_check.check(g, [claim(f"r{cell['row']}c{cell['col']}", 1200, unit="GBP", period="FY2025",
                                     period_cell=f"r{cell['row'] - 1}c{cell['col']}")])["items"][0]
    assert got["status"] == page_check.MATCHED and got["period"] == "2025"


@pytest.mark.parametrize("line, digit", [
    ("Revenue grew to three million euros", False), ("Twenty new customers signed", False), ("Our mission", False),
    ("Founded in 2019", True), ("Launched in January 2011", True), ("Revenue grew to €3M", True), ("20 new customers signed", True), ("97%", True),
    ("1", True), ("Slide 1", True), ("Page 1 of 25", True), ("1/25", True), ("- 1 -", True), ("2", True), ("Top 1", True),
    ("We signed 12 customers in the quarter and expect more", True)])
def test_a_page_is_sent_whenever_its_text_holds_a_digit_and_only_then(line, digit):
    """George, 2026-10-31: a page goes to the model whenever its text layer holds at least one digit (a year, a page number, a figure inside a
    sentence); only a page with no digit in its text is skipped. Number-words are no digit."""
    g = grid_of([(50, 560, 20, "Mission"), (50, 500, 12, line)])
    assert pages.has_digit_figure(g) is digit
    assert bool(pages.sendable([g])) is digit
    assert bool(pipeline.sendable_pages([g])) is digit, "the sender's floor agrees"
    problem = redact.page_text_problem(redact.page_text([(1, g["cells"])]))
    assert (problem is None) is digit, "the gateway's floor agrees"


def test_a_figure_inside_a_sentence_on_a_page_is_sent():
    g = grid_of([(50, 560, 20, "Mission"), (50, 500, 12, "Over the last year the team signed 12 new customers and kept every one of them")])
    sent, = pipeline.sendable_pages([g])
    assert "12 new customers" in pipeline.batch_text([sent])
    assert pipeline.skipped_pages([g], 1) == []


def test_a_page_whose_only_digit_is_its_page_number_is_sent():
    """A footer page number on a prose page (06-uber.pdf page 4: 17 lines, the digit line "4") is a digit, so the page goes (2026-10-31)."""
    pytest.importorskip("pdfplumber")
    deck_path = DECKS / "06-uber.pdf"
    if not deck_path.exists():
        pytest.skip("public test decks not checked out")
    grids = pages.page_grids(parse_deck(deck_path.read_bytes(), deck_path.name)["blocks"])
    by_page = {pages.page_number(g): g for g in grids}
    assert pages.has_digit_figure(by_page[4]) is True and len(pipeline.sendable_pages([by_page[4]])) == 1
    synthetic = grid_of([(50, 560, 20, "Our mission"), (50, 500, 12, "We help teams ship faster"), (500, 30, 8, "1")])
    assert len(pipeline.sendable_pages([synthetic])) == 1
    nothing = grid_of([(50, 560, 20, "Our mission"), (50, 500, 12, "We help teams ship faster")])
    assert pipeline.sendable_pages([nothing]) == []


def test_a_background_or_cited_research_page_is_sent_like_any_page_with_a_digit():
    g = grid_of([(50, 560, 20, "Problem"), (50, 500, 12, "Companies lose 3 hours a day")])
    assert g.get("excluded") is True, "the rules read still drops its figures"
    assert len(pages.sendable([g])) == 1


def test_batches_hold_five_pages_and_the_text_comes_through_the_one_builder_as_printed():
    grids = [{**grid_of([TITLE, *LINES, PROSE, LONG]), "page": n} for n in range(1, 8)]
    batched = pipeline.batches(grids)
    assert [[p["grid"]["page"] for p in b] for b in batched] == [[1, 2, 3, 4, 5], [6, 7]]
    text = pipeline.batch_text(batched[1])
    assert redact.page_text_problem(text) is None
    assert text.startswith("p6r1c1 title: Traction\np6r2c1: 800 Paying Users")
    for needle in ("Jane Doe", "Max Mustermann", "Northwind Trading"):
        assert needle in text, f"{needle!r} is printed on the page and goes as printed (page-image.md section 2)"
    assert "[person]" not in text and "Client-01" not in text and "[redacted]" not in text
    cells = redact.parse_page_text(text)
    assert set(cells) == {6, 7}
    assert not [c for page in cells.values() for c in page if len(c["text"]) > 200], "a line over 200 characters is left out (1b)"
    assert "the team grew. Our" not in text and PROSE[3] in text


# ---------------------------------------------------------------------------
# process_deck under the switch
# ---------------------------------------------------------------------------
def _page_db(parsed, rows=()):
    db = _db()
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "mapping": REVENUE_MAPPING, "mapped_at": "2026-10-05T00:00:00"})
    db[TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "file": "deck.pdf", "page_unit": "page",
                                     "blocks": parsed["blocks"], "structures": parsed["structures"]})
    db[CANDIDATES_COLLECTION].docs.extend(copy.deepcopy(r) for r in rows)
    return db


REPLY = {"type": "page_claims", "claims": [
    claim("p1r2c1", 800, metric="customers", unit="count", label_cell="p1r1c1"),
    claim("p1r3c1", 150000, unit="USD"),
    claim("p1r4c1", 61, metric="gross_margin", unit="%"),                 # the value is on no cell of the page (one found elsewhere is corrected)
]}


def test_with_the_switch_at_ai_the_pages_are_read_and_each_claim_is_a_row_matched_or_not(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = deck([TITLE, *LINES, PROSE])
    db = _page_db(parsed)
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    status = asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert status == "read" and adapter.calls == 1
    sent = json.loads(adapter.payloads[0])
    # The sender builds the text as printed; the gateway masks it (read-check-review.md section 8): the name is removed, the rest is as built.
    built = pipeline.batch_text(pipeline.batches(pages.page_grids(parsed["blocks"]))[0])
    assert sent["type"] == PAGE_CLAIMS and sent["text"] == built.replace("Jane Doe", "[person]")
    assert adapter.requests[-1]["cache_system"] is True, "the fixed prompt is marked for the prompt cache"
    rows = sorted(db[CANDIDATES_COLLECTION].docs, key=lambda r: r["order"])
    assert [(r["claim_type"], r["value"], r["ai_label"]) for r in rows] == [
        ("customers", 800, "Matched to page"), ("revenue", 150000, "Matched to page"), ("gross_margin", 61, "AI suggestion, not matched")]
    assert rows[2]["snippet"] == "97% margins", "the unmatched row shows the model's value against the cell it cited (decision 2a)"
    first = rows[0]
    assert first["sources"] == [{"file": "deck.pdf", "page": 1, "kind": "page", "cell": "r2c1"}]
    assert first["label_from"] is None and first["snippet"] == "800 Paying Users" and first["origin"] == "ai"
    assert first["ai_checks"]["value"] is True and rows[2]["ai_checks"]["value"] is False
    deck_doc, = db[TEXT_COLLECTION].docs
    assert deck_doc["ai_status"] == "read" and deck_doc["page_reads"][0]["pages"] == [1]
    assert {k: deck_doc["page_reads"][0][k] for k in ("matched", "unmatched", "dropped")} == {"matched": 2, "unmatched": 1, "dropped": 0}
    stored, = db[gateway.STRUCTURES_COLLECTION].docs
    assert stored["type"] == PAGE_CLAIMS and stored["pages"] == [1] and stored["output"]["claims"] == [{**dict.fromkeys(("label_text", "segment", "share_of", "is_quote")), **c} for c in REPLY["claims"]]
    assert stored["statuses"] == ["matched", "matched", "unmatched"]


def test_the_default_switch_is_ai_and_rules_selects_the_former_structure_path(monkeypatch):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    assert pipeline.deck_pipeline() == structures.deck_pipeline() == "ai", "the default since 2026-10-22"
    monkeypatch.setenv("DECK_PIPELINE", "pages")
    assert pipeline.deck_pipeline() == "ai", "a typo changes nothing on screen"
    monkeypatch.setenv("DECK_PIPELINE", "rules")
    parsed = deck([TITLE, *LINES, PROSE])
    db = _page_db(parsed)
    adapter = t.FakeAdapter(replies=[json.dumps({"type": "kpi_panel", "labels": [], "pairs": []})])
    asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert all(json.loads(p)["type"] != PAGE_CLAIMS for p in adapter.payloads)
    assert "page_reads" not in db[TEXT_COLLECTION].docs[0]


def test_a_batch_too_large_for_the_cap_is_split_and_a_single_page_too_large_is_skipped(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = deck([TITLE, *LINES])
    blocks = [dict(b, page=n) for n in range(1, 4) for b in parsed["blocks"]]
    db = _page_db({"blocks": blocks, "structures": []})

    class Counting(t.FakeAdapter):
        def count_tokens(self, *, model, system, user_payload, json_schema, images=None):
            self.counted = getattr(self, "counted", 0) + 1
            if system is None:
                return 100 * user_payload.count("Traction")          # a page counts 100 tokens; the cap is 150 below
            return 1200
    adapter = Counting(replies=[json.dumps({"type": "page_claims", "claims": []})])
    monkeypatch.setattr(gateway, "PAGE_INPUT_CAP", 150)
    status = asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert status == "read"
    reads = db[TEXT_COLLECTION].docs[0]["page_reads"]
    assert [(r["pages"], r["status"]) for r in reads] == [([1], "read"), ([2], "read"), ([3], "read")]
    monkeypatch.setattr(gateway, "PAGE_INPUT_CAP", 50)
    db = _page_db({"blocks": blocks, "structures": []})
    status = asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=Counting(replies=[]), sleep=t._noop_sleep))
    assert status == "not_read" and [r["status"] for r in db[TEXT_COLLECTION].docs[0]["page_reads"]] == ["too_large"] * 3


def test_a_page_read_twice_is_served_from_the_cache_and_lists_no_row_twice(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = deck([TITLE, *LINES])
    db = _page_db(parsed)
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert adapter.calls == 1 and len(db[CANDIDATES_COLLECTION].docs) == 3
    # The second run asks for no page it already read (deck page reads, 2026-10-23): its entry stays, and the gateway's cache is not even asked.
    assert [(r["pages"], r["status"]) for r in db[TEXT_COLLECTION].docs[0]["page_reads"]] == [([1], "read")]


def test_without_consent_no_page_goes_and_no_file_is_waited_for(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = deck([TITLE, *LINES])
    db = _page_db(parsed)
    db["audits"].docs[0]["structure_reading_consent"] = False
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    assert asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep)) == "python_only"
    assert adapter.calls == 0
    db = _page_db(parsed)
    db["datasets"].docs.clear()          # no file in the audit: a deck never waits for one (PR 4), it is read
    assert asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep)) != "waiting"
    assert adapter.calls > 0


def test_an_axis_tick_is_marked_on_its_own_cell_and_a_bar_value_in_the_same_column_is_not():
    """The chart of a figure column beside its axis (zero2hero p17): the ticks are the round axis labels, never the bar values,
    whatever band the grid puts them in."""
    texts = [(50, 560, 20, "Turnover")] + [(60, 300 + 40 * i, 9, tick) for i, tick in enumerate(("0", "100,000", "200,000", "300,000"))]
    texts += [(200, 330, 10, "181,193"), (320, 350, 10, "278,085"), (200, 280, 10, "2020"), (320, 280, 10, "2021")]
    g = grid_of(texts)
    ticks = {c["text"] for c in g["cells"] if c.get("tick")}
    assert ticks == {"0", "100,000", "200,000", "300,000"}, ticks
    bars = {c["text"]: c.get("bar_year") for c in g["cells"] if c.get("bar_year")}
    assert bars == {"181,193": "2020", "278,085": "2021"}
    got = page_check.check(g, [claim(f"r{c['row']}c{c['col']}", 278085, unit=None, period="2021") for c in g["cells"] if c["text"] == "278,085"])
    assert got["dropped"] == 0 and got["items"][0]["status"] == page_check.MATCHED


def test_a_page_whose_only_digits_are_a_phone_number_is_sent():
    """A phone number is a digit (2026-10-31); the page goes, and the masking of the page text is the gateway's own."""
    g = grid_of([(50, 560, 20, "Contact"), (50, 500, 12, "Call us on +44 20 7946 0958 or write to the team")])
    assert pages.has_digit_figure(g) is True
    assert len(pipeline.sendable_pages([g])) == 1


# ---------------------------------------------------------------------------
# PR B: a reply cut at the output limit, and the cache bypass of the consistency passes
# ---------------------------------------------------------------------------
class Truncating(t.FakeAdapter):
    """The provider cuts a reply at max_tokens for a batch of more than `limit` pages: the adapter raises the gateway's
    "truncated" error with the tokens the cut reply billed, as AnthropicAdapter does on stop_reason max_tokens."""

    def __init__(self, replies, limit=2):
        super().__init__(replies=replies)
        self.limit = limit
        self.truncated = 0

    def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema, cache_system=False, images=None):
        if json.loads(user_payload)["text"].count("Traction") > self.limit:
            self.calls += 1
            self.truncated += 1
            error = gateway.GatewayError("truncated", "the reply was cut at max_tokens")
            error.tokens = (self.input_tokens, max_tokens)
            raise error
        return super().complete(model=model, system=system, user_payload=user_payload, max_tokens=max_tokens,
                                temperature=temperature, json_schema=json_schema, cache_system=cache_system, images=images)


def test_a_batch_whose_reply_is_cut_at_the_output_limit_is_split_and_read_again(monkeypatch):
    """PR B, the live run of 2026-10-22: a 5-page batch answered with more than PAGE_MAX_TOKENS is cut and fails the schema; the
    same batch asked again is cut again. The step splits it and reads the halves; the cut attempts are billed, not reasked. The
    audit's deck read asks for one page per call since 2026-10-23; the scripts still read five to a call, which this reads."""
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = deck([TITLE, *LINES])
    blocks = [dict(b, page=n) for n in range(1, 6) for b in parsed["blocks"]]
    db = _page_db({"blocks": blocks, "structures": []})
    adapter = Truncating(replies=[json.dumps({"type": "page_claims", "claims": []})])
    read = asyncio.run(pipeline.read_pages(db, AUDIT, "d1", pages.page_grids(blocks), page_images.image_for, adapter=adapter, sleep=t._noop_sleep))
    assert [([pages.page_number(g) for g in grids], r.status) for grids, r in read] == \
        [([1, 2], "read"), ([3], "read"), ([4, 5], "read")], "halves of 2 and 3, the 3 split again"
    assert adapter.truncated == 2 and adapter.calls == 5, "the 5-page batch and its 3-page half were cut once each, no reask"
    calls = [c for c in db["llm_calls"].docs if c["status"] == "truncated"]
    assert [(c["input_tokens"], c["output_tokens"]) for c in calls] == [(1200, gateway.PAGE_MAX_TOKENS)] * 2, "the cut replies are billed"
    assert all(c["estimated_cost_usd"] == gateway.estimate_cost_usd(gateway.STRUCTURE_MODEL, 1200, gateway.PAGE_MAX_TOKENS) for c in calls)


def test_a_single_page_whose_reply_is_cut_keeps_the_status_truncated(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = deck([TITLE, *LINES])
    blocks = [dict(b, page=n) for n in range(1, 3) for b in parsed["blocks"]]
    db = _page_db({"blocks": blocks, "structures": []})
    adapter = Truncating(replies=[], limit=0)
    status = asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert status == "not_read"
    reads = db[TEXT_COLLECTION].docs[0]["page_reads"]
    assert [(r["pages"], r["status"]) for r in reads] == [([1], "truncated"), ([2], "truncated")]
    assert adapter.calls == 2, "each page once (one page to a call); a single page is not split or reasked"
    assert db[TEXT_COLLECTION].docs[0]["unread_pages"] == [1, 2] and db[TEXT_COLLECTION].docs[0]["retry_pages"] == [], "a cut page would be cut again: not retried"


def test_the_adapter_raises_truncated_with_the_billed_tokens_when_the_provider_stops_at_max_tokens():
    """AnthropicAdapter: a reply with stop_reason max_tokens is not JSON the schema can check; it is reported as "truncated" with
    the tokens it billed, so the gateway bills it, logs the closed reason and lets the page step split the batch."""
    from types import SimpleNamespace
    adapter = gateway.AnthropicAdapter(api_key="not-a-key")
    usage = SimpleNamespace(input_tokens=3000, output_tokens=4000, cache_creation_input_tokens=2000, cache_read_input_tokens=0)
    response = SimpleNamespace(stop_reason="max_tokens", content=[SimpleNamespace(type="text", text='{"type": "page_claims", "cl')],
                               usage=usage)
    adapter._client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: response))
    with pytest.raises(gateway.GatewayError) as cut:
        adapter.complete(model=gateway.STRUCTURE_MODEL, system="S", user_payload="{}", max_tokens=4000, temperature=None,
                         json_schema={}, cache_system=True)
    assert cut.value.reason == "truncated" and cut.value.tokens == (5000, 4000)
    assert "page_claims" not in str(cut.value), "the cut reply is not quoted"


def test_the_consistency_passes_bypass_the_cache_and_measure_the_model(monkeypatch):
    """A second read of the same pages in the same audit is a cache hit (0 tokens, the same reply); with use_cache=False the model
    is asked again, so a consistency pass measures the model, not the cache."""
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = deck([TITLE, *LINES])
    db = _page_db(parsed)
    grids = pages.page_grids(parsed["blocks"])
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    first = asyncio.run(pipeline.read_pages(db, AUDIT, "d1", grids, page_images.image_for, adapter=adapter, sleep=t._noop_sleep))
    again = asyncio.run(pipeline.read_pages(db, AUDIT, "d1", grids, page_images.image_for, adapter=adapter, sleep=t._noop_sleep))
    assert adapter.calls == 1 and again[0][1].cache_hit is True and again[0][1].input_tokens == 0
    bypassed = asyncio.run(pipeline.read_pages(db, AUDIT, "d1", grids, page_images.image_for, adapter=adapter, sleep=t._noop_sleep,
                                               use_cache=False))
    assert adapter.calls == 2 and bypassed[0][1].cache_hit is False and bypassed[0][1].input_tokens > 0
    assert bypassed[0][1].claims == first[0][1].claims


