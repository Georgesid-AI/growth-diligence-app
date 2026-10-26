"""The claims list changes of the live run (George, 2026-10-26): what the app made of a row, legend labels on charts, and the Sales question.

Fixture decks only (CLAUDE.md rule 15): synthetic grids, synthetic names and figures. The title of a test names the new behaviour.
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")
pytest.importorskip("pptx")

import test_source_association as sa  # noqa: E402
from claim_matching_support import engine_results  # noqa: E402
from test_claims_enter_on_their_own import AUDIT, claim as run_claim, stored  # noqa: E402
from test_segment_partitions import FYE, PRODUCTS, TOTAL, cand, register  # noqa: E402

from app import claim_groups as cg  # noqa: E402
from app import claim_matching as cm  # noqa: E402
from app.structures import checker  # noqa: E402
from app.structures import pages as pipeline  # noqa: E402


# ---------------------------------------------------------------------------
# 3. What the app made of a row
# ---------------------------------------------------------------------------
def test_a_row_says_its_segment_and_the_total_it_is_a_part_of():
    rows = register([TOTAL, *PRODUCTS])
    made = {r["claim_id"]: cg.made_of(r, rows) for r in rows}
    assert made["c2"] == {"segment": "Product A", "part_of": "part of Revenue FY2024 total"}
    assert made["c3"] == {"segment": "Product B", "part_of": "part of Revenue FY2024 total"}
    assert made["c1"] == {"segment": None, "part_of": None}, "the total is not a part of anything and sets no segment"


def test_a_lone_figure_with_a_segment_names_the_segment_and_no_total():
    row, = register([cand("c2", 600_000, "FY2024", "Product A")])
    assert cg.made_of(row, [row]) == {"segment": "Product A", "part_of": None}


# ---------------------------------------------------------------------------
# 4. Legend labels on charts
# ---------------------------------------------------------------------------
def chart_page():
    """Two bars of one colour with values over them, a page title, a chart title above them, axis ticks, two legend lines to the right and a footnote."""
    cells = [sa.cell(1, "Revenue by product", (0.05, 0.05, 0.50, 0.10), 1, title=True),
             sa.cell(2, "Growth by year", (0.32, 0.20, 0.46, 0.24), 2),
             sa.cell(3, "42", (0.31, 0.25, 0.37, 0.29), 3),
             sa.cell(4, "17", (0.41, 0.45, 0.47, 0.49), 4),
             sa.cell(5, "2024", (0.31, 0.82, 0.37, 0.85), 5, tick=True),
             sa.cell(6, "2025", (0.41, 0.82, 0.47, 0.85), 6, tick=True),
             sa.cell(7, "Platform Subscriptions", (0.55, 0.35, 0.75, 0.38), 7),
             sa.cell(8, "Services", (0.55, 0.40, 0.70, 0.43), 8),
             sa.cell(9, "Source: management accounts", (0.05, 0.95, 0.40, 0.98), 9)]
    rects = [sa.rect((0.30, 0.30, 0.38, 0.80), sa.BLUE), sa.rect((0.40, 0.50, 0.48, 0.80), sa.BLUE)]
    return cells, rects


def test_legend_items_are_the_short_lines_that_are_no_heading_no_chart_title_and_no_tick():
    cells, rects = chart_page()
    item = sa.check(sa.grid(cells, rects), sa.claim("r3c1", 42, unit="EUR", label_cell="r9c1"))
    assert checker.LABEL_MISMATCH in item["flags"]
    plan, = item["corrections"]
    assert (plan["flag"], plan["field"]) == (checker.LABEL_MISMATCH, "segment")
    assert [o["value"] for o in plan["options"]] == ["Platform Subscriptions", "Services"]
    assert all(o["segment"] == o["value"] for o in plan["options"])


def test_a_page_with_no_chart_offers_no_legend_items():
    cells, _ = chart_page()
    item = sa.check(sa.grid(cells, []), sa.claim("r3c1", 42, unit="EUR", label_cell="r9c1"))
    assert checker.LABEL_MISMATCH in item["flags"] and item["corrections"] == []


def test_a_legend_item_is_never_applied_on_its_own_even_when_it_is_the_only_one():
    cells, rects = chart_page()
    del cells[7]                                   # "Services" goes: one legend item left
    item = sa.check(sa.grid(cells, rects), sa.claim("r3c1", 42, unit="EUR", label_cell="r9c1"))
    grid = sa.grid(cells, rects)
    row, _ = pipeline.corrected_row(item, grid, {"file": "deck.pdf", "blocks": []}, FYE, 1)
    entry, = row["corrections"]
    assert entry["state"] == "choose" and entry["field"] == "segment" and [o["segment"] for o in entry["options"]] == ["Platform Subscriptions"]
    assert checker.LABEL_MISMATCH in row["flags"] and row["label_from"] is None


def test_the_legend_items_of_a_stored_item_keep_cell_ids_and_no_text():
    cells, rects = chart_page()
    item = sa.check(sa.grid(cells, rects), sa.claim("r3c1", 42, unit="EUR", label_cell="r9c1"))
    kept = pipeline.stored_items([item])["claims"][0]["corrections"]
    assert kept[0]["options"] == ["r7c1", "r8c1"] and "Platform" not in str(kept)


def test_figures_that_add_up_to_a_stated_total_are_named_with_it():
    flagged = register([cand("c2", 600_000, "FY2024"), cand("c3", 400_000, "FY2024")])
    total, = register([TOTAL])
    assert cg.adds_up_to(flagged, [total, *flagged]) == "Revenue FY2024"
    off = register([cand("c2", 600_000, "FY2024"), cand("c3", 300_000, "FY2024")])
    assert cg.adds_up_to(off, [total, *off]) is None
    assert cg.adds_up_to(register([cand("c2", 990_000, "FY2024")]), [total]) == "Revenue FY2024", "within 2%"


def test_once_every_figure_has_a_segment_they_are_a_partition_of_the_total():
    parts = [cand("c2", 600_000, "FY2024", claim_inputs={"c2": {"segment": "Platform Subscriptions"}}, slide=4),
             cand("c3", 400_000, "FY2024", claim_inputs={"c3": {"segment": "Services"}}, slide=4)]
    rows = register([TOTAL, *parts])
    by = {r["claim_id"]: r for r in rows}
    assert by["c2"]["group_role"] == by["c3"]["group_role"] == "segment_part" and by["c1"]["group_role"] == "total"
    assert cg.made_of(by["c2"], rows)["segment"] == "Platform Subscriptions"
    half = register([TOTAL, parts[0], cand("c3", 400_000, "FY2024", slide=4)])
    assert {r["group_role"] for r in half if r["claim_id"] == "c2"} != {"segment_part"}, "a figure with no segment makes no partition"


# ---------------------------------------------------------------------------
# 5. The Sales question
# ---------------------------------------------------------------------------
def sales(cid, label="Sales", period="FY2022", **over):
    return cand(cid, 1_200_000, period, label, snippet="EUR 1,200,000", **{"deck_id": "d1", **over})


def row_of(c, choices=None):
    base = {"fiscal_year_end": FYE, "as_of_month": None, "reporting_currency": "EUR", "fx": {"EUR": 1.0}, "sales_choices": choices or {}}
    return cm.build_register([c], engine_results(), base)[0]


@pytest.mark.parametrize("label", ["Sales", "Sales by product", "Sales by quarter", "Total Sales", "SALES"])
def test_a_money_claim_labelled_sales_with_a_past_period_asks_once_per_deck(label):
    c = sales("c1", label)
    assert cm.is_sales_claim(c, engine_results()) is True
    row = row_of(c)
    assert row["evidence_label"] == "Unverified" and row["reason"] == cm.SALES_ASK_REASON
    assert cm.sales_questions([c, sales("c2", label)], engine_results(), {}) == [{"deck_id": "d1", "file": "testco_board.pptx", "claims": 2}]


@pytest.mark.parametrize("label, extra", [("Sales & Marketing", {}), ("Sales cycle", {}), ("Revenue", {}), ("Sales", {"period": "FY2031"}),
                                          ("Sales", {"currency": None, "unit": "%"})])
def test_other_claims_are_no_sales_question(label, extra):
    c = sales("c1", label, **{k: v for k, v in extra.items() if k == "period"})
    c.update({k: v for k, v in extra.items() if k != "period"})
    assert cm.is_sales_claim(c, engine_results()) is False
    assert cm.sales_questions([c], engine_results(), {}) == []


def test_revenue_tests_every_sales_claim_of_the_deck_as_revenue():
    row = row_of(sales("c1"), {"d1": {"as": "revenue"}})
    assert row["metric"] == "Revenue" and row["reason"] != cm.SALES_ASK_REASON and row["reason"] != "no metric"
    assert cm.sales_questions([sales("c1")], engine_results(), {"sales_choices": {"d1": {"as": "revenue"}}}) == []


def test_bookings_keep_every_sales_claim_of_the_deck_unverified_with_the_reason():
    row = row_of(sales("c1"), {"d1": {"as": "bookings"}})
    assert (row["evidence_label"], row["reason"]) == ("Unverified", "bookings not in the data")


def test_the_answer_of_one_deck_does_not_reach_another():
    other = sales("c2", deck_id="d2")
    assert row_of(other, {"d1": {"as": "revenue"}})["reason"] == cm.SALES_ASK_REASON


# ---------------------------------------------------------------------------
# The server: the claims list payload, the legend click, the Sales answer
# ---------------------------------------------------------------------------
def _client(run_api, *candidates):
    from test_claims_enter_on_their_own import prepared
    prepared(run_api, *candidates)
    return run_api


def _decks(client):
    return client.get(f"/api/audits/{AUDIT}/decks").json()


LEGEND = {"field": "segment", "reason": "label mismatch", "original": None, "state": "choose", "undo": {},
          "options": [{"value": "Platform Subscriptions", "segment": "Platform Subscriptions", "set": {}},
                      {"value": "Services", "segment": "Services", "set": {}}]}


def test_a_legend_click_sets_the_segment_enters_the_row_and_undo_brings_the_card_back(run_api):
    client = _client(run_api, run_claim("c1", status="pending", flags=["label mismatch"], corrections=[dict(LEGEND)]))
    url = f"/api/audits/{AUDIT}/decks/candidates/c1/correction"
    assert client.post(url, json={"index": 0, "action": "choose", "option": 1}).status_code == 200
    got = stored(client)["c1"]
    assert (got["status"], got["flags"], got["claim_inputs"]["c1"]["segment"], got["corrections"][0]["state"]) == ("approved", [], "Services", "applied")
    row = {r["claim_id"]: r for r in client.get(f"/api/audits/{AUDIT}/claims").json()["register"]}["c1"]
    assert (row["segment"], row["segment_set_by"]) == ("Services", "analyst")
    assert _decks(client)["candidates"][0]["made_of"]["segment"] == "Services"
    assert client.post(url, json={"index": 0, "action": "undo"}).status_code == 200
    back = stored(client)["c1"]
    assert (back["status"], back["flags"], "segment" in (back.get("claim_inputs") or {}).get("c1", {}), back["corrections"][0]["state"]) \
        == ("pending", ["label mismatch"], False, "choose")


def test_the_card_names_the_total_the_flagged_figures_add_up_to(run_api):
    def legend(cid, value):
        return run_claim(cid, status="pending", flags=["label mismatch"], corrections=[dict(LEGEND)], value=value, snippet=f"Revenue EUR {value}",
                         target_date="2022", period_text="2022")
    total = run_claim("c3", status="approved", value=1_000_000, snippet="Revenue EUR 1,000,000", target_date="2022", period_text="2022",
                      sources=[{"file": "deck.pptx", "page": 1}])
    page2 = [{"file": "deck.pptx", "page": 2}]
    client = _client(run_api, legend("c1", 600_000), legend("c2", 400_000), total)
    for c in client.db[__import__("app.decks", fromlist=["x"]).CANDIDATES_COLLECTION].docs:
        if c["id"] in ("c1", "c2"):
            c["sources"] = page2
    attention = {a["id"]: a for a in _decks(client)["attention"]}
    assert attention["c1"].get("adds_up_to") == attention["c2"].get("adds_up_to") == "Revenue 2022"


def test_a_sales_claim_asks_once_per_deck_and_the_answer_decides_how_it_is_tested(run_api):
    sales_claim = run_claim("c1", status="approved", label_from="Sales", snippet="EUR 200,000", target_date="2023", period_text="2023",
                            deck_id="d1")
    client = _client(run_api, sales_claim)
    assert _decks(client)["sales_questions"] == [{"deck_id": "d1", "file": "deck.pptx", "claims": 1}]
    assert client.put(f"/api/audits/{AUDIT}/decks/nope/sales", json={"as": "revenue"}).status_code == 404
    assert client.put(f"/api/audits/{AUDIT}/decks/d1/sales", json={"as": "profit"}).status_code == 422
    done = client.put(f"/api/audits/{AUDIT}/decks/d1/sales", json={"as": "bookings"})
    assert done.status_code == 200 and done.json()["sales_questions"] == []
    row = {r["claim_id"]: r for r in client.get(f"/api/audits/{AUDIT}/claims").json()["register"]}["c1"]
    assert (row["evidence_label"], row["reason"]) == ("Unverified", "bookings not in the data")
    assert client.put(f"/api/audits/{AUDIT}/decks/d1/sales", json={"as": "revenue"}).status_code == 200
    row = {r["claim_id"]: r for r in client.get(f"/api/audits/{AUDIT}/claims").json()["register"]}["c1"]
    assert row["metric"] == "Revenue"


# ---------------------------------------------------------------------------
# Decision 2: the metric of a revenue-typed figure from the title above it
# ---------------------------------------------------------------------------
def pie_page(title="Revenue by Channel", gaps=("graphic",)):
    """A pie: a title, two slice labels (the figures), two legend lines and a footnote. No rectangle: the slices are a graphic the reader does not draw."""
    cells = [sa.cell(1, title, (0.05, 0.05, 0.60, 0.10), 1, title=True),
             sa.cell(2, "600,000", (0.20, 0.40, 0.30, 0.44), 2),
             sa.cell(3, "400,000", (0.35, 0.55, 0.45, 0.59), 3),
             sa.cell(4, "Online", (0.60, 0.40, 0.75, 0.43), 4),
             sa.cell(5, "Retail", (0.60, 0.46, 0.75, 0.49), 5),
             sa.cell(6, "Source: management accounts", (0.05, 0.95, 0.40, 0.98), 6)]
    return sa.grid(cells, [], gaps=list(gaps))


def test_a_pie_with_a_graphic_the_reader_cannot_draw_still_offers_its_legend_items():
    item = sa.check(pie_page(), sa.claim("r2c1", 600_000, unit="EUR", label_cell="r6c1"))
    plan, = item["corrections"]
    assert plan["field"] == "segment" and [o["value"] for o in plan["options"]] == ["Online", "Retail"]
    plain = sa.check(pie_page(gaps=()), sa.claim("r2c1", 600_000, unit="EUR", label_cell="r6c1"))
    assert plain["corrections"] == [], "nothing says a chart is there"


@pytest.mark.parametrize("title, word", [("Revenue by Channel", "revenue"), ("ARR by Channel", "ARR"), ("MRR split", "MRR"), ("Sales by Channel", "sales"),
                                         ("Revenue and ARR by Channel", None), ("Growth by Channel", None), ("Sales and Revenue", None)])
def test_the_title_names_the_metric_only_when_it_names_exactly_one(title, word):
    grid = pie_page(title)
    item = sa.check(grid, sa.claim("r2c1", 600_000, unit="EUR", label_cell="r6c1"))
    row = pipeline.corrected_row(item, grid, {"file": "deck.pdf", "blocks": []}, FYE, 1)[0]
    assert row.get("heading_metric") == word


def test_a_chart_title_over_the_bars_outranks_the_page_title():
    cells, rects = chart_page()
    cells[1]["text"] = "ARR by year"                       # the chart's own title, over the bars; the page title says Revenue by product
    grid = sa.grid(cells, rects)
    item = sa.check(grid, sa.claim("r3c1", 42, unit="EUR", label_cell="r9c1"))
    assert pipeline.corrected_row(item, grid, {"file": "deck.pdf", "blocks": []}, FYE, 1)[0]["heading_metric"] == "ARR"


def part(cid, value, segment, heading="revenue", **over):
    c = cand(cid, value, "FY2024", **{"snippet": f"EUR {value:,}", "claim_inputs": {cid: {"segment": segment}}, "slide": 4, **over})
    return {**c, "heading_metric": heading} if heading else c


def test_legend_labelled_parts_of_a_chart_titled_revenue_join_the_partition_of_the_revenue_total():
    rows = register([TOTAL, part("c2", 600_000, "Online"), part("c3", 400_000, "Retail")])
    by = {r["claim_id"]: r for r in rows}
    assert (by["c2"]["metric"], by["c2"]["metric_set_by"]) == ("Revenue", "python")
    assert by["c2"]["group_role"] == by["c3"]["group_role"] == "segment_part" and by["c1"]["group_role"] == "total"
    assert cg.made_of(by["c2"], rows) == {"segment": "Online", "part_of": "part of Revenue FY2024 total"}


def test_without_a_title_that_names_the_metric_the_parts_stay_apart():
    for heading in (None, "ARR"):
        rows = register([TOTAL, part("c2", 600_000, "Online", heading), part("c3", 400_000, "Retail", heading)])
        assert {r["group_role"] for r in rows if r["claim_id"] in ("c2", "c3")} != {"segment_part"}, heading


def test_a_figure_whose_own_text_names_a_metric_keeps_it():
    c = part("c2", 600_000, "Online", "ARR", snippet="MRR EUR 600,000")
    assert register([c])[0]["metric"] == "MRR"


def test_a_title_naming_sales_follows_the_sales_answer():
    c = part("c1", 1_200_000, "Online", "sales", target_date="FY2022", period_text="FY2022")
    c = deck_claims_resolve(c)
    assert row_of(c)["reason"] == cm.SALES_ASK_REASON
    assert row_of(c, {"d1": {"as": "bookings"}})["reason"] == "bookings not in the data"
    assert row_of(c, {"d1": {"as": "revenue"}})["metric"] == "Revenue"
    assert cm.sales_questions([c], engine_results(), {}) == [{"deck_id": "d1", "file": "testco_board.pptx", "claims": 1}]


def deck_claims_resolve(c):
    from app.decks import claims as deck_claims
    return deck_claims.resolve_period({**c, "deck_id": "d1"}, FYE)
