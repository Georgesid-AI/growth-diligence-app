"""Finding D of 20 Oct, from the artefact: a bar chart on a deck page titled "Average Revenue Per Account", one bar per year
(2019-2022) with its value as the bar label, gave Revenue claims matched against engine revenue; the same page held a pipeline table
with the columns "Size of opportunity" and "Weighted in forecast". Decisions of 20 Oct (George): a chart or table title with "per
account", "per user", "per client", "per customer", "ARPA" or "ARPU" types its figures as unit economics (ARPA, ARPU), Unsupported, never
matched, no value at stake, out of the top 5; the amounts of the pipeline columns are Pipeline, never Revenue or Bookings.
Synthetic page only (CLAUDE.md rules 13 and 15)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from claim_matching_support import engine_results  # noqa: E402,F401
from pdf_support import pdf_page, ruled_table  # noqa: E402
from test_claim_matching import RUNS, results_for, settings  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import verdict as vd  # noqa: E402
from app.decks import claims  # noqa: E402
from app.decks.parser import parse_deck  # noqa: E402

BARS = (("2019", "$1,100"), ("2020", "$1,250"), ("2021", "$1,400"), ("2022", "$1,650"))


def page(title, pipeline_headers=("Opportunity", "Size of opportunity", "Weighted in forecast")):
    texts = [(50, 560, 22, title)]
    for i, (year, label) in enumerate(BARS):
        texts += [(90 + 150 * i, 380, 12, label), (90 + 150 * i, 340, 12, year)]
    table, rects = ruled_table([pipeline_headers, ("Deal A", "$500,000", "$250,000"), ("Deal B", "$800,000", "$320,000")],
                               top=260, col_widths=(200, 270, 270))
    return parse_deck(pdf_page(texts + table, rects), "deck.pdf")


def detect(title, **kw):
    return claims.detect_candidates(page(title, **kw)["blocks"], "deck.pdf")


def values_of(found, family):
    return sorted(v["value"] for c in found if c["claim_type"] == family for v in claims.claim_values(c))


def test_the_bars_of_a_per_account_chart_are_arpa_with_their_years_and_never_revenue():
    found = detect("Average Revenue Per Account")
    assert values_of(found, "arpa") == [1100, 1250, 1400, 1650]
    assert not any(c["claim_type"] == "revenue" for c in found)
    assert {(c["value"], c["period_text"]) for c in found if c["claim_type"] == "arpa"} == \
        {(float(v.strip("$").replace(",", "")), y) for y, v in BARS}


@pytest.mark.parametrize("title, family", [
    ("Revenue per user", "arpu"), ("ARPU", "arpu"), ("Average Revenue per Customer", "arpa"), ("Revenue per client by year", "arpa"),
    ("ARPA by year", "arpa"), ("Monthly revenue per account", "arpa"), ("Revenue Per User", "arpu")])
def test_a_title_with_a_per_unit_term_types_the_bars_as_that_unit_economics_metric(title, family):
    found = detect(title)
    assert values_of(found, family) == [1100, 1250, 1400, 1650]
    assert not any(c["claim_type"] in ("revenue", "revenue_growth") for c in found)


def test_a_title_without_the_term_still_reads_revenue():
    found = detect("Revenue by year")
    assert values_of(found, "revenue") == [1100, 1250, 1400, 1650]
    assert not any(c["claim_type"] in ("arpa", "arpu") for c in found)


def test_the_pipeline_table_under_a_per_account_title_is_pipeline_never_revenue_bookings_or_arpa():
    found = detect("Average Revenue Per Account")
    assert values_of(found, "pipeline") == [250000, 320000, 500000, 800000]
    assert not any(c["claim_type"] in ("revenue", "arpa") and v["value"] >= 250000 for c in found for v in claims.claim_values(c))


def test_the_pipeline_columns_are_pipeline_even_under_a_bookings_title():
    found = detect("Bookings outlook")
    assert values_of(found, "pipeline") == [250000, 320000, 500000, 800000]


def register_of(title):
    found = detect(title)
    for n, c in enumerate(found, 1):
        c.update(id=f"c{n}", status="approved", file="deck.pdf", order=n)
        claims.resolve_period(c, 12)
    run = RUNS["A"]
    return found, cm.build_register(found, results_for(run), settings(run))


def test_arpa_and_pipeline_claims_are_unsupported_unmatched_unranked_and_have_no_value_at_stake():
    found, rows = register_of("Average Revenue Per Account")
    kinds = {c["id"]: c["claim_type"] for c in found}
    arpa = [r for r in rows if kinds[r["claim_id"].split("#")[0]] == "arpa"]
    pipeline = [r for r in rows if kinds[r["claim_id"].split("#")[0]] == "pipeline"]
    assert len(arpa) == 4 and len(pipeline) == 4
    for r in arpa + pipeline:
        assert (r["evidence_label"], r["observed_value"], r["value_at_stake_arr"]) == ("Unsupported", None, None)
    assert {r["metric"] for r in arpa} == {"ARPA"} and {r["reason"] for r in arpa} == {cm.UNIT_ECONOMICS_REASON}
    assert not any(r["gate_needed"] for r in arpa)
    top5 = vd.proposal(rows)
    assert top5 == [], "ARPA and pipeline rows are never in the top 5 (George, 2026-10-20)"
    assert all(cm.is_untested(r) for r in arpa + pipeline)
    assert cm.UNIT_ECONOMICS_REASON == "Unit economics – not computed by the app"
    assert not any(r["claim_type"] == "revenue" for r in rows)


def test_arpa_and_arpu_are_metrics_that_are_never_computed():
    assert cm.METRICS["ARPA"]["unit"] == cm.METRICS["ARPU"]["unit"] == "currency"
    assert cm.propose_metric("arpa", "currency", "Average Revenue Per Account") == "ARPA"
    assert cm.propose_metric("arpu", "currency", "Revenue per user") == "ARPU"
    assert cm.propose_metric("revenue", "currency", "Revenue per user") in (None, "Revenue")
    assert "ARPA" not in cm.EVIDENCE and "ARPU" not in cm.EVIDENCE


# --- Review of 20 Oct: the per-unit term must END the phrase; breakdowns stay Revenue ---------------------------------------------

@pytest.mark.parametrize("title", [
    "Revenue per customer segment", "Revenue per client type", "Revenue per customer cohort", "Revenue per user group",
    "Revenue per account manager", "Revenue per segment", "Revenue by customer segment"])
def test_a_breakdown_title_with_a_noun_after_the_per_unit_term_stays_revenue(title):
    found = detect(title)
    assert values_of(found, "revenue") == [1100, 1250, 1400, 1650]
    assert not any(c["claim_type"] in ("arpa", "arpu") for c in found)


@pytest.mark.parametrize("title, family", [
    ("ARR per customer", "arpa"), ("Average revenue per paying customer", "arpa"), ("Average revenue per active user", "arpu"),
    ("Revenue / customer", "arpa"), ("Revenue / user", "arpu"), ("MRR per account", "arpa"), ("Bookings per client", "arpa"),
    ("Revenue per customer (EUR)", "arpa"), ("Revenue per customer, by year", "arpa"), ("Average revenue per customer segment", "arpa")])
def test_the_per_unit_variants_are_arpa_or_arpu(title, family):
    found = detect(title)
    assert values_of(found, family) == [1100, 1250, 1400, 1650]
    assert not any(c["claim_type"] == "revenue" for c in found)


def test_a_line_with_arr_per_customer_is_arpa_and_a_count_per_account_is_not():
    assert [c["claim_type"] for c in claims.line_candidates("€45k ARR per customer", [(0, 21, {})])] == ["arpa"]
    for line in ("Licences per customer", "Seats per account: 42", "Users per account: 12"):
        assert not any(c["claim_type"] in ("arpa", "arpu") for c in claims.line_candidates(line, [(0, len(line), {})])), line


def table_values(header, rows, family):
    table, rects = ruled_table([("Name", header)] + rows, top=400, col_widths=(200, 270))
    found = claims.detect_candidates(parse_deck(pdf_page([(50, 560, 22, "Overview")] + table, rects), "deck.pdf")["blocks"], "deck.pdf")
    return sorted(v["value"] for c in found if c["claim_type"] == family for v in claims.claim_values(c)), found


def test_a_revenue_per_client_column_over_rows_that_name_clients_is_revenue_not_arpa():
    values, found = table_values("Revenue per client", [("Acme", "$500,000"), ("Beta", "$800,000")], "revenue")
    assert values == [500000, 800000]
    assert not any(c["claim_type"] in ("arpa", "arpu") for c in found)


def test_a_revenue_per_client_column_over_rows_that_are_years_is_still_arpa():
    values, _ = table_values("Revenue per client", [("2021", "$1,400"), ("2022", "$1,650")], "arpa")
    assert values == [1400, 1650]


def test_under_a_pipeline_column_every_row_is_pipeline_whatever_its_row_label_says():
    """Review L3, decision of 20 Oct (George): "ARR expansion Acme" and "Bookings renewal Beta" under "Size of opportunity" are Pipeline."""
    table, rects = ruled_table([("Opportunity", "Size of opportunity"), ("ARR expansion Acme", "$500,000"), ("Bookings renewal Beta", "$800,000")],
                               top=400, col_widths=(300, 270))
    found = claims.detect_candidates(parse_deck(pdf_page([(50, 560, 22, "Overview")] + table, rects), "deck.pdf")["blocks"], "deck.pdf")
    assert values_of(found, "pipeline") == [500000, 800000]
    assert not any(c["claim_type"] in ("revenue", "arpa") for c in found)
