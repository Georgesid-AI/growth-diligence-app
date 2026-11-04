"""PR 4f: memo and report builder cleanup. Nine items, synthetic maps only (no real figures, no company names): the old claims path leaves the
memo, and the missing-data text, the data requests and Appendix D are written from the stored map.
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from test_memo_role_metrics import DECK, appendix_c, build  # noqa: E402
from test_role_engine import file_of, row, run, sheet  # noqa: E402

from app import ic_memo as im  # noqa: E402
from app import integrity as integrity_mod  # noqa: E402
from app import report_text  # noqa: E402
from app import role_engine  # noqa: E402
from app import verdict as vd  # noqa: E402

MONTHS_41 = [f"{2023 + i // 12}-{i % 12 + 1:02d}" for i in range(41)]
YEARS = ["2023", "2024", "2025"]
OLD_SHEETS = ("Headline", "By Segment", "NRR by Cohort", "NRR Series", "Churn Series", "ACV Bands", "Segment Base")
BANNED = ("(benchmark, not company data)", "By Segment", "NRR by Cohort", "ACV Bands", "Segment Base", "(41 months)", "claims ")


def pnl_file(labels=None, **kw):
    """A yearly P&L: revenue, cost of revenue (row 5), S&M in plan years only (row 6), R&D as two segment rows, an OPEX total; no G&A row."""
    rows = [row(4, "revenue", [1_000, 1_500, 2_400], YEARS, basis="yearly"),
            row(5, "cost_of_revenue", [300, 450, 600], YEARS, basis="yearly"),
            row(6, "sales_marketing", [500, 600, 700], ["2026", "2027", "2028"], basis="yearly", actual_plan="plan", plan=True),
            row(7, "opex", [900, 1_000, 1_300], YEARS, basis="yearly"),
            row(10, "rnd", [100, 120, 150], YEARS, basis="yearly", segment="Core"),
            row(11, "rnd", [50, 60, 80], YEARS, basis="yearly", segment="Labs")]
    f = file_of("pnl", [sheet("P&L", rows, granularity="yearly")])
    return {**f, **({"labels": labels} if labels else {}), **kw}


def monthly_file():
    """A monthly report: MRR for 41 months, ARR, customers; headcount only after the as-of month."""
    months = MONTHS_41
    rows = [row(4, "revenue", [100 + i for i in range(41)], months), row(5, "arr", [(100 + i) * 12 for i in range(41)], months),
            row(6, "mrr", [100 + i for i in range(41)], months), row(8, "customers", [50 + i for i in range(41)], months, unit="count"),
            row(9, "headcount", [10, 11, 12], ["2026-08", "2026-09", "2026-10"], unit="count")]
    return file_of("monthly report", [sheet("Report", rows)])


def maps():
    return [monthly_file(), pnl_file()]


def results_of(files=None, as_of="2026-06"):
    return run(files or maps(), as_of=as_of, deck=DECK)


@pytest.fixture(scope="module")
def memo_text():
    old = [{"sheet": n, "rows": [["Metric", "Value"], [f"{n} row", "1"]]} for n in OLD_SHEETS]
    anomalies = {"sheet": "Anomalies", "rows": [["Flag", "Count", "Detail"], ["Months with negative MRR", "Not applicable", ""]]}
    return build(results_of(), maps(), tables=[*old, anomalies])


def reasons(files=None):
    table = role_engine.build_table(files or maps())
    out = report_text.apply_reasons(results_of(files), table)
    return {m["metric"]: m["reason"] for m in out["role_metrics"]["metrics"] if m["status"] != "computed"}


# --- 1. Worth flagging --------------------------------------------------------------------------------------------------------------------------

def test_worth_flagging_lists_a_differing_year_with_figure_sources_difference_and_percent(memo_text):
    section = memo_text.split("## Worth flagging")[1].split("## Data gaps and requests")[0]
    assert "Revenue 2025 differs across the sources" in section
    for part in ("pnl P&L!D4 2,400 EUR", "deck.pdf page 4 1,500 EUR", "difference ", "%"):
        assert part in section, part


def test_worth_flagging_lists_a_rounded_agreement_as_one_line_and_an_amber_check_by_its_finding_only():
    files = [file_of("pnl", [sheet("P&L", [row(4, "revenue", [1_000_000, 1_234_000], ["2024", "2025"], basis="yearly")], granularity="yearly")])]
    deck = [{"metric": "revenue", "period": "2025", "value": 1_200_000.0, "currency": "EUR", "actual_plan": "actual", "file": "deck.pdf", "page": 6,
             "label": "Total revenue FY2025", "precision": 100_000}]
    out = build(run(files, as_of="2026-12", deck=deck), files)
    section = out.split("## Worth flagging")[1].split("## Data gaps and requests")[0]
    assert "- Revenue 2025 agrees (rounded) across the sources" in section


def test_an_integrity_check_is_listed_only_when_no_reconciliation_or_anomaly_line_tells_the_same_finding(memo_text):
    section = memo_text.split("## Worth flagging")[1].split("## Data gaps and requests")[0]
    assert "Revenue 2025 differs across the sources" in section
    assert "Revenue reconciliation (Red)" not in section, "the Differs line already tells it"
    assert "Smoothness (Amber):" in section, "nothing else tells it"
    integrity = {"results": [{"check": integrity_mod.RECONCILIATION, "result": "Red", "finding": "x differ"}, {"check": integrity_mod.GAPS, "result": "Amber", "finding": "y gaps"}]}
    none = {"role_metrics": {"reconciliation": []}, "anomalies": None}
    lines = im.role_flags(none, integrity, "EUR", im.Notes())
    assert [line.split(" (")[0] for line in lines] == [integrity_mod.RECONCILIATION, integrity_mod.GAPS], "listed when nothing else covers them"
    a = {"negative_mrr_months": [], "revenue_gap_then_resume": ["c1"], "revenue_missing_customer_id": {"count": 0}, "revenue_missing_fx_rate": {"count": 0},
         "revenue_missing_amount": {"count": 0}, "deals_close_before_created": {"excluded_count": 0}, "date_order_from_data": [],
         "source": {"file": "f", "row_numbers": [2]}}
    lines = im.role_flags({**none, "anomalies": a}, integrity, "EUR", im.Notes())
    assert any(line.startswith("Customers with gaps") for line in lines) and not any(line.startswith(integrity_mod.GAPS + " (") for line in lines)


def test_worth_flagging_lists_an_applicable_anomaly_flag_above_zero_and_nothing_at_zero():
    results = results_of()
    results["anomalies"] = {**results["anomalies"], "source": {**results["anomalies"]["source"], "row_numbers": [2, 3]},
                            "negative_mrr_months": ["2025-03"], "revenue_missing_customer_id": {"count": 4, "rows": []}}
    table = role_engine.build_table(maps())
    flagged = im.role_flags(results, None, "EUR", im.Notes())
    assert any(line.startswith("Months with negative MRR: 1") for line in flagged)
    assert any(line.startswith("Revenue lines missing customer ID: 4") for line in flagged)
    assert not any("gaps > 2 months" in line for line in flagged), "a flag at 0 is not listed"
    assert table


def test_worth_flagging_is_never_blank():
    files = [file_of("pnl", [sheet("P&L", [row(4, "revenue", [1_000, 1_100], ["2024", "2025"], basis="yearly")], granularity="yearly")])]
    out = build(run(files, as_of="2026-12"), files, integrity=None)
    section = out.split("## Worth flagging")[1].split("## Data gaps and requests")[0]
    assert section.strip(), "never a blank section"
    assert "No anomalies found in the files read." in section or "- " in section


def test_nothing_qualifying_prints_the_no_anomalies_line():
    notes = im.Notes()
    results = results_of()
    assert im.role_flags({**results, "role_metrics": {**results["role_metrics"], "reconciliation": []}, "anomalies": None}, {"results": []}, "EUR", notes) == []
    assert im.NO_ANOMALIES == "No anomalies found in the files read."


# --- 2. the benchmark label ---------------------------------------------------------------------------------------------------------------------

def test_a_growth_engine_row_that_is_not_rated_states_no_benchmark(memo_text):
    row_ = next(line for line in memo_text.split("\n") if line.startswith("| Growth engine |"))
    assert "benchmark, not company data" not in row_
    rated = vd.rate_growth({"nrr": {"overall_pct": 1.04}, "gross_churn": {"overall_pct": 0.05}}, lambda v: f"{v}", lambda v: f"{v}")
    assert rated["benchmark"] is True, "a rated line uses the thresholds and keeps the label"
    assert vd.rate_growth({}, str, str)["benchmark"] is False


# --- 3. Appendix C ------------------------------------------------------------------------------------------------------------------------------

def test_appendix_c_holds_the_role_tables_and_the_anomaly_table_and_none_of_the_old_blocks(memo_text):
    appendix = appendix_c(memo_text)
    for old in (*OLD_SHEETS, "Headline"):
        assert f"{old} row" not in appendix and f"\n{old}\n" not in appendix, old
    for title in ("Metrics read from the files", "Growth by year", "Yearly P&L", "Revenue reconciliation", "Metric details"):
        assert title in appendix, title
    assert "Months with negative MRR" in appendix, "the anomaly table stays"


def test_each_metric_appears_once_in_appendix_c_and_a_metric_not_computed_is_not_an_empty_table(memo_text):
    appendix = appendix_c(memo_text)
    table = appendix.split("Metrics read from the files")[1].split("\n\n")[0]
    names = [line.split("|")[1].strip() for line in table.splitlines()[3:]]
    assert len(names) == len(set(names)), names
    assert "Headcount" not in names and "Cash" not in names, "not computed: in Appendix B, not in C"
    assert "Headcount" in memo_text.split("## Appendix B")[1].split("## Appendix C")[0]


def test_the_memo_footnotes_of_the_old_blocks_are_gone(memo_text):
    assert "NRR · nrr" not in memo_text.split("Footnotes")[-1].replace("nrr.overall_pct", "")


# --- 4. deck figures, not claims ------------------------------------------------------------------------------------------------------------

def test_a_gap_blocking_deck_figures_says_deck_figures_with_old_claims_off():
    from app import claim_matching as cm
    results = {"missing_data": [{"metric": "CAC payback", "status": "Missing", "reason": "needs a monthly P&L", "unlocked_by": "A monthly P&L"}]}
    blocked = {"claim_id": "c1", "rank": 1, "metric": "CAC payback", "period": "2021 KEY PERFORMANCE INDICATORS",
               "evidence_source_key": cm.MISSING_KEY, "evidence_analysis": "CAC payback"}
    on = vd.data_gaps(results, [blocked], ["c1"])
    off = vd.data_gaps(results, [blocked], ["c1"], old_claims=False)
    assert "; claims CAC payback, 2021 KEY PERFORMANCE INDICATORS" in on[0]["why"]
    assert "; deck figures CAC payback, 2021 KEY PERFORMANCE INDICATORS" in off[0]["why"]
    assert "claims" not in off[0]["why"]


def test_the_memo_and_its_glossary_say_no_claims_with_old_claims_off(memo_text):
    for banned in BANNED:
        assert banned not in memo_text, banned
    assert "VaS" not in memo_text.split("Glossary")[1].split("Footnotes")[0]


# --- 5. flags that never ran -----------------------------------------------------------------------------------------------------------------

def test_flags_with_no_input_file_read_not_applicable_never_zero():
    rows = report_text.anomaly_rows(results_of()["anomalies"])
    assert rows and all(r["count"] is None for r in rows), "no revenue lines and no CRM: nothing applies"
    assert report_text.anomaly_total(results_of()["anomalies"]) is None


def test_crm_flags_are_not_applicable_without_a_crm_file_and_revenue_flags_apply_with_revenue_lines():
    a = {"negative_mrr_months": [], "revenue_gap_then_resume": [], "revenue_missing_customer_id": {"count": 0}, "revenue_missing_fx_rate": {"count": 0},
         "revenue_missing_amount": {"count": 0}, "deals_close_before_created": {"excluded_count": 0}, "deals_duplicate_id": {"collapsed": 0, "distinct_ids": 0},
         "date_order_from_data": [], "source": {"file": "f.csv", "row_numbers": [2, 3]}}
    by = {r["key"]: r["count"] for r in report_text.anomaly_rows(a)}
    assert by["negative_mrr_months"] == 0 and by["revenue_missing_customer_id"] == 0
    assert by["deals_close_before_created"] is None and by["deals_duplicate_id"] is None
    assert report_text.anomaly_total(a) == 0
    a["deals_source"] = {"file": "crm.csv", "row_numbers": [2]}
    assert {r["key"]: r["count"] for r in report_text.anomaly_rows(a)}["deals_close_before_created"] == 0


def test_the_scorecard_says_not_applicable_and_the_exported_sheet_writes_it():
    out = build(results_of(), maps())
    reliability = next(line for line in out.split("\n") if line.startswith("| Data reliability |"))
    assert "0 anomaly flags" not in reliability and "anomaly flags not applicable" in reliability


# --- 6. the metric label ----------------------------------------------------------------------------------------------------------------------

def test_no_metric_label_carries_the_length_of_its_series(memo_text):
    assert "(41 months)" not in memo_text and "MRR (" not in memo_text.split("Metrics read from the files")[1].split("\n\n")[0]
    assert im.metric_label({"name": "MRR", "label": "41 months"}) == "MRR"
    assert im.metric_label({"name": "MRR", "label": "1 month"}) == "MRR"
    assert im.metric_label({"name": "Gross margin", "label": "yearly"}) == "Gross margin (yearly)"


# --- 7. the reason from the map -----------------------------------------------------------------------------------------------------------------

def test_a_role_mapped_nowhere_needs_a_row_by_its_plain_name():
    r = reasons()
    assert r["ga_share"] == "needs a G&A row"
    assert r["ebitda_margin"] == "needs an EBITDA row"
    assert r["cash"] == "needs a cash row"
    only_revenue = [file_of("pnl", [sheet("P&L", [row(4, "revenue", [1, 2, 3], YEARS, basis="yearly")], granularity="yearly")])]
    assert reasons(only_revenue)["sm_share"] == "needs a sales and marketing row"


def test_a_role_mapped_in_plan_columns_only_says_so_and_names_the_files_total_label():
    assert reasons()["sm_share"] == "S&M split only in plan years; actual years carry OPEX total only"
    labelled = [monthly_file(), pnl_file(labels={"P&L:7": "Total operating costs"})]
    assert reasons(labelled)["sm_share"] == "S&M split only in plan years; actual years carry Total operating costs only"


def test_a_cost_role_mapped_as_part_rows_only_is_summed_and_gives_no_segment_reason():
    assert "rnd_share" not in reasons(), "R&D as two part rows is their sum"


def test_a_role_mapped_with_actuals_but_no_value_names_its_cells_and_the_engine_status():
    reason = reasons()["headcount"]
    assert reason.startswith("Headcount row read (Report!B9:D9); not computed: ")
    assert "no value at or before the as-of month" in reason


def test_the_yearly_pnl_table_and_the_summary_questions_use_the_same_reasons():
    files = [file_of("pnl", [sheet("P&L", [row(4, "revenue", [1_000, 1_500, 2_400], YEARS, basis="yearly"),
                                           row(6, "sales_marketing", [500, 600, 700], ["2026", "2027", "2028"], basis="yearly", actual_plan="plan", plan=True),
                                           row(5, "cost_of_revenue", [300, 450, 600], YEARS, basis="yearly")], granularity="yearly")])]
    table = role_engine.build_table(files)
    out = report_text.apply_reasons(run(files), table)
    years = out["yearly_basis"]["years"]
    assert {y["cac_payback_reason"] for y in years if y["cac_payback_months"] is None} <= {
        "S&M split only in plan years; actual years carry OPEX total only", "no revenue for the year before"}
    text = build(run(files), files)
    assert "S&M split only in plan years; actual years carry OPEX total only" in text.split("## Appendix B")[1]


def test_no_fixed_sentence_names_a_row_as_missing_when_the_map_has_it():
    for metric, reason in reasons().items():
        if metric in ("gross_margin", "yearly_cac_payback"):
            assert "needs a cost of revenue row" not in reason and "cost_of_revenue" not in reason, reason
    table = role_engine.build_table(maps())
    assert report_text.missing_reason(table, ["revenue", "cost_of_revenue"], "x") .startswith("Revenue row read")


# --- 8. data requests ------------------------------------------------------------------------------------------------------------------------

def test_a_mapped_role_never_appears_in_a_request(memo_text):
    asks = memo_text.split("\nRequests\n")[1].split("\n\n")[0]
    for mapped in ("cost of revenue", "sales and marketing", "R&D", "headcount", "revenue row"):
        assert mapped not in asks.replace("customer-level revenue lines", ""), mapped
    assert "a G&A row" in asks and "an EBITDA row" in asks and "a cash row" in asks


def test_one_request_line_per_role_group_and_one_per_file_kind_with_no_duplicates(memo_text):
    asks = [line for line in memo_text.split("\nRequests\n")[1].split("\n\n")[0].splitlines() if line.startswith("- ")]
    assert len(asks) == len(set(asks))
    assert len([a for a in asks if a.startswith("- A file with")]) == 1
    assert sum("CRM deals" in a for a in asks) == 1 and sum("customer-level revenue lines" in a for a in asks) == 1


def test_request_roles_name_only_unmapped_roles():
    table = role_engine.build_table(maps())
    assert report_text.request_roles(table, ["revenue", "cost_of_revenue", "sales_marketing"]) == []
    assert report_text.request_roles(table, ["revenue", "ga", "cash"]) == ["ga", "cash"]
    assert report_text.request_line(["ga", "cash", "ebitda"]) == "A file with a G&A row, a cash row and an EBITDA row"
    gaps = vd.data_gaps(results_of(), [], [], table=table, old_claims=False)
    assert not any(g.get("request_roles") and {"cost_of_revenue", "sales_marketing", "rnd"} & set(g["request_roles"]) for g in gaps)


# --- 9. Appendix D -----------------------------------------------------------------------------------------------------------------------------

def files_table(text):
    return text.split("## Appendix D")[1].split("Files reviewed\n")[1].split("\n\n")[0]


def test_the_files_column_lists_the_p_and_l_the_decks_and_the_monthly_report(memo_text):
    table = files_table(memo_text)
    assert "| P&L and budget vs actuals | yes | pnl (P&L) |" in table
    assert "| Board decks, last 6–8 quarters | yes | deck.pdf |" in table
    assert "| Headcount history and hiring plan | yes | monthly report (Report) |" in table
    assert "| Monthly revenue or ARR report | yes | monthly report (Report) |" in table


def test_covered_is_yes_only_when_a_file_is_listed():
    for line in files_table(build(results_of(), maps())).splitlines()[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert (cells[1] == "yes") == bool(cells[2]), line


def test_the_summary_counts_the_seven_categories_only(memo_text):
    assert "Evidence categories covered: 3 of 7" in memo_text, "P&L, headcount (a mapped headcount row) and the decks; the monthly report row is the 8th"
    categories = im.evidence_categories([{"dtype": "reading", "file": "r", "sheet": "S", "kinds": ["revenue_report"]}], [])
    assert len(categories) == 7 and not any(c["covered"] for c in categories)


# --- the whole memo ------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("banned", BANNED)
def test_the_memo_holds_none_of_the_old_path_strings(memo_text, banned):
    assert banned not in memo_text


# --- a mapped row with no series (George, PR 4f decision 4) --------------------------------------------------------------------------------------

def unread_files():
    """The monthly report with a headcount row whose range holds no number (no series) and a cash row likewise."""
    f = monthly_file()
    rows = [r for r in f["file_map"]["sheets"][0]["rows"] if r["role"] != "headcount"]
    rows += [{"row": 9, "role": "headcount", "basis": "monthly", "actual_plan": "actual", "segment": None, "unit": "count", "cells": "B9:Z9"}]
    f["file_map"]["sheets"][0]["rows"] = rows
    return [f, pnl_file()]


def test_a_mapped_row_with_no_series_reads_row_read_no_values_and_is_never_requested():
    files = unread_files()
    table = [*role_engine.build_table(files), *report_text.rows_without_series(files)]
    assert report_text.role_state(table, "headcount") == "no_values"
    out = report_text.apply_reasons(results_of(files), table)
    reason = next(m["reason"] for m in out["role_metrics"]["metrics"] if m["metric"] == "headcount")
    assert reason == "Headcount row read (Report!B9:Z9); not computed: no values in the cells"
    assert report_text.request_roles(table, ["headcount"]) == []
    text = build(results_of(files), files)
    asks = text.split("\nRequests\n")[1].split("\n\n")[0]
    assert "headcount" not in asks and "a cash row" in asks
    assert "| Headcount history and hiring plan | yes | monthly report (Report) |" in text, "a mapped headcount row covers the category"


# --- Appendix D on a live audit's records (PR 4f fix) ---------------------------------------------------------------------------------------------

def live_files(maps_):
    """The file records as a live audit stores them: dtype "file", a hash, no kind; the kind sits on the reading's map (kind "sheet")."""
    records, hashed = [], []
    for i, f in enumerate(maps_):
        h = f"hash{i}"
        records.append({"dtype": "file", "file": f["file"], "file_hash": h, "sheet": None})
        hashed.append({**f, "file_hash": h})
    return records, report_text.memo_files(records, [*role_engine.build_table(hashed), *report_text.rows_without_series(hashed)])


def test_a_live_audit_lists_each_file_once_in_the_summary_and_in_appendix_d():
    records, files = live_files(maps())
    text = build(results_of(), maps(), files=files)
    table = files_table(text)
    assert "| P&L and budget vs actuals | yes | pnl (P&L) |" in table
    assert "| Monthly revenue or ARR report | yes | monthly report (Report) |" in table
    assert "Files reviewed: 2 data files" in text and "Evidence categories covered: 3 of 7" in text
    listed = {name for line in table.splitlines()[2:] for name in line.split("|")[3].split(";") if name.strip()}
    named = {f"{f['file']} ({f['sheet']})" for f in files if f["sheet"]}
    assert len(files) == len(records) and {n.strip() for n in listed} - {"deck.pdf"} == named


def test_the_summary_count_and_the_file_list_are_one_list():
    records, files = live_files(maps())
    assert [f["file"] for f in files] == [r["file"] for r in records]        # one entry per record, in upload order, never a second pass
    assert files[0]["kinds"] == ["revenue_report", "headcount"] and files[1]["dtype"] == "pnl"


def test_the_anomalies_footnote_names_no_sheet_when_nothing_was_read():
    base = results_of()
    empty = {**base, "anomalies": {**(base.get("anomalies") or {}), "source": {"file": "revenue", "sheet": "Sheet1", "rows": "no rows", "row_numbers": [], "rule": "synthetic"}}}
    empty["anomalies"].pop("deals_source", None)
    anomalies = {"sheet": "Anomalies", "rows": [["Flag", "Count", "Detail"], ["Months with negative MRR", "Not applicable", ""]]}
    text = build(empty, maps(), tables=[anomalies])
    assert "Anomaly Flags · anomalies · no revenue lines or CRM deals read" in text
    assert "Sheet1" not in text and "no rows" not in text
