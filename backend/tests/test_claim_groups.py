"""Claim groups and conflict resolution (docs/specs/claim-groups.md; docs/design/claim-review-simplified-design.md sections 1 and 2).

The acceptance table of the design note, for this scope: complete, partial and mixed partitions, negative and zero totals, different scopes and
scenarios, March year-end, edit and Undo; a contradicted part stays visible and affects the conclusion despite a verified annual total; no invented
segment; choices survive valid reads and expire after relevant edits. Fixture decks only: a synthetic company, synthetic figures.
"""
import copy

import pytest

from claim_matching_support import engine_results

from app import claim_groups as cg
from app import claim_matching as cm
from app import verdict as verdict_mod
from app.decks import claims as deck_claims

FYE = 12
DECK = "testco_board.pptx"
METRIC_OF = {"revenue": "Revenue", "arr": "ARR", "mrr": "MRR", "customers": "Customer count"}      # as the register proposes them; the rest have none


def span(label, fye=FYE):
    start, end = deck_claims.period_range(label, fye)
    return start, end


def row(cid, value, label, claim_type="revenue", fye=FYE, **over):
    """A register row as the groups read it: the scope, the period, the figure and the label."""
    start, end = span(label, fye)
    n = int("".join(ch for ch in cid if ch.isdigit()) or 0)
    out = dict.fromkeys(cm.FIELDS)
    out.update(
        claim_id=cid, claim_type=claim_type, metric=METRIC_OF.get(claim_type), population=None,
        segment=cm.WHOLE, currency="EUR", unit=None, figure_type="actual", basis="actual", scenario="none", required_unknown=[],
        deck_reading="Verified", claimed_value=value, claimed_high=None, period=label, period_start=start, period_end=end,
        deck_file=DECK, page_ref=f"slide {n}", evidence_label="Verified", reason="within ±5% of the claim", shortfall=None,
        value_at_stake_arr=value * 4 if claim_type == "revenue" else None, vas_reason=None, rank=n, overlaps_with=[], status="approved")
    out.update(over)
    return out


def quarters(values, year="2024", start_at=10, **over):
    return [row(f"q{start_at + i}", v, f"{year}-Q{i + 1}", **over) for i, v in enumerate(values)]


def halves(values, year="2024", start_at=20, **over):
    return [row(f"h{start_at + i}", v, f"{year}-H{i + 1}", **over) for i, v in enumerate(values)]


def months(values, year="2024", start_at=30, **over):
    return [row(f"m{start_at + i}", v, f"{year}-{i + 1:02d}", **over) for i, v in enumerate(values)]


def annual(value, year="2024", cid="a1", **over):
    return row(cid, value, year, **over)


def related(rows, choices=None, fye=FYE):
    return cg.annotate(rows, choices, fye)


def roles(rows):
    return {r["claim_id"]: r["group_role"] for r in rows}


# --- 1. complete, partial and mixed partitions ----------------------------------------------------------------------------------

def test_a_complete_set_of_quarters_that_reconciles_is_one_group_with_the_total_once_and_the_parts_under_it():
    rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000])]
    found = related(rows)
    assert len(found["groups"]) == 1
    group = found["groups"][0]
    assert group["total"] == "a1" and group["partition"] == "quarter" and group["parts"] == ["q10", "q11", "q12", "q13"]
    assert roles(rows) == {"a1": "total", "q10": "part", "q11": "part", "q12": "part", "q13": "part"}
    assert len({r["group_id"] for r in rows}) == 1
    assert cg.counts(rows) == {"items": 1, "claims": 5, "groups": 1}, "one displayed group, five underlying claims"
    total = rows[0]
    assert "quarters reconcile" in total["relationship"] and "€1,000,000" in total["relationship"]
    assert all("annual total" in r["relationship"] for r in rows[1:])


def test_a_group_keeps_every_claim_and_its_evidence_label():
    rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000], evidence_label="Unverified")]
    before = copy.deepcopy(rows)
    related(rows)
    for old, new in zip(before, rows):
        assert {k: new[k] for k in ("claim_id", "claimed_value", "period", "evidence_label", "reason", "shortfall", "rank")} == \
               {k: old[k] for k in ("claim_id", "claimed_value", "period", "evidence_label", "reason", "shortfall", "rank")}


def test_two_halves_and_twelve_months_group_the_same_way():
    for parts, name in ((halves([480_000, 520_000]), "half"), (months([100_000] * 4 + [75_000] * 8), "month")):
        rows = [annual(1_000_000), *parts]
        found = related(rows)
        assert [g["partition"] for g in found["groups"]] == [name], name


def test_an_incomplete_set_stays_independent_with_a_note_on_the_total():
    rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000])[:3]]
    found = related(rows)
    assert found["groups"] == [] and all(r["group_role"] is None for r in rows)
    assert rows[0]["relationship"] == "Quarters: 3 of 4 stated; kept as independent claims"
    assert all(r["relationship"] is None for r in rows[1:]), "the parts say nothing: they are claims of their own"


def test_one_part_alone_is_no_relationship_and_no_note():
    rows = [annual(1_000_000), *quarters([240_000])]
    related(rows)
    assert rows[0]["relationship"] is None and rows[0]["group_role"] is None


def test_a_complete_set_that_does_not_reconcile_stays_independent_with_a_note():
    rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 300_000])]
    found = related(rows)
    assert found["groups"] == [] and rows[0]["group_role"] is None
    assert rows[0]["relationship"] == "Quarters sum to €1,040,000, outside ±2% of €1,000,000; kept as independent claims"


def test_the_tolerance_is_two_percent_of_the_total_inclusive():
    for parts_sum, expect in ((1_020_000, 1), (980_000, 1), (1_020_100, 0), (979_900, 0)):
        rows = [annual(1_000_000), *halves([parts_sum - 500_000, 500_000])]
        assert len(related(rows)["groups"]) == expect, parts_sum


def test_quarters_and_halves_that_both_reconcile_group_under_the_finer_set_and_the_halves_go_under_details():
    rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000]), *halves([480_000, 520_000])]
    found = related(rows)
    assert found["reviews"] == [], "no card: the finer set is the default"
    assert [g["partition"] for g in found["groups"]] == ["quarter"]
    group = found["groups"][0]
    assert group["parts"] == ["q10", "q11", "q12", "q13"] and group["other_parts"] == ["h20", "h21"] and group["other_partitions"] == ["half"]
    assert roles(rows) == {"a1": "total", "q10": "part", "q11": "part", "q12": "part", "q13": "part", "h20": "also", "h21": "also"}
    assert len({r["group_id"] for r in rows}) == 1
    halves_ = [r for r in rows if r["claim_id"].startswith("h")]
    assert all(r["relationship"] == "Halves also reconcile with this total; shown under its Details" for r in halves_)
    assert all(r["value_at_stake_arr"] is None and r["vas_reason"] == cg.VAS_IN_TOTAL for r in halves_), "the halves add no second exposure"
    assert all(cg.is_subordinate(r) and cg.is_ineligible(r) for r in halves_)
    assert cg.counts(rows) == {"items": 1, "claims": 7, "groups": 1}


def test_months_are_finer_than_quarters_and_quarters_finer_than_halves():
    rows = [annual(1_000_000), *months([100_000] * 4 + [75_000] * 8), *quarters([400_000, 225_000, 225_000, 150_000])]
    assert [g["partition"] for g in related(rows)["groups"]] == ["month"]
    assert roles(rows)["q10"] == "also" and roles(rows)["m30"] == "part"


def test_a_contradicted_half_that_also_reconciles_surfaces_on_the_group_item():
    rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000]), *halves([480_000, 520_000])]
    rows[5]["evidence_label"] = "Contradicted"
    related(rows)
    assert cg.effective_label(rows[0], cg.members(rows)) == "Contradicted"
    assert [m["claim_id"] for m in cg.contradicted_members(rows[0], cg.members(rows))] == ["h20"]


def test_when_only_the_halves_reconcile_they_are_the_group_and_the_quarters_stay_independent():
    rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 300_000]), *halves([480_000, 520_000])]
    found = related(rows)
    assert [g["partition"] for g in found["groups"]] == ["half"]
    assert roles(rows) == {"a1": "total", "h20": "part", "h21": "part", "q10": None, "q11": None, "q12": None, "q13": None}


def test_a_set_that_mixes_granularities_is_no_partition():
    # Q1, Q2 and the second half tile the year without overlap, but a partition is quarters, halves or months, never a mix
    rows = [annual(1_000_000), row("q10", 240_000, "2024-Q1"), row("q11", 250_000, "2024-Q2"), row("h21", 510_000, "2024-H2")]
    found = related(rows)
    assert found["groups"] == [] and all(r["group_role"] is None for r in rows)


# --- 2. negative and zero totals ------------------------------------------------------------------------------------------------

def test_a_negative_total_reconciles_with_negative_parts():
    rows = [annual(-1_000_000, claim_type="net_profit"), *quarters([-240_000, -250_000, -250_000, -260_000], claim_type="net_profit")]
    assert len(related(rows)["groups"]) == 1
    assert rows[0]["relationship"].startswith("Annual total: quarters reconcile") and "-€1,000,000" in rows[0]["relationship"]


def test_a_negative_total_is_not_reconciled_by_parts_of_the_other_sign_or_size():
    for parts in ([240_000, 250_000, 250_000, 260_000], [-240_000, -250_000, -250_000, -300_000]):
        rows = [annual(-1_000_000, claim_type="net_profit"), *quarters(parts, claim_type="net_profit")]
        assert related(rows)["groups"] == [], parts


def test_a_zero_total_accepts_only_exact_equality():
    rows = [annual(0, claim_type="net_profit"), *quarters([100, -100, 50, -50], claim_type="net_profit")]
    assert len(related(rows)["groups"]) == 1
    rows = [annual(0, claim_type="net_profit"), *quarters([100, -100, 50, -49], claim_type="net_profit")]
    assert related(rows)["groups"] == [], "there is no rounding allowance, so a tolerance of 2% of zero is zero"


def test_a_zero_total_is_exact_in_decimals_not_in_floats():
    rows = [annual(0, claim_type="net_profit"), *quarters([0.1, 0.2, -0.3, 0.0], claim_type="net_profit")]
    assert len(related(rows)["groups"]) == 1, "0.1 + 0.2 - 0.3 is 0 in the figures as stated"


def test_the_reconciliation_rule_is_the_design_notes():
    from decimal import Decimal
    assert cg.TOLERANCE == Decimal("0.02")
    assert cg.within(Decimal(98), Decimal(100)) and cg.within(Decimal(102), Decimal(100)) and not cg.within(Decimal("102.01"), Decimal(100))
    assert cg.within(Decimal(-98), Decimal(-100)) and not cg.within(Decimal(98), Decimal(-100))
    assert cg.within(Decimal(0), Decimal(0)) and not cg.within(Decimal("0.0001"), Decimal(0))


# --- 3. different scopes and scenarios -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("field, other", [
    ("segment", "Enterprise"), ("currency", "GBP"), ("unit", "k"), ("figure_type", "target"), ("basis", "projection"),
    ("scenario", "realistic"), ("metric", "Transaction volume"), ("population", "paying"),
])
def test_a_part_of_another_scope_or_scenario_is_not_grouped(field, other):
    parts = quarters([240_000, 250_000, 250_000, 260_000])
    parts[2][field] = other
    rows = [annual(1_000_000), *parts]
    assert related(rows)["groups"] == [], field
    assert all(r["group_role"] is None for r in rows)


def test_a_row_whose_scope_is_unknown_is_never_assumed_equal():
    for unknown in ({"required_unknown": ["currency"]}, {"figure_type": "unknown"}, {"figure_type": None}, {"turnover_state": "ask"},
                    {"currency": None}):
        parts = quarters([240_000, 250_000, 250_000, 260_000])
        parts[0].update(unknown)
        rows = [annual(1_000_000), *parts]
        assert related(rows)["groups"] == [], unknown


def test_a_best_case_or_worst_case_figure_and_an_untested_claim_never_join_a_group():
    parts = quarters([240_000, 250_000, 250_000, 260_000])
    parts[1].update(scenario="best")
    assert related([annual(1_000_000), *parts])["groups"] == []
    parts = quarters([240_000, 250_000, 250_000, 260_000])
    parts[1].update(deck_reading=cm.FORECAST_READING)
    assert related([annual(1_000_000), *parts])["groups"] == []


def test_two_claim_types_are_never_related_and_a_rate_is_never_summed():
    parts = quarters([240_000, 250_000, 250_000, 260_000], claim_type="costs")
    assert related([annual(1_000_000), *parts])["groups"] == []
    rates = [row(f"r{i}", 10, f"2024-Q{i + 1}", claim_type="churn", unit="%") for i in range(4)]
    assert related([row("r9", 40, "2024", claim_type="churn", unit="%"), *rates])["groups"] == []


def test_a_range_is_not_one_figure_and_is_not_grouped():
    parts = quarters([240_000, 250_000, 250_000, 260_000])
    parts[0].update(claimed_high=260_000)
    assert related([annual(1_000_000), *parts])["groups"] == []


def test_the_same_quarters_group_under_each_scope_on_their_own():
    whole = [annual(1_000_000, cid="a1"), *quarters([240_000, 250_000, 250_000, 260_000], start_at=10)]
    seg = [annual(400_000, cid="a2", segment="Enterprise"), *quarters([90_000, 100_000, 100_000, 110_000], start_at=40, segment="Enterprise")]
    found = related(whole + seg)
    assert len(found["groups"]) == 2 and {g["segment"] for g in found["groups"]} == {cm.WHOLE, "Enterprise"}


# --- 4. balances and counts --------------------------------------------------------------------------------------------------------

def obs(cid, value, label, claim_type="arr", **over):
    return row(cid, value, label, claim_type=claim_type, metric="ARR", value_at_stake_arr=None, **over)


def test_an_annual_balance_reconciles_with_the_year_end_observation_and_not_the_sum_of_observations():
    rows = [obs("a1", 2_000_000, "2024"), obs("o10", 1_000_000, "2024-03"), obs("o11", 1_500_000, "2024-09"), obs("o12", 2_010_000, "2024-12")]
    found = related(rows)
    assert [g["partition"] for g in found["groups"]] == ["year-end"] and found["groups"][0]["parts"] == ["o12"]
    assert roles(rows) == {"a1": "total", "o10": None, "o11": None, "o12": "part"}, "earlier snapshots are no duplicates of the year-end balance"


def test_an_annual_balance_that_the_year_end_observation_does_not_match_is_not_grouped():
    rows = [obs("a1", 2_000_000, "2024"), obs("o12", 1_500_000, "2024-12")]
    assert related(rows)["groups"] == []
    assert "outside ±2%" in rows[0]["relationship"]


def test_a_claim_typed_revenue_whose_metric_is_arr_is_a_balance_and_its_quarters_are_never_summed():
    parts = [row(f"q1{i}", 400_000, f"2024-Q{i + 1}", metric="ARR") for i in range(4)]
    rows = [row("a1", 1_600_000, "2024", metric="ARR"), *parts]
    assert related(rows)["groups"] == [], "four quarter-end ARR figures are not a year of ARR"
    year_end = [row("a1", 1_600_000, "2024", metric="ARR"), row("o12", 1_610_000, "2024-12", metric="ARR")]
    assert [g["partition"] for g in related(year_end)["groups"]] == ["year-end"]


def test_a_metric_that_is_neither_an_amount_nor_a_level_is_never_related():
    parts = [row(f"q1{i}", 60_000, f"2024-Q{i + 1}", metric="New MRR") for i in range(4)]
    assert related([row("a1", 240_000, "2024", metric="New MRR"), *parts])["groups"] == []


def test_a_quarter_end_balance_is_not_the_year_end_observation():
    rows = [obs("a1", 2_000_000, "2024"), obs("o10", 2_000_000, "2024-Q4")]
    assert related(rows)["groups"] == []


def test_a_customer_count_groups_like_any_balance():
    rows = [row("a1", 120, "2024", claim_type="customers", metric="Customer count", population="paying", unit="customers", currency=None,
                value_at_stake_arr=None),
            row("o12", 121, "2024-12", claim_type="customers", metric="Customer count", population="paying", unit="customers", currency=None,
                value_at_stake_arr=None)]
    assert len(related(rows)["groups"]) == 1


# --- 5. March year-end -------------------------------------------------------------------------------------------------------------

def test_a_march_year_end_year_is_april_to_march_and_its_fiscal_quarters_are_its_parts():
    assert span("FY2025", 3) == ("2024-04-01", "2025-03-31")
    rows = [row("a1", 1_000_000, "FY2025", fye=3)] + [row(f"q1{i}", v, f"2025-Q{i + 1}", fye=3)
                                                      for i, v in enumerate([240_000, 250_000, 250_000, 260_000])]
    found = related(rows, fye=3)
    assert len(found["groups"]) == 1 and found["groups"][0]["parts"] == ["q10", "q11", "q12", "q13"]


def test_calendar_quarters_do_not_tile_a_march_year_end_year():
    cal = [row(f"q1{i}", v, f"2025-Q{i + 1}", fye=12) for i, v in enumerate([240_000, 250_000, 250_000, 260_000])]
    rows = [row("a1", 1_000_000, "FY2025", fye=3)] + cal
    assert related(rows, fye=3)["groups"] == []
    assert rows[0]["relationship"] is None, "no fiscal quarter is stated, so there is nothing useful to say"


def test_the_march_year_end_groups_through_the_register_with_the_periods_resolved_for_the_year_end():
    results = engine_results()
    cands = []
    for i, (label, value) in enumerate([("FY2023", 187_700), ("2023-Q1", 44_845), ("2023-Q2", 46_204), ("2023-Q3", 47_604), ("2023-Q4", 49_047)]):
        c = {"id": f"c{i}", "status": "approved", "claim_type": "revenue", "value": value, "currency": "EUR", "target_date": label,
             "period_text": label, "snippet": f"Revenue EUR {value}", "label_from": None, "file": DECK, "order": i, "basis": "actual",
             "sources": [{"file": DECK, "slide": 3 + i}]}
        deck_claims.resolve_period(c, 12)
        cands.append(c)
    rows = cm.build_register(cands, results, {"fiscal_year_end": 12, "as_of_month": None, "reporting_currency": "EUR", "fx": {"EUR": 1.0}})
    assert sorted(r["group_role"] or "-" for r in rows) == ["part"] * 4 + ["total"]
    for c in cands:
        deck_claims.resolve_period(c, 3)           # the same labels for a March year-end: other months, so the same quarters no longer tile 2023
    rows = cm.build_register(cands, results, {"fiscal_year_end": 3, "as_of_month": None, "reporting_currency": "EUR", "fx": {"EUR": 1.0}})
    assert sorted(r["group_role"] or "-" for r in rows) == ["part"] * 4 + ["total"], "the fiscal year and its fiscal quarters tile each other"


# --- 6. exposure: the headline once, run-rate for what is independent -------------------------------------------------------------------

def register(cands, **settings):
    base = {"fiscal_year_end": 12, "as_of_month": None, "reporting_currency": "EUR", "fx": {"EUR": 1.0}, "target_arr": 5_000_000,
            "target_date": "2026-12-31"}
    return cm.build_register(cands, engine_results(), {**base, **settings})


def cand(cid, value, label, claim_type="revenue", **over):
    c = {"id": cid, "status": "approved", "claim_type": claim_type, "value": value, "currency": "EUR", "target_date": label,
         "period_text": label, "snippet": f"Revenue EUR {value}", "label_from": None, "file": DECK, "order": int(cid[1:]), "basis": "actual",
         "sources": [{"file": DECK, "slide": int(cid[1:])}], **over}
    return deck_claims.resolve_period(c, FYE)


def test_the_annual_headline_keeps_its_value_at_stake_and_its_parts_add_none():
    rows = register([cand("c1", 187_700, "2023"), cand("c2", 44_845, "2023-Q1"), cand("c3", 46_204, "2023-Q2"),
                     cand("c4", 47_604, "2023-Q3"), cand("c5", 49_047, "2023-Q4")])
    by_id = {r["claim_id"]: r for r in rows}
    assert by_id["c1"]["value_at_stake_arr"] == 187_700 and by_id["c1"]["vas_reason"] is None
    for cid in ("c2", "c3", "c4", "c5"):
        assert by_id[cid]["value_at_stake_arr"] is None and by_id[cid]["vas_reason"] == cg.VAS_IN_TOTAL
    assert sum(r["value_at_stake_arr"] or 0 for r in rows) == 187_700, "the exposure is counted once"


def test_an_independent_short_period_claim_keeps_its_run_rate_and_says_so():
    rows = register([cand("c1", 47_604, "2023-Q3")])
    assert rows[0]["value_at_stake_arr"] == 47_604 * 4 and rows[0]["vas_reason"] == "run-rate: 2023-Q3 × 4"


def test_a_non_reconciling_annual_claim_does_not_suppress_the_run_rate_of_a_quarter():
    rows = register([cand("c1", 400_000, "2023"), cand("c2", 47_604, "2023-Q3")])
    by_id = {r["claim_id"]: r for r in rows}
    assert by_id["c2"]["group_role"] is None and by_id["c2"]["value_at_stake_arr"] == 47_604 * 4
    assert by_id["c2"]["vas_reason"].startswith("run-rate: ")
    assert by_id["c1"]["value_at_stake_arr"] == 400_000


# --- 7. the top five --------------------------------------------------------------------------------------------------------------

def test_a_reconciled_group_is_one_item_of_the_top_five_its_total():
    rows = register([cand("c1", 187_700, "2023"), cand("c2", 44_845, "2023-Q1"), cand("c3", 46_204, "2023-Q2"),
                     cand("c4", 47_604, "2023-Q3"), cand("c5", 49_047, "2023-Q4")])
    assert verdict_mod.proposal(rows) == ["c1"]
    assert [r["claim_id"] for r in verdict_mod.sortable(rows)] == ["c1"]
    state = verdict_mod.top5_state(rows, {"claim_ids": ["c2"], "set_at": "x"})
    assert state["in_force"] == ["c1"] and not state["changed"], "a part cannot be put in the five on its own"


def test_the_priority_of_a_group_is_its_most_material_unresolved_issue():
    # two groups with the same headline exposure: the one with a part that misses by more is first
    plain = [row("a1", 1_000_000, "2024", shortfall=None, rank=1), *quarters([240_000, 250_000, 250_000, 260_000], start_at=10)]
    other = [row("a2", 1_000_000, "2023", shortfall=None, rank=2, segment="Enterprise"),
             *quarters([240_000, 250_000, 250_000, 260_000], year="2023", start_at=50, segment="Enterprise")]
    other[3]["shortfall"] = 0.3
    rows = plain + other
    related(rows)
    assert verdict_mod.proposal(rows)[:2] == ["a2", "a1"]


def test_displayed_groups_are_counted_apart_from_the_underlying_claims():
    rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000]), row("x1", 5, "2022", claim_type="churn", unit="%")]
    related(rows)
    assert cg.counts(rows) == {"items": 2, "claims": 6, "groups": 1}


# --- 8. a contradicted part stays visible and affects the conclusion --------------------------------------------------------------

OFFSETTING = [cand("c1", 187_700, "2023"), cand("c2", 44_845, "2023-Q1"), cand("c3", 46_204, "2023-Q2"),
              cand("c4", 52_000, "2023-Q3"), cand("c5", 44_651, "2023-Q4")]      # Q3 overstated and Q4 understated by the same amount


def test_a_verified_annual_total_does_not_hide_a_contradicted_quarter():
    rows = register(copy.deepcopy(OFFSETTING))
    by_id = {r["claim_id"]: r for r in rows}
    assert by_id["c1"]["evidence_label"] == "Verified" and by_id["c4"]["evidence_label"] == "Contradicted"
    assert by_id["c1"]["group_role"] == "total" and by_id["c4"]["group_role"] == "part", "the offsetting parts still reconcile"
    ver = verdict_mod.verdict(rows, engine_results(), None)
    assert ver["outcome_code"] == "not_supported" and ver["rule"].startswith("1 selected claim is Contradicted")
    item = ver["five"][0]
    assert item["claim_id"] == "c1" and item["evidence_label"] == "Contradicted"
    assert item["group"] == {"id": by_id["c1"]["group_id"], "parts": 4, "contradicted": ["c4"]}
    assert "Contradicted" in ver["reasons"][0] and "2023-Q3" in ver["reasons"][0], "the reason names the part that is contradicted"
    assert ver["other_contradictions"] == [], "the part is inside the group's item, not outside the five"


def test_the_group_item_is_verified_when_every_member_is():
    rows = register([cand("c1", 187_700, "2023"), cand("c2", 44_845, "2023-Q1"), cand("c3", 46_204, "2023-Q2"),
                     cand("c4", 47_604, "2023-Q3"), cand("c5", 49_047, "2023-Q4")])
    assert verdict_mod.verdict(rows, engine_results(), None)["outcome_code"] == "supported"


def test_a_contradicted_part_of_a_group_outside_the_five_is_listed_with_the_other_contradictions():
    rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000])]
    rows[3].update(evidence_label="Contradicted", gloss="€4,000 lower (miss)", observed_source={"file": "rev.xlsx"}, evidence_analysis="Revenue")
    related(rows)
    others = verdict_mod.other_contradictions(rows, ["zzz"])
    assert [o["claim_id"] for o in others] == ["q12"]
    assert verdict_mod.other_contradictions(rows, ["a1"]) == [], "inside a group in the five, it is not outside"


def test_the_conclusion_lists_a_contradicted_part_of_a_group_the_analyst_left_out_of_the_five():
    group = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000])]
    group[3].update(evidence_label="Contradicted", reason="outside ±5%: a miss", gloss="€4,000 lower (miss)", observed_source={"file": "rev.xlsx"})
    others = [row(f"x{60 + i}", 10_000 + i, "2022", segment=f"S{i}") for i in range(1, 6)]
    rows = group + others
    related(rows)
    stored = {"claim_ids": [r["claim_id"] for r in others], "set_at": "2026-10-26"}
    ver = verdict_mod.verdict(rows, {"reporting_currency": "EUR"}, stored)
    assert ver["top5"]["changed"] and [f["claim_id"] for f in ver["five"]] == [r["claim_id"] for r in others]
    assert [o["claim_id"] for o in ver["other_contradictions"]] == ["q12"], "the part is outside the five, so it is listed with the others"
    with_group = verdict_mod.verdict(rows, {"reporting_currency": "EUR"}, {"claim_ids": ["a1"] + [r["claim_id"] for r in others[:4]], "set_at": "t"})
    assert with_group["other_contradictions"] == [] and with_group["outcome_code"] == "not_supported"


# --- 9. conflict resolution --------------------------------------------------------------------------------------------------------

def conflict_rows():
    return [annual(1_000_000, cid="a1"), annual(1_250_000, cid="a2", rank=2), *quarters([240_000, 250_000, 250_000, 260_000])]


def test_two_annual_figures_that_differ_are_a_conflict_with_no_figure_selected():
    rows = conflict_rows()
    found = related(rows)
    assert found["groups"] == [], "several candidate totals remain, so the quarters are not attached to either"
    assert [c["state"] for c in found["conflicts"]] == ["open"] and found["reviews"] == found["conflicts"]
    review = found["reviews"][0]
    assert review["kind"] == "total" and [c["claim_id"] for c in review["candidates"]] == ["a1", "a2"]
    assert not any(c["chosen"] for c in review["candidates"])
    assert review["candidates"][0]["hint"] == "quarters sum to €1,000,000, within ±2%" and review["candidates"][1]["hint"] is None
    assert review["candidates"][0]["source"] == f"{DECK} slide 1"
    assert {r["claim_id"]: r["group_role"] for r in rows if r["claim_id"] in ("a1", "a2")} == {"a1": "candidate", "a2": "candidate"}
    assert "choose the one to use" in rows[0]["relationship"]


def test_while_no_total_is_chosen_none_of_the_candidates_can_enter_the_top_five_and_the_conflict_stays_in_the_conclusion():
    results = engine_results()
    rows = register([cand("c1", 187_700, "2023"), cand("c2", 250_000, "2023"), cand("c3", 90_000, "2023", claim_type="costs"),
                     cand("c4", 1_100_000, "2023-Q3", claim_type="costs")])
    related_ = cg.relate(rows, fiscal_year_end=12)
    assert verdict_mod.proposal(rows) and not {"c1", "c2"} & set(verdict_mod.proposal(rows))
    ver = verdict_mod.verdict(rows, results, None, 0, related_["conflicts"])
    assert [c["state"] for c in ver["conflicts"]] == ["open"]
    assert "Revenue, 2023" in ver["conflicts"][0]["text"] and "No figure chosen" in ver["conflicts"][0]["text"]
    assert ver["conflicts"][0]["text"].count(DECK) == 2, "each figure is named with its source"


def test_choosing_a_total_selects_it_and_makes_no_other_figure_a_segment():
    rows = conflict_rows()
    review = related(rows)["reviews"][0]
    choices = {review["id"]: {"kind": "total", "chosen": review["candidates"][0]["identity"], "context": review["context"]}}
    rows = conflict_rows()
    found = related(rows, choices)
    assert [g["total"] for g in found["groups"]] == ["a1"], "the chosen figure reconciles with the quarters, so the group forms around it"
    other = next(r for r in rows if r["claim_id"] == "a2")
    assert other["group_role"] == "alternative" and other["segment"] == cm.WHOLE, "the alternative is not a segment"
    assert other["evidence_label"] == "Verified", "it is not marked false because it was not chosen"
    assert "not a segment" in other["relationship"]
    assert [c["state"] for c in found["conflicts"]] == ["chosen"] and found["reviews"] == [], "the conflict stays listed, no longer a question"
    assert not any(r["claim_id"] == "a2" for r in verdict_mod.sortable(rows)), "it does not take a place in the five either"


def test_a_choice_that_does_not_reconcile_is_still_the_preferred_total_with_no_group():
    rows = conflict_rows()
    review = related(rows)["reviews"][0]
    choices = {review["id"]: {"kind": "total", "chosen": review["candidates"][1]["identity"], "context": review["context"]}}
    rows = conflict_rows()
    found = related(rows, choices)
    assert found["groups"] == [] and rows[1]["group_role"] is None and rows[0]["group_role"] == "alternative"
    assert [c["state"] for c in found["conflicts"]] == ["chosen"]


def test_a_choice_survives_every_read_that_does_not_change_the_candidates():
    rows = conflict_rows()
    review = related(rows)["reviews"][0]
    choices = {review["id"]: {"kind": "total", "chosen": review["candidates"][0]["identity"], "context": review["context"]}}
    for _ in range(3):
        again = [r for r in reversed(conflict_rows())]                    # another read order
        for r in again:
            r["rank"] = 99 - r["rank"]                                    # a new run ranks the same claims differently
            r["evidence_label"] = "Contradicted"                          # and labels them differently
            r["claim_id"] = r["claim_id"] + "x"                           # a page read again gives new claim ids for the same figures
            r["claimed_value"] = float(r["claimed_value"])                # and an edited value comes back a float
        assert [c["state"] for c in related(again, choices)["conflicts"]] == ["chosen"]
    extra = conflict_rows() + [row("z1", 5, "2022", claim_type="churn", unit="%")]
    assert [c["state"] for c in related(extra, choices)["conflicts"]] == ["chosen"], "an unrelated claim does not expire it"


@pytest.mark.parametrize("change", [
    {"claimed_value": 1_000_500}, {"claimed_value": 1_300_000}, {"period": "2024", "period_start": "2024-01-01", "period_end": "2024-12-30"},
    {"segment": "Enterprise"}, {"currency": "USD"}, {"page_ref": "slide 9"}, {"deck_file": "other_board.pptx"}, {"basis": "projection"},
])
def test_a_choice_expires_after_an_edit_to_any_candidate_or_its_scope(change):
    rows = conflict_rows()
    review = related(rows)["reviews"][0]
    choices = {review["id"]: {"kind": "total", "chosen": review["candidates"][0]["identity"], "context": review["context"]}}
    edited = conflict_rows()
    edited[0].update(change)
    found = related(edited, choices)
    assert "chosen" not in [c["state"] for c in found["conflicts"]], "the saved choice no longer applies"
    assert all(r["claim_id"] != "a1" or r["group_role"] != "total" for r in edited), "and no group is formed from it"


def test_a_choice_expires_when_a_candidate_is_added_removed_or_the_fiscal_calendar_changes():
    rows = conflict_rows()
    review = related(rows)["reviews"][0]
    choices = {review["id"]: {"kind": "total", "chosen": review["candidates"][0]["identity"], "context": review["context"]}}
    third = conflict_rows() + [annual(1_400_000, cid="a3", rank=3)]
    assert [c["state"] for c in related(third, choices)["conflicts"]] == ["open"], "a third candidate is a new question"
    assert [c["state"] for c in related(conflict_rows(), choices, fye=3)["conflicts"]] == ["open"], "another fiscal calendar is another context"
    assert related(conflict_rows()[:1] + conflict_rows()[2:], choices)["conflicts"] == [], "with one candidate left there is no conflict"


def test_a_conflict_resolves_when_a_figure_is_corrected_scoped_or_excluded():
    for fix in ("corrected", "scoped", "excluded"):
        rows = conflict_rows()
        if fix == "corrected":
            rows[1].update(claimed_value=1_005_000)
        elif fix == "scoped":
            rows[1].update(segment="Enterprise")
        else:
            rows.pop(1)
        found = related(rows)
        assert found["conflicts"] == [] and found["reviews"] == [], fix
        assert [g["total"] for g in found["groups"]] == ["a1"], f"{fix}: the remaining figure reconciles with the quarters"


def test_two_annual_figures_within_the_tolerance_are_the_same_figure_not_a_conflict_and_the_repeat_folds_into_the_group():
    rows = [annual(1_000_000, cid="a1"), annual(1_010_000, cid="a2", rank=2, page_ref="slide 8"), *quarters([240_000, 250_000, 250_000, 260_000])]
    found = related(rows)
    assert found["conflicts"] == [] and len(found["groups"]) == 1 and found["groups"][0]["total"] == "a1"
    assert roles(rows)["a2"] == "repeat" and rows[1]["group_id"] == rows[0]["group_id"], "the repeat folds into its total's group"
    assert rows[1]["relationship"] == "Same figure as #1 (slide 1); counted once"
    assert rows[1]["value_at_stake_arr"] is None and rows[1]["vas_reason"] == cg.VAS_REPEAT, "and adds no exposure"
    assert cg.counts(rows) == {"items": 1, "claims": 6, "groups": 1}
    assert cg.is_subordinate(rows[1]) and cg.is_ineligible(rows[1])


def test_a_conflict_between_parts_blocks_that_set_and_is_noted_on_the_total():
    parts = quarters([240_000, 250_000, 250_000, 260_000])
    rows = [annual(1_000_000), *parts, row("q99", 300_000, "2024-Q2", rank=99)]
    found = related(rows)
    assert found["groups"] == [] and found["conflicts"] == []
    assert rows[0]["relationship"] == "Quarters: a period is stated with figures that differ; kept as independent claims"


# --- 10. the data boundary of a group ---------------------------------------------------------------------------------------------

def test_a_saved_choice_holds_hashes_only_and_a_relationship_names_no_claim_id():
    rows = conflict_rows()
    review = related(rows)["reviews"][0]
    assert len(review["context"]) == 16 and all(len(c["identity"]) == 16 for c in review["candidates"])
    for r in rows:
        assert not r["relationship"] or not any(r2["claim_id"] in r["relationship"] for r2 in rows)


# --- 11. the contract: no engine field changes ---------------------------------------------------------------------------------------

def test_the_groups_add_three_register_fields_and_no_engine_output_field():
    from schemas import metrics
    assert cm.FIELDS[-3:] == ("group_id", "group_role", "relationship")
    assert metrics.CONTRACT_VERSION == 9, "the engine output is unchanged: results stored under contract 9 need no re-run"
    assert not {"group_id", "group_role", "relationship"} & set(metrics.MetricsPayload.model_fields)


# --- 12. the review of PR 187: gates, open questions, expiry, pending parts, repeats, labels --------------------------------------------

def test_a_group_item_whose_part_is_contradicted_has_that_parts_gate_as_its_key_gate():
    rows = register(copy.deepcopy(OFFSETTING))
    by_id = {r["claim_id"]: r for r in rows}
    assert by_id["c1"]["evidence_label"] == "Verified" and not by_id["c1"].get("gate_sentence")
    assert by_id["c4"]["evidence_label"] == "Contradicted" and by_id["c4"]["gate_sentence"]
    ver = verdict_mod.verdict(rows, engine_results(), None)
    five = ver["top5"]["in_force"]
    assert five == ["c1"]
    key = verdict_mod.key_gates(rows, five)
    assert [g["claim_id"] for g in key["gates"]] == ["c4"] and key["saved"] == 1
    marked = {r["claim_id"]: r["key_gate"] for r in verdict_mod.mark_key_gates(rows, five)}
    assert marked["c4"] is True and marked["c1"] is False
    thesis = verdict_mod.default_thesis({}, ver, key, str)
    assert "every selected claim is Verified" not in thesis["condition"] and thesis["condition"] == verdict_mod.gate_text(by_id["c4"])


def test_a_group_item_whose_members_are_all_verified_has_no_key_gate_and_the_thesis_says_so():
    rows = register([cand("c1", 187_700, "2023"), cand("c2", 44_845, "2023-Q1"), cand("c3", 46_204, "2023-Q2"),
                     cand("c4", 47_604, "2023-Q3"), cand("c5", 49_047, "2023-Q4")])
    ver = verdict_mod.verdict(rows, engine_results(), None)
    key = verdict_mod.key_gates(rows, ver["top5"]["in_force"])
    assert key["gates"] == [] and verdict_mod.default_thesis({}, ver, key, str)["condition"] == "No condition: every selected claim is Verified."


@pytest.mark.parametrize("question", [{"definition_check": "ask"}, {"turnover_state": "ask"}, {"growth_basis": "unknown"},
                                       {"evidence_label": "Unverified", "reason": "required field unknown: period"}])
def test_a_row_with_an_open_question_is_not_grouped_until_it_is_answered(question):
    answered = {"definition_check": "yes"} if "definition_check" in question else {"turnover_state": "answered"} if "turnover_state" in question \
        else {"growth_basis": "yoy"} if "growth_basis" in question else {"reason": "within ±5% of the claim", "evidence_label": "Verified"}
    for part in (0, 2):
        rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000])]
        rows[1 + part].update(question)
        found = related(rows)
        assert found["groups"] == [] and all(r["group_role"] is None for r in rows), f"{question}: its control stays on its own row"
        rows[1 + part].update(answered)
        assert [g["total"] for g in related(rows)["groups"]] == ["a1"], f"{question}: answered, it joins the group"
    total = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000])]
    total[0].update(question)
    assert related(total)["groups"] == [], "an annual total with a question is not a total yet"


def test_a_saved_total_choice_expires_when_the_parts_of_a_reconciling_set_are_edited():
    rows = conflict_rows()
    review = related(rows)["reviews"][0]
    choices = {review["id"]: {"kind": "total", "chosen": review["candidates"][0]["identity"], "context": review["context"]}}
    assert [c["state"] for c in related(conflict_rows(), choices)["conflicts"]] == ["chosen"]
    edited = conflict_rows()
    edited[5]["claimed_value"] = 510_000       # the quarters now sum to 1,250,000 and reconcile with the other figure, not the chosen one
    found = related(edited, choices)
    assert [c["state"] for c in found["conflicts"]] == ["open"], "the hint the analyst chose on has changed: it is a new question"
    assert {c["claim_id"]: c["hint"] for c in found["reviews"][0]["candidates"]}["a2"].startswith("quarters sum to")


def test_a_saved_total_choice_survives_an_edit_to_parts_outside_every_reconciling_set():
    rows = conflict_rows() + quarters([5, 6, 7, 8], year="2022", start_at=70)
    review = related(rows)["reviews"][0]
    choices = {review["id"]: {"kind": "total", "chosen": review["candidates"][0]["identity"], "context": review["context"]}}
    again = conflict_rows() + quarters([5, 6, 7, 9], year="2022", start_at=70)
    assert [c["state"] for c in related(again, choices)["conflicts"]] == ["chosen"]


CONFLICT_CLAIMS = [cand("c1", 187_700, "2023"), cand("c2", 250_000, "2023"), cand("c3", 44_845, "2023-Q1"), cand("c4", 46_204, "2023-Q2"),
                   cand("c5", 47_604, "2023-Q3"), cand("c6", 49_047, "2023-Q4"), cand("c7", 90_000, "2023-Q1", claim_type="costs")]


def test_while_an_annual_conflict_is_open_the_parts_of_its_reconciling_sets_take_no_top_five_slot_and_no_exposure():
    rows = register(copy.deepcopy(CONFLICT_CLAIMS))
    by_id = {r["claim_id"]: r for r in rows}
    for cid in ("c3", "c4", "c5", "c6"):
        assert by_id[cid]["group_role"] == "pending_part" and cg.is_ineligible(by_id[cid]) and not cg.is_subordinate(by_id[cid]), \
            "waiting parts stay visible in the register"
        assert by_id[cid]["value_at_stake_arr"] is None and by_id[cid]["vas_reason"] == cg.VAS_PENDING
    assert verdict_mod.proposal(rows) == ["c7"], "the unrelated claim is the only one left to select"
    assert by_id["c7"]["group_role"] is None


def test_the_waiting_parts_return_to_independent_claims_when_the_figure_chosen_has_no_parts():
    rows = register(copy.deepcopy(CONFLICT_CLAIMS))
    review = cg.relate(rows, fiscal_year_end=12)["reviews"][0]
    other = next(c for c in review["candidates"] if c["claim_id"] == "c2")["identity"]
    rows = register(copy.deepcopy(CONFLICT_CLAIMS), group_choices={review["id"]: {"kind": "total", "chosen": other, "context": review["context"]}})
    by_id = {r["claim_id"]: r for r in rows}
    assert by_id["c3"]["group_role"] is None and by_id["c3"]["vas_reason"].startswith("run-rate: "), "the conflict is settled: no longer waiting"
    assert by_id["c1"]["group_role"] == "alternative"


def test_the_parts_of_the_chosen_figure_become_a_group_when_the_conflict_is_settled():
    rows = register(copy.deepcopy(CONFLICT_CLAIMS))
    review = cg.relate(rows, fiscal_year_end=12)["reviews"][0]
    chosen = next(c for c in review["candidates"] if c["claim_id"] == "c1")["identity"]
    rows = register(copy.deepcopy(CONFLICT_CLAIMS), group_choices={review["id"]: {"kind": "total", "chosen": chosen, "context": review["context"]}})
    assert {r["claim_id"]: r["group_role"] for r in rows if r["claim_id"] in ("c1", "c3", "c6")} == {"c1": "total", "c3": "part", "c6": "part"}


def test_the_same_annual_figure_stated_twice_folds_into_one_row_also_when_no_group_forms():
    rows = [annual(1_000_000, cid="a1"), annual(1_005_000, cid="a2", rank=2, page_ref="slide 8")]
    found = related(rows)
    assert found["groups"] == [] and found["conflicts"] == []
    assert roles(rows) == {"a1": None, "a2": "repeat"}
    assert rows[0]["group_id"] and rows[0]["group_id"] == rows[1]["group_id"], "the lead and its repeat share an id, so the screen can show both sources"
    assert rows[1]["relationship"] == "Same figure as #1 (slide 1); counted once"
    assert rows[1]["value_at_stake_arr"] is None and rows[1]["vas_reason"] == cg.VAS_REPEAT
    assert cg.counts(rows) == {"items": 1, "claims": 2, "groups": 0}
    assert not cg.is_ineligible(rows[0]) and cg.is_ineligible(rows[1])


def test_a_conflict_candidate_stated_twice_folds_and_the_question_still_lists_both_statements():
    rows = [annual(1_000_000, cid="a1"), annual(1_004_000, cid="a3", rank=3, page_ref="slide 9"), annual(1_250_000, cid="a2", rank=2), *quarters([240_000, 250_000, 250_000, 260_000])]
    found = related(rows)
    assert roles(rows)["a3"] == "repeat" and roles(rows)["a1"] == "candidate" and roles(rows)["a2"] == "candidate"
    assert rows[0]["group_id"] == rows[1]["group_id"] != rows[2]["group_id"], "each statement folds with its own lead, not with the other candidate"
    review = found["reviews"][0]
    assert [c["claim_ids"] for c in review["candidates"]] == [["a1", "a3"], ["a2"]]
    assert cg.counts(rows) == {"items": 6, "claims": 7, "groups": 0}


def test_a_part_stated_twice_folds_into_its_group_too():
    rows = [annual(1_000_000), *quarters([240_000, 250_000, 250_000, 260_000]), row("q99", 250_500, "2024-Q2", rank=99, page_ref="slide 12")]
    found = related(rows)
    assert [g["total"] for g in found["groups"]] == ["a1"]
    repeat = rows[-1]
    assert repeat["group_role"] == "repeat" and repeat["group_id"] == rows[0]["group_id"]
    assert repeat["relationship"] == "Same figure as #11 (slide 11); counted once" and repeat["value_at_stake_arr"] is None
    assert cg.counts(rows) == {"items": 1, "claims": 6, "groups": 1}


def test_a_contradicted_figure_stated_twice_is_listed_once():
    rows = [annual(1_000_000, cid="a1"), annual(1_005_000, cid="a2", rank=2)]
    for r in rows:
        r.update(evidence_label="Contradicted", gloss="€4,000 lower (miss)", observed_source={"file": "rev.xlsx"})
    related(rows)
    assert [o["claim_id"] for o in verdict_mod.other_contradictions(rows, [])] == ["a1"]


def test_a_passed_over_contradicted_figure_is_not_listed_with_the_other_contradictions():
    rows = conflict_rows()
    review = related(rows)["reviews"][0]
    choices = {review["id"]: {"kind": "total", "chosen": review["candidates"][0]["identity"], "context": review["context"]}}
    rows = conflict_rows()
    rows[1].update(evidence_label="Contradicted", gloss="€250,000 higher (beat)", observed_source={"file": "rev.xlsx"})
    found = related(rows, choices)
    assert rows[1]["group_role"] == "alternative"
    assert verdict_mod.other_contradictions(rows, []) == [], "it is listed once, under Unresolved conflicts"
    assert [c["state"] for c in found["conflicts"]] == ["chosen"]


def test_grouping_keys_on_the_metric_not_on_the_claim_type():
    total = annual(2_000_000, claim_type="revenue", metric="ARR")             # "ARR FY2024" typed as revenue
    observation = row("d1", 2_010_000, "2024-12", claim_type="arr", metric="ARR")      # "Dec 2024 ARR" typed as arr
    rows = [total, observation]
    assert [g["total"] for g in related(rows)["groups"]] == ["a1"] and roles(rows) == {"a1": "total", "d1": "part"}
    other = [annual(2_000_000, claim_type="revenue", metric=None), row("d1", 2_010_000, "2024-12", claim_type="costs", metric=None)]
    assert related(other)["groups"] == [], "with no metric the claim type still tells revenue from costs"
