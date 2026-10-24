"""The checker (app/structures/checker.py; docs/design/ai-reads-rules-check.md, built 2026-10-22): Python flags on the claims the
model read from a page. A failed check flags the claim and never deletes or retypes it; a flagged claim is listed in the review tab.

The four checks (value on the page, unit or currency, scenario and period label, page within the document) and the rules of the
former parser read converted to post-checks (use-of-funds cues, acquisition-channel cues, turnover, the year label under a bar,
the pipeline column). Fixture: 06-uber.pdf page 20 with the model's recorded reply (tests/fixtures/page_replies/uber_p20.json):
exactly four company claims, all basis scenario, all matched, no flag but the informational "currency assumed" on the profit claim; a qualitative line is flagged
and listed under Review, never matched.
"""
import asyncio
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
from app.llm.schemas import PAGE_BASES, PAGE_CLAIMS, PAGE_SCENARIOS  # noqa: E402
from app.structures import checker, page_check  # noqa: E402
from app.structures import pages as pipeline  # noqa: E402

DECKS = BACKEND.parent / "tests" / "fixtures" / "decks" / "decks"
REPLIES = BACKEND / "tests" / "fixtures" / "page_replies"
TITLE = (50, 560, 20, "Traction")
LINES = [(50, 500, 12, "800 Paying Users"), (50, 480, 12, "$150,000 annual revenue run rate"), (50, 460, 12, "97% margins")]


def deck(texts, rects=()):
    return parse_deck(pdf_page(texts, rects), "deck.pdf")


def grid_of(parsed):
    grids = pages.page_grids(parsed["blocks"])
    assert len(grids) == 1
    return grids[0]


def claim(value_cell, value, metric="revenue", unit="USD", period=None, period_cell=None, label_cell=None, value_high=None,
          basis="actual", scenario="none"):
    return {"metric": metric, "value": value, "value_high": value_high, "unit": unit, "unit_other": None, "period": period,
            "basis": basis, "scenario": scenario, "value_cell": value_cell, "label_cell": label_cell, "period_cell": period_cell}


def one(parsed, claim_, fiscal_year_end=12):
    """The checked item of one claim, cited by page cell id ("p1r2c1") as the model writes it."""
    grid = grid_of(parsed)
    by_page = page_check.by_page([claim_])
    out = checker.check(grid, by_page.get(pages.page_number(grid), []), fiscal_year_end, checker.page_blocks(parsed["blocks"], grid), "deck.pdf")
    assert len(out["items"]) == 1, "a claim on a cell of the page is never deleted"
    return out["items"][0]


def cell_of(parsed, text):
    grid = grid_of(parsed)
    return next(page_check._id(c) for c in grid["cells"] if c["text"] == text)


# ---------------------------------------------------------------------------
# The fixture: 06-uber.pdf page 20
# ---------------------------------------------------------------------------
def uber_page_20():
    parsed = parse_deck((DECKS / "06-uber.pdf").read_bytes(), "06-uber.pdf")
    grid = next(g for g in pages.page_grids(parsed["blocks"]) if pages.page_number(g) == 20)
    reply = json.loads((REPLIES / "uber_p20.json").read_text(encoding="utf-8"))
    return parsed, grid, reply


def test_uber_page_20_gives_exactly_four_scenario_claims_with_one_currency_flag():
    parsed, grid, reply = uber_page_20()
    assert grid in pages.sendable(pages.page_grids(parsed["blocks"])), "the page carries figures as digits"
    out = checker.check(grid, page_check.by_page(reply["claims"])[20], 12, checker.page_blocks(parsed["blocks"], grid), "06-uber.pdf")
    rows = [(i["metric"], i["value"], i["value_high"], i["unit"], i["basis"], i["scenario"], i["status"], i["flags"]) for i in out["items"]]
    assert rows == [
        ("revenue", 1_000_000_000, None, "USD", "scenario", "best", "matched", []),
        ("market_share", 5, None, "%", "scenario", "realistic", "matched", []),
        # Matched since 2026-10-23 (George): "Matched to page" means the figure is in the cited cell, and "20-30M+" is in it. The unit
        # ("USD" is not next to it) no longer gates the match; it stays the informational flag "currency assumed", so the claim is not in Review.
        ("net_profit", 20_000_000, 30_000_000, "USD", "scenario", "realistic", "matched", [checker.CURRENCY_ASSUMED]),
        ("customers", 100, None, "count", "scenario", "worst", "matched", []),
    ]
    assert all(i["basis"] == "scenario" for i in out["items"])
    assert {k: v for k, v in out.items() if k != "items"} == {"matched": 4, "unmatched": 0, "dropped": 0, "periods_corrected": 0, "flagged": 0}
    assert [i["value_cell"] for i in out["items"]] == ["r2c5", "r2c6", "r3c6", "r2c7"]


def test_uber_page_20_qualitative_lines_are_flagged_and_never_matched():
    """A claim the model might read into "Time-saver for San-Francisco based executives" (no figure) is flagged "value not on page" and
    listed under Review, never matched and never in the main list: with a value the page does not hold, or with no value and no period."""
    parsed, grid, reply = uber_page_20()
    qualitative = next(c for c in grid["cells"] if c["text"].startswith("Time-saver"))
    cell = f"p20{page_check._id(qualitative)}"
    invented = [claim(cell, 7_654, metric="product", unit="count", basis="scenario", scenario="worst"),
                {**claim(cell, None, metric="product", unit=None, basis="scenario", scenario="worst"), "value": None}]
    out = checker.check(grid, page_check.by_page(reply["claims"] + invented)[20], 12, checker.page_blocks(parsed["blocks"], grid), "06-uber.pdf")
    assert len(out["items"]) == 6, "flagged, not deleted"
    for item in out["items"][4:]:
        assert item["status"] == "unmatched" and checker.VALUE_NOT_ON_PAGE in item["flags"]
    assert [i["flags"] for i in out["items"][:4]] == [[], [], [checker.CURRENCY_ASSUMED], []], "the four claims are unchanged"
    assert out["flagged"] == 2, "the profit claim's currency flag is informational since 2026-10-23: only the two invented claims are flagged"


# ---------------------------------------------------------------------------
# The four checks
# ---------------------------------------------------------------------------
def test_a_value_the_page_does_not_hold_is_flagged_and_a_value_in_another_cell_is_only_unmatched():
    parsed = deck([TITLE, *LINES])
    missing = one(parsed, claim("p1r3c1", 999_000))
    assert missing["status"] == "unmatched" and missing["flags"] == [checker.VALUE_NOT_ON_PAGE]
    assert missing["value"] == 999_000, "the row shows the model's value (decision 2a), flagged"
    elsewhere = one(parsed, claim("p1r4c1", 150_000))             # the value stands in r3c1, not in the cited cell: corrected (tolerance)
    assert elsewhere["status"] == "matched" and elsewhere["flags"] == ["cell corrected"] and elsewhere["value_cell"] == "r3c1"
    matched = one(parsed, claim("p1r3c1", 150_000))
    assert matched["status"] == "matched" and matched["flags"] == []


def test_a_currency_the_cell_and_its_neighbours_do_not_show_is_currency_assumed():
    parsed = deck([TITLE, (50, 500, 12, "Generates 20-30M+ per year profit"), (50, 300, 12, "$1B+ in yearly revenue")])
    assumed = one(parsed, claim("p1r2c1", 20_000_000, metric="net_profit", value_high=30_000_000))
    assert assumed["flags"] == [checker.CURRENCY_ASSUMED] and assumed["status"] == "matched" and not checker.flagged(assumed)
    assert assumed["value"] == 20_000_000 and assumed["value_high"] == 30_000_000, "flagged, not retyped"
    stated = one(parsed, claim("p1r3c1", 1_000_000_000))
    assert stated["flags"] == [] and stated["status"] == "matched"
    percent = one(parsed, claim("p1r2c1", 20_000_000, metric="gross_margin", unit="%", value_high=30_000_000))
    assert percent["flags"] == [checker.UNIT_ASSUMED] and percent["status"] == "matched" and not checker.flagged(percent)


def test_a_scenario_or_period_the_model_set_must_be_on_the_page():
    plain = deck([TITLE, *LINES])
    scenario = one(plain, claim("p1r3c1", 150_000, basis="scenario", scenario="best"))
    assert scenario["flags"] == [checker.SCENARIO_NOT_ON_PAGE] and scenario["status"] == "matched"
    cases = deck([(50, 560, 20, "Potential Outcomes"), (50, 500, 12, "Best-Case Scenario"), (200, 500, 12, "$1B+ in yearly revenue"),
                  (50, 460, 12, "Downside"), (200, 460, 12, "$20M in yearly revenue")])
    for text, name in (("$1B+ in yearly revenue", "best"), ("$20M in yearly revenue", "worst")):
        found = one(cases, claim(f"p1{cell_of(cases, text)}", 1e9 if name == "best" else 20e6, basis="scenario", scenario=name))
        assert found["flags"] == [], (text, name)
    assert one(cases, claim(f"p1{cell_of(cases, '$20M in yearly revenue')}", 20e6, basis="scenario", scenario="realistic"))["flags"] \
        == [checker.SCENARIO_NOT_ON_PAGE]
    assert one(plain, claim("p1r3c1", 150_000, basis="projection", scenario="none"))["flags"] == [], "no scenario, nothing to find"
    # A period cited from a sentence on the page is informational (George, 2026-10-23: heading band or another cell); a period nowhere on the page is flagged.
    dated = deck([TITLE, (50, 520, 12, "We finished 2024 with a strong pipeline."), (50, 480, 12, "$150,000 annual revenue run rate")])
    sentence = one(dated, claim("p1r3c1", 150_000, period="2024", period_cell="p1r2c1"))
    assert sentence["status"] == "matched" and sentence["flags"] == [checker.PERIOD_FROM_HEADING] and not checker.flagged(sentence)
    nowhere = one(dated, claim("p1r3c1", 150_000, period="2027"))
    assert nowhere["status"] == "matched" and nowhere["flags"] == [checker.PERIOD_NOT_ON_PAGE] and checker.flagged(nowhere)


def test_a_page_outside_the_document_is_flagged_and_its_row_carries_the_models_values_without_a_cell():
    assert checker.out_of_range(26, 25) == checker.PAGE_OUT_OF_RANGE and checker.out_of_range(0, 25) == checker.PAGE_OUT_OF_RANGE
    assert checker.out_of_range(25, 25) is None and checker.out_of_range(3, None) is None
    row = pipeline.row_out_of_range(claim("p26r1c1", 5_000_000, period="2026", basis="projection"), 26, {"file": "deck.pdf", "page_unit": "page"})
    assert row["flags"] == [checker.PAGE_OUT_OF_RANGE] and row["ai_status"] == "unmatched" and row["cell"] is None
    assert row["sources"] == [{"file": "deck.pdf", "page": 26, "kind": "page", "cell": None}]
    assert (row["value"], row["currency"], row["target_date"], row["figure_type"], row["basis"]) == (5_000_000, "USD", "2026", None, "projection")


# ---------------------------------------------------------------------------
# The rules of the parser read, as post-checks
# ---------------------------------------------------------------------------
def test_a_percentage_on_a_use_of_funds_slide_is_flagged_not_retyped():
    funds = deck([(50, 560, 20, "Capital raise"), (50, 500, 12, "Marketing (25%)"), (50, 480, 12, "Product (75%)")])
    found = one(funds, claim("p1r2c1", 25, metric="growth", unit="%"))
    assert found["flags"] == [checker.USE_OF_FUNDS] and found["metric"] == "growth"
    raise_page = deck([(50, 560, 20, "Use of Funds"), (50, 500, 12, "Marketing (25%)"), (50, 480, 12, "Product (75%)")])
    assert one(raise_page, claim("p1r2c1", 25, metric="growth", unit="%"))["flags"] == [], "a raise cue on the page: no flag (2026-10-23)"
    plain = deck([(50, 560, 20, "Revenue by geography"), (50, 500, 12, "Europe (25%)"), (50, 480, 12, "Americas (75%)")])
    assert one(plain, claim("p1r2c1", 25, metric="revenue", unit="%"))["flags"] == []


def test_a_platform_count_on_a_user_acquisition_slide_is_flagged():
    funnel = deck([(50, 560, 20, "User acquisition funnel"), (50, 500, 12, "Telegram(30K)"), (50, 480, 12, "Facebook (12,500)")])
    found = one(funnel, claim("p1r2c1", 30_000, metric="users", unit="count"))
    assert found["flags"] == [checker.ACQUISITION_CHANNEL] and found["metric"] == "users"
    no_cue = deck([(50, 560, 20, "Community"), (50, 500, 12, "Telegram(30K)"), (50, 480, 12, "Facebook (12,500)")])
    assert one(no_cue, claim("p1r2c1", 30_000, metric="users", unit="count"))["flags"] == []


def test_a_revenue_claim_on_a_turnover_line_is_flagged_for_the_revenue_or_volume_answer():
    turnover = deck([TITLE, (50, 500, 12, "Turnover €190,000 in FY2023"), (50, 480, 12, "GMV"), (50, 460, 12, "€900,000")])
    own = one(turnover, claim("p1r2c1", 190_000, unit="EUR", period="2023", period_cell="p1r2c1"))
    assert own["flags"] == [checker.TURNOVER] and own["metric"] == "revenue" and own["status"] == "matched"
    labelled = one(turnover, claim("p1r4c1", 900_000, unit="EUR", label_cell="p1r3c1"))
    assert labelled["flags"] == [checker.TURNOVER]
    assert one(turnover, claim("p1r4c1", 900_000, metric="sales", unit="EUR", label_cell="p1r3c1"))["flags"] == [], "revenue only"


def bars():
    texts = [(50, 560, 20, "Revenue forecast")] + [(x, 380 + 20 * i, 12, bar) for i, (bar, x) in
                                                   enumerate(zip(("€1.48MM", "€3.39MM", "€5.3MM"), (100, 255, 410)))]
    texts += [(x, 340, 12, year) for year, x in zip(("2022", "2023", "2024"), (150, 300, 450))]
    return deck(texts)


def test_a_period_other_than_the_year_under_the_bar_is_flagged():
    parsed = bars()
    first = cell_of(parsed, "€1.48MM")
    assert grid_of(parsed)["cells"][[page_check._id(c) for c in grid_of(parsed)["cells"]].index(first)]["bar_year"] == "2022"
    wrong = one(parsed, claim(f"p1{first}", 1_480_000, unit="EUR", period="2023"))
    assert wrong["flags"] == [checker.BAR_YEAR] and wrong["status"] == "matched"
    right = one(parsed, claim(f"p1{first}", 1_480_000, unit="EUR", period="2022"))
    assert right["flags"] == [] and right["status"] == "matched" and right["period"] == "2022"


def test_a_claim_with_no_period_over_a_year_label_is_flagged_with_the_year_and_the_period_stays_empty():
    """George, 2026-10-23: flag only ("year label below: 2022"), so the analyst can set the period with Edit; Python never sets it."""
    parsed = bars()
    first, third = cell_of(parsed, "€1.48MM"), cell_of(parsed, "€5.3MM")
    got = one(parsed, claim(f"p1{first}", 1_480_000, unit="EUR"))
    assert got["flags"] == ["year label below: 2022"] and got["period"] is None and got["status"] == "matched"
    assert one(parsed, claim(f"p1{third}", 5_300_000, unit="EUR"))["flags"] == ["year label below: 2024"]
    assert checker.year_label_flag("2022") == "year label below: 2022"
    assert one(parsed, claim(f"p1{first}", 1_480_000, unit="EUR", period="2022"))["flags"] == [], "a claim with a period needs no hint"
    plain = deck([TITLE, (50, 500, 12, "$150,000 annual revenue run rate")])
    assert one(plain, claim("p1r2c1", 150_000))["flags"] == [], "no year label below, no flag"


def test_a_figure_under_a_pipeline_column_claimed_as_another_metric_is_flagged():
    texts, rects = ruled_table([["Account", "Weighted pipeline", "ARR"], ["Acme", "€50,000", "€12,000"]], col_widths=(200, 200, 200))
    parsed = deck([(50, 560, 20, "Accounts"), *texts], rects)
    pipe = cell_of(parsed, "€50,000")
    flagged = one(parsed, claim(f"p1{pipe}", 50_000, unit="EUR"))
    assert flagged["flags"] == [checker.PIPELINE_COLUMN] and flagged["metric"] == "revenue"
    assert one(parsed, claim(f"p1{pipe}", 50_000, metric="pipeline", unit="EUR"))["flags"] == []
    assert one(parsed, claim(f"p1{cell_of(parsed, '€12,000')}", 12_000, unit="EUR"))["flags"] == [], "the ARR column is not a pipeline"


def test_an_axis_tick_and_a_funds_raised_line_are_flagged_not_dropped():
    parsed = deck([TITLE, (50, 500, 12, "Raised $2M seed round"), (50, 480, 12, "$150,000 annual revenue run rate")])
    found = one(parsed, claim("p1r2c1", 2_000_000))
    assert found["flags"] == [checker.NOT_PLAN_LINE]
    ticks = deck([(50, 560, 20, "Revenue"), (50, 430, 10, "0"), (50, 410, 10, "500"), (50, 390, 10, "1,000"), (50, 370, 10, "1,500"),
                  (50, 350, 10, "2,000"), (300, 400, 12, "€1,200")])
    grid = grid_of(ticks)
    tick = next(c for c in grid["cells"] if c.get("tick"))
    on_tick = page_check.by_page([claim(f"p1{page_check._id(tick)}", float(tick["text"].replace(",", "")), unit=None)])[1]
    out = checker.check(grid, on_tick, 12)
    assert len(out["items"]) == 1 and checker.AXIS_TICK in out["items"][0]["flags"] and out["dropped"] == 0
    # page_check alone, as the compare script runs it, still drops them.
    assert page_check.check(grid, on_tick, 12)["dropped"] == 1


def test_every_flag_is_a_closed_string_and_a_cell_the_page_does_not_have_is_still_dropped():
    assert len(set(checker.FLAGS)) == len(checker.FLAGS) == 22 and all(f == f.strip() and f.lower() == f for f in checker.FLAGS)
    assert set(PAGE_BASES) == {"actual", "projection", "scenario"} and set(PAGE_SCENARIOS) == {"best", "realistic", "worst", "none"}
    parsed = deck([TITLE, *LINES])
    out = checker.check(grid_of(parsed), page_check.by_page([claim("p1r9c9", 1)])[1], 12)
    assert out["items"] == [] and out["dropped"] == 1 and out["flagged"] == 0


# ---------------------------------------------------------------------------
# The pipeline: rows carry basis, scenario, figure type and flags
# ---------------------------------------------------------------------------
def _page_db(parsed):
    db = _db()
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "mapping": REVENUE_MAPPING, "mapped_at": "2026-10-05T00:00:00"})
    db[TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "file": "deck.pdf", "page_unit": "page", "pages": 1,
                                     "blocks": parsed["blocks"], "structures": parsed["structures"]})
    return db


def test_under_the_default_switch_each_row_carries_its_basis_scenario_figure_type_and_flags(monkeypatch, caplog):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    parsed = deck([TITLE, *LINES, (50, 440, 12, "Generates 20-30M+ per year profit")])
    db = _page_db(parsed)
    reply = {"type": PAGE_CLAIMS, "claims": [
        claim("p1r2c1", 800, metric="customers", unit="count", label_cell="p1r1c1"),
        claim("p1r3c1", 150_000, basis="projection"),
        claim("p1r5c1", 20_000_000, metric="net_profit", value_high=30_000_000, basis="scenario", scenario="best"),
    ]}
    adapter = t.FakeAdapter(replies=[json.dumps(reply)])
    import logging
    with caplog.at_level(logging.INFO):
        status = asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert status == "read" and adapter.calls == 1
    rows = sorted(db[CANDIDATES_COLLECTION].docs, key=lambda r: r["order"])
    assert [(r["claim_type"], r["basis"], r["scenario"], r["figure_type"], r["flags"]) for r in rows] == [
        ("customers", "actual", "none", None, []),
        ("revenue", "projection", "none", None, []),
        ("net_profit", "scenario", "best", None, [checker.CURRENCY_ASSUMED, checker.SCENARIO_NOT_ON_PAGE]),
    ]
    assert rows[2]["ai_label"] == "Matched to page" and rows[2]["value_high"] == 30_000_000
    assert all(r["figure_type_set_by"] is None for r in rows), "the model's basis sets no figure type (George, 2026-10-23, M2)"
    deck_doc, = db[TEXT_COLLECTION].docs
    assert {k: deck_doc["page_reads"][0][k] for k in ("matched", "unmatched", "flagged")} == {"matched": 3, "unmatched": 0, "flagged": 1}
    assert "pages checked: run_id=audit-s deck_id=d1 pages=1 matched=3 unmatched=0 dropped=0 flagged=1" in caplog.text
    stored, = db[gateway.STRUCTURES_COLLECTION].docs
    assert stored["items"]["claims"][2]["flags"] == [checker.CURRENCY_ASSUMED, checker.SCENARIO_NOT_ON_PAGE]
    assert stored["output"]["claims"][2]["basis"] == "scenario" and stored["output"]["claims"][2]["scenario"] == "best"
    assert "snippet" not in json.dumps(stored["items"]) and "Paying Users" not in json.dumps(stored), "no text stored (rule 17)"


def test_an_upload_lists_no_rule_candidates_under_the_default_switch(monkeypatch):
    """The rules read no longer lists candidates at upload: the model reads the pages after the response (process_deck). It stays
    for Add from deck and, under DECK_PIPELINE=rules, for scripts/compare_pipelines.py (tests/test_deck_parser.py)."""
    pytest.importorskip("fastapi")
    import os
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "deck_parser_test")
    from fastapi.testclient import TestClient
    import server
    db = t.FakeDB()
    db["audits"].docs.append({"id": "audit-1", "company_name": "Testco", "results": None, "structure_reading_consent": False})
    monkeypatch.setattr(server, "db", db)
    client = TestClient(server.app, raise_server_exceptions=False)
    content = (DECKS / "03-buffer.pptx").read_bytes()
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    r = client.post("/api/audits/audit-1/decks/upload", files={"file": ("03-buffer.pptx", content)})
    assert r.status_code == 200 and r.json()["pages"] == 13 and r.json()["candidates"] == 0, r.text
    assert db[CANDIDATES_COLLECTION].docs == []
    stored, = db[TEXT_COLLECTION].docs
    assert stored["blocks"] and stored["ai_status"] == "python_only", "consent off: no page call, and no rules row either"
    monkeypatch.setenv("DECK_PIPELINE", "rules")
    r = client.post("/api/audits/audit-1/decks/upload", files={"file": ("03-buffer.pptx", content)})
    assert r.status_code == 200 and r.json()["candidates"] > 0, "the former path still lists the rules read"
