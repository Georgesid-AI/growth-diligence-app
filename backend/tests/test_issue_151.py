"""Issue #151, from the artefact (a KPI panel with "MRR (SaaS) in 2021 = €27K" and "2021 Revenue =€501K (64% SaaS)": the first was typed
Revenue, read as FY2021, and flagged as a deck inconsistency against the second). One failing test per point, synthetic page only
(CLAUDE.md rules 13 and 15):

a a figure whose own label holds MRR or ARR is typed MRR or ARR, never Revenue, in the rules read and the panel read; a contracted or
  committed MRR or ARR stays Contract value · b "MRR in 2021" (or ARR in a year) is read as Dec 2021 and the row notes it; the analyst
  can change it · c figures of different metrics are never compared for deck inconsistency."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from claim_matching_support import engine_results  # noqa: E402,F401
from pdf_support import pdf_page  # noqa: E402
from test_claim_matching import RUNS, results_for, settings  # noqa: E402

import server  # noqa: E402
from app import claim_matching as cm  # noqa: E402
from app.decks import claims  # noqa: E402
from app.decks.parser import parse_deck  # noqa: E402
from app.structures import candidate_from_item, items, verify  # noqa: E402

MRR_LINE = "MRR (SaaS) in 2021 = €27K"
REVENUE_LINE = "2021 Revenue =€501K (64% SaaS)"
NOTE = "period read as Dec 2021 from 'in 2021'"


def deck(*lines):
    texts = [(50, 560, 20, "Traction")] + [(50, 400 - 40 * i, 12, line) for i, line in enumerate(lines)]
    return parse_deck(pdf_page(texts, []), "deck.pdf")


def found(*lines, periods=None):
    """The rules read's money candidates (not the 64% share) by value."""
    return {c["value"]: c for c in claims.detect_candidates(deck(*lines)["blocks"], "deck.pdf") if c["unit"] != "%"}


def panel_read(*lines, periods=None):
    """The panel read: every figure revenue with the period the model gave, as approval rows."""
    structure, = [s for s in deck(*lines)["structures"] if s["type"] == "kpi_panel"]
    listed = items.list_items(structure)
    labels = [{"item": i["id"], "metric": "revenue", "period": (periods or ["FY2021"] * 9)[n], "unit": "%" if i["raw"].endswith("%") else "EUR", "unit_other": None,
               "actual_or_forecast": "actual"} for n, i in enumerate(listed["items"])]
    checked = verify.verify(structure, listed, labels, (), 12, "suggest")["items"]
    rows = [candidate_from_item(i, structure, {"file": "deck.pdf", "blocks": []}, "kpi_panel", 12) for i in checked]
    return {r["value"]: r for r in rows if r["unit"] != "%"}


def register_of(*candidates):
    for n, c in enumerate(candidates, 1):
        c.update(id=f"c{n}", status="approved", file="deck.pdf", order=n)
        claims.resolve_period(c, 12)
    run = RUNS["A"]
    return cm.build_register(list(candidates), results_for(run), settings(run))


READS = {"rules": found, "panel": panel_read}


# ---------------------------------------------------------------------------
# a. MRR and ARR are typed MRR and ARR, never Revenue
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("read", READS)
@pytest.mark.parametrize("line, word", [(MRR_LINE, "MRR"), ("ARR (SaaS) in 2021 = €27K", "ARR"), ("ARR in 2021: €27K", "ARR")])
def test_a_a_figure_labelled_mrr_or_arr_is_typed_so_never_revenue(read, line, word):
    c = READS[read](line, REVENUE_LINE)[27000]
    assert claims.deck_label(c) == word
    assert register_of(c)[0]["metric"] == word


def test_a_the_spelled_out_form_is_typed_too():
    assert claims.deck_label(found("Monthly recurring revenue in 2021 = €27K")[27000]) == "MRR"
    assert claims.deck_label(found("Annual recurring revenue in 2021 = €27K")[27000]) == "ARR"


@pytest.mark.parametrize("read", READS)
def test_a_the_revenue_figure_beside_it_stays_revenue(read):
    assert claims.deck_label(READS[read](MRR_LINE, REVENUE_LINE)[501000]) == "Revenue"


@pytest.mark.parametrize("read", READS)
@pytest.mark.parametrize("line", ["Contracted MRR in 2021 = €27K", "Committed ARR in 2021 = €27K"])
def test_a_a_contracted_or_committed_mrr_or_arr_stays_contract_value(read, line):
    c = READS[read](line, REVENUE_LINE)[27000]
    assert claims.deck_label(c) == claims.CONTRACT_LABEL
    assert register_of(c)[0]["metric"] == cm.CONTRACT_VALUE


def test_a_a_bracketed_contracted_mrr_stays_contract_value():
    c = found("MRR (contracted) in 2021 = €27K", REVENUE_LINE)[27000]      # too wide for the test panel's box: the rules read only
    assert claims.deck_label(c) == claims.CONTRACT_LABEL and register_of(c)[0]["metric"] == cm.CONTRACT_VALUE


# ---------------------------------------------------------------------------
# b. "MRR in 2021" is Dec 2021
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("read", READS)
@pytest.mark.parametrize("line, year", [(MRR_LINE, "2021"), ("ARR (SaaS) in 2022 = €27K", "2022")])
def test_b_mrr_or_arr_in_a_year_takes_december_and_the_row_notes_it(read, line, year):
    c = READS[read](line, REVENUE_LINE, periods=[f"FY{year}"] * 3)[27000]
    assert (c["target_date"], c["period_start"], c["period_end"]) == (f"{year}-12", f"{year}-12-01", f"{year}-12-31"), c
    note = f"period read as Dec {year} from 'in {year}'"
    assert c["period_read_note"] == note
    row = register_of(c)[0]
    assert row["period_note"] == note and row["period_start"] == f"{year}-12-01"


@pytest.mark.parametrize("read", READS)
def test_b_revenue_in_a_year_and_mrr_without_in_keep_the_year(read):
    c = READS[read]("Revenue in 2021 = €27K", "MRR 2021 = €9K")
    assert c[27000]["target_date"] == "2021" and not c[27000].get("period_read_note")
    assert c[9000]["target_date"] == "2021" and not c[9000].get("period_read_note")


def test_b_a_month_the_deck_states_is_not_moved():
    c = found("MRR in Jun 2021 = €27K")[27000]
    assert c["target_date"] == "2021-06" and not c.get("period_read_note")


def test_b_the_analyst_changes_the_period_and_the_note_goes():
    c = found(MRR_LINE)[27000]
    edited = server._edited_period({**c, "target_date": "2021-06"}, c, 12)
    assert edited["period_start"] == "2021-06-01" and edited["period_read_note"] is None
    assert server._period_fields(edited)["period_read_note"] is None
    kept = server._edited_period({**c}, c, 12)
    assert kept["period_read_note"] == NOTE


# ---------------------------------------------------------------------------
# c. Different metrics are never compared for a deck inconsistency
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("read", READS)
@pytest.mark.parametrize("line", [MRR_LINE, "MRR in 2021 = €27K", "ARR (SaaS) in 2021 = €27K"])
def test_c_monthly_mrr_is_not_a_deck_inconsistency_against_annual_revenue(read, line):
    got = READS[read](line, REVENUE_LINE)
    if read == "panel":                  # the panel read's rows meet the check the register runs over stored candidates
        pairs = claims.cross_deck_inconsistencies(list(got.values()))
        assert pairs == []
    else:
        assert [c["inconsistent_dates"] for c in got.values()] == [[], []], got
        assert claims.cross_deck_inconsistencies(list(got.values())) == []


def test_c_two_different_mrr_figures_for_one_month_are_still_an_inconsistency():
    got = found("MRR in 2021 = €27K", "ARR 2021 = €9K", "MRR in 2021 = €30K")
    assert got[27000]["inconsistent_dates"] and got[30000]["inconsistent_dates"]
    assert not got[9000]["inconsistent_dates"]
