"""Claim grouping and card noise (George, 2026-10-27): the page reader's segment, period slices, an oversize slice, populations, the flags that
are only notes, the title that is no label, and the blank period a dated heading fills. Synthetic pages and decks only (CLAUDE.md rule 15).
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from test_segment_partitions import TOTAL, by_id, cand, register, roles  # noqa: E402

from app import claim_groups as cg  # noqa: E402
from app import claim_matching as cm  # noqa: E402
from app import verdict as verdict_mod  # noqa: E402

COUNTRIES = ["Germany", "France", "Spain", "Italy", "Poland", "Sweden", "Norway", "Austria"]


def slices(names, values, period="FY2024", slide=4, **over):
    """Figures of one metric and period that differ in the segment the page reader printed, with no cited label."""
    return [cand(f"c{i + 2}", v, period, None, slide=slide, page_segment=name, **over) for i, (name, v) in enumerate(zip(names, values))]


# --- 1. the segment the page reader printed ------------------------------------------------------------------------------------

def test_eight_country_slices_with_no_total_are_one_group_of_their_own_and_out_of_the_five():
    rows = register(slices(COUNTRIES, [100_000 + 1_000 * i for i in range(8)]))
    found = cg.relate(rows)
    assert found["reviews"] == [] and found["conflicts"] == [], "different segments are slices, never rivals"
    assert {r["segment"] for r in rows} == set(COUNTRIES) and {r["segment_set_by"] for r in rows} == {"python"}
    assert set(roles(rows).values()) == {cg.SLICE} and len({r["group_id"] for r in rows}) == 1
    assert all(cg.is_ineligible(r) for r in rows) and verdict_mod.sortable(rows) == []
    assert "no company total stated" in rows[0]["relationship"] and "8 segments" in rows[0]["relationship"]


def test_a_lone_segment_and_a_segment_beside_a_stated_total_that_reconciles_are_not_a_slice_group():
    assert set(roles(register(slices(["Germany"], [100_000]))).values()) == {None}
    got = roles(register([TOTAL, *slices(["Product A", "Product B"], [600_000, 400_000], slide=4)]))
    assert got == {"c1": "total", "c2": "segment_part", "c3": "segment_part"}


def test_slices_that_sum_to_a_total_on_the_same_deck_sit_under_it_with_no_exposure_of_their_own():
    rows = register([TOTAL, *slices(["Product A", "Product B"], [600_000, 400_000])])
    got = by_id(rows)
    assert roles(rows) == {"c1": "total", "c2": "segment_part", "c3": "segment_part"}
    assert got["c2"]["value_at_stake_arr"] is None and got["c1"]["value_at_stake_arr"] == 1_000_000
    assert verdict_mod.sortable(rows) == [got["c1"]]


def test_slices_do_not_sit_under_a_total_of_another_deck():
    other = cand("c9", 1_000_000, "FY2024", "Total revenue", file="other_deck.pptx", sources=[{"file": "other_deck.pptx", "slide": 2}])
    rows = register([other, *slices(["Product A", "Product B"], [600_000, 400_000])])
    assert roles(rows)["c2"] == cg.SLICE and roles(rows)["c9"] is None


def test_the_page_segment_wins_over_the_label_and_the_analyst_over_both():
    row = register([cand("c1", 600_000, "FY2024", "Product A", page_segment="Enterprise")])[0]
    assert row["segment"] == "Enterprise"
    row = register([cand("c1", 600_000, "FY2024", "Product A", page_segment="Enterprise", claim_inputs={"c1": {"segment": "SMB"}})])[0]
    assert (row["segment"], row["segment_set_by"]) == ("SMB", "analyst")


@pytest.mark.parametrize("printed", ["Q1", "Q3 2024", "H2", "January", "FY2024", "Total", "Whole company", "Product", None, ""])
def test_a_page_segment_that_names_a_period_the_company_or_a_dimension_only_is_no_segment(printed):
    assert register([cand("c1", 250_000, "2024-Q1", "Total revenue", page_segment=printed)])[0]["segment"] == cm.WHOLE


# --- 2. period slices -------------------------------------------------------------------------------------------------------------

def test_four_quarters_that_sum_to_a_forecast_year_sit_under_it_and_read_no_segment_nor_run_rate():
    year = cand("c1", 1_000_000, "2030", "Total revenue", slide=3, basis="projection")
    quarters = [cand(f"c1{i}", v, f"2030-Q{i + 1}", "Total revenue", slide=5, basis="projection", page_segment=f"Q{i + 1}")
                for i, v in enumerate([240_000, 250_000, 250_000, 260_000])]
    rows = register([year, *quarters])
    got = by_id(rows)
    assert roles(rows)["c1"] == "total" and {roles(rows)[f"c1{i}"] for i in range(4)} == {"part"}
    for i in range(4):
        r = got[f"c1{i}"]
        assert r["segment"] == cm.WHOLE and "segment not in the data" not in (r["reason"] or "")
        assert r["value_at_stake_arr"] is None and r["vas_reason"] == cg.VAS_IN_TOTAL and "run-rate" not in (r["vas_reason"] or "")
    assert verdict_mod.sortable(rows) == [got["c1"]]


# --- 3. a slice larger than the company total ---------------------------------------------------------------------------------------

def test_one_channel_larger_than_the_total_raises_one_card_and_no_slice_is_an_independent_claim():
    rows = register([TOTAL, *slices(["Direct", "Partners", "Online"], [1_300_000, 200_000, 100_000])])
    found = cg.relate(rows)
    card, = found["reviews"]
    assert card["kind"] == cg.KIND_SIZE and card["reason"] == "Segment larger than the company total; check what this figure is"
    assert sorted(c["claim_id"] for c in card["candidates"]) == ["c2", "c3", "c4"] and found["conflicts"] == []
    assert roles(rows) == {"c1": None, "c2": "slice", "c3": "slice", "c4": "slice"}
    assert verdict_mod.sortable(rows) == [by_id(rows)["c1"]]
    assert "larger than the company total" in by_id(rows)["c2"]["relationship"]


def test_slices_within_the_total_raise_no_card():
    assert cg.relate(register([TOTAL, *slices(["Direct", "Partners"], [900_000, 100_000])]))["reviews"] == []


# --- 4. customers: the population the label or the segment names -------------------------------------------------------------------

def clients(cid, value, label=None, **over):
    return cand(cid, value, "FY2024", label, claim_type="customers", currency=None, unit="count", snippet=f"{value} clients", **over)


def test_75_paying_clients_and_161_all_clients_are_two_populations_not_a_conflict():
    rows = register([clients("c1", 75, "Paying clients", slide=3), clients("c2", 161, "All clients", slide=4)])
    found = cg.relate(rows)
    assert found["reviews"] == [] and found["conflicts"] == [], "different populations are never a conflict"
    assert [r["population"] for r in rows] == ["paying", "all"] and roles(rows) == {"c1": None, "c2": None}


@pytest.mark.parametrize("label, segment, population", [
    ("Paying clients", None, "paying"), ("Registered users", None, "registered"), ("Free accounts", None, "free"),
    ("Trial users", None, "trial"), ("Active users", None, "active"), ("All clients", None, "all"),
    (None, "Free", "free"), ("Clients", "Trial", "trial"), (None, None, "paying"),
])
def test_a_population_named_in_the_label_or_the_segment_sets_the_population_and_is_no_segment(label, segment, population):
    row = register([clients("c1", 75, label, page_segment=segment)])[0]
    assert row["population"] == population and row["segment"] == cm.WHOLE


# --- page reads: the heading fill, the notes and the title that is no label ---------------------------------------------------------

import test_checker as tc  # noqa: E402
import test_claim_corrections as cc  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402
from app.structures import checker  # noqa: E402


def lines(n, first=500):
    return [(50, first - 20 * i, 12, f"{100 + 10 * i} Paying Users") for i in range(n)]


def test_six_undated_figures_under_a_dated_heading_take_its_year_and_raise_no_card():
    parsed = tc.deck([(50, 560, 20, "2021 KEY PERFORMANCE INDICATORS"), *lines(6)])
    page = [tc.claim(cc.at(parsed, text), 100 + 10 * i, metric="customers", unit="count") for i, (_, _, _, text) in enumerate(lines(6))]
    rows, _ = cc.read(parsed, *page)
    assert len(rows) == 6
    for row in rows:
        assert row["target_date"] == "2021" and row["period_start"] == "2021-01-01" and row["period_end"] == "2021-12-31"
        assert row["flags"] == [checker.PERIOD_FROM_HEADING] and not checker.review_flags(row["flags"]), "informational: no card"


def test_a_heading_that_states_two_periods_or_none_fills_nothing():
    two = tc.deck([(50, 580, 20, "2021 KEY PERFORMANCE INDICATORS"), (50, 560, 20, "2022 OUTLOOK"), *lines(1, 480)])
    item = tc.one(two, tc.claim(cc.at(two, lines(1, 480)[0][3]), 100, metric="customers", unit="count"))
    assert item["period"] is None and checker.PERIOD_FROM_HEADING not in item["flags"]
    plain = tc.deck([(50, 560, 20, "KEY PERFORMANCE INDICATORS"), *lines(1)])
    assert tc.one(plain, tc.claim(cc.at(plain, lines(1)[0][3]), 100, metric="customers", unit="count"))["period"] is None


def test_the_figures_own_period_beats_the_heading():
    parsed = tc.deck([(50, 560, 20, "2021 KEY PERFORMANCE INDICATORS"), (50, 500, 12, "120 Paying Users in 2023")])
    item = tc.one(parsed, tc.claim(cc.at(parsed, "120 Paying Users in 2023"), 120, metric="customers", unit="count"))
    assert checker.PERIOD_FROM_HEADING not in item["flags"] and item["period"] is None, "a figure with a period of its own is left to its own source"


TWO_HEADINGS = [(50, 580, 20, "2021 KEY PERFORMANCE INDICATORS"), (50, 555, 20, "2022 OUTLOOK"), (50, 480, 12, "800 Paying Users")]


def ambiguous(**more):
    parsed = tc.deck(TWO_HEADINGS)
    first = next(t for _, _, _, t in TWO_HEADINGS if t.startswith("2021"))
    claim_ = tc.claim(cc.at(parsed, "800 Paying Users"), 800, metric="customers", unit="count", period="2021", period_cell=cc.at(parsed, first))
    claim_.update({"label_text": None, "segment": None, "share_of": None, "is_quote": None, **more})
    return parsed, claim_


def test_more_than_one_period_fits_is_a_card_without_label_text_and_a_note_with_label_text_and_a_period():
    parsed, claim_ = ambiguous()
    assert checker.SOURCE_AMBIGUOUS in tc.one(parsed, claim_)["flags"]
    parsed, claim_ = ambiguous(label_text="Paying users")
    item = tc.one(parsed, claim_)
    assert checker.SOURCE_AMBIGUOUS not in item["flags"] and checker.SOURCE_AMBIGUOUS_NOTED in item["flags"]
    assert not checker.review_flags(item["flags"]) and not item["corrections"], "informational: no card, no choice"
    rows, _ = cc.read(parsed, claim_)
    row, = rows
    assert row["target_date"] == "2021" and not checker.review_flags(row["flags"]) and not row.get("corrections")


def test_the_period_notes_are_informational_with_label_text_and_a_period():
    assert {checker.PERIOD_FROM_HEADING, checker.PERIOD_FROM_OTHER_CELL, checker.SOURCE_AMBIGUOUS_NOTED} <= set(checker.INFORMATIONAL_FLAGS)
    assert checker.SOURCE_AMBIGUOUS not in checker.INFORMATIONAL_FLAGS, "without both, a competing source is still a question"
    for flag in (checker.PERIOD_FROM_HEADING, checker.PERIOD_FROM_OTHER_CELL, checker.SOURCE_AMBIGUOUS_NOTED):
        assert deck_claims.is_informational(flag)


def test_a_title_cited_as_the_label_is_no_label_and_asks():
    parsed = tc.deck([tc.TITLE, (50, 500, 12, "800 Paying Users")])
    claim_ = tc.claim(cc.at(parsed, "800 Paying Users"), 800, metric="customers", unit="count", label_cell=cc.at(parsed, "Traction"))
    item = tc.one(parsed, claim_)
    assert item["label_cell"] is None and checker.NO_LABEL in item["flags"] and checker.LABEL_MISMATCH not in item["flags"]
    row, = cc.read(parsed, claim_)[0]
    assert row["label_from"] is None and checker.NO_LABEL in row["flags"] and checker.NO_LABEL in checker.REVIEW_FLAGS
    said = {**claim_, "label_text": "Paying users", "label_cell": cc.at(parsed, "Traction"), "segment": None, "share_of": None, "is_quote": None}
    row, = cc.read(parsed, said)[0]
    assert row["label_from"] == "Paying users" and checker.NO_LABEL not in row["flags"], "the page reader's own label stands"


# --- 6. undated figures on one page: one card ---------------------------------------------------------------------------------------

def undated(cid, page=3, **extra):
    return {"id": cid, "status": "pending", "claim_type": "revenue", "value": 200000, "value_high": None, "unit": None, "currency": "EUR",
            "target_date": None, "period_text": None, "snippet": f"ARR of €200,000 {cid}", "label_from": None, "file": "deck.pptx", "order": 0,
            "sources": [{"file": "deck.pptx", "page": page}], **extra}


def test_undated_figures_of_one_page_are_one_question_and_a_lone_one_stays_its_own(run_api):
    import test_claims_enter_on_their_own as own
    own.prepared(run_api, *[undated(f"u{i}") for i in range(6)], undated("lone", page=9))
    own.stage(run_api, "claims")
    attention = {q["id"]: q for q in run_api.get(f"/api/audits/{own.AUDIT}/decks").json()["attention"]}
    assert {attention[f"u{i}"]["undated"]["key"] for i in range(6)} == {attention["u0"]["undated"]["key"]}
    assert all(attention[f"u{i}"]["undated"]["n"] == 6 for i in range(6)) and "undated" not in attention["lone"]
    assert attention["lone"]["set"] == cm.PERIOD_NOT_READ


def test_keep_undated_closes_the_question_and_leaves_the_claim_undated(run_api):
    import test_claims_enter_on_their_own as own
    own.prepared(run_api, *[undated(f"u{i}") for i in range(3)])
    own.stage(run_api, "claims")
    ids = [f"u{i}" for i in range(3)]
    assert run_api.put(f"/api/audits/{own.AUDIT}/undated-periods", json={"claim_ids": ids}).json() == {"kept": 3}
    assert run_api.get(f"/api/audits/{own.AUDIT}/decks").json()["attention"] == []
    row = own.registered(run_api)["u0"]
    assert row["reason"] == cm.PERIOD_NOT_READ and row["period"] is None, "kept undated: still Unverified, no period invented"


def test_one_date_set_on_every_undated_figure_closes_the_question(run_api):
    import test_claims_enter_on_their_own as own
    own.prepared(run_api, *[undated(f"u{i}") for i in range(3)])
    own.stage(run_api, "claims")
    for i in range(3):
        assert run_api.put(f"/api/audits/{own.AUDIT}/decks/candidates/u{i}", json={"target_date": "2024-02"}).status_code == 200
    assert run_api.get(f"/api/audits/{own.AUDIT}/decks").json()["attention"] == []


def test_a_card_that_asks_what_a_figure_is_has_no_figure_to_choose(run_api):
    import test_claims_enter_on_their_own as own
    year = {"target_date": "2024", "period_text": "FY2024", "sources": [{"file": "deck.pptx", "page": 3}]}
    own.prepared(run_api, own.claim("t", value=1_000_000, **year),
                 own.claim("s1", value=1_300_000, page_segment="Direct", **year), own.claim("s2", value=200_000, page_segment="Partners", **year))
    own.stage(run_api, "claims")
    body = run_api.get(f"/api/audits/{own.AUDIT}/claims").json()
    card, = body["reviews"]
    assert card["kind"] == cg.KIND_SIZE and body["conflicts"] == []
    assert run_api.put(f"/api/audits/{own.AUDIT}/claim-groups/{card['id']}", json={"choice": card["candidates"][0]["identity"]}).status_code == 400
