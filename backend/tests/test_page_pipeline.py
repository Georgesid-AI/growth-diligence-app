"""The page pipeline behind DECK_PIPELINE (docs/design/ai-reads-rules-check.md, PR A): the page grid gives every line of a page a
cell id; only a page with a figure as digits may go (decision 1b; number-words do not count); the page text comes through one
builder, redacted, in batches of five; a batch too large is split; under the switch "ai" process_deck reads the pages and lists
each claim as "Matched to page" or "AI suggestion, not matched"; under the default "rules" nothing changes."""
import asyncio
import copy
import json
import sys
from pathlib import Path

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
PROSE = (50, 300, 10, "Our CEO Jane Doe and CTO Max Mustermann met at Northwind Trading in 2019; " * 3 + "the team grew.")


def deck(texts, rects=()):
    return parse_deck(pdf_page(texts, rects), "deck.pdf")


def grid_of(texts, rects=()):
    grids = pages.page_grids(deck(texts, rects)["blocks"])
    assert len(grids) == 1
    return grids[0]


def claim(value_cell, value, metric="revenue", unit="USD", period=None, period_cell=None, label_cell=None):
    return {"metric": metric, "value": value, "value_high": None, "unit": unit, "unit_other": None, "period": period,
            "actual_or_forecast": "actual", "value_cell": value_cell, "label_cell": label_cell, "period_cell": period_cell}


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


@pytest.mark.parametrize("line, figure", [
    ("Revenue grew to three million euros", False), ("Twenty new customers signed", False), ("Founded in 2019", False),
    ("Launched in January 2011", False), ("Revenue grew to €3M", True), ("20 new customers signed", True), ("97%", True)])
def test_a_page_carries_a_figure_only_when_one_is_written_in_digits(line, figure):
    """Decision 1b: a page goes to the model only when it carries a figure as digits; number-words and dates do not count."""
    g = grid_of([TITLE, (50, 500, 12, line)])
    assert pages.has_digit_figure(g) is figure
    assert bool(pages.sendable([g])) is figure


def test_a_background_or_cited_research_page_is_never_sent():
    g = grid_of([(50, 560, 20, "Problem"), (50, 500, 12, "Companies lose 3 hours a day")])
    assert g.get("excluded") is True and pages.sendable([g]) == []


def test_batches_hold_five_pages_and_the_text_comes_through_the_one_builder_redacted():
    grids = [{**grid_of([TITLE, *LINES, PROSE]), "page": n} for n in range(1, 8)]
    batched = pipeline.batches(grids, "Target Co", {"Northwind Trading": "Customer_01"})
    assert [[p["grid"]["page"] for p in b] for b in batched] == [[1, 2, 3, 4, 5], [6, 7]]
    text = pipeline.batch_text(batched[1])
    assert redact.page_text_problem(text) is None
    assert text.startswith("p6r1c1 title: Traction\np6r2c1: 800 Paying Users")
    for needle in ("Jane Doe", "Max Mustermann", "Northwind Trading"):
        assert needle not in text, f"{needle!r} in the page text"
    assert "[person]" in text and "Customer_01" in text
    long_lines = [line for line in text.splitlines() if len(line) > 200]
    assert long_lines, "the prose line over 200 characters goes, redacted"
    assert set(redact.parse_page_text(text)) == {6, 7}


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
    claim("p1r4c1", 150000, metric="gross_margin", unit="%"),             # the value is not in that cell
]}


def test_with_the_switch_at_ai_the_pages_are_read_and_each_claim_is_a_row_matched_or_not(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = deck([TITLE, *LINES, PROSE])
    db = _page_db(parsed)
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    status = asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert status == "read" and adapter.calls == 1
    sent = json.loads(adapter.payloads[0])
    assert sent["type"] == PAGE_CLAIMS and sent["text"] == pipeline.batch_text(pipeline.batches(pages.page_grids(parsed["blocks"]), "Zero2Hero", {})[0])
    assert adapter.requests[-1]["cache_system"] is True, "the fixed prompt is marked for the prompt cache"
    rows = sorted(db[CANDIDATES_COLLECTION].docs, key=lambda r: r["order"])
    assert [(r["claim_type"], r["value"], r["ai_label"]) for r in rows] == [
        ("customers", 800, "Matched to page"), ("revenue", 150000, "Matched to page"), ("gross_margin", 97, "AI suggestion, not matched")]
    first = rows[0]
    assert first["sources"] == [{"file": "deck.pdf", "page": 1, "kind": "page", "cell": "r2c1"}]
    assert first["label_from"] == "Traction" and first["snippet"] == "800 Paying Users" and first["origin"] == "ai"
    assert first["ai_checks"]["value"] is True and rows[2]["ai_checks"]["value"] is False
    deck_doc, = db[TEXT_COLLECTION].docs
    assert deck_doc["ai_status"] == "read" and deck_doc["page_reads"][0]["pages"] == [1]
    assert {k: deck_doc["page_reads"][0][k] for k in ("matched", "unmatched", "dropped")} == {"matched": 2, "unmatched": 1, "dropped": 0}
    stored, = db[gateway.STRUCTURES_COLLECTION].docs
    assert stored["type"] == PAGE_CLAIMS and stored["pages"] == [1] and stored["output"]["claims"] == REPLY["claims"]
    assert stored["statuses"] == ["matched", "matched", "unmatched"]


def test_under_the_default_switch_no_page_is_read_and_the_structure_path_runs_as_before(monkeypatch):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    assert pipeline.deck_pipeline() == "rules"
    monkeypatch.setenv("DECK_PIPELINE", "pages")
    assert pipeline.deck_pipeline() == "rules", "a typo changes nothing on screen"
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
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
        def count_tokens(self, *, model, system, user_payload, json_schema):
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
    assert db[TEXT_COLLECTION].docs[0]["page_reads"][0]["cache_hit"] is True


def test_without_consent_or_before_the_revenue_file_no_page_goes(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = deck([TITLE, *LINES])
    db = _page_db(parsed)
    db["audits"].docs[0]["structure_reading_consent"] = False
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    assert asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep)) == "python_only"
    db = _page_db(parsed)
    db["datasets"].docs.clear()
    assert asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep)) == "waiting"
    assert adapter.calls == 0


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


def test_a_page_whose_only_digits_are_a_phone_number_is_not_sent_after_redaction():
    """The parser's reader sees digits in "+44 20 7946 0958"; redaction turns them into [phone], so the page carries no figure
    and never goes (the gateway would refuse it as no_figure, and would refuse the whole batch with it)."""
    g = grid_of([(50, 560, 20, "Contact"), (50, 500, 12, "Call us on +44 20 7946 0958 or write to the team")])
    assert pages.has_digit_figure(g) is True
    assert pipeline.redacted_pages([g], "Target Co", {}) == []
    assert pipeline.batches([g, grid_of([TITLE, *LINES])], "Target Co", {})[0][0]["grid"]["cells"][0]["text"] == "Traction"
