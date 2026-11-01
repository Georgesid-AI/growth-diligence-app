"""A Word file goes through the deck reader as a text-based PDF does (docs/specs/deck-parser.md: PowerPoint, Word and text-based PDF).

The fixture is synthetic (tests/fixtures/decks/synthetic_plan.docx: a made-up company, no person, no contact): prose paragraphs, a table
and a hard page break, so it has two pages. The parser reads paragraphs and tables in document order, each page with a digit goes to the page
reader as text with its cell ids, and a claim the model cites is matched to its cell. Nothing reaches a provider: the fake adapter answers."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("docx")

from test_page_pipeline import _page_db, claim, t  # noqa: E402

from app import structures  # noqa: E402
from app.decks import CANDIDATES_COLLECTION, TEXT_COLLECTION, pages, parser  # noqa: E402
from app.llm.schemas import PAGE_CLAIMS  # noqa: E402

FIXTURE = BACKEND / "tests" / "fixtures" / "decks" / "synthetic_plan.docx"


def parsed_docx():
    return parser.parse_deck(FIXTURE.read_bytes(), FIXTURE.name)


def test_the_parser_reads_a_docx_as_pages_of_paragraphs_and_tables_in_document_order():
    deck = parsed_docx()
    assert deck["format"] == "docx" and deck["page_unit"] == "page" and deck["pages"] == 2
    texts = [(b["page"], b["kind"], b["text"]) for b in deck["blocks"]]
    assert texts[0] == (1, "text", "Northwind Analytics – Growth plan 2026")
    assert (1, "text", "800 paying customers at the end of 2025.") in texts
    assert (1, "table", "1,150") in texts and (1, "table", "FY2026 plan") in texts, "table cells are blocks of the page they sit on"
    assert texts[-1] == (2, "text", "Headcount grows from 24 to 40 people by December 2026."), "the text after the page break is page 2"
    order = [b["text"] for b in deck["blocks"] if b["page"] == 1]
    assert order.index("ARR of EUR 1.2M in December 2025, up 60% year on year.") < order.index("FY2025"), "paragraphs before the table that follows them"
    cell, = [b for b in deck["blocks"] if b["text"] == "2,300"]
    assert cell["table"] == 1 and (cell["row"], cell["col"]) == (2, 3)


def test_every_docx_page_with_a_digit_goes_to_the_page_reader_as_text_with_cell_ids_and_a_cited_claim_is_matched(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    deck = parsed_docx()
    grids = pages.page_grids(deck["blocks"])
    assert [(pages.page_number(g), pages.has_digit_figure(g)) for g in grids] == [(1, True), (2, True)]
    customers = next(c for c in grids[0]["cells"] if c["text"].startswith("800 paying"))
    revenue = next(c for c in grids[0]["cells"] if c["text"] == "1,150")
    header = next(c for c in grids[0]["cells"] if c["text"] == "FY2025")
    reply = {"type": PAGE_CLAIMS, "claims": [
        claim(f"p1r{customers['row']}c{customers['col']}", 800, metric="customers", unit="count"),
        claim(f"p1r{revenue['row']}c{revenue['col']}", 1150, unit="EUR", period="FY2025", period_cell=f"p1r{header['row']}c{header['col']}")]}
    db = _page_db(deck)
    db[TEXT_COLLECTION].docs[0].update(file="synthetic_plan.docx", format="docx", pages=2)
    adapter = t.FakeAdapter(replies=[json.dumps(reply)])
    status = asyncio.run(structures.process_deck(db, "audit-s", "d1", adapter=adapter, sleep=t._noop_sleep))
    assert status == "read" and adapter.calls == 2, "one request per page with its image, as for a two-page PDF"
    sent = [json.loads(p) for p in adapter.payloads]
    assert all(s["type"] == PAGE_CLAIMS for s in sent)
    text = "\n".join(s["text"] for s in sent)
    assert "p1r1c1: Northwind Analytics – Growth plan 2026" in text or "p1r1c1: Client-01" in text
    assert "Headcount grows from 24 to 40 people by December 2026." in text, "page 2 goes too"
    assert "1,150" in text and "FY2026 plan" in text, "the table's cells go as lines of the page"
    rows = sorted(db[CANDIDATES_COLLECTION].docs, key=lambda r: r["order"])
    assert [(r["claim_type"], r["value"], r["ai_label"]) for r in rows] == [("customers", 800, "Matched to page"), ("revenue", 1150, "Matched to page")]
    assert rows[0]["sources"] == [{"file": "synthetic_plan.docx", "page": 1, "kind": "page", "cell": f"r{customers['row']}c{customers['col']}"}]
    assert sorted(n for r in db[TEXT_COLLECTION].docs[0]["page_reads"] for n in r["pages"]) == [1, 2]


def test_a_docx_is_accepted_at_the_deck_upload_and_parsed_as_word(monkeypatch):
    from test_structure_reading import AUDIT, _deck_api
    client, db, adapter = _deck_api(monkeypatch)
    r = client.post(f"/api/audits/{AUDIT}/decks/upload", files={"file": (FIXTURE.name, FIXTURE.read_bytes())})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["format"], body["page_unit"], body["pages"], body["figure_pages"]) == ("docx", "page", 2, 2)
    stored, = db[TEXT_COLLECTION].docs
    assert stored["format"] == "docx" and stored["pages"] == 2
    assert parser.deck_format("plan.DOCX") == "docx" and parser.UNSUPPORTED.startswith("We read text from PowerPoint (.pptx), Word (.docx)")
