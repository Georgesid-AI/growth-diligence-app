"""Segment from the label and segment partitions (docs/design/segment-partitions.md).

Fixture decks only: a synthetic company, synthetic names and figures. A product split that sums exactly to the company total, a customer split that does
not, and a deck stating both; a period partition beside a segment partition of the same total; a conflict among whole-company totals.
"""
import pytest

from claim_matching_support import engine_results

from app import claim_groups as cg
from app import claim_matching as cm
from app.decks import claims as deck_claims

FYE = 12
DECK = "testco_board.pptx"


def register(cands, **settings):
    base = {"fiscal_year_end": FYE, "as_of_month": None, "reporting_currency": "EUR", "fx": {"EUR": 1.0}, "target_arr": 5_000_000,
            "target_date": "2026-12-31"}
    return cm.build_register(cands, engine_results(), {**base, **settings})


def cand(cid, value, label, cited=None, claim_type="revenue", **over):
    """A deck claim as the register reads it; `cited` is the label the figure borrowed (the product, customer or legend item)."""
    n = int(cid[1:])
    c = {"id": cid, "status": "approved", "claim_type": claim_type, "value": value, "currency": "EUR", "target_date": label,
         "period_text": label, "snippet": f"Revenue EUR {value}", "label_from": cited, "file": DECK, "order": n, "basis": "actual",
         "sources": [{"file": DECK, "slide": over.pop("slide", n)}], **over}
    return deck_claims.resolve_period(c, FYE)


def by_id(rows):
    return {r["claim_id"]: r for r in rows}


def roles(rows):
    return {r["claim_id"]: r["group_role"] for r in rows}


PRODUCTS = [cand("c2", 600_000, "FY2024", "Product A", slide=4), cand("c3", 400_000, "FY2024", "Product B", slide=4)]      # sums exactly
CUSTOMERS = [cand("c4", 500_000, "FY2024", "Acme Corp", slide=6), cand("c5", 300_000, "FY2024", "Globex", slide=6)]       # sums to 800,000: no
TOTAL = cand("c1", 1_000_000, "FY2024", "Total revenue", slide=3)


# --- 1. the segment comes from the label -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("label, segment", [
    ("Product A", "Product A"), ("Enterprise ARR", "Enterprise"), ("Acme Corp", "Acme Corp"), ("Mid-Market revenue FY2024", "Mid-Market"),
    ("Core Platform", "Core Platform"), ("SMB", "SMB"), ("Product 2 revenue", "Product 2"), ("Revenue — Pay-ins", "Pay-ins"),
    ("Total revenue", None), ("Revenue", None), ("ARR", None), ("Annual recurring revenue 2024", None), ("Revenue by product", None),
    ("Product", None), ("Customers", None), ("Best case revenue", None), ("Forecast revenue FY2025", None), ("Q4 2024", None),
    ("Strong growth in the second half of the year", None), ("revenue per segment", None), (None, None), ("", None),
    ("Plan", None), ("Whole company", None), ("Revenue (EUR m)", None),
])
def test_the_segment_is_what_the_cited_label_names_besides_the_metric(label, segment):
    assert cm.label_segment(label) == segment


def test_a_product_label_is_the_segment_and_the_metric_stays_the_metric():
    rows = register([cand("c1", 600_000, "FY2024", "Product A")])
    row = rows[0]
    assert (row["segment"], row["segment_set_by"], row["metric"]) == ("Product A", "python", "Revenue")
    assert row["evidence_label"] != "Contradicted", "a product's figure is never tested against the whole company"
    assert "segment not in the data" in row["reason"]


def test_a_label_that_names_the_metric_only_leaves_the_whole_company():
    row = register([cand("c1", 1_000_000, "FY2024", "Total revenue")])[0]
    assert row["segment"] == cm.WHOLE


def test_the_analyst_segment_wins_over_the_label():
    row = register([cand("c1", 600_000, "FY2024", "Product A", claim_inputs={"c1": {"segment": "Enterprise"}})])[0]
    assert (row["segment"], row["segment_set_by"]) == ("Enterprise", "analyst")


def test_figures_of_different_segments_are_never_candidates_in_the_same_annual_conflict():
    rows = register([TOTAL, *PRODUCTS])
    found = cg.relate(rows)
    assert found["conflicts"] == [] and found["reviews"] == [], "three annual figures of one metric and period, but three scopes: no question"


def test_a_conflict_offers_only_candidates_of_its_own_scope():
    other = cand("c9", 1_250_000, "FY2024", "Total revenue", slide=8)
    rows = register([TOTAL, other, *PRODUCTS])
    found = cg.relate(rows)
    assert len(found["reviews"]) == 1
    assert sorted(c["claim_id"] for c in found["reviews"][0]["candidates"]) == ["c1", "c9"]


# --- 2. segment partitions ---------------------------------------------------------------------------------------------------------

def test_a_product_split_that_sums_to_the_total_becomes_its_parts_under_details_with_no_exposure_of_their_own():
    rows = register([TOTAL, *PRODUCTS])
    assert roles(rows) == {"c1": "total", "c2": "segment_part", "c3": "segment_part"}
    group = cg.relate(rows)["groups"][0]
    assert group["total"] == "c1" and sorted(group["segment_parts"]) == ["c2", "c3"] and group["parts"] == []
    assert len({r["group_id"] for r in rows}) == 1
    got = by_id(rows)
    assert got["c1"]["value_at_stake_arr"] == 1_000_000
    assert got["c2"]["value_at_stake_arr"] is None and got["c2"]["vas_reason"] == cg.VAS_IN_TOTAL
    assert sum(r["value_at_stake_arr"] or 0 for r in rows) == 1_000_000, "counted once"
    assert cg.counts(rows) == {"items": 1, "claims": 3, "groups": 1}
    assert all(cg.is_ineligible(got[i]) for i in ("c2", "c3"))
    assert got["c2"]["relationship"] == "Product A: part of the company total for FY2024, by segment"
    assert "segments reconcile with it (€1,000,000 against €1,000,000, within ±2%)" in got["c1"]["relationship"]


def test_a_customer_split_that_does_not_reconcile_stays_independent_with_a_relationship_note():
    rows = register([TOTAL, *CUSTOMERS])
    assert roles(rows) == {"c1": None, "c4": None, "c5": None}
    assert cg.relate(rows)["groups"] == []
    got = by_id(rows)
    for cid in ("c4", "c5"):
        assert "outside ±2%" in got[cid]["relationship"] and "€800,000" in got[cid]["relationship"] and "kept as independent claims" in got[cid]["relationship"]
        assert got[cid]["group_role"] is None and got[cid]["group_id"] is None


def test_a_deck_stating_both_splits_groups_the_one_that_reconciles_and_leaves_the_other_independent():
    rows = register([TOTAL, *CUSTOMERS, *PRODUCTS])
    got = by_id(rows)
    assert roles(rows) == {"c1": "total", "c2": "segment_part", "c3": "segment_part", "c4": None, "c5": None}
    assert got["c4"]["relationship"] and "independent claims" in got["c4"]["relationship"]
    assert got["c2"]["value_at_stake_arr"] is None and got["c4"]["segment"] == "Acme Corp"
    assert sum(r["value_at_stake_arr"] or 0 for r in rows if r["claim_id"] in ("c1", "c2", "c3")) == 1_000_000


def test_a_period_partition_and_a_segment_partition_of_the_same_total_are_both_under_details():
    quarters = [cand(f"c1{i}", v, f"2024-Q{i + 1}", "Total revenue", slide=10 + i) for i, v in enumerate([240_000, 250_000, 250_000, 260_000])]
    rows = register([TOTAL, *PRODUCTS, *quarters])
    assert sorted(r["group_role"] or "-" for r in rows) == ["part"] * 4 + ["segment_part"] * 2 + ["total"]
    assert len({r["group_id"] for r in rows}) == 1
    group = cg.relate(rows)["groups"][0]
    assert group["partition"] == "quarter" and len(group["parts"]) == 4 and len(group["segment_parts"]) == 2
    assert sum(r["value_at_stake_arr"] or 0 for r in rows) == 1_000_000


def test_segment_parts_wait_with_the_question_while_the_annual_figure_is_in_conflict():
    other = cand("c9", 1_250_000, "FY2024", "Total revenue", slide=8)
    rows = register([TOTAL, other, *PRODUCTS])
    assert roles(rows)["c2"] == cg.PENDING and roles(rows)["c3"] == cg.PENDING
    assert all(r["value_at_stake_arr"] is None for r in rows if r["claim_id"] in ("c2", "c3"))
    choose = cg.relate(rows, None, FYE)["reviews"][0]
    rows = register([TOTAL, other, *PRODUCTS], group_choices={choose["id"]: {"context": choose["context"], "chosen": cg.identity(by_id(rows)["c1"])}})
    assert roles(rows)["c2"] == "segment_part" and roles(rows)["c3"] == "segment_part", "the chosen total's set is the group's"


def test_a_segment_with_two_different_figures_is_not_part_of_a_partition():
    rows = register([TOTAL, *PRODUCTS, cand("c6", 450_000, "FY2024", "Product B", slide=9)])
    assert cg.relate(rows)["groups"] == []
    assert roles(rows)["c2"] is None


def test_one_segment_alone_is_no_partition():
    rows = register([TOTAL, cand("c2", 1_000_000, "FY2024", "Product A")])
    assert cg.relate(rows)["groups"] == [] and roles(rows)["c2"] is None


def test_the_sum_must_be_within_two_percent_of_the_total():
    inside = register([TOTAL, cand("c2", 600_000, "FY2024", "Product A"), cand("c3", 410_000, "FY2024", "Product B")])      # 1,010,000: +1%
    assert roles(inside)["c2"] == "segment_part"
    outside = register([TOTAL, cand("c2", 600_000, "FY2024", "Product A"), cand("c3", 430_000, "FY2024", "Product B")])     # 1,030,000: +3%
    assert roles(outside)["c2"] is None


def test_segments_of_another_currency_or_period_or_scenario_are_not_parts():
    other_year = [cand("c2", 600_000, "FY2023", "Product A"), cand("c3", 400_000, "FY2023", "Product B")]
    assert cg.relate(register([TOTAL, *other_year]))["groups"] == []
    usd = [cand("c2", 600_000, "FY2024", "Product A", currency="USD"), cand("c3", 400_000, "FY2024", "Product B", currency="USD")]
    assert cg.relate(register([TOTAL, *usd]))["groups"] == []


def test_a_contradicted_segment_part_stays_visible_and_counts_on_the_total():
    rows = register([TOTAL, *PRODUCTS])
    got = by_id(rows)
    got["c2"]["evidence_label"] = "Contradicted"
    members = cg.members(rows)[got["c1"]["group_id"]]
    assert got["c2"] in cg.contradicted_members(got["c1"], cg.members(rows)) and got["c2"] in members
    assert cg.effective_label(got["c1"], cg.members(rows)) == "Contradicted"
