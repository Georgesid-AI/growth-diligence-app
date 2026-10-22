"""Follow-up to PR #152 (issue #151): the three decisions George gave on that PR. One failing test per point, synthetic pages only
(CLAUDE.md rules 13 and 15):

1 the deck list shows the period note the register shows; the analyst's date edit clears it (the list's display is in
  frontend/src/components/DeckPanel.test.jsx; here the edit that clears it) · 2 a percentage or count beside an MRR or ARR word
  ("50% of MRR") gets no MRR or ARR deck label and no December reading · 3 figures of different metrics of the Sales family (ACV, win
  rate, sales cycle) are never compared for a deck inconsistency; two figures of one metric and period still are."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_issue_151 import deck  # noqa: E402

import server  # noqa: E402
from app.decks import claims  # noqa: E402
from app.structures import candidate_from_item, items, verify  # noqa: E402


def rules(*lines):
    return claims.detect_candidates(deck(*lines)["blocks"], "deck.pdf")


def of(found, value):
    one, = [c for c in found if c["value"] == value]
    return one


# ---------------------------------------------------------------------------
# 1. The analyst's date edit clears the note (the deck list sends the same edit as the register)
# ---------------------------------------------------------------------------
def test_1_the_note_stays_with_the_date_python_read_and_goes_with_the_analysts_date():
    c = of(rules("MRR in 2021 = €27K"), 27000)
    assert c["period_read_note"] == "period read as Dec 2021 from 'in 2021'"
    assert server._edited_period({**c, "target_date": "2021-12"}, c, 12)["period_read_note"] == c["period_read_note"], "same date: kept"
    assert server._edited_period({**c, "target_date": "2021-11"}, c, 12)["period_read_note"] is None


# ---------------------------------------------------------------------------
# 2. A percentage or a count beside MRR or ARR is no MRR or ARR figure
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("line", ["50% of MRR in 2021", "ARR share 50% in 2021", "New MRR 20% in 2021"])
def test_2_a_percentage_beside_an_mrr_or_arr_word_has_no_mrr_or_arr_label_and_keeps_its_year(line):
    c, = [c for c in rules(line) if c["unit"] == "%"]
    assert claims.deck_label(c) == "Revenue", c
    assert (c["target_date"], c.get("period_read_note")) == ("2021", None)


@pytest.mark.parametrize("unit", ["%", "x", "count", "customers", "months"])
def test_2_a_figure_with_a_unit_is_never_typed_mrr_or_arr(unit):
    for line in ("MRR in 2021", "ARR in 2021", "New MRR in 2021", "Monthly recurring revenue in 2021"):
        c = {"claim_type": "revenue", "unit": unit, "label_from": None, "snippet": line, "target_date": "2021"}
        assert claims.deck_label(c) == "Revenue" and claims.recurring_year_end(dict(c)).get("period_read_note") is None, (unit, line)


def test_2_the_panel_read_follows_the_rules_read():
    structure, = [s for s in deck("MRR in 2021 = €27K", "Share of MRR in 2021 = 50%")["structures"] if s["type"] == "kpi_panel"]
    listed = items.list_items(structure)
    labels = [{"item": i["id"], "metric": "revenue", "period": "FY2021", "unit": "%" if i["raw"].endswith("%") else "EUR", "unit_other": None,
               "actual_or_forecast": "actual"} for i in listed["items"]]
    checked = verify.verify(structure, listed, labels, (), 12, "suggest")["items"]
    rows = [candidate_from_item(i, structure, {"file": "deck.pdf", "blocks": []}, "kpi_panel", 12) for i in checked]
    share, = [r for r in rows if r["unit"] == "%"]
    assert claims.deck_label(share) == "Revenue" and not share.get("period_read_note")
    money, = [r for r in rows if r["unit"] != "%"]
    assert claims.deck_label(money) == "MRR" and money["target_date"] == "2021-12"


def test_2_a_money_run_rate_keeps_its_label():
    assert [claims.deck_label(c) for c in rules("MRR in 2021 = €27K", "ARR in 2021 = €30K")] == ["MRR", "ARR"]


# ---------------------------------------------------------------------------
# 3. Different metrics of the Sales family are never compared
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("lines", [("ACV 30K in 2021", "Sales cycle 45 days in 2021"), ("Win rate 30% in 2021", "Lead conversion 20% in 2021"),
                                   ("ACV 30K in 2021", "Pipeline 2M in 2021")])
def test_3_figures_of_different_sales_metrics_are_no_deck_inconsistency(lines):
    found = rules(*lines)
    assert len(found) == 2 and all(c["claim_type"] == "sales" for c in found)
    assert [c["inconsistent_dates"] for c in found] == [[], []], found
    assert claims.cross_deck_inconsistencies(found) == []


def test_3_two_figures_of_one_sales_metric_and_period_still_are():
    found = rules("ACV 30K in 2021", "Sales cycle 45 days in 2021", "ACV 40K in 2021")
    assert of(found, 30000)["inconsistent_dates"] == ["2021"] and of(found, 40000)["inconsistent_dates"] == ["2021"]
    assert of(found, 45)["inconsistent_dates"] == []
    assert len(claims.cross_deck_inconsistencies(found)) == 2
    cycles = rules("Sales cycle 45 days in 2021", "Sales cycle 60 days in 2021")
    assert [c["inconsistent_dates"] for c in cycles] == [["2021"], ["2021"]]


def test_3_other_families_are_compared_as_before():
    found = rules("5 customers in 2021", "6 customers in 2021")
    assert sorted((c["value"], c["inconsistent_dates"]) for c in found) == [(5, ["2021"]), (6, ["2021"])]
