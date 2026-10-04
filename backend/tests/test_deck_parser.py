"""Deck parser and candidate claims (docs/specs/deck-parser.md sections 1, 2 and 5).

Small decks are built in the test with the same libraries the parser reads them with; the
public decks in tests/fixtures/decks/decks/ check references on real layouts. Endpoints run
against the in-memory Mongo stub.
"""
import io
import os
import sys
from pathlib import Path

import pytest

pptx = pytest.importorskip("pptx")
docx = pytest.importorskip("docx")
pytest.importorskip("pdfplumber")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import decks  # noqa: E402
from app.decks import claims, parser  # noqa: E402

DECKS = BACKEND.parent / "tests" / "fixtures" / "decks" / "decks"


def _pptx(slides, notes=None, groups=None, tables=None) -> bytes:
    """slides: list of lists of text-box texts. notes/groups/tables: {slide index: ...}."""
    from pptx.util import Inches
    prs = pptx.Presentation()
    for i, texts in enumerate(slides):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        for j, text in enumerate(texts):
            slide.shapes.add_textbox(Inches(1), Inches(1 + j), Inches(6), Inches(1)).text_frame.text = text
        for text in (groups or {}).get(i, []):
            slide.shapes.add_group_shape().shapes.add_textbox(Inches(1), Inches(5), Inches(4), Inches(1)).text_frame.text = text
        if i in (tables or {}):
            rows = tables[i]
            table = slide.shapes.add_table(len(rows), len(rows[0]), Inches(1), Inches(3), Inches(6), Inches(2)).table
            for r, row in enumerate(rows):
                for c, text in enumerate(row):
                    table.cell(r, c).text = text
        if i in (notes or {}):
            slide.notes_slide.notes_text_frame.text = notes[i]
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _pdf(pages: int) -> bytes:
    """A PDF of blank pages: no text, as a scanned file would have."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(612, 792)
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def _has(blocks, **fields):
    """A block with these fields (it may also carry layout fields: box, bbox, title)."""
    return any(all(b.get(k) == v for k, v in fields.items()) for b in blocks)


def _by_value(candidates, value):
    return [c for c in candidates if c["value"] == value]


# ---------------------------------------------------------------------------
# Parsing and references
# ---------------------------------------------------------------------------
def test_pptx_text_boxes_groups_tables_and_notes_keep_their_slide():
    content = _pptx(
        [["Traction", "ARR grew to $3.6M by Q4 2024"], ["Plan"], ["Recap: ARR grew to $3.6M by Q4 2024"]],
        notes={1: "Team grows to 40 hires in 2025"},
        groups={0: ["Churn is 5%"]},
        tables={1: [["", "2023", "2024"], ["Revenue", "$1.2M", "$2.5M"]]},
    )
    deck = parser.parse_deck(content, "board.pptx")
    assert (deck["format"], deck["page_unit"], deck["pages"]) == ("pptx", "slide", 3)
    assert _has(deck["blocks"], slide=1, kind="text", text="Churn is 5%"), "text inside a group shape"
    assert _has(deck["blocks"], slide=2, kind="notes", text="Team grows to 40 hires in 2025")
    assert _has(deck["blocks"], slide=2, kind="table", table=1, row=2, col=3, text="$2.5M")

    found = claims.detect_candidates(deck["blocks"], "board.pptx")
    arr, = _by_value(found, 3600000)
    assert (arr["claim_type"], arr["currency"], arr["target_date"]) == ("revenue", "USD", "2024-Q4")
    assert arr["sources"] == [{"file": "board.pptx", "slide": 1, "kind": "text"},
                              {"file": "board.pptx", "slide": 3, "kind": "text"}], "merged, every source kept"
    churn, = _by_value(found, 5)
    assert (churn["claim_type"], churn["unit"]) == ("retention", "%")
    revenue, = _by_value(found, 2500000)
    assert revenue["sources"] == [{"file": "board.pptx", "slide": 2, "kind": "table", "table": 1, "row": 2, "col": 3}]
    assert (revenue["snippet"], revenue["date_from"], revenue["target_date"]) == ("Revenue | $1.2M | $2.5M", "2024", "2024")
    hires, = _by_value(found, 40)
    assert hires["claim_type"] == "people" and hires["target_date"] == "2025"
    assert hires["sources"] == [{"file": "board.pptx", "slide": 2, "kind": "notes"}]


def test_docx_pages_follow_page_breaks_and_new_page_sections():
    from docx.enum.section import WD_SECTION
    doc = docx.Document()
    doc.add_paragraph("Board update")
    doc.add_page_break()
    doc.add_paragraph("Revenue was €2M in 2023")                     # page 2
    doc.add_section(WD_SECTION.NEW_PAGE)
    table = doc.add_table(rows=2, cols=2)                             # page 3
    table.cell(0, 0).text, table.cell(0, 1).text = "Metric", "Value"
    table.cell(1, 0).text, table.cell(1, 1).text = "Churn", "4%"
    doc.add_section(WD_SECTION.CONTINUOUS)
    doc.add_paragraph("Headcount 25 by March 2026")                   # still page 3
    buf = io.BytesIO()
    doc.save(buf)

    deck = parser.parse_deck(buf.getvalue(), "plan.docx")
    assert deck["pages"] == 3
    assert _has(deck["blocks"], page=2, kind="text", text="Revenue was €2M in 2023")
    assert _has(deck["blocks"], page=3, kind="table", table=1, row=2, col=2, text="4%")
    assert _has(deck["blocks"], page=3, kind="text", text="Headcount 25 by March 2026")
    found = claims.detect_candidates(deck["blocks"], "plan.docx")
    churn, = _by_value(found, 4)
    assert churn["sources"] == [{"file": "plan.docx", "page": 3, "kind": "table", "table": 1, "row": 2, "col": 2}]
    people, = _by_value(found, 25)
    assert (people["claim_type"], people["target_date"]) == ("people", "2026-03")


@pytest.mark.parametrize("file, page, value, kind", [
    ("01-front-b.pptx", 13, 150, "text"),             # 150% net retention rate at 1 year
    ("03-buffer.pptx", 5, 150000, "text"),            # $150,000 annual revenue run rate
    ("02-moz.pdf", 21, 25, "text"),                   # Churn Rate in 1st 2 Paid Months ~25%
    ("09-genesisai-2024.pdf", 5, 8000, "text"),       # $8,000 revenue in 2022
    ("05-zero2hero.pdf", 19, 130550, "table"),        # Revenue row of the projections table
    ("04-clevergig.docx", 6, 260, "text"),            # €260 MRR per client
    ("04-clevergig.docx", 9, 200000000, "text"),      # TAM of €200M
    ("04-clevergig.docx", 11, 20, "text"),            # teams to a total of 20 end of 2020
    ("07-equals-seed.docx", 9, 180000000, "text"),    # Intercom's ARR (a distractor, but its page is still cited)
])
def test_public_decks_cite_the_right_slide_or_page(file, page, value, kind):
    content = (DECKS / file).read_bytes()
    deck = parser.parse_deck(content, file)
    hits = [s for c in _by_value(claims.detect_candidates(deck["blocks"], file), value) for s in c["sources"]]
    assert any(s.get("slide", s.get("page")) == page and s["kind"] == kind for s in hits), hits


def test_zero2hero_table_figures_cite_row_and_column():
    file = "05-zero2hero.pdf"
    deck = parser.parse_deck((DECKS / file).read_bytes(), file)
    found = claims.detect_candidates(deck["blocks"], file)
    cells = [(c["sources"][0]["row"], c["sources"][0]["col"], c["value"], c["currency"])
             for c in found if c["sources"][0] == {**c["sources"][0], "page": 19, "kind": "table", "row": 4}]
    assert cells == [(4, 2, 130550, "GBP"), (4, 3, 150000, "GBP"), (4, 4, 250000, "GBP"),
                     (4, 5, 1000000, "GBP"), (4, 6, 2500000, "GBP")]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
def test_a_file_with_no_readable_text_is_refused_with_the_spec_message():
    expected = ("No readable text found in this file. It may be scanned or made of images. "
                "Please upload a text-based version.")
    for content, name in ((_pdf(2), "scan.pdf"), (_pptx([[]]), "pictures.pptx")):
        with pytest.raises(parser.DeckError) as err:
            parser.parse_deck(content, name)
        assert err.value.message == expected


@pytest.mark.parametrize("name, message", [
    ("deck.key", "We cannot read Keynote files. Please export it as PowerPoint or PDF first."),
    ("deck.ppt", parser.UNSUPPORTED),
    ("https://docs.google.com/presentation/d/abc", parser.UNSUPPORTED),
])
def test_out_of_scope_formats_are_refused(name, message):
    with pytest.raises(parser.DeckError) as err:
        parser.parse_deck(b"anything", name)
    assert err.value.message == message


def test_limits_50_mb_and_200_pages():
    with pytest.raises(parser.DeckError) as err:
        parser.parse_deck(b"\0" * (parser.MAX_BYTES + 1), "big.pdf")
    assert err.value.message == "This file is larger than 50 MB. Please upload a file of 50 MB or less."
    with pytest.raises(parser.DeckError) as err:
        parser.parse_deck(_pdf(201), "long.pdf")
    assert err.value.message.startswith("This file has 201 pages. We read up to 200 slides or pages per file.")
    with pytest.raises(parser.DeckError) as err:
        parser.parse_deck(_pptx([["ARR $1M"]] * 201), "long.pptx")
    assert err.value.message.startswith("This file has 201 slides.")
    assert parser.parse_deck(_pptx([["ARR $1M"]] * 200), "ok.pptx")["pages"] == 200


def test_a_damaged_file_is_refused_without_quoting_it():
    with pytest.raises(parser.DeckError) as err:
        parser.parse_deck(b"Jane Doe (CEO) not a zip", "board.pptx")
    assert err.value.message == parser.UNREADABLE.format(kind="PowerPoint")
    assert "Jane Doe" not in err.value.message


# ---------------------------------------------------------------------------
# Candidate detection
# ---------------------------------------------------------------------------
def _line(text):
    return claims.line_candidates(text, [(0, len(text), {"file": "f.pdf", "page": 1, "kind": "text"})])


def test_a_line_needs_a_number_and_a_keyword():
    assert _line("We grew fast and churn is low") == []          # keyword, no number
    assert _line("Section 111, Row 15") == []                    # numbers, no keyword, nothing counted
    assert [c["value"] for c in _line("800 paying users, ARR $1.2M")] == [800, 1200000]


@pytest.mark.parametrize("text, value, unit, currency, date", [
    ("Revenues stand at €15K MRR", 15000, None, "EUR", None),
    ("2011 Estimated Revenue $12 - $13 million", 12000000, None, "USD", "2011"),
    ("Current Revenue Run Rate (June) ~$10.8 million", 10800000, None, "USD", None),
    ("Revenue £ 150,000", 150000, None, "GBP", None),
    ("4.9x more growth per user", 4.9, "x", None, None),
    ("150% net retention rate", 150, "%", None, None),
    ("Our BHAG is €5M ARR by end of 2024", 5000000, None, "EUR", "2024"),
    ("To fund an initial team for 24 months.", 24, "months", None, None),
    ("A TAM of USD 200M", 200000000, None, "USD", None),
    ("Market size ($52 B)", 52000000000, None, "USD", None),
])
def test_figures_are_read_with_unit_currency_and_date(text, value, unit, currency, date):
    first = _line(text)[0]
    assert (first["value"], first["unit"], first["currency"], first["target_date"]) == (value, unit, currency, date)


@pytest.mark.parametrize("text, dates", [
    ("Launched web app January 2011", ["2011-01"]),
    ("1981 2001 Feb. 2007 Oct. 2008 July 2011", ["2007-02", "2008-10", "2011-07"]),
    ("Q1 17\tQ2 17\tQ3 17", ["2017-Q1", "2017-Q2", "2017-Q3"]),
    ("Release planned 2021 Q3", ["2021-Q3"]),
    ("Iphone dev license applied for Nov28,08", ["2008-11"]),
    ("Aiming for $xx ARR by end of 2018", ["2018"]),
])
def test_a_line_whose_figures_are_dates_gives_one_candidate_per_date(text, dates):
    found = _line(text)
    assert [c["target_date"] for c in found] == dates and all(c["value"] is None for c in found)


def test_ordinals_and_lone_years_next_to_a_month_are_not_figures():
    assert _line("We are raising a seed round in the 2nd half of 2019") == []
    assert _line("Launch an app-store, host 3rd party apps") == []
    assert _line("Mayor of 2021") == []                           # "May" is a month only as a word


def test_snippet_is_at_most_300_characters_and_shows_the_figure():
    text = "Background " * 40 + "ARR reached $9.9M in 2024 " + "and more " * 40
    snippet = _line(text)[0]["snippet"]
    assert len(snippet) <= 300 and "$9.9M" in snippet


# ---------------------------------------------------------------------------
# Endpoints and storage
# ---------------------------------------------------------------------------
@pytest.fixture()
def api(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("motor")
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "deck_parser_test")
    from fastapi.testclient import TestClient
    import server
    import test_llm_gateway as t
    db = t.FakeDB()
    db["audits"].docs += [{"id": "audit-1", "results": None}, {"id": "audit-2", "results": None}]
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app, raise_server_exceptions=False), db


def _upload(client, audit, name, content):
    return client.post(f"/api/audits/{audit}/decks/upload", files={"file": (name, content)})


def test_upload_stores_parsed_text_and_candidates_linked_to_the_audit(api):
    client, db = api
    r = _upload(client, "audit-1", "03-buffer.pptx", (DECKS / "03-buffer.pptx").read_bytes())
    assert r.status_code == 200, r.text
    assert r.json()["pages"] == 13 and r.json()["candidates"] > 0
    stored, = db[decks.TEXT_COLLECTION].docs
    assert stored["audit_id"] == "audit-1"
    assert _has(stored["blocks"], slide=5, kind="text", text="$150,000 annual revenue run rate")
    assert all(c["audit_id"] == "audit-1" and c["status"] == "pending" for c in db[decks.CANDIDATES_COLLECTION].docs)

    listed = client.get("/api/audits/audit-1/decks").json()
    assert [d["file"] for d in listed["decks"]] == ["03-buffer.pptx"] and "blocks" not in listed["decks"][0]
    run_rate = next(c for c in listed["candidates"] if c["value"] == 150000)
    assert run_rate["sources"][0] == {"file": "03-buffer.pptx", "slide": 5, "kind": "text"}

    # The same file again replaces its earlier parse.
    _upload(client, "audit-1", "03-buffer.pptx", (DECKS / "03-buffer.pptx").read_bytes())
    assert len(db[decks.TEXT_COLLECTION].docs) == 1
    assert len(db[decks.CANDIDATES_COLLECTION].docs) == r.json()["candidates"]


def test_refusals_reach_the_upload_screen_as_400_with_the_message(api):
    client, _ = api
    r = _upload(client, "audit-1", "scan.pdf", _pdf(1))
    assert r.status_code == 400 and r.json()["detail"] == parser.NO_TEXT
    r = _upload(client, "audit-1", "deck.key", b"keynote")
    assert r.status_code == 400 and r.json()["detail"] == parser.KEYNOTE
    assert _upload(client, "no-such-audit", "deck.pdf", _pdf(1)).status_code == 404


def test_approve_reject_and_edit_a_candidate(api):
    client, db = api
    _upload(client, "audit-1", "03-buffer.pptx", (DECKS / "03-buffer.pptx").read_bytes())
    first, second = db[decks.CANDIDATES_COLLECTION].docs[:2]
    url = "/api/audits/audit-1/decks/candidates/{}"
    assert client.put(url.format(first["id"]), json={"status": "approved"}).json()["status"] == "approved"
    assert client.put(url.format(first["id"]), json={"status": "rejected"}).json()["status"] == "rejected"

    before = {k: second[k] for k in ("claim_type", "value", "value_high", "unit", "currency", "target_date")}
    edited = client.put(url.format(second["id"]), json={"claim_type": "sales", "value": 42, "unit": None}).json()
    assert edited["status"] == "edited" and (edited["claim_type"], edited["value"], edited["unit"]) == ("sales", 42, None)
    assert edited["parsed"] == before, "what the parser found is kept next to the edit"
    assert edited["snippet"] == second["snippet"] and edited["sources"] == second["sources"]
    ranged = client.put(url.format(second["id"]), json={"value": 12000000, "value_high": 13000000}).json()
    assert (ranged["value"], ranged["value_high"], ranged["parsed"]) == (12000000, 13000000, before)

    assert client.put(url.format(second["id"]), json={"snippet": "typed"}).status_code == 400, "evidence is not editable"
    assert client.put(url.format(second["id"]), json={"status": "approved", "value": 1}).status_code == 400
    assert client.put(url.format(second["id"]), json={"target_date": "June"}).status_code == 422
    assert client.put(url.format(second["id"]), json={"unit": "x" * 41}).status_code == 422
    assert client.put("/api/audits/audit-2/decks/candidates/" + second["id"], json={"status": "approved"}).status_code == 404


def test_delete_audit_removes_its_parsed_text_and_candidates_only(api):
    client, db = api
    for audit in ("audit-1", "audit-2"):
        assert _upload(client, audit, "03-buffer.pptx", (DECKS / "03-buffer.pptx").read_bytes()).status_code == 200
    r = client.delete("/api/audits/audit-1")
    assert r.status_code == 200, r.text
    assert r.json()["decks_purged"]["deck_text"] == 1 and r.json()["decks_purged"]["deck_candidates"] > 0
    for name in (decks.TEXT_COLLECTION, decks.CANDIDATES_COLLECTION):
        assert {d["audit_id"] for d in db[name].docs} == {"audit-2"}


def test_reseeding_the_demo_audits_removes_their_parsed_text_and_candidates(api):
    """The startup re-seed deletes the old demo audits; their deck text goes with them."""
    import asyncio
    import server
    client, db = api
    db["audits"].docs.append({"id": "old-demo", "demo": True, "seed_version": 2, "results": None})
    for audit in ("old-demo", "audit-1"):
        assert _upload(client, audit, "03-buffer.pptx", (DECKS / "03-buffer.pptx").read_bytes()).status_code == 200
    asyncio.run(server.seed_demo())
    for name in (decks.TEXT_COLLECTION, decks.CANDIDATES_COLLECTION):
        assert {d["audit_id"] for d in db[name].docs} == {"audit-1"}


# ---------------------------------------------------------------------------
# Borrowing a keyword and a date from nearby text (spec section 2)
# ---------------------------------------------------------------------------
def _slide(boxes, title=None, table=None) -> bytes:
    """One slide. boxes: [(text, left_in, top_in)]; table: (rows, left_in, top_in)."""
    from pptx.util import Inches
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5 if title else 6])
    if title:
        slide.shapes.title.text = title
    for text, left, top in boxes:
        slide.shapes.add_textbox(Inches(left), Inches(top), Inches(2), Inches(0.5)).text_frame.text = text
    if table:
        rows, left, top = table
        grid = slide.shapes.add_table(len(rows), len(rows[0]), Inches(left), Inches(top), Inches(4), Inches(1)).table
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                grid.cell(r, c).text = text
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _found(content, name="deck.pptx"):
    deck = parser.parse_deck(content, name)
    return claims.detect_candidates(deck["blocks"], name)


def test_a_figure_borrows_its_label_from_the_same_text_box():
    found = _found(_slide([("Gross churn\n4.5%", 1, 2)]))
    churn, = _by_value(found, 4.5)
    assert (churn["claim_type"], churn["snippet"], churn["label_from"]) == ("retention", "4.5%", "Gross churn")
    assert churn["sources"] == [{"file": "deck.pptx", "slide": 1, "kind": "text"}], "the figure's own line is cited"


def test_a_figure_borrows_its_label_and_date_from_the_table_column_header():
    found = _found(_slide([], table=([["Year", "ARR"], ["2024", "$3M"], ["2025", "$5M"]], 1, 2)))
    arr, = _by_value(found, 5000000)
    assert (arr["claim_type"], arr["target_date"]) == ("revenue", "2025")
    found = _found(_slide([], table=([["Metric", "2024", "2025"], ["Pipeline", "$1M", "$2M"]], 1, 2)))
    assert [(c["value"], c["claim_type"], c["target_date"]) for c in found if c["value"]] == \
        [(1000000, "sales", "2024"), (2000000, "sales", "2025")]


def test_a_figure_borrows_by_position_from_the_same_row_or_above_never_below():
    beside = _found(_slide([("Gross churn", 1, 3), ("6%", 3.5, 3)]))
    assert [(c["value"], c["claim_type"]) for c in beside] == [(6, "retention")]
    above = _found(_slide([("Gross churn", 1, 3), ("6%", 1, 3.6)]))
    assert [(c["value"], c["claim_type"]) for c in above] == [(6, "retention")]
    below = _found(_slide([("6%", 1, 3), ("Gross churn", 1, 3.6)]))
    assert below == []
    too_far = _found(_slide([("Gross churn", 0.2, 0.2), ("6%", 8, 6.5)]))
    assert too_far == [], f"beyond REACH ({claims.REACH} of the slide)"


def test_a_figure_borrows_the_slide_title_last():
    found = _found(_slide([("$4.2M", 8, 6.5)], title="Pipeline coverage"))
    pipeline, = _by_value(found, 4200000)
    assert (pipeline["claim_type"], pipeline["snippet"], pipeline["label_from"]) == ("sales", "$4.2M", "Pipeline coverage")
    nearer = _found(_slide([("Win rate", 7, 6.5), ("31%", 8.5, 6.5)], title="Pipeline coverage"))
    assert [c["claim_type"] for c in _by_value(nearer, 31)] == ["sales"]
    assert _by_value(nearer, 31)[0]["label_from"] == "Win rate", "the nearest label wins over the title"


def test_a_product_line_without_a_figure_takes_a_nearby_date():
    found = _found(_slide([("Launch the API\nOctober 2026", 1, 2)]))
    api, = found
    assert (api["claim_type"], api["value"], api["target_date"]) == ("product", None, "2026-10")
    assert (api["snippet"], api["label_from"], api["date_from"]) == ("Launch the API", None, "October 2026")
    hire = _found(_slide([("Hire a CFO\nOctober 2026", 1, 2)]))
    assert [c["snippet"] for c in hire] == ["October 2026"], "a line without a figure counts only when it is a product line"


def test_a_roadmap_bullet_takes_the_quarter_beside_it():
    file = "10-tea.pdf"
    found = claims.detect_candidates(parser.parse_deck((DECKS / file).read_bytes(), file)["blocks"], file)
    gluon = [c for c in found if c["snippet"] == "Gluon wallet"]
    assert [(c["claim_type"], c["value"], c["target_date"]) for c in gluon] == [("product", None, "2021-Q2")]
    assert [s["page"] for s in gluon[0]["sources"]] == [11] and gluon[0]["date_from"] == "2021 Q2"


def test_a_pdf_value_borrows_the_label_on_its_row():
    file = "02-moz.pdf"
    found = claims.detect_candidates(parser.parse_deck((DECKS / file).read_bytes(), file)["blocks"], file)
    cac, = [c for c in _by_value(found, 100) if c["currency"] == "USD"]
    assert (cac["claim_type"], cac["snippet"], cac["label_from"]) == ("sales", "~$100", "Avg. Cost of Paid Acquisition")


@pytest.mark.parametrize("text, family", [
    ("Turnover £49,284", "revenue"), ("Avg. Customer Lifetime Value ~$900", "sales"), ("LTV $240", "sales"),
    ("Implied Customer Life ~9 Months", "retention"), ("% of Free Trials Converting to Paid ~57%", "sales"),
    ("30% of our leads come via referrals", "sales"), ("This covers 50% of entire US market", "market"),
    ("Recruit 3 engineers", "people"), ("Low attrition: 0", "people"), ("Ship v2 in 40 days", "product"),
    ("Milestone 3 reached", "product"),
])
def test_added_keywords(text, family):
    assert _line(text)[0]["claim_type"] == family


@pytest.mark.parametrize("text", ["Marketing spend is 20% of budget", "30% of marketplace transactions"])
def test_market_is_a_whole_word(text):
    assert _line(text) == []


@pytest.mark.parametrize("text, low, high, unit, currency", [
    ("2011 Estimated Revenue $12 - $13 million", 12000000, 13000000, None, "USD"),
    ("Churn of 5-10%", 5, 10, "%", None),
    ("Team grows from 40 to 100", 40, 100, None, None),
])
def test_a_range_is_one_candidate_with_low_and_high(text, low, high, unit, currency):
    c, = _line(text)
    assert (c["value"], c["value_high"], c["unit"], c["currency"]) == (low, high, unit, currency)


# ---------------------------------------------------------------------------
# Unpack cap for zip-based formats (spec section 1)
# ---------------------------------------------------------------------------
def _zip(parts=1, unpacked=0) -> bytes:
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for i in range(parts):
            z.writestr(f"ppt/part{i}.xml", b"")
        if unpacked:
            with z.open("ppt/big.xml", "w", force_zip64=True) as f:
                chunk = b"\0" * (1 << 20)
                for _ in range(unpacked // len(chunk)):
                    f.write(chunk)
    return buf.getvalue()


@pytest.mark.parametrize("name", ["deck.pptx", "plan.docx"])
def test_a_zip_that_unpacks_too_far_is_refused_before_it_is_opened(name):
    assert parser.MAX_UNPACKED_BYTES == 250 * 1024 * 1024 and parser.MAX_PARTS == 5000
    big = _zip(unpacked=251 * 1024 * 1024)
    assert len(big) < 2 * 1024 * 1024, "small on disk, large unpacked"
    with pytest.raises(parser.DeckError) as err:
        parser.parse_deck(big, name)
    assert err.value.message == ("This file unpacks to more than 250 MB. We read files that unpack to 250 MB or less. "
                                 "Please save a copy with fewer or smaller pictures and upload it again.")
    with pytest.raises(parser.DeckError) as err:
        parser.parse_deck(_zip(parts=5001), name)
    assert err.value.message == ("This file holds more than 5,000 parts. We read files with up to 5,000 parts. "
                                 "Please save a simpler copy and upload it again.")


def test_a_zip_at_the_limits_is_opened():
    """5,000 parts and 250 MB pass the cap; this zip then fails as not a real deck."""
    for content in (_zip(parts=5000), _zip(unpacked=250 * 1024 * 1024)):
        with pytest.raises(parser.DeckError) as err:
            parser.parse_deck(content, "deck.pptx")
        assert err.value.message == parser.UNREADABLE.format(kind="PowerPoint")


# ---------------------------------------------------------------------------
# Claim types (customers, users, gross margin, usage, growth by noun)
# ---------------------------------------------------------------------------
def test_buffer_slide_5_types_and_units():
    """The browser test that found the wrong types: each line keeps its own keyword."""
    file = "03-buffer.pptx"
    found = claims.detect_candidates(parser.parse_deck((DECKS / file).read_bytes(), file)["blocks"], file)
    slide5 = [(c["claim_type"], c["value"], c["unit"], c["currency"], c["snippet"], c["label_from"])
              for c in found if c["sources"][0]["slide"] == 5]
    assert slide5 == [
        ("customers", 800, "paying users", None, "800 Paying Users", None),
        ("revenue", 150000, None, "USD", "$150,000 annual revenue run rate", None),
        ("gross_margin", 97, "%", None, "97% margins", None),
        ("users", 55000, "users", None, "55,000 users, growing 40% per month", None),
        ("user_growth", 40, "%", None, "55,000 users, growing 40% per month", None),
        ("usage", 1500000, "updates", None, "1.5 million updates Buffered", None),
    ]


@pytest.mark.parametrize("text, family", [
    ("Revenues stand at €15K MRR and are growing 15% MoM", "revenue_growth"),
    ("55,000 users, growing 40% per month", "user_growth"),
    ("Proven record of 2X+ growth for 4 years", "growth"),
    ("ARR grew 3x", "revenue_growth"),
    ("A CAGR of 17.2% from 2021 to 2026", "growth"),
])
def test_growth_takes_its_type_from_the_noun_on_its_line(text, family):
    assert [c["claim_type"] for c in _line(text) if c["unit"] in ("%", "x")] == [family]


def test_an_amount_beside_a_growth_word_takes_the_noun_type():
    assert [c["claim_type"] for c in _line("ARR grew to $3.6M")] == ["revenue"]
    assert [c["claim_type"] for c in _line("Users grew to 55,000")] == ["users"]


@pytest.mark.parametrize("text, family, unit", [
    ("800 Paying Users", "customers", "paying users"),
    ("or some 1,500 clients", "customers", "clients"),
    ("12 enterprise accounts", "customers", None),
    ("2,600+ users", "users", "users"),
    ("Gross Margins ~82%", "gross_margin", "%"),
    ("1.5 million updates Buffered", "usage", "updates"),
    ("Avg. Customer Lifetime Value ~$900", "sales", None),
])
def test_customers_users_margin_and_usage(text, family, unit):
    c = _line(text)[0]
    assert c["claim_type"] == family and (unit is None or c["unit"] == unit)


def test_a_line_with_its_own_keyword_never_borrows_a_label():
    found = _found(_slide([("Revenue\n800 Paying Users\n97% margins", 1, 2)], title="ARR"))
    assert [(c["claim_type"], c["label_from"]) for c in found] == [("customers", None), ("gross_margin", None)]
    usage = _found(_slide([("Revenue\n1.5 million updates", 1, 2)]))
    assert [(c["claim_type"], c["label_from"]) for c in usage] == [("usage", None)], "a count is usage, not a borrowed type"


# ---------------------------------------------------------------------------
# What approve, edit and reject do (the instruction text above the approval list)
# ---------------------------------------------------------------------------
def test_approved_and_edited_claims_make_the_register_rejected_stay_on_record(api):
    client, db = api
    _upload(client, "audit-1", "03-buffer.pptx", (DECKS / "03-buffer.pptx").read_bytes())
    one, two, three = (dict(c) for c in db[decks.CANDIDATES_COLLECTION].docs[:3])
    url = "/api/audits/audit-1/decks/candidates/{}"
    client.put(url.format(one["id"]), json={"status": "approved"})
    edited = client.put(url.format(two["id"]), json={"value": 900}).json()
    assert edited["status"] == "edited" and edited["parsed"]["value"] == two["value"]
    again = client.put(url.format(two["id"]), json={"status": "approved"}).json()
    assert again["status"] == "edited" and again["parsed"]["value"] == two["value"], "approving an edit keeps it edited"
    client.put(url.format(three["id"]), json={"status": "rejected"})

    register = client.get("/api/audits/audit-1/claims").json()["claims"]
    assert [(c["id"], c["status"]) for c in register] == [(one["id"], "approved"), (two["id"], "edited")]
    assert register[1]["value"] == 900 and register[1]["parsed"]["value"] == two["value"], "original kept beside the edit"
    listed = client.get("/api/audits/audit-1/decks").json()["candidates"]
    assert next(c for c in listed if c["id"] == three["id"])["status"] == "rejected", "rejected stays on record"
    assert client.get("/api/audits/no-such-audit/claims").status_code == 404


def test_a_re_upload_keeps_approved_edited_and_rejected_claims(api):
    client, db = api
    content = (DECKS / "03-buffer.pptx").read_bytes()
    first = _upload(client, "audit-1", "03-buffer.pptx", content).json()
    one, two, three = (dict(c) for c in db[decks.CANDIDATES_COLLECTION].docs[:3])
    url = "/api/audits/audit-1/decks/candidates/{}"
    client.put(url.format(one["id"]), json={"status": "approved"})
    client.put(url.format(two["id"]), json={"value": 900})
    client.put(url.format(three["id"]), json={"status": "rejected"})

    again = _upload(client, "audit-1", "03-buffer.pptx", content).json()
    assert again["kept_reviewed"] == 3 and again["candidates"] == first["candidates"] - 3, "no duplicate of a reviewed claim"
    stored = {c["id"]: c for c in db[decks.CANDIDATES_COLLECTION].docs}
    assert (stored[one["id"]]["status"], stored[two["id"]]["status"], stored[three["id"]]["status"]) == \
        ("approved", "edited", "rejected")
    assert stored[two["id"]]["value"] == 900 and stored[two["id"]]["parsed"]["value"] == two["value"]
    assert len(db[decks.CANDIDATES_COLLECTION].docs) == first["candidates"]
    assert {c["deck_id"] for c in db[decks.CANDIDATES_COLLECTION].docs} == {again["deck_id"]}


@pytest.mark.parametrize("text, families", [
    ("800 Paying Users", ["customers"]),
    ("Avg. Customer Lifetime Value", ["sales"]),
    ("Implied Customer Life", ["retention"]),
])
def test_of_two_overlapping_keywords_the_longer_one_counts(text, families):
    assert [k["family"] for k in claims._keywords(text)] == families


# ---------------------------------------------------------------------------
# Several decks per audit: removal and order
# ---------------------------------------------------------------------------
def _page(c):
    return min(s.get("slide", s.get("page")) for s in c["sources"])


def test_decks_list_newest_first_and_within_a_deck_to_review_first_then_by_slide(api):
    client, db = api
    old = _upload(client, "audit-1", "03-buffer.pptx", (DECKS / "03-buffer.pptx").read_bytes()).json()
    new = _upload(client, "audit-1", "09-genesisai-2024.pdf", (DECKS / "09-genesisai-2024.pdf").read_bytes()).json()
    old_claims = [c for c in db[decks.CANDIDATES_COLLECTION].docs if c["deck_id"] == old["deck_id"]]
    late = max(old_claims, key=_page)
    client.put(f"/api/audits/audit-1/decks/candidates/{late['id']}", json={"status": "approved"})

    listed = client.get("/api/audits/audit-1/decks").json()
    assert [d["deck_id"] for d in listed["decks"]] == [new["deck_id"], old["deck_id"]], "most recent deck first"
    order = [c["deck_id"] for c in listed["candidates"]]
    assert order == sorted(order, key=lambda d: d != new["deck_id"]), "grouped by deck, most recent first"
    in_old = [c for c in listed["candidates"] if c["deck_id"] == old["deck_id"]]
    keys = [(c["status"] != "pending", _page(c)) for c in in_old]
    assert keys == sorted(keys), "to review first, then by slide"
    assert in_old[-1]["id"] == late["id"], "the reviewed claim moves below the ones to review"


def test_remove_deck_deletes_its_text_and_all_its_claims_including_reviewed(api):
    client, db = api
    keep = _upload(client, "audit-1", "09-genesisai-2024.pdf", (DECKS / "09-genesisai-2024.pdf").read_bytes()).json()
    gone = _upload(client, "audit-1", "03-buffer.pptx", (DECKS / "03-buffer.pptx").read_bytes()).json()
    other = _upload(client, "audit-2", "03-buffer.pptx", (DECKS / "03-buffer.pptx").read_bytes()).json()
    mine = [c for c in db[decks.CANDIDATES_COLLECTION].docs if c["deck_id"] == gone["deck_id"]]
    url = "/api/audits/audit-1/decks/candidates/{}"
    client.put(url.format(mine[0]["id"]), json={"status": "approved"})
    client.put(url.format(mine[1]["id"]), json={"value": 1})
    client.put(url.format(mine[2]["id"]), json={"status": "rejected"})

    r = client.delete(f"/api/audits/audit-1/decks/{gone['deck_id']}")
    assert r.status_code == 200 and r.json() == {"removed": gone["deck_id"], "deck_text": 1,
                                                 "deck_candidates": gone["candidates"]}
    assert {d["deck_id"] for d in db[decks.TEXT_COLLECTION].docs} == {keep["deck_id"], other["deck_id"]}
    assert {c["deck_id"] for c in db[decks.CANDIDATES_COLLECTION].docs} == {keep["deck_id"], other["deck_id"]}
    assert all(c["deck_id"] != gone["deck_id"] for c in client.get("/api/audits/audit-1/claims").json()["claims"])
    assert client.delete(f"/api/audits/audit-1/decks/{gone['deck_id']}").status_code == 404
    assert client.delete(f"/api/audits/audit-2/decks/{keep['deck_id']}").status_code == 404, "a deck of another audit"
