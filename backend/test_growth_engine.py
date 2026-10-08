"""Synthetic-data unit tests for the deterministic growth engine.

Each scenario has a KNOWN answer. Run `python test_growth_engine.py` to print the
Stop-1 verification table (metric, expected, actual, pass/fail), or `pytest` to
assert. No LLM, no guessing — pure arithmetic checks.
"""

import pandas as pd

import demo_data
import growth_engine as ge

BASE = pd.Timestamp("2023-01-01")


def month(i):
    return (BASE + pd.DateOffset(months=i)).normalize()


def rev_df(rows):
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Scenario builders (return DataFrames with known answers)
# ---------------------------------------------------------------------------

def monthly_lines(customer, values_by_month, currency="EUR", segment=None, start_row=1):
    """One monthly invoice per active month. values_by_month: {month_index: amount}."""
    rows = []
    r = start_row
    for i, amt in values_by_month.items():
        rows.append({"customer_id": customer, "invoice_date": month(i), "amount": amt,
                     "currency": currency, **({"segment": segment} if segment else {}), "_row": r})
        r += 1
    return rows


CASES = {}


def case(name):
    def deco(fn):
        CASES[name] = fn
        return fn
    return deco


@case("NRR overall = 110%")
def _nrr():
    # Base customer A: 100 at m0, 110 at m12 (expansion). New customer B starts m3 (ignored in base).
    rows = monthly_lines("A", {i: (110 if i == 12 else 100) for i in range(13)})
    rows += monthly_lines("B", {i: 200 for i in range(3, 13)}, start_row=100)
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    res = ge.compute_nrr(mrr, seg, fm)
    return 1.1, res["overall_pct"]


@case("Gross revenue churn = 35%")
def _churn():
    rows = monthly_lines("A", {i: 100 for i in range(13)})                          # flat
    rows += monthly_lines("B", {i: (60 if i == 12 else 100) for i in range(13)}, start_row=100)   # -40 contraction
    rows += monthly_lines("C", {i: 100 for i in range(12)}, start_row=200)          # churns at m12 (0)
    rows += monthly_lines("D", {i: (150 if i == 12 else 100) for i in range(13)}, start_row=300)  # expansion (not netted)
    mrr, _, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    res = ge.compute_gross_churn(mrr)
    return 0.35, res["overall_pct"]


@case("Median sales cycle = 60 days")
def _cycle():
    created = pd.Timestamp("2024-01-01")
    deals = pd.DataFrame([
        {"deal_id": 1, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=40), "_row": 1},
        {"deal_id": 2, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=50), "_row": 2},
        {"deal_id": 3, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=60), "_row": 3},
        {"deal_id": 4, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=70), "_row": 4},
        {"deal_id": 5, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=80), "_row": 5},
        {"deal_id": 6, "stage": "lost", "created_date": created, "close_date": created + pd.Timedelta(days=30), "_row": 6},
        {"deal_id": 7, "stage": "open", "created_date": created, "close_date": pd.NaT, "_row": 7},
        {"deal_id": 8, "stage": "won", "created_date": created, "close_date": created - pd.Timedelta(days=5), "_row": 8},  # invalid → excluded
    ])
    res = ge.compute_sales_cycle(deals)
    return 60.0, res["median_days"]


@case("Win rate overall = 30%")
def _winrate():
    rows = []
    rid = 1
    for _ in range(8):
        rows.append({"deal_id": rid, "stage": "won", "founder_involved": "yes", "_row": rid}); rid += 1
    for _ in range(2):
        rows.append({"deal_id": rid, "stage": "lost", "founder_involved": "yes", "_row": rid}); rid += 1
    for _ in range(22):
        rows.append({"deal_id": rid, "stage": "won", "founder_involved": "no", "_row": rid}); rid += 1
    for _ in range(68):
        rows.append({"deal_id": rid, "stage": "lost", "founder_involved": "no", "_row": rid}); rid += 1
    res = ge.compute_win_rate(pd.DataFrame(rows), True)
    return 0.3, res["win_rate_pct"]


@case("Win rate small-sample flag (founder n=10)")
def _winrate_flag():
    rows = []
    rid = 1
    for _ in range(8):
        rows.append({"deal_id": rid, "stage": "won", "founder_involved": "yes", "_row": rid}); rid += 1
    for _ in range(2):
        rows.append({"deal_id": rid, "stage": "lost", "founder_involved": "yes", "_row": rid}); rid += 1
    for _ in range(22):
        rows.append({"deal_id": rid, "stage": "won", "founder_involved": "no", "_row": rid}); rid += 1
    for _ in range(68):
        rows.append({"deal_id": rid, "stage": "lost", "founder_involved": "no", "_row": rid}); rid += 1
    res = ge.compute_win_rate(pd.DataFrame(rows), True)
    return True, res["by_founder"]["with_founder"]["small_sample"]


@case("Annual prepayment → MRR spread = 100/mo")
def _annual():
    rows = [{"customer_id": "X", "invoice_date": month(0), "amount": 1200, "currency": "EUR", "_row": 1}]
    mrr, _, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {"X": "annual"}, {"EUR": 1.0})
    dec_val = mrr.at["X", pd.Period("2023-12", "M")]
    return 100.0, ge._round(dec_val)


@case("Billing term 'annual' (no service dates): 1200 → 100/mo × 12 months")
def _annual_full_year():
    rows = [{"customer_id": "X", "invoice_date": month(0), "amount": 1200, "currency": "EUR", "_row": 1}]
    mrr, _, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {"X": "annual"}, {"EUR": 1.0})
    vals = [ge._round(v) for v in mrr.loc["X"].values]
    return [100.0] * 12, vals


@case("FX conversion USD→EUR (rate 0.9)")
def _fx():
    rows = [{"customer_id": "U", "invoice_date": month(0), "amount": 1000, "currency": "USD", "_row": 1}]
    mrr, _, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"USD": 0.9})
    return 900.0, ge._round(mrr.at["U", pd.Period("2023-01", "M")])


@case("Currency with no exchange rate is excluded, never guessed at 1.0")
def _fx_missing_rate():
    # GBP has no entry in fx — must NOT silently convert at 1.0. It should be
    # excluded from MRR entirely and flagged, while the EUR row still computes.
    rows = [
        {"customer_id": "K", "invoice_date": month(0), "amount": 1000, "currency": "GBP", "_row": 1},
        {"customer_id": "E", "invoice_date": month(0), "amount": 500, "currency": "EUR", "_row": 2},
    ]
    mrr, _, _, _, notes = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    excluded = "K" not in mrr.index
    flagged = notes["rows_missing_fx"] == [1] and notes["missing_fx_currencies"] == ["GBP"]
    eur_ok = ge._round(mrr.at["E", pd.Period("2023-01", "M")]) == 500.0
    return True, (excluded and flagged and eur_ok)


@case("Churn-and-return gap flagged")
def _gap():
    rows = monthly_lines("G", {0: 100, 1: 100, 5: 100})  # gap months 2,3,4
    mrr, _, _, _, notes = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    flags = ge.compute_anomalies(mrr, rev_df(rows), pd.DataFrame(), notes)
    return True, ("G" in flags["revenue_gap_then_resume"])


@case("Negative MRR month flagged")
def _negative():
    rows = [
        {"customer_id": "R", "invoice_date": month(0), "amount": 500, "currency": "EUR", "_row": 1},
        {"customer_id": "R", "invoice_date": month(1), "amount": -500, "currency": "EUR", "_row": 2},
    ]
    mrr, _, _, _, notes = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    flags = ge.compute_anomalies(mrr, rev_df(rows), pd.DataFrame(), notes)
    return True, ("2023-02" in flags["negative_mrr_months"])


@case("Invalid deal (close<created) excluded count = 1")
def _invalid_deal():
    created = pd.Timestamp("2024-01-01")
    deals = pd.DataFrame([
        {"deal_id": 1, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=40), "_row": 1},
        {"deal_id": 2, "stage": "won", "created_date": created, "close_date": created - pd.Timedelta(days=5), "_row": 2},
    ])
    flags = ge.compute_anomalies(pd.DataFrame(), pd.DataFrame(), deals, {})
    return 1, flags["deals_close_before_created"]["excluded_count"]


@case("Missing customer-id rows counted = 2")
def _missing_id():
    rows = [
        {"customer_id": "A", "invoice_date": month(0), "amount": 100, "currency": "EUR", "_row": 1},
        {"customer_id": None, "invoice_date": month(0), "amount": 100, "currency": "EUR", "_row": 2},
        {"customer_id": "", "invoice_date": month(0), "amount": 100, "currency": "EUR", "_row": 3},
    ]
    mrr, _, _, _, notes = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    flags = ge.compute_anomalies(mrr, rev_df(rows), pd.DataFrame(), notes)
    return 2, flags["revenue_missing_customer_id"]["count"]


@case("Blank revenue amount flagged, not treated as zero")
def _missing_amount():
    rows = [
        {"customer_id": "A", "invoice_date": month(0), "amount": 100, "currency": "EUR", "_row": 1},
        {"customer_id": "A", "invoice_date": month(0), "amount": None, "currency": "EUR", "_row": 2},
        {"customer_id": "A", "invoice_date": month(0), "amount": float("nan"), "currency": "EUR", "_row": 3},
    ]
    mrr, _, _, _, notes = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    flags = ge.compute_anomalies(mrr, rev_df(rows), pd.DataFrame(), notes)
    # blank rows excluded (not zero) -> only row 1's 100 counted, and both blanks flagged
    still_100 = ge._round(mrr.at["A", pd.Period("2023-01", "M")]) == 100.0
    return (2, True), (flags["revenue_missing_amount"]["count"], still_100)


@case("One-off revenue excluded from MRR")
def _oneoff():
    rows = [
        {"customer_id": "A", "invoice_date": month(0), "amount": 100, "currency": "EUR", "revenue_type": "recurring", "_row": 1},
        {"customer_id": "A", "invoice_date": month(0), "amount": 999, "currency": "EUR", "revenue_type": "one-off", "_row": 2},
    ]
    mrr, _, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    return 100.0, ge._round(mrr.at["A", pd.Period("2023-01", "M")])


@case("CAC payback L=1 = 5.0 months")
def _cac():
    # New customer N first revenue in 2023-Q2 (Apr), MRR 1000/mo through Jun.
    rows = monthly_lines("N", {3: 1000, 4: 1000, 5: 1000})
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    new_q = ge.compute_new_mrr_by_quarter(mrr, fm)
    # P&L: Q1 S&M = 4000; Q2 revenue 1000, cost 200 → GM 80%.
    pnl = pd.DataFrame([
        {"month": month(0), "sm_expense": 4000, "revenue": 0, "cost_of_revenue": 0, "_row": 1},
        {"month": month(1), "sm_expense": 0, "revenue": 0, "cost_of_revenue": 0, "_row": 2},
        {"month": month(2), "sm_expense": 0, "revenue": 0, "cost_of_revenue": 0, "_row": 3},
        {"month": month(3), "sm_expense": 500, "revenue": 400, "cost_of_revenue": 80, "_row": 4},
        {"month": month(4), "sm_expense": 500, "revenue": 300, "cost_of_revenue": 60, "_row": 5},
        {"month": month(5), "sm_expense": 500, "revenue": 300, "cost_of_revenue": 60, "_row": 6},
    ])
    cac = ge.compute_cac_payback(new_q, pnl, default_l=1)
    return 5.0, cac["quarters"]["2023-Q2"]["L1"]["months"]


@case("CAC not computable when GM ≤ 0")
def _cac_bad_gm():
    rows = monthly_lines("N", {3: 1000, 4: 1000, 5: 1000})
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    new_q = ge.compute_new_mrr_by_quarter(mrr, fm)
    pnl = pd.DataFrame([
        {"month": month(0), "sm_expense": 4000, "revenue": 0, "cost_of_revenue": 0, "_row": 1},
        {"month": month(3), "sm_expense": 0, "revenue": 100, "cost_of_revenue": 200, "_row": 2},
        {"month": month(4), "sm_expense": 0, "revenue": 100, "cost_of_revenue": 200, "_row": 3},
        {"month": month(5), "sm_expense": 0, "revenue": 100, "cost_of_revenue": 200, "_row": 4},
    ])
    cac = ge.compute_cac_payback(new_q, pnl, default_l=1)
    computable = cac["quarters"]["2023-Q2"]["L1"]["months"] is not None
    return False, computable


@case("ACV bands: 1 strategic account, 1 self-serve")
def _acv_bands():
    rows = monthly_lines("BIG", {12: 20000})   # annual 240k -> strategic accounts
    rows += monthly_lines("SMALL", {12: 50}, start_row=100)  # annual 600 -> self-serve
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    acv = ge.compute_acv_path(mrr, seg, fm, target_arr=10_000_000, target_date="2026-01-01")
    by_key = {b["key"]: b["count"] for b in acv["bands"]}
    ok = by_key["strategic_accounts"] == 1 and by_key["self_serve"] == 1
    return True, ok


@case("ACV bands: renamed labels + range labels present, fixed low-to-high order")
def _acv_band_labels():
    rows = monthly_lines("BIG", {12: 20000})
    rows += monthly_lines("SMALL", {12: 50}, start_row=100)
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    acv = ge.compute_acv_path(mrr, seg, fm, target_arr=10_000_000, target_date="2026-01-01", reporting_currency="EUR")
    expected_keys = ["consumer_viral", "self_serve", "sales_assisted", "consultative_sales", "strategic_accounts"]
    expected_labels = ["Consumer / Viral", "Self-serve", "Sales-assisted", "Consultative sales", "Strategic accounts"]
    keys = [b["key"] for b in acv["bands"]]
    labels = [b["label"] for b in acv["bands"]]
    range_ok = acv["bands"][2]["range_label"] == "€1K–10K"  # sales_assisted band
    return (expected_keys, expected_labels, True), (keys, labels, range_ok)


@case("ACV band counts sum to active customers (demo data, both companies)")
def _acv_bands_sum_active():
    ok = True
    for idx in (0, 1):
        mrr, seg, fm, fx, spec = _demo_engine_inputs(idx)
        acv = ge.compute_acv_path(mrr, seg, fm, target_arr=spec["target_arr"], target_date=spec["target_date"],
                                   reporting_currency=spec["reporting_currency"])
        total_banded = sum(b["count"] for b in acv["bands"])
        ok = ok and total_banded == acv["current_customers"]
    return True, ok


@case("Cohort month-6 retention = 130%")
def _cohort_m6():
    vals = {i: 100 for i in range(7)}
    vals[6] = 130  # month-6 MRR is 130% of the starting month
    rows = monthly_lines("A", vals)
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    coh = ge.compute_cohort_retention(mrr, fm)
    return 1.3, coh["data"][0]["values"]["6"]


@case("Cohort heatmap: ramping cohort no longer inflates past 100% (regression for M0 bug)")
def _cohort_ramp_in_fix():
    # Same quarter cohort, but customers ramp in on different calendar months: A starts
    # month 0 (100 flat), B starts month 1 (200 flat), C starts month 2 (300 flat). Under
    # the old "M0 = first calendar month of the quarter" bug, the base would be A's 100
    # alone while later months sum in B and C too -> impossible readings (e.g. 600% at
    # month 2). Aging each customer from their OWN start month keeps every cell near 100%.
    rows = monthly_lines("A", {0: 100, 1: 100, 2: 100, 3: 100})
    rows += monthly_lines("B", {1: 200, 2: 200, 3: 200}, start_row=100)
    rows += monthly_lines("C", {2: 300, 3: 300}, start_row=200)
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    coh = ge.compute_cohort_retention(mrr, fm)
    row = coh["data"][0]
    # only ages 0 and 1 are fully observed for all three customers as of month 3
    return ({"0": 1.0, "1": 1.0}, 1), (row["values"], max(int(k) for k in row["values"]))


def _demo_engine_inputs(spec_idx):
    """Build (mrr, seg_map, first_month, fx, spec) straight from revenue lines for a demo
    company, bypassing the DB/API layer — same normalization server.py's `normalize()` does
    for the revenue dataset, kept local so this file stays dependency-free."""
    spec = demo_data.DEMO_AUDITS[spec_idx]
    datasets, meta = demo_data.build(spec)
    rev_raw, mapping = datasets["revenue"]
    out = pd.DataFrame()
    out["_row"] = range(2, len(rev_raw) + 2)
    for field, col in mapping.items():
        if col and col in rev_raw.columns:
            out[field] = rev_raw[col].values
    out["invoice_date"] = pd.to_datetime(out["invoice_date"], errors="coerce")
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
    fx[spec["reporting_currency"].upper()] = 1.0
    mrr, seg_map, first_month, _, _ = ge.build_mrr_matrix(out, {}, fx)
    return mrr, seg_map, first_month, fx, spec


@case("Cohort heatmap: M0 column is always 100% (demo data, both companies)")
def _cohort_m0_always_100_demo():
    ok = True
    for idx in (0, 1):
        mrr, _, fm, _, _ = _demo_engine_inputs(idx)
        coh = ge.compute_cohort_retention(mrr, fm)
        ok = ok and all(row["values"].get("0") == 1.0 for row in coh["data"])
    return True, ok


@case("Cohort heatmap: values stay in a plausible range on demo data (no impossible %)")
def _cohort_plausible_range_demo():
    ok = True
    for idx in (0, 1):
        mrr, _, fm, _, _ = _demo_engine_inputs(idx)
        coh = ge.compute_cohort_retention(mrr, fm)
        for row in coh["data"]:
            for v in row["values"].values():
                if v is None or v < 0 or v > 2.5:
                    ok = False
    return True, ok


@case("NRR by cohort is unchanged by the heatmap fix (demo data, Apex Cloud)")
def _nrr_by_cohort_unchanged_demo():
    mrr, seg, fm, _, _ = _demo_engine_inputs(0)
    nrr = ge.compute_nrr(mrr, seg, fm)
    # The numbers are exactly the ones this case has always pinned; only the count's field name
    # changed ("n" -> "nrr_base_customers"), and a null NRR now carries its reason.
    expected = {
        "2023-Q1": (1.2764, 8), "2023-Q2": (0.9014, 11), "2023-Q3": (1.1156, 8),
        "2023-Q4": (1.2763, 7), "2024-Q1": (1.2742, 5), "2024-Q2": (None, 0), "2024-Q3": (None, 0),
    }
    actual = {q: (v["nrr_pct"], v["nrr_base_customers"]) for q, v in nrr["by_cohort"].items()}
    return expected, actual


# --- CAC payback at L=0 / L=2 / zero-new-MRR --------------------------------
def _cac_scenario():
    rows = monthly_lines("M", {i: 500 for i in range(0, 7)})   # Jan–Jul, Q1 cohort
    rows += monthly_lines("N", {i: 1000 for i in range(3, 6)}, start_row=100)  # Apr–Jun, Q2 cohort
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    new_q = ge.compute_new_mrr_by_quarter(mrr, fm)
    pnl = pd.DataFrame([
        {"month": month(0), "sm_expense": 1500, "revenue": 0,   "cost_of_revenue": 0,  "_row": 2},
        {"month": month(1), "sm_expense": 1500, "revenue": 0,   "cost_of_revenue": 0,  "_row": 3},
        {"month": month(2), "sm_expense": 1000, "revenue": 0,   "cost_of_revenue": 0,  "_row": 4},
        {"month": month(3), "sm_expense": 700,  "revenue": 400, "cost_of_revenue": 80, "_row": 5},
        {"month": month(4), "sm_expense": 700,  "revenue": 300, "cost_of_revenue": 60, "_row": 6},
        {"month": month(5), "sm_expense": 600,  "revenue": 300, "cost_of_revenue": 60, "_row": 7},
        {"month": month(6), "sm_expense": 1000, "revenue": 100, "cost_of_revenue": 20, "_row": 8},
    ])
    return ge.compute_cac_payback(new_q, pnl, default_l=1)


@case("CAC payback 2023-Q2 L=0 = 2.5 months")
def _cac_l0():
    return 2.5, _cac_scenario()["quarters"]["2023-Q2"]["L0"]["months"]


@case("CAC payback 2023-Q2 L=2 not computable (no prior P&L)")
def _cac_l2():
    q = _cac_scenario()["quarters"]["2023-Q2"]["L2"]
    return True, (q["months"] is None and "no P&L" in q["reason"])


@case("CAC not computable when new MRR = 0 (2023-Q3)")
def _cac_zero_newmrr():
    q = _cac_scenario()["quarters"]["2023-Q3"]["L1"]
    return "new MRR is zero", (q["reason"] if q["months"] is None else "computable")


# --- Segment mix paths to target ARR ---------------------------------------
#   Segment A: A1 1000/mo flat; A2 1000 then 1500 in the latest month; A3 lands 8 months
#              before the latest month at 3000/mo and grows to 4000 by the latest month.
#   Segment B: B1 100/mo flat; B2 100 then 50 in the latest month (erosion); B3 lands 5
#              months back at 200; B4 lands 4 months back at 400.
#   Latest-month MRR: A = 1000+1500+4000 = 6500 (ARR 78,000, 3 customers)
#                     B = 100+50+200+400 = 750  (ARR 9,000, 4 customers)
#   NRR (base = active 12 months earlier, so A3/B3/B4 are excluded): A 2500/2000 = 125%,
#   B 150/200 = 75%.  Landed ACV: A3 3000*12 = 36,000 (NOT its grown 48,000); B3 2,400, B4 4,800.
def _seg_scenario(n_months=14, drop_b_landings=False, only_new_segment=False, no_segments=False):
    last = n_months - 1
    seg = (lambda name: None) if no_segments else (lambda name: name)
    rows = []
    rows += monthly_lines("A1", {i: 1000 for i in range(n_months)}, segment=seg("A"), start_row=1)
    rows += monthly_lines("A2", {i: (1500 if i == last else 1000) for i in range(n_months)}, segment=seg("A"), start_row=100)
    rows += monthly_lines("A3", {i: (4000 if i == last else 3000) for i in range(last - 8, n_months)}, segment=seg("A"), start_row=200)
    rows += monthly_lines("B1", {i: 100 for i in range(n_months)}, segment=seg("B"), start_row=300)
    rows += monthly_lines("B2", {i: (50 if i == last else 100) for i in range(n_months)}, segment=seg("B"), start_row=400)
    b3_start, b4_start = (0, 0) if drop_b_landings else (last - 5, last - 4)
    rows += monthly_lines("B3", {i: 200 for i in range(b3_start, n_months)}, segment=seg("B"), start_row=500)
    rows += monthly_lines("B4", {i: 400 for i in range(b4_start, n_months)}, segment=seg("B"), start_row=600)
    if only_new_segment:   # segment C exists only among customers who landed inside the last 12 months
        rows += monthly_lines("C1", {i: 500 for i in range(last - 3, n_months)}, segment="C", start_row=700)
    mrr, sm, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    return mrr, sm, fm


def _seg_paths(target_arr=None, target_date="2026-03-15", **kw):
    mrr, sm, fm = _seg_scenario(**kw)
    nrr = ge.compute_nrr(mrr, sm, fm) if len(mrr.columns) >= 13 else None
    if nrr and nrr.get("insufficient_history"):
        nrr = None
    acv = ge.compute_acv_path(mrr, sm, fm, target_arr or 1.0, target_date)
    years, _ = ge._years_to_target(mrr.columns[-1], target_date)
    base = 78000 * 1.25 ** years + 9000 * 0.75 ** years if years else None
    return ge.compute_segment_paths(mrr, sm, fm, nrr, acv, target_arr or 1.0, target_date), years, base


def _r(x, n=4):
    return None if x is None else round(x, n)


@case("Segment paths stage one: each segment compounds at its own NRR over the exact horizon")
def _sp_stage_one():
    sp, years, base = _seg_paths(target_arr=1_000_000)
    a, b = sp["stage_one"]["segments"]["A"], sp["stage_one"]["segments"]["B"]
    return (_r(78000 * 1.25 ** years), _r(9000 * 0.75 ** years), _r(base), _r(years * 12)), (
        _r(a["projected_arr"]), _r(b["projected_arr"]), _r(sp["stage_one"]["projected_base_arr"]), _r(sp["horizon_months"]))


@case("Segment paths: a segment with NRR < 100 shows its erosion, negative, in stage one")
def _sp_erosion():
    sp, years, _ = _seg_paths(target_arr=1_000_000)
    b = sp["stage_one"]["segments"]["B"]
    return (True, _r(9000 * 0.75 ** years - 9000)), (b["change_arr"] < 0, _r(b["change_arr"]))


@case("Segment paths: NRR inputs are the segment's own (125% and 75%), small bases flagged")
def _sp_nrr_inputs():
    sp, _, _ = _seg_paths(target_arr=1_000_000)
    a, b = sp["stage_one"]["segments"]["A"], sp["stage_one"]["segments"]["B"]
    return (1.25, 0.75, 2, 2, True, True), (a["nrr_pct"], b["nrr_pct"], a["nrr_base_customers"], b["nrr_base_customers"], a["small_base"], b["small_base"])


@case("Segment paths: per-point sensitivity is the derivative of ARR * (NRR/100)^years")
def _sp_sensitivity():
    sp, years, _ = _seg_paths(target_arr=1_000_000)
    a = sp["stage_one"]["segments"]["A"]
    bump = 78000 * (1.26 ** years - 1.25 ** years)     # one whole point, finite difference
    return True, abs(a["arr_change_per_nrr_point"] - bump) / bump < 0.02


@case("Segment paths stage two: the gap is target minus projected base")
def _sp_gap():
    sp, _, base = _seg_paths(target_arr=1_000_000)
    return (_r(1_000_000 - base), False), (_r(sp["gap_arr"]), sp["target_met_by_base"])


@case("Segment paths: target already met by the base -> zero gap, said so")
def _sp_met():
    sp, _, _ = _seg_paths(target_arr=50_000)
    return (0.0, True, True), (sp["gap_arr"], sp["target_met_by_base"], sp["reverse_solve"]["12"]["target_met_by_base"])


@case("Landed ACV is first-month ARR with no expansion (A3 = 36,000, not its grown 48,000)")
def _sp_landed():
    sp, _, _ = _seg_paths(target_arr=1_000_000)
    seg = sp["landed"]["12"]["segments"]
    return (36000.0, 1, 3600.0, 2, 3.0), (seg["A"]["landed_acv"], seg["A"]["new_customers"], seg["B"]["landed_acv"], seg["B"]["new_customers"], sp["landed"]["12"]["gross_new_per_year"])


@case("Landings are gross: churned or shrunk customers still count as landed")
def _sp_gross():
    sp, _, _ = _seg_paths(target_arr=1_000_000)
    # net-new (active-count change) would ignore a customer who landed and left; gross counts all three
    return 3, sum(v["new_customers"] for v in sp["landed"]["12"]["segments"].values())


@case("Reverse-solve, mix must shift: required blended ACV 25,000 -> A share 66.05%, +23.19 pts")
def _sp_shift():
    _, years, base = _seg_paths(target_arr=1_000_000)
    target = base + 25_000 * 3 * years                      # 3 gross landings a year at the observed rate
    sp, _, _ = _seg_paths(target_arr=target)
    r = sp["reverse_solve"]["12"]
    a = r["by_segment"]["A"]
    return (True, 25000.0, round(21400 / 32400, 5), round(21400 / 32400 - 3 / 7, 5), _r(3 / 7, 5)), (
        r["reachable"], _r(r["required_blended_landed_acv"], 2), _r(a["required_mix_pct"], 5), _r(a["shift_pct_points"], 5), _r(a["current_mix_pct"], 5))


@case("Reverse-solve: the shift comes out of the segment with the lowest landed ACV")
def _sp_shift_source():
    _, years, base = _seg_paths(target_arr=1_000_000)
    sp, _, _ = _seg_paths(target_arr=base + 25_000 * 3 * years)
    r = sp["reverse_solve"]["12"]["by_segment"]
    return (True, True, r["A"]["shift_pct_points"] + r["B"]["shift_pct_points"] == 0 or abs(r["A"]["shift_pct_points"] + r["B"]["shift_pct_points"]) < 1e-9), (
        r["A"]["shift_pct_points"] > 0, r["B"]["shift_pct_points"] < 0,
        r["A"]["shift_pct_points"] == 0 or abs(r["A"]["shift_pct_points"] + r["B"]["shift_pct_points"]) < 1e-9)


@case("Reverse-solve: current mix already reaches the target -> no shift")
def _sp_no_shift():
    _, years, base = _seg_paths(target_arr=1_000_000)
    sp, _, _ = _seg_paths(target_arr=base + 15_000 * 3 * years)
    r = sp["reverse_solve"]["12"]
    return (True, 0.0), (r["reachable"], _r(r["moved_mix_pct"]))


@case("Reverse-solve: no mix reaches the target -> unreachable, and the rate needed at the current mix is stated")
def _sp_unreachable():
    _, years, base = _seg_paths(target_arr=1_000_000)
    gap = 50_000 * 3 * years                                # needs a blended 50,000 > best segment's 36,000
    sp, _, _ = _seg_paths(target_arr=base + gap)
    r = sp["reverse_solve"]["12"]
    cur = 3 / 7 * 36000 + 4 / 7 * 3600                      # landed ACV at the current customer mix
    need = gap / (cur * years)
    return (False, _r(cur, 2), _r(need, 4), _r(need / 3, 4), "required_mix_pct" in r["by_segment"]["A"]), (
        r["reachable"], _r(r["current_mix_landed_acv"], 2), _r(r["required_new_per_year_at_current_mix"], 4),
        _r(r["required_vs_observed_gross"], 4), "required_mix_pct" in r["by_segment"]["A"])


@case("Reverse-solve: current mix comes from the distribution of active customers (3 of 7 in A)")
def _sp_current_mix():
    _, years, base = _seg_paths(target_arr=1_000_000)
    sp, _, _ = _seg_paths(target_arr=base + 25_000 * 3 * years)
    r = sp["reverse_solve"]["12"]["by_segment"]
    return (_r(3 / 7, 5), _r(4 / 7, 5)), (_r(r["A"]["current_mix_pct"], 5), _r(r["B"]["current_mix_pct"], 5))


@case("24-month window not computable on 14 months of history: stated, not omitted")
def _sp_24_missing():
    sp, _, _ = _seg_paths(target_arr=1_000_000)
    l, r = sp["landed"]["24"], sp["reverse_solve"]["24"]
    return (False, True, False, True), (l["computable"], "24 months" in l["reason"], r["computable"], "24 months" in r["reason"])


@case("24-month window computable on 26 months of history: gross rate is 3 landings / 2 years")
def _sp_24_ok():
    sp, _, _ = _seg_paths(target_arr=1_000_000, n_months=26)
    return (True, 1.5, 3.0), (sp["landed"]["24"]["computable"], sp["landed"]["24"]["gross_new_per_year"], sp["landed"]["12"]["gross_new_per_year"])


@case("A segment with no landings in the window: reachability is undetermined and the segment is named")
def _sp_missing_landed():
    _, years, base = _seg_paths(target_arr=1_000_000, drop_b_landings=True)
    sp, _, _ = _seg_paths(target_arr=base + 10_000 * 1 * years, drop_b_landings=True)
    r = sp["reverse_solve"]["12"]
    return (None, True, False), (r["reachable"], "B" in r["reason"], "required_new_per_year_at_current_mix" in r)


@case("A segment with no NRR: no projection, no blended stand-in, and what would resolve it is named")
def _sp_no_nrr():
    sp, _, _ = _seg_paths(target_arr=1_000_000, only_new_segment=True)
    c = sp["stage_one"]["segments"]["C"]
    return (False, None, False, True, True), (
        sp["available"], c["projected_arr"], "projected_base_arr" in sp["stage_one"], "C" in sp["missing_inputs"][0]["input"],
        "gap_arr" not in sp)


@case("No segment column mapped: unavailable, resolution named, nothing invented")
def _sp_no_segments():
    sp, _, _ = _seg_paths(target_arr=1_000_000, no_segments=True)
    return (False, True, False), (sp["available"], "segment" in sp["missing_inputs"][0]["resolve"], "stage_one" in sp)


@case("Under 13 months of history: no segment NRR, so unavailable with the resolution named")
def _sp_short_history():
    sp, _, _ = _seg_paths(target_arr=1_000_000, n_months=10)
    return (False, True), (sp["available"], "13 months" in sp["missing_inputs"][0]["resolve"])


@case("An invalid target date makes the projection unavailable instead of guessing a horizon")
def _sp_bad_date():
    sp, _, _ = _seg_paths(target_arr=1_000_000, target_date="2020-01-01")
    return (False, True), (sp["available"], "target date" in sp["missing_inputs"][0]["input"])


@case("Segment paths run on segments only: ACV bands are untouched")
def _sp_bands_untouched():
    mrr, sm, fm = _seg_scenario()
    acv = ge.compute_acv_path(mrr, sm, fm, 1_000_000, "2026-03-15")
    keys = sorted(b["key"] for b in acv["bands"])
    return (sorted(k for k, *_ in ge.ACV_BANDS), 5), (keys, len(acv["bands"]))


# --- CAC payback: a partial quarter never headlines -------------------------
def _pnl_rows(spec):
    return pd.DataFrame([
        {"month": month(i), "sm_expense": sm, "revenue": rev, "cost_of_revenue": cost, "_row": i + 1}
        for i, (sm, rev, cost) in spec.items()
    ])


def _cac_with_partial_last_quarter():
    # N starts in Q2 (Apr-Jun, complete). P starts in Jul: Q3 has one month of data (partial).
    rows = monthly_lines("N", {3: 1000, 4: 1000, 5: 1000, 6: 1000})
    rows += monthly_lines("P", {6: 1000}, start_row=100)
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    new_q = ge.compute_new_mrr_by_quarter(mrr, fm)
    pnl = _pnl_rows({0: (1500, 0, 0), 1: (1500, 0, 0), 2: (1000, 0, 0),
                     3: (700, 400, 80), 4: (700, 300, 60), 5: (600, 300, 60), 6: (1000, 1000, 200)})
    return new_q, ge.compute_cac_payback(new_q, pnl, default_l=1)


@case("New MRR by quarter flags a quarter with fewer than 3 months of data as partial")
def _partial_flags():
    new_q, _ = _cac_with_partial_last_quarter()
    return ((3, False), (1, True)), (
        (new_q["2023-Q2"]["months_in_quarter"], new_q["2023-Q2"]["partial"]),
        (new_q["2023-Q3"]["months_in_quarter"], new_q["2023-Q3"]["partial"]),
    )


@case("CAC payback: headline is the last complete quarter; the partial one is excluded but still computed")
def _cac_headline_skips_partial():
    _, cac = _cac_with_partial_last_quarter()
    q3 = cac["quarters"]["2023-Q3"]
    return ("2023-Q2", "2023-Q3", True, True), (
        cac["headline_quarter"], cac["partial_quarter_excluded"],
        q3["partial"], q3["L1"]["months"] is not None,   # calculation unchanged, no pro-rating
    )


@case("CAC payback: with no complete quarter there is no headline, and the partial quarter is named")
def _cac_no_complete_quarter():
    rows = monthly_lines("P", {6: 1000})
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    new_q = ge.compute_new_mrr_by_quarter(mrr, fm)
    pnl = _pnl_rows({3: (700, 400, 80), 4: (700, 300, 60), 5: (600, 300, 60), 6: (1000, 1000, 200)})
    cac = ge.compute_cac_payback(new_q, pnl, default_l=1)
    return (None, "2023-Q3"), (cac["headline_quarter"], cac["partial_quarter_excluded"])


@case("CAC payback: a complete quarter is never flagged partial")
def _cac_complete_not_partial():
    _, cac = _cac_with_partial_last_quarter()
    return (False, 3), (cac["quarters"]["2023-Q2"]["partial"], cac["quarters"]["2023-Q2"]["months_in_quarter"])


# --- Missing Data reflects inputs that are actually missing ------------------
def _cac_gap_inputs(pnl_months):
    # Revenue in 2023-Q1..Q3 (N from January, P from July); the P&L covers only `pnl_months`.
    rows = monthly_lines("N", {i: 1000 for i in range(0, 9)})
    rows += monthly_lines("P", {6: 1000, 7: 1000, 8: 1000}, start_row=100)
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    new_q = ge.compute_new_mrr_by_quarter(mrr, fm)
    pnl = _pnl_rows({i: (1000, 1000, 200) for i in pnl_months})
    cac = ge.compute_cac_payback(new_q, pnl, default_l=1)
    return cac, ge._cac_input_gaps(cac, {"file": "pnl.csv"})


@case("Missing data: quarters with no P&L are listed, and the quarters they block at the default lag")
def _gap_no_pnl():
    cac, gaps = _cac_gap_inputs(pnl_months=[6, 7, 8])         # P&L for Q3 only; Q1 and Q2 are absent
    g = gaps[0]
    return (1, "CAC payback (quarters without P&L)", True, True, True, "pnl.csv"), (
        len(gaps), g["metric"], "No P&L rows for 2023-Q1, 2023-Q2" in g["reason"],
        "cannot be computed for 2023-Q2, 2023-Q3" in g["reason"], "2023-Q1, 2023-Q2" in g["unlocked_by"], g["file"])


@case("Missing data: the lag quarters before the first revenue quarter are not reported (they predate the data)")
def _gap_predates_data():
    _, gaps = _cac_gap_inputs(pnl_months=range(0, 9))
    return [], gaps


@case("Missing data: a complete P&L reports no CAC input gap")
def _gap_none():
    _, gaps = _cac_gap_inputs(pnl_months=range(0, 9))
    return [], gaps


@case("Missing data: a quarter whose P&L gives no usable gross margin is reported")
def _gap_margin():
    rows = monthly_lines("N", {3: 1000, 4: 1000, 5: 1000})
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    pnl = _pnl_rows({0: (4000, 0, 0), 3: (0, 100, 200), 4: (0, 100, 200), 5: (0, 100, 200)})
    gaps = ge._cac_input_gaps(ge.compute_cac_payback(ge.compute_new_mrr_by_quarter(mrr, fm), pnl, default_l=1), {"file": "pnl.csv"})
    return (1, "CAC payback (quarters without a usable gross margin)", True), (
        len(gaps), gaps[0]["metric"], "2023-Q2" in gaps[0]["reason"])


@case("Missing data: a genuine zero (no new customers) is not reported as a missing input")
def _gap_zero_is_not_missing():
    rows = monthly_lines("M", {i: 500 for i in range(0, 7)})
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    pnl = _pnl_rows({i: (1000, 1000, 200) for i in range(0, 7)})
    cac = ge.compute_cac_payback(ge.compute_new_mrr_by_quarter(mrr, fm), pnl, default_l=1)
    zero_reason = any(cac["quarters"][q]["L1"].get("reason") == "new MRR is zero" for q in cac["quarters"])
    return (True, []), (zero_reason, ge._cac_input_gaps(cac, {}))


@case("Missing data: observed net-new customer rates need 13 (12-month) and 25 (24-month) months of history")
def _gap_history():
    return ([1, "Observed net-new customers (12 and 24 months)", "Needs 25+ months of revenue history; have 10"],
            [1, "Observed net-new customers (24 months)", "Needs 25+ months of revenue history; have 20"], []), (
        [len(ge._history_gaps(10, {})), ge._history_gaps(10, {})[0]["metric"], ge._history_gaps(10, {})[0]["reason"]],
        [len(ge._history_gaps(20, {})), ge._history_gaps(20, {})[0]["metric"], ge._history_gaps(20, {})[0]["reason"]],
        ge._history_gaps(30, {}))


@case("Missing data end to end: a P&L that starts late puts the CAC gap in the results the panel reads")
def _gap_end_to_end():
    rows = monthly_lines("N", {3: 1000, 4: 1000, 5: 1000, 6: 1000, 7: 1000, 8: 1000})
    rows += monthly_lines("P", {6: 1000, 7: 1000, 8: 1000}, start_row=100)
    cfg = {"reporting_currency": "EUR", "fx": {"EUR": 1.0}, "target_arr": 1_000_000, "target_date": "2027-01-01",
           "default_l": 1, "billing_terms": {}}
    res = ge.compute_all(rev_df(rows), pd.DataFrame(), _pnl_rows({6: (1000, 1000, 200), 7: (1000, 1000, 200), 8: (1000, 1000, 200)}),
                         cfg, {"revenue": {"file": "r.csv"}, "crm": {"file": "c.csv"}, "pnl": {"file": "p.csv"}})
    metrics = [m["metric"] for m in res["missing_data"]]
    return True, "CAC payback (quarters without P&L)" in metrics


# --- Deals follow the same as-of cut as MRR and the P&L ---------------------
def _cut_deals():
    def deal(i, stage, created, closed):
        return {"deal_id": i, "stage": stage, "created_date": pd.Timestamp(created),
                "close_date": pd.Timestamp(closed) if closed else pd.NaT, "_row": i}
    return pd.DataFrame([
        deal(1, "won", "2024-01-05", "2024-02-10"),    # closed inside the period
        deal(2, "lost", "2024-01-06", "2024-03-31"),   # closed on the last day of the as-of month: kept
        deal(3, "won", "2024-02-01", "2024-04-01"),    # closed the day after: excluded
        deal(4, "lost", "2024-02-15", "2024-05-20"),   # excluded
        deal(5, "open", "2024-05-02", None),           # created after the as-of month: excluded
        deal(6, "open", "2024-03-02", None),           # still open at the as-of date: kept, not a closed deal
        deal(7, "won", "2024-03-02", None),            # won with no close date: cannot be placed, kept
    ])


@case("Deals cut at as-of: closed or created after the as-of month are dropped (3 of 7)")
def _deals_cut_count():
    kept, dropped = ge.cut_deals_at_as_of(_cut_deals(), pd.Period("2024-03", "M"))
    return (4, 3), (len(kept), dropped)


@case("Deals cut at as-of: last day of the as-of month is kept, the next day is not")
def _deals_cut_boundary():
    kept, _ = ge.cut_deals_at_as_of(_cut_deals(), pd.Period("2024-03", "M"))
    return [1, 2, 6, 7], sorted(kept["deal_id"].tolist())


@case("Deals cut at as-of: win rate counts only deals closed by the as-of month")
def _deals_cut_win_rate():
    kept, _ = ge.cut_deals_at_as_of(_cut_deals(), pd.Period("2024-03", "M"))
    wr = ge.compute_win_rate(kept, founder_available=False)
    return (2, 1), (wr["won"], wr["lost"])


@case("Deals cut at as-of: no as-of month leaves the deals untouched")
def _deals_cut_none():
    kept, dropped = ge.cut_deals_at_as_of(_cut_deals(), None)
    return (7, 0), (len(kept), dropped)


# --- Path to plan -----------------------------------------------------------
def _path_scenario():
    rows = []
    r = 1
    for c in ("B1", "B2", "B3", "B4"):
        rows += monthly_lines(c, {i: 1000 for i in range(0, 25)}, start_row=r); r += 40
    for c in ("L1", "L2", "L3", "L4", "L5", "L6"):
        rows += monthly_lines(c, {i: 1000 for i in range(18, 25)}, start_row=r); r += 40
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    return ge.compute_acv_path(mrr, seg, fm, target_arr=1_200_000, target_date="2027-01-01")


@case("Path to plan: total customers at target ARR = 100")
def _path_needed():
    return 100.0, _path_scenario()["total_customers_at_target"]


@case("Path to plan: additional customers needed = total at target - customers today (100 - 10 = 90)")
def _path_additional():
    ap = _path_scenario()
    return (90.0, 10, 100.0), (ap["additional_customers_needed"], ap["current_customers"], ap["total_customers_at_target"])


@case("Path to plan: the required net-new per year is the additional count spread over the years to target")
def _path_additional_matches_rate():
    ap = _path_scenario()
    years = ge._years_to_target(pd.Period("2025-01", "M"), "2027-01-01")[0]   # scenario's last month is 2025-01
    return ap["required_net_new_per_year"], ge._round(ap["additional_customers_needed"] / years, 1)


@case("Path to plan: no additional customers are needed when today's count already covers the target")
def _path_additional_floor():
    rows = []
    for i, c in enumerate(("X1", "X2", "X3", "X4")):
        rows += monthly_lines(c, {m: 1000 for m in range(0, 13)}, start_row=1 + 40 * i)
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    res = ge.compute_acv_path(mrr, seg, fm, target_arr=24_000, target_date="2027-01-01")   # below today's 48,000 ARR
    return (0.0, 2.0), (res["additional_customers_needed"], res["total_customers_at_target"])


@case("Path to plan: customers needed stored at full precision (not 1 decimal)")
def _path_needed_full_precision():
    rows = []
    for i, c in enumerate(("B1", "B2", "B3", "B4")):
        rows += monthly_lines(c, {m: 1000 for m in range(0, 25)}, start_row=1 + 40 * i)
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    res = ge.compute_acv_path(mrr, seg, fm, target_arr=1_234_567, target_date="2027-01-01")
    return 1_234_567 / 12_000, res["total_customers_at_target"]


@case("Path to plan: observed net-new 12m = 6.0/yr")
def _path_obs12():
    return 6.0, _path_scenario()["observed_net_new_per_year_12m"]


@case("Path to plan: observed net-new 24m = 3.0/yr")
def _path_obs24():
    return 3.0, _path_scenario()["observed_net_new_per_year_24m"]


@case("Path to plan: observed net-new not computable with < lookback months of history")
def _path_obs_insufficient_history():
    # Only 6 months of revenue history: neither the 12m nor 24m lookback has a
    # reference month, so both must report "not computable" (None), never treat
    # the missing starting count as 0 (which would overstate net-new customers).
    rows = []
    r = 1
    for c in ("A", "B", "C"):
        rows += monthly_lines(c, {i: 1000 for i in range(0, 6)}, start_row=r); r += 40
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    acv = ge.compute_acv_path(mrr, seg, fm, target_arr=1_200_000, target_date="2027-01-01")
    return (None, None), (acv["observed_net_new_per_year_12m"], acv["observed_net_new_per_year_24m"])


@case("Path to plan: required net-new/yr matches exact-day-count formula")
def _path_required():
    acv = _path_scenario()
    latest = pd.Period("2025-01", "M")
    now = latest.to_timestamp(how="end")
    years = max((pd.Timestamp("2027-01-01") - now).days / 365, 0.01)  # exact days ÷ 365, never a rounded 1.5
    expected = round((100.0 - 10) / years, 1)
    return expected, acv["required_net_new_per_year"]


@case("Path to plan: required ÷ observed(12m) ratio self-consistent")
def _path_ratio():
    acv = _path_scenario()
    latest = pd.Period("2025-01", "M")
    now = latest.to_timestamp(how="end")
    years = max((pd.Timestamp("2027-01-01") - now).days / 365, 0.01)
    raw_required = (100.0 - 10) / years  # unrounded, as the engine uses internally
    expected = round(raw_required / acv["observed_net_new_per_year_12m"], 2)
    return expected, acv["required_vs_observed_12m"]


@case("Path to plan: target date before as-of is flagged, not silently computed")
def _path_target_before_asof():
    # Same customer setup as the main path scenario, but the target date is set
    # to the as-of month itself (2025-01) — not after it. required_net_new_per_year
    # must be None (never an absurd figure), and target_date_error must explain why.
    rows = []
    r = 1
    for c in ("B1", "B2", "B3", "B4"):
        rows += monthly_lines(c, {i: 1000 for i in range(0, 25)}, start_row=r); r += 40
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    acv = ge.compute_acv_path(mrr, seg, fm, target_arr=1_200_000, target_date="2025-01-15")
    ok = acv["required_net_new_per_year"] is None and acv["target_date_error"] is not None
    return True, ok


@case("Path to plan: target date with an implausible year (0027) is flagged")
def _path_target_bad_year():
    rows = monthly_lines("A", {i: 1000 for i in range(0, 13)})
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    acv = ge.compute_acv_path(mrr, seg, fm, target_arr=1_200_000, target_date="0027-01-01")
    ok = acv["required_net_new_per_year"] is None and acv["target_date_error"] is not None
    return True, ok


@case("Path to plan: overall ACV band matches the per-customer bucketing")
def _path_overall_band():
    # Blended ACV here is 120,000 ARR / 10 customers = 12,000 annual, landing in
    # consultative_sales (10,000-100,000) — the same band every one of this
    # scenario's customers individually falls in (all flat at 1000/mo).
    acv = _path_scenario()
    ok = (
        acv["overall_band"] is not None
        and acv["overall_band"]["key"] == "consultative_sales"
        and acv["overall_band"]["label"] == "Consultative sales"
        and acv["overall_band"]["value_label"] == "€12K"
    )
    return True, ok


# --- Founder win-rate split + sales-cycle IQR -------------------------------
def _founder_deals():
    rows, rid = [], 1
    for _ in range(8):
        rows.append({"deal_id": rid, "stage": "won", "founder_involved": "yes", "_row": rid}); rid += 1
    for _ in range(2):
        rows.append({"deal_id": rid, "stage": "lost", "founder_involved": "yes", "_row": rid}); rid += 1
    for _ in range(22):
        rows.append({"deal_id": rid, "stage": "won", "founder_involved": "no", "_row": rid}); rid += 1
    for _ in range(68):
        rows.append({"deal_id": rid, "stage": "lost", "founder_involved": "no", "_row": rid}); rid += 1
    return pd.DataFrame(rows)


@case("Win rate WITH founder = 80.0%")
def _wr_with():
    return 0.8, ge.compute_win_rate(_founder_deals(), True)["by_founder"]["with_founder"]["win_rate_pct"]


@case("Win rate WITHOUT founder = 24.44%")
def _wr_without():
    return 0.2444, ge.compute_win_rate(_founder_deals(), True)["by_founder"]["without_founder"]["win_rate_pct"]


@case("CRM founder-involved value that isn't yes/no-like is flagged, not silently dropped")
def _wr_founder_unrecognized():
    rows = _founder_deals()
    extra = pd.DataFrame([
        {"deal_id": 9999, "stage": "won", "founder_involved": "maybe", "_row": 9999},
        {"deal_id": 10000, "stage": "lost", "founder_involved": "TBD", "_row": 10000},
        {"deal_id": 10001, "stage": "won", "founder_involved": None, "_row": 10001},  # blank stays silent
    ])
    deals = pd.concat([rows, extra], ignore_index=True)
    wr = ge.compute_win_rate(deals, True)
    fie = wr["founder_involved_excluded"]
    ok = fie["count"] == 2 and set(fie["rows"]) == {9999, 10000} and fie["values"] == ["maybe", "tbd"]
    return True, ok


@case("Sales-cycle IQR = [50.0, 70.0]")
def _cycle_iqr():
    created = pd.Timestamp("2024-01-01")
    deals = pd.DataFrame([
        {"deal_id": i, "stage": "won", "created_date": created,
         "close_date": created + pd.Timedelta(days=d), "_row": i}
        for i, d in enumerate([40, 50, 60, 70, 80], start=1)
    ])
    return [50.0, 70.0], ge.compute_sales_cycle(deals)["iqr"]


# --- NRR by segment / cohort + new MRR per quarter --------------------------
def _nrr_scenario():
    e = {i: 100 for i in range(16)}; e[15] = 120
    s = {i: 100 for i in range(3, 16)}; s[15] = 80
    rows = monthly_lines("E", e, segment="Ent")
    rows += monthly_lines("S", s, segment="SMB", start_row=100)
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    return ge.compute_nrr(mrr, seg, fm), ge.compute_new_mrr_by_quarter(mrr, fm)


@case("NRR overall (mixed cohorts) = 100%")
def _nrr_overall_mixed():
    return 1.0, _nrr_scenario()[0]["overall_pct"]


@case("NRR by segment: Enterprise = 120%")
def _nrr_seg_ent():
    return 1.2, _nrr_scenario()[0]["by_segment"]["Ent"]["nrr_pct"]


@case("NRR by segment: SMB = 80%")
def _nrr_seg_smb():
    return 0.8, _nrr_scenario()[0]["by_segment"]["SMB"]["nrr_pct"]


@case("NRR by cohort: 2023-Q1 = 120%")
def _nrr_cohort_q1():
    return 1.2, _nrr_scenario()[0]["by_cohort"]["2023-Q1"]["nrr_pct"]


@case("NRR by cohort: 2023-Q2 = 80%")
def _nrr_cohort_q2():
    return 0.8, _nrr_scenario()[0]["by_cohort"]["2023-Q2"]["nrr_pct"]


@case("New MRR 2023-Q1 = 100")
def _newmrr_q1():
    return 100.0, _nrr_scenario()[1]["2023-Q1"]["new_mrr"]


@case("New MRR 2023-Q2 = 100")
def _newmrr_q2():
    return 100.0, _nrr_scenario()[1]["2023-Q2"]["new_mrr"]


# --- Zero-revenue month -----------------------------------------------------
@case("Zero-revenue month total MRR = 0")
def _zero_month():
    rows = monthly_lines("Z", {0: 100, 1: 100, 3: 100})  # month index 2 has no revenue
    mrr, seg, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"EUR": 1.0})
    series = ge.compute_mrr_series(mrr, seg)
    return 0.0, series["data"][2]["total"]


# --- Source references (file / sheet / rows) --------------------------------
def _source_scenario():
    rev = pd.DataFrame([
        {"customer_id": "A", "invoice_date": month(i), "amount": 100, "currency": "EUR"} for i in range(13)
    ])
    rev.insert(0, "_row", range(2, len(rev) + 2))
    pnl = pd.DataFrame([
        {"month": month(i), "sm_expense": 1000, "revenue": 500, "cost_of_revenue": 100} for i in range(13)
    ])
    pnl.insert(0, "_row", range(2, len(pnl) + 2))
    config = {"reporting_currency": "EUR", "target_arr": 1_000_000, "target_date": "2027-01-01",
              "fx": {"EUR": 1.0}, "billing_terms": {}, "default_l": 1}
    sources = {"revenue": {"file": "rev.xlsx", "sheet": "S1"}, "pnl": {"file": "pnl.xlsx", "sheet": "P1"}}
    return ge.compute_all(rev, pd.DataFrame(), pnl, config, sources)


@case("Source ref (NRR) = rev.xlsx / S1 / rows 2–14")
def _src_nrr():
    s = _source_scenario()["nrr"]["source"]
    return "rev.xlsx|S1|rows 2–14 (13 rows)", f"{s['file']}|{s['sheet']}|{s['rows']}"


@case("Source ref (CAC) = pnl.xlsx / P1 / rows 2–14")
def _src_cac():
    s = _source_scenario()["cac_payback"]["source"]
    return "pnl.xlsx|P1|rows 2–14 (13 rows)", f"{s['file']}|{s['sheet']}|{s['rows']}"


# --- Missing-data panel when segment + founder columns are absent -----------
@case("Missing-data lists segment & founder splits")
def _missing_data():
    rev = pd.DataFrame(
        [{"customer_id": c, "invoice_date": month(i), "amount": 100, "currency": "EUR"}
         for c in ("A", "B") for i in range(13)]
    )
    rev.insert(0, "_row", range(2, len(rev) + 2))
    created = pd.Timestamp("2024-01-01")
    crm = pd.DataFrame([
        {"deal_id": 1, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=40)},
        {"deal_id": 2, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=60)},
        {"deal_id": 3, "stage": "lost", "created_date": created, "close_date": created + pd.Timedelta(days=30)},
    ])
    crm.insert(0, "_row", range(2, len(crm) + 2))
    pnl = pd.DataFrame([{"month": month(i), "sm_expense": 1000, "revenue": 500, "cost_of_revenue": 100} for i in range(13)])
    pnl.insert(0, "_row", range(2, len(pnl) + 2))
    config = {"reporting_currency": "EUR", "target_arr": 1_000_000, "target_date": "2027-01-01",
              "fx": {"EUR": 1.0}, "billing_terms": {}, "default_l": 1}
    sources = {"revenue": {"file": "r"}, "crm": {"file": "c"}, "pnl": {"file": "p"}}
    res = ge.compute_all(rev, crm, pnl, config, sources)
    metrics = {m["metric"] for m in res["missing_data"]}
    needed = {"NRR by segment", "Sales cycle by segment", "Win rate by founder involvement"}
    return True, needed.issubset(metrics)


# --- As-of month (item 1) ---------------------------------------------------
@case("As-of month: current MRR taken at as-of, not latest")
def _asof_current():
    rows = monthly_lines("A", {i: 100 + i for i in range(16)})  # rising MRR, months 0..15
    config = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None,
              "fx": {"EUR": 1.0}, "billing_terms": {}, "default_l": 1, "as_of_month": str(month(12).to_period("M"))}
    res = ge.compute_all(rev_df([{**r, "invoice_date": r["invoice_date"]} for r in rows]), pd.DataFrame(), pd.DataFrame(), config, {})
    # as-of is index 12 -> MRR must be 112 (not 115 from the latest month)
    return 112.0, res["arr"]["mrr"]


@case("As-of month: charts/series end at as-of month")
def _asof_series_end():
    rows = monthly_lines("A", {i: 100 for i in range(16)})
    config = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None,
              "fx": {"EUR": 1.0}, "billing_terms": {}, "default_l": 1, "as_of_month": str(month(12).to_period("M"))}
    res = ge.compute_all(rev_df(rows), pd.DataFrame(), pd.DataFrame(), config, {})
    return ("2024-01", 13), (res["mrr_series"]["months"][-1], len(res["mrr_series"]["months"]))


@case("As-of month defaults to last P&L month")
def _asof_default_pnl():
    rows = monthly_lines("A", {i: 100 for i in range(16)})
    pnl = pd.DataFrame([{"month": month(i), "sm_expense": 100, "revenue": 100, "cost_of_revenue": 20, "_row": i + 2}
                        for i in range(10)])  # P&L only through index 9
    config = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None,
              "fx": {"EUR": 1.0}, "billing_terms": {}, "default_l": 1, "as_of_month": None}
    res = ge.compute_all(rev_df(rows), pd.DataFrame(), pnl, config, {})
    return "2023-10", res["as_of_month"]  # index 9 = 2023-10


# --- Win rate excludes invalid deals (item 2) -------------------------------
@case("Win rate excludes close<created deals (3W/2L = 60%)")
def _winrate_excl_invalid():
    created = pd.Timestamp("2024-01-01")
    deals = pd.DataFrame([
        {"deal_id": 1, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=30), "_row": 1},
        {"deal_id": 2, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=40), "_row": 2},
        {"deal_id": 3, "stage": "won", "created_date": created, "close_date": created + pd.Timedelta(days=50), "_row": 3},
        {"deal_id": 4, "stage": "lost", "created_date": created, "close_date": created + pd.Timedelta(days=20), "_row": 4},
        {"deal_id": 5, "stage": "lost", "created_date": created, "close_date": created + pd.Timedelta(days=25), "_row": 5},
        {"deal_id": 6, "stage": "won", "created_date": created, "close_date": created - pd.Timedelta(days=5), "_row": 6},   # invalid
        {"deal_id": 7, "stage": "lost", "created_date": created, "close_date": created - pd.Timedelta(days=3), "_row": 7},  # invalid
    ])
    wr = ge.compute_win_rate(deals, False)
    return (0.6, 3, 2, 2), (wr["win_rate_pct"], wr["won"], wr["lost"], wr["excluded_invalid"])


# ---------------------------------------------------------------------------
# Runner + pytest hooks
# ---------------------------------------------------------------------------

# --- NRR fields say what they count, and a null NRR says why -----------------
def _demo_segment_paths(idx):
    mrr, seg, fm, _, spec = _demo_engine_inputs(idx)
    nrr = ge.compute_nrr(mrr, seg, fm)
    acv = ge.compute_acv_path(mrr, seg, fm, spec["target_arr"], spec["target_date"])
    return ge.compute_segment_paths(mrr, seg, fm, nrr, acv, spec["target_arr"], spec["target_date"])


@case("NRR: a cohort younger than 12 months has base 0, null NRR and a reason - never a bare zero")
def _nrr_young_cohort_reason():
    mrr, seg, fm, _, _ = _demo_engine_inputs(0)
    row = ge.compute_nrr(mrr, seg, fm)["by_cohort"]["2024-Q3"]
    return (None, 0, True, True), (row["nrr_pct"], row["nrr_base_customers"],
                                   row["reason"].startswith("cohort younger than 12 months"), "n" not in row)


@case("NRR: a cohort with a computable NRR carries no reason")
def _nrr_no_reason_when_computed():
    mrr, seg, fm, _, _ = _demo_engine_inputs(0)
    return False, "reason" in ge.compute_nrr(mrr, seg, fm)["by_cohort"]["2023-Q1"]


@case("NRR: every null nrr_pct in the payload has a reason (overall, segments and cohorts)")
def _nrr_every_null_explained():
    mrr, seg, fm, _, _ = _demo_engine_inputs(0)
    nrr = ge.compute_nrr(mrr, seg, fm)
    groups = list(nrr["by_cohort"].values()) + list(nrr["by_segment"].values()) + [nrr]
    nulls = [g for g in groups if g.get("nrr_pct", g.get("overall_pct")) is None]
    return (True, True), (len(nulls) > 0, all(g.get("reason") for g in nulls))


@case("NRR and gross churn state their 12-month window, so neither reads as one month")
def _windows_stated():
    mrr, seg, fm, _, _ = _demo_engine_inputs(0)
    return (12, 12), (ge.compute_nrr(mrr, seg, fm)["trailing_window_months"], ge.compute_gross_churn(mrr)["trailing_window_months"])


@case("Reconciliation: the segment ratio is the simple ratio times the three factors, exactly")
def _reconciliation_closes():
    sp = _demo_segment_paths(0)
    out = []
    for w, rc in sp["reconciliation"].items():
        if rc["available"]:
            prod = rc["path_to_plan_ratio"] * rc["factor_compounded_base"] * rc["factor_landed_acv"] * rc["factor_gross_rate"]
            out.append(abs(prod - rc["segment_ratio"]) < 1e-9 * rc["segment_ratio"])
    return (True, True), (len(out) > 0, all(out))


@case("Reconciliation: the simple ratio equals the Path to Plan ratio to its displayed precision")
def _reconciliation_matches_path_to_plan():
    mrr, seg, fm, _, _ = _demo_engine_inputs(0)
    acv = ge.compute_acv_path(mrr, seg, fm, 40_000_000, "2027-12-31")
    sp = _demo_segment_paths(0)
    return round(acv["required_vs_observed_12m"], 2), round(sp["reconciliation"]["12"]["path_to_plan_ratio"], 2)


@case("Reconciliation: each factor moves the ratio the right way (compounding and gross landings help; landed ACV hurts)")
def _reconciliation_directions():
    rc = _demo_segment_paths(0)["reconciliation"]["12"]
    return (True, True, True), (rc["factor_compounded_base"] < 1, rc["factor_landed_acv"] > 1, rc["factor_gross_rate"] < 1)


@case("Reconciliation: unavailable, with the reason, when active customers have no segment (the views differ in ARR)")
def _reconciliation_unsegmented():
    mrr, sm, fm = _seg_scenario()
    sm = dict(sm); sm.pop("A2")                               # one active customer loses its segment
    nrr = ge.compute_nrr(mrr, sm, fm)
    acv = ge.compute_acv_path(mrr, sm, fm, 1_000_000, "2026-03-15")
    rc = ge.compute_segment_paths(mrr, sm, fm, nrr, acv, 1_000_000, "2026-03-15")["reconciliation"]["12"]
    return (False, True), (rc["available"], "no segment" in rc["reason"])


@case("Reconciliation: unavailable when the target is already met by the base")
def _reconciliation_met():
    sp, _, _ = _seg_paths(target_arr=50_000)
    rc = sp["reconciliation"]["12"]
    return (False, True), (rc["available"], "reaches the target" in rc["reason"])


def run_all():
    results = []
    for name, fn in CASES.items():
        try:
            expected, actual = fn()
            passed = expected == actual
        except Exception as e:  # noqa: BLE001
            expected, actual, passed = "-", f"ERROR: {e}", False
        results.append((name, expected, actual, passed))
    return results


def test_all_metrics():
    for name, expected, actual, passed in run_all():
        assert passed, f"{name}: expected {expected}, got {actual}"


if __name__ == "__main__":
    rows = run_all()
    w = max(len(r[0]) for r in rows) + 2
    print(f"\n{'METRIC'.ljust(w)}{'EXPECTED'.ljust(28)}{'ACTUAL'.ljust(28)}RESULT")
    print("-" * (w + 64))
    npass = 0
    for name, expected, actual, passed in rows:
        npass += passed
        mark = "PASS" if passed else "FAIL"
        print(f"{name.ljust(w)}{str(expected).ljust(28)}{str(actual).ljust(28)}{mark}")
    print("-" * (w + 64))
    print(f"{npass}/{len(rows)} passed\n")

