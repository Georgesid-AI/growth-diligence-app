"""Issue #136, from the artefact (an audit with the as-of month 2021-12 set by the analyst; a deck page with the table "2021 COMPARISON
SALES vs RECOGNISED REVENUE", columns Q1-Q4 2021, rows "Sales (Annual Contracted Value)" and "Recognised Revenue"; two register rows of
one table candidate, #2 and #4, both read as Q1 2021 Revenue against one figure summed for 2021-01 to 2021-03 from row 39 of a metrics
sheet whose label column holds a monthly "RECOGNISED REVENUE" line and a cumulative "TOTAL RECOGNISED REVENUE (current year)" line).
One failing test per finding, on synthetic data only (CLAUDE.md rules 13 and 15):

1 a table row whose figures share one cell (a borderless PDF table) gave every figure the header's first period · 2 a claim whose
period was not read is Unverified "Period not read – set it in the claim row" and is never read at the as-of month · 3 every observed
value carries its citation (source key, sheet, rows, period) in the register, the CSV, the banner and the memo · 4 "Annual Contracted
Value" is Contract value, never matched to engine revenue · 5 a cumulative "(current year)" revenue line is never the revenue row, so the
engine reads the monthly recognised-revenue row only · 6 (decision 4 of 19 Oct) a metrics sheet under a customer-style header offers the
monthly report type, and its label rows are never summed as customers."""
import csv
import io

import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import growth_engine as ge  # noqa: E402
import server  # noqa: E402
from claim_matching_support import engine_results  # noqa: E402
from test_chat_upload import AUDIT, _banner_audit, upload  # noqa: E402
from test_claim_matching import RUNS, register, results_for, row_of, run_claim  # noqa: E402
from test_ic_memo import memo  # noqa: E402
from test_revenue_recognition import csv_sheets, decide, rules_only  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import recognition as rec  # noqa: E402
from app import verdict as vd  # noqa: E402
from app.decks import claims  # noqa: E402

PERIOD_NOT_READ = "Period not read – set it in the claim row"
CONTRACT_REASON = "Contract value – not computed by the app"


# ---------------------------------------------------------------------------
# 1. A table row whose figures share one cell
# ---------------------------------------------------------------------------
def _cell(r, c, text):
    return {"page": 5, "kind": "table", "table": 1, "row": r, "col": c, "text": text}


TITLE = {"page": 5, "kind": "text", "text": "2021 COMPARISON SALES vs RECOGNISED REVENUE", "bbox": [0.1, 0.1, 0.6, 0.13], "box": 1,
         "title": True}
QUARTERS = ("Q1 2021", "Q2 2021", "Q3 2021", "Q4 2021")
ACV = "€ 120,000.00 € 156,000.00 € 130,000.00 € 140,000.00"          # four figures the PDF reader put in one cell
REV = "€ 100,000.00 € 125,000.00 € 127,000.00 € 148,000.00"
EXPECTED_ACV = [(120000, "Q1 2021", "2021-01-01", "2021-03-31"), (156000, "Q2 2021", "2021-04-01", "2021-06-30"),
                (130000, "Q3 2021", "2021-07-01", "2021-09-30"), (140000, "Q4 2021", "2021-10-01", "2021-12-31")]


def comparison_table(header_cells):
    return [TITLE, *header_cells, _cell(2, 1, "Sales (Annual Contracted Value)"), _cell(2, 2, ACV),
            _cell(3, 1, "Recognised Revenue"), _cell(3, 2, REV)]


def by_period(found, value):
    c = next(c for c in found if any(i["value"] == value for i in c.get("by_period") or ()))
    return [(i["value"], i["period_text"], i["period_start"], i["period_end"]) for i in c["by_period"]]


def test_1_figures_that_share_one_cell_take_the_header_period_of_the_same_position():
    """The header cell holds the four quarters and the value cell the four figures: the k-th figure is the k-th quarter's."""
    found = claims.detect_candidates(comparison_table([_cell(1, 2, " ".join(QUARTERS))]), "deck.pdf")
    assert by_period(found, 156000) == EXPECTED_ACV
    assert by_period(found, 148000)[3] == (148000, "Q4 2021", "2021-10-01", "2021-12-31")


def test_1_figures_that_share_one_cell_under_separate_header_cells_read_the_header_cells_left_to_right():
    found = claims.detect_candidates(comparison_table([_cell(1, c + 2, q) for c, q in enumerate(QUARTERS)]), "deck.pdf")
    assert by_period(found, 156000) == EXPECTED_ACV


def test_1_figures_that_share_one_cell_with_no_period_of_their_own_get_none_and_never_the_first():
    """Three quarters over four figures: no figure can be paired, so none takes a period (decision 3 of 19 Oct: no fallback)."""
    found = claims.detect_candidates(comparison_table([_cell(1, 2, " ".join(QUARTERS[:3]))]), "deck.pdf")
    assert by_period(found, 156000) == [(120000, None, None, None), (156000, None, None, None), (130000, None, None, None),
                                          (140000, None, None, None)]


# ---------------------------------------------------------------------------
# 2. A period that was not read
# ---------------------------------------------------------------------------
def test_2_a_claim_whose_period_was_not_read_is_unverified_with_the_text_and_never_read_at_the_as_of_month():
    acv = run_claim({"claim_type": "sales", "snippet": "ACV €12,000", "unit": None, "currency": "EUR", "value": 12000})
    assert (acv["metric"], acv["evidence_label"], acv["observed_value"], acv["reason"]) == ("ACV", "Unverified", None, PERIOD_NOT_READ)
    assert cm.PERIOD_NOT_READ == PERIOD_NOT_READ
    unread = run_claim({"claim_type": "revenue", "snippet": "Revenue €1M", "value": 1_000_000, "target_date": "later"})
    assert (unread["evidence_label"], unread["reason"], unread["observed_value"]) == ("Unverified", PERIOD_NOT_READ, None)
    results = results_for(RUNS["A"])
    as_of = cm._mi(results["as_of_month"])
    for metric in ("ACV", "ARR", "Revenue", "Gross margin"):       # as-of, month, sum and quarter metrics alike: no figure without a period
        observed, at, _, _ = cm._observe(cm._Figures(results, metric, cm.WHOLE), cm.METRICS[metric], metric, None, None, as_of)
        assert (observed, at) == (f"Unverified|{PERIOD_NOT_READ}", None), metric


# ---------------------------------------------------------------------------
# 3. The citation beside every observed value
# ---------------------------------------------------------------------------
def test_3_the_register_row_cites_source_key_sheet_rows_and_period_beside_the_observed_figure():
    rows = register(RUNS["A"])
    quarter = row_of(rows, "c28")            # Revenue €60,000, Q4 2023: three months summed
    assert quarter["observed_at"] == "2023-10 to 2023-12"
    assert quarter["observed_citation"] == f"(revenue_series.data.total, CSV, {quarter['observed_source']['rows']}, Oct–Dec 2023)"
    month = row_of(rows, "c01")              # ARR €200,000, Feb 2024
    assert month["observed_citation"] == f"(mrr_series.data.total, CSV, {month['observed_source']['rows']}, Feb 2024)"
    assert all(r["observed_citation"] is None for r in rows if r["observed_value"] is None)
    assert all(r["observed_citation"] for r in rows if r["observed_value"] is not None)
    assert list(cm.FIELDS)[list(cm.FIELDS).index("observed_source") + 1] == "observed_citation"


@pytest.mark.parametrize("observed_at, words", [
    ("2024-02", "Feb 2024"), ("2023-Q4", "Oct–Dec 2023"), ("2023-10 to 2023-12", "Oct–Dec 2023"), ("2022-04 to 2023-03", "Apr 2022–Mar 2023"),
    ("2023-01 to 2023-03 (3 of 12 months)", "Jan–Mar 2023 (3 of 12 months)"), ("2024-02 vs 2023-02", "Feb 2024 vs Feb 2023"),
    ("2024-01 to 2024-12 vs 2023-01 to 2023-12", "Jan–Dec 2024 vs Jan–Dec 2023"), ("missing", "missing")])
def test_3_the_period_of_a_citation_is_written_in_month_names(observed_at, words):
    assert cm.period_words(observed_at) == words


def test_3_the_csv_carries_the_citation_beside_the_observed_source(register_api):
    client, _ = register_api
    rows = {r["claim_id"]: r for r in client.get(f"/api/audits/{AUDIT_CM}/claims").json()["register"]}
    lines = list(csv.DictReader(io.StringIO(client.get(f"/api/audits/{AUDIT_CM}/claims.csv").text)))
    one = next(r for r in lines if r["claim_id"] == "c28")
    assert one["observed_citation"] == rows["c28"]["observed_citation"]
    assert list(one).index("observed_citation") == list(one).index("observed_source") + 1


AUDIT_CM = "audit-cm"


def test_3_the_banner_cites_the_observed_figure_before_the_deck_page(api, monkeypatch):
    row = {"claim_id": "c1", "rank": 1, "evidence_label": "Contradicted", "claim_type": "revenue", "metric": "Revenue",
           "claimed_value": 156000, "claimed_high": None, "unit": None, "currency": "EUR", "observed_value": 136000.0,
           "observed_source": {"file": "r.xlsx", "sheet": "Sales", "rows": "row 39"},
           "observed_citation": "(revenue_series.data.total, Sales, row 39, Jan–Mar 2021)", "deck_file": "deck.pdf", "page_ref": "p5",
           "gap_kind": "miss"}

    async def fake_rows(audit_id, audit):
        return [], [row]
    monkeypatch.setattr(server, "_claim_rows", fake_rows)
    _banner_audit(api, {"arr": None})
    text = api.get(f"/api/audits/{AUDIT}/blockers").json()["blockers"][0]["text"]
    assert text == ("Top-5 claim contradicted: revenue 156,000 EUR vs 136,000 EUR observed "
                    "(revenue_series.data.total, Sales, row 39, Jan–Mar 2021) (deck.pdf, p5).")


def test_3_the_verdict_reason_and_the_memo_register_cite_the_figure_with_its_period():
    rows = register(RUNS["A"])
    quarter = row_of(rows, "c28")
    assert vd.reason_text(quarter, "EUR").endswith(f"Evidence: Revenue by month {quarter['observed_citation']}.")
    assert quarter["observed_citation"] in vd._source_text(quarter)
    appendix = memo().split("## Appendix A")[1].split("## Appendix B")[0]
    line = next(line for line in appendix.splitlines() if line.startswith(f"| #{quarter['rank']} "))
    assert f"Revenue by month {quarter['observed_citation']}" in line


# ---------------------------------------------------------------------------
# 4. Contract value
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("snippet, label", [
    ("Sales (Annual Contracted Value) | € 156,000.00", "2021 COMPARISON SALES vs RECOGNISED REVENUE"),
    ("Contracted ARR €1.2M", None), ("Committed ARR €900K", None), ("CARR €2M", None), ("TCV €5M", None),
    ("Annual contract value €300K", None), ("Contracted revenue €4M", None), ("Committed MRR €50K", None)])
def test_4_a_contract_value_is_typed_contract_value_and_never_matched_to_engine_revenue(snippet, label):
    row = run_claim({"claim_type": "revenue", "snippet": snippet, "label_from": label, "value": 156000, "target_date": "2023-Q4"})
    assert (row["metric"], row["metric_set_by"]) == ("Contract value", "python")
    assert (row["evidence_label"], row["reason"], row["observed_value"]) == ("Unverified", CONTRACT_REASON, None)
    assert row["gap"] is None and row["evidence_analysis"] is None and row["observed_citation"] is None


def test_4_the_screen_may_pick_contract_value_and_the_engines_acv_stays_a_sales_metric():
    assert cm.METRICS["Contract value"]["unit"] == "currency" and cm.fits_metric("Contract value", None, "EUR")
    assert cm.propose_metric("sales", "currency", "ACV €12,000") == "ACV", "an average contract value per customer is still the engine's ACV"
    assert cm.propose_metric("revenue", "currency", "Revenue €1M") == "Revenue"


def test_4_a_contract_value_row_and_a_revenue_row_of_the_same_period_are_no_deck_inconsistency():
    found = claims.detect_candidates(comparison_table([_cell(1, 2, " ".join(QUARTERS))]), "deck.pdf")
    acv = next(c for c in found if any(i["value"] == 156000 for i in c.get("by_period") or ()))
    revenue = next(c for c in found if any(i["value"] == 148000 for i in c.get("by_period") or ()))
    assert (claims.deck_label(acv), claims.deck_label(revenue)) == ("Contract value", "Revenue")
    assert acv["inconsistent_dates"] == [] and revenue["inconsistent_dates"] == []


# ---------------------------------------------------------------------------
# 5. A cumulative revenue line is never the revenue row
# ---------------------------------------------------------------------------
MONTHS = [f"{m}-{y}" for y in ("19", "20", "21") for m in ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")]
MONTHLY = [None] + [1000 + 10 * i for i in range(1, 36)]          # the company started in February 2019
FORECAST_YTD = [0 if v is None else 0 for v in MONTHLY]


def _ytd(values):
    out, total = [], 0
    for i, v in enumerate(values):
        total = (0 if i % 12 == 0 else total) + (v or 0)
        out.append(total)
    return out


def _ltm(values):
    return [sum(v or 0 for v in values[max(0, i - 11):i + 1]) for i in range(len(values))]


def _row(label, values):
    return label + "," + ",".join("" if v is None else str(v) for v in values)


QUARTER_HEADERS = ",".join(h for y in ("2019", "2020", "2021") for q in (1, 2, 3, 4) for h in (f"Q{q} {y}", "", ""))
METRICS_SHEET = "\n".join([
    "," + QUARTER_HEADERS, _row("Month", MONTHS),
    _row("SALES", [None, None] + [500 + i for i in range(2, 36)]),
    _row("NEW SALES (Annual Contract Value)", [700 + i for i in range(36)]),
    _row("RECOGNISED REVENUE", MONTHLY),
    _row("RECURRING REVENUE % SHARE", [0.5] * 36),
    _row("ARR (current year)", [12000 + i for i in range(36)]),
    _row("MRR", [1000 + i for i in range(36)]),
    _row("CUSTOMERS", [10 + i for i in range(36)]),
    _row("FORECAST: RECOGNISED REVENUE (current year)", [1500] * 36),
    _row("QUARTERLY RECOGNISED REVENUE", [sum(v or 0 for v in MONTHLY[i - 2:i + 1]) if i % 3 == 2 else None for i in range(36)]),
    _row("TOTAL RECOGNISED REVENUE (current year)", _ytd(MONTHLY)),           # a running total: a figure in every column
    _row("RECOGNISED REVENUE IN LAST 12 MONTHS", _ltm(MONTHLY)),
    _row("CONTRACTED REVENUE IN LAST 12 MONTHS (sales)", [9000] * 36),
    _row("EBITDA (current year)", [100] * 36)]) + "\n"
CONFIG = {"reporting_currency": "EUR", "target_arr": 1_000_000, "target_date": "2027-12-31", "fx": {"EUR": 1.0}, "billing_terms": {},
          "default_l": 1, "as_of_month": "2021-12-31"}
CUMULATIVE = ("TOTAL RECOGNISED REVENUE (current year)", "RECOGNISED REVENUE IN LAST 12 MONTHS")


def test_5_a_cumulative_current_year_line_is_never_the_revenue_row_and_the_engine_reads_the_monthly_row_only():
    """George, 19 Oct: a metric-labelled sheet with recognised revenue, ARR and forecast rows yields engine revenue equal to the
    recognised-revenue row only. The running total has a figure in every column, so by count alone it would win."""
    got = rec.recognise(csv_sheets(METRICS_SHEET, "metrics.csv"), as_of_month="2021-12-31", reporting_currency="EUR")
    assert got["recognised"] and got["label_mode"] == "metric" and got["series_basis"] == "row"
    assert (got["revenue_row"]["label"], got["revenue_row"]["row"], got["revenue_row"]["state"]) == ("RECOGNISED REVENUE", 5, "auto")
    assert not [c["label"] for c in got["revenue_row"]["candidates"] if c["label"] in CUMULATIVE], "a running total is no candidate"
    out = ge.compute_all(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {**CONFIG, "recognition": rec.engine_feed(got, "metrics.csv", "CSV")},
                         {"revenue": {"file": "metrics.csv", "sheet": "CSV"}})
    series = out["revenue_series"]
    assert [d["total"] for d in series["data"] if d["month"].startswith("2021")] == MONTHLY[24:36]
    assert sum(d["total"] for d in series["data"] if d["month"].startswith("2021")) == sum(MONTHLY[24:36])
    assert "row 5" in series["source"]["rows"] and series["source"]["sheet"] == "CSV"


@pytest.mark.parametrize("label", ["Revenue YTD", "Revenue (year to date)", "Total revenue (current year)", "Revenue in last 12 months",
                                   "Revenue LTM", "Revenue TTM", "Trailing 12 months revenue", "Lifetime revenue", "Cumulative revenue",
                                   "Revenue to date", "Rolling 12m revenue"])
def test_5_a_cumulative_or_rolling_label_is_never_a_revenue_candidate(label):
    assert rec.is_candidate_label(label) is False, label
    assert rec.is_candidate_label("Revenue") and rec.is_candidate_label("Total recognised revenue")


# ---------------------------------------------------------------------------
# 6. Decision 4: a customer-style header on a metrics sheet
# ---------------------------------------------------------------------------
CUSTOMER_HEADED = ("Customer,Jan-21,Feb-21,Mar-21\n"
                   "Recognised revenue,100,110,120\n"
                   "ARR,1200,1300,1400\n"
                   "MRR,100,108,117\n"
                   "Committed ARR,2000,2100,2200\n"
                   "Forecast revenue,150,160,170\n")


def test_6_the_legacy_mapping_path_sums_every_label_row_as_a_customer_which_is_why_the_type_must_be_chosen_first():
    """The suspicion of 19 Oct, confirmed: through the column mapping the five label rows are five customers and are summed."""
    sheet = rec.cr.read_workbook(CUSTOMER_HEADED.encode(), "metrics.csv")[0]
    mapping = {**rec.cr.suggest_mapping("revenue", list(sheet.columns)), "currency": server.CONFIRMED_CURRENCY}
    frame = server.normalize(server.df_to_records(sheet.frame), "revenue", mapping, sheet.row_numbers, 1, {server.CONFIRMED_CURRENCY: "EUR"})
    assert [d["total"] for d in ge.compute_revenue_series(frame, {}, {"EUR": 1.0})["data"]] == [3550.0, 3778.0, 4007.0]


def test_6_a_metrics_sheet_under_a_customer_header_offers_the_monthly_report_type_and_reads_its_revenue_row_once_chosen():
    got = rec.recognise(csv_sheets(CUSTOMER_HEADED, "metrics.csv"), as_of_month="2021-03-31")
    assert got["recognised"] is True and got["file_type"] is None and got["type_state"] == "click"
    assert got["type_candidates"] == ["customer_revenue", "monthly_revenue_report"] and got["needs_click"] is True
    assert got["label_mode"] != "metric", "the header still says customer, so the analyst decides (review L1)"
    chosen = rec.recognise(csv_sheets(CUSTOMER_HEADED, "metrics.csv"), as_of_month="2021-03-31", decisions={"file_type": "monthly_revenue_report"})
    assert (chosen["file_type"], chosen["series_basis"], chosen["revenue_row"]["label"]) == ("monthly_revenue_report", "row", "Recognised revenue")
    assert [s["value"] for s in chosen["series"]] == [100, 110, 120] and chosen["series_rows"] == [2]
    customers = rec.recognise(csv_sheets(CUSTOMER_HEADED, "metrics.csv"), as_of_month="2021-03-31", decisions={"file_type": "customer_revenue"})
    assert (customers["file_type"], customers["series_basis"]) == ("customer_revenue", "sum_of_rows")


def test_6_run_audit_waits_for_the_type_and_the_chosen_monthly_report_feeds_the_engine_its_revenue_row_only(api):
    rules_only(api, "2021-03-31")
    body = upload(api, "metrics.csv", CUSTOMER_HEADED.encode()).json()
    assert body["dtype"] == "revenue" and body["recognition"]["file_type"] is None
    assert body["recognition"]["type_candidates"] == ["customer_revenue", "monthly_revenue_report"]
    assert api.post(f"/api/audits/{AUDIT}/compute").status_code == 409, "label rows are never summed as customers on a guess"
    assert body["mapping_dropped"] is False
    chosen = decide(api, action="change", part="file_type", file_type="monthly_revenue_report")
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["recognition_only"] is True and chosen.json()["recognition"]["revenue_row"]["label"] == "Recognised revenue"
    assert chosen.json()["mapping_dropped"] is True, "the screen says that switching back to Customer revenue needs a re-upload"
    currency = decide(api, action="change", part="currency", currency="EUR")
    assert currency.status_code == 200, currency.text
    assert api.post(f"/api/audits/{AUDIT}/compute").status_code == 200
    series = api.db["audits"].docs[0]["results"]["revenue_series"]
    assert [d["total"] for d in series["data"]] == [100, 110, 120] and "row 2" in series["source"]["rows"]


def test_the_engine_results_fixture_is_the_one_the_register_tests_read():
    assert engine_results()["as_of_month"] == "2024-02"
