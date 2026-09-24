"""Synthetic-data unit tests for the deterministic growth engine.

Each scenario has a KNOWN answer. Run `python test_growth_engine.py` to print the
Stop-1 verification table (metric, expected, actual, pass/fail), or `pytest` to
assert. No LLM, no guessing — pure arithmetic checks.
"""

import pandas as pd

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
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
    res = ge.compute_nrr(mrr, seg, fm)
    return 110.0, res["overall_pct"]


@case("Gross revenue churn = 35%")
def _churn():
    rows = monthly_lines("A", {i: 100 for i in range(13)})                          # flat
    rows += monthly_lines("B", {i: (60 if i == 12 else 100) for i in range(13)}, start_row=100)   # -40 contraction
    rows += monthly_lines("C", {i: 100 for i in range(12)}, start_row=200)          # churns at m12 (0)
    rows += monthly_lines("D", {i: (150 if i == 12 else 100) for i in range(13)}, start_row=300)  # expansion (not netted)
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
    res = ge.compute_gross_churn(mrr)
    return 35.0, res["overall_pct"]


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
    return 30.0, res["win_rate_pct"]


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
    mrr, _, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {"X": "annual"}, {})
    dec_val = mrr.at["X", pd.Period("2023-12", "M")]
    return 100.0, ge._round(dec_val)


@case("Billing term 'annual' (no service dates): 1200 → 100/mo × 12 months")
def _annual_full_year():
    rows = [{"customer_id": "X", "invoice_date": month(0), "amount": 1200, "currency": "EUR", "_row": 1}]
    mrr, _, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {"X": "annual"}, {})
    vals = [ge._round(v) for v in mrr.loc["X"].values]
    return [100.0] * 12, vals


@case("FX conversion USD→EUR (rate 0.9)")
def _fx():
    rows = [{"customer_id": "U", "invoice_date": month(0), "amount": 1000, "currency": "USD", "_row": 1}]
    mrr, _, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {"USD": 0.9})
    return 900.0, ge._round(mrr.at["U", pd.Period("2023-01", "M")])


@case("Churn-and-return gap flagged")
def _gap():
    rows = monthly_lines("G", {0: 100, 1: 100, 5: 100})  # gap months 2,3,4
    mrr, _, fm, _, notes = ge.build_mrr_matrix(rev_df(rows), {}, {})
    flags = ge.compute_anomalies(mrr, rev_df(rows), pd.DataFrame(), notes)
    return True, ("G" in flags["revenue_gap_then_resume"])


@case("Negative MRR month flagged")
def _negative():
    rows = [
        {"customer_id": "R", "invoice_date": month(0), "amount": 500, "currency": "EUR", "_row": 1},
        {"customer_id": "R", "invoice_date": month(1), "amount": -500, "currency": "EUR", "_row": 2},
    ]
    mrr, _, _, _, notes = ge.build_mrr_matrix(rev_df(rows), {}, {})
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
    mrr, _, _, _, notes = ge.build_mrr_matrix(rev_df(rows), {}, {})
    flags = ge.compute_anomalies(mrr, rev_df(rows), pd.DataFrame(), notes)
    return 2, flags["revenue_missing_customer_id"]["count"]


@case("One-off revenue excluded from MRR")
def _oneoff():
    rows = [
        {"customer_id": "A", "invoice_date": month(0), "amount": 100, "currency": "EUR", "revenue_type": "recurring", "_row": 1},
        {"customer_id": "A", "invoice_date": month(0), "amount": 999, "currency": "EUR", "revenue_type": "one-off", "_row": 2},
    ]
    mrr, _, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
    return 100.0, ge._round(mrr.at["A", pd.Period("2023-01", "M")])


@case("CAC payback L=1 = 5.0 months")
def _cac():
    # New customer N first revenue in 2023-Q2 (Apr), MRR 1000/mo through Jun.
    rows = monthly_lines("N", {3: 1000, 4: 1000, 5: 1000})
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
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
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
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


@case("ACV bands: 1 elephant, 1 mouse")
def _acv_bands():
    rows = monthly_lines("BIG", {12: 20000})   # annual 240k → elephant
    rows += monthly_lines("SMALL", {12: 50}, start_row=100)  # annual 600 → mouse
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
    acv = ge.compute_acv_path(mrr, seg, fm, target_arr=10_000_000, target_date="2026-01-01")
    ok = acv["bands"]["elephants"] == 1 and acv["bands"]["mice"] == 1
    return True, ok


@case("Cohort month-6 retention = 130%")
def _cohort_m6():
    vals = {i: 100 for i in range(7)}
    vals[6] = 130  # month-6 MRR is 130% of the starting month
    rows = monthly_lines("A", vals)
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
    coh = ge.compute_cohort_retention(mrr, fm)
    return 130.0, coh["data"][0]["values"]["6"]


# --- CAC payback at L=0 / L=2 / zero-new-MRR --------------------------------
def _cac_scenario():
    rows = monthly_lines("M", {i: 500 for i in range(0, 7)})   # Jan–Jul, Q1 cohort
    rows += monthly_lines("N", {i: 1000 for i in range(3, 6)}, start_row=100)  # Apr–Jun, Q2 cohort
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
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


# --- Path to plan -----------------------------------------------------------
def _path_scenario():
    rows = []
    r = 1
    for c in ("B1", "B2", "B3", "B4"):
        rows += monthly_lines(c, {i: 1000 for i in range(0, 25)}, start_row=r); r += 40
    for c in ("L1", "L2", "L3", "L4", "L5", "L6"):
        rows += monthly_lines(c, {i: 1000 for i in range(18, 25)}, start_row=r); r += 40
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
    return ge.compute_acv_path(mrr, seg, fm, target_arr=1_200_000, target_date="2027-01-01")


@case("Path to plan: customers needed = 100")
def _path_needed():
    return 100.0, _path_scenario()["customers_needed"]


@case("Path to plan: observed net-new 12m = 6.0/yr")
def _path_obs12():
    return 6.0, _path_scenario()["observed_net_new_per_year_12m"]


@case("Path to plan: observed net-new 24m = 3.0/yr")
def _path_obs24():
    return 3.0, _path_scenario()["observed_net_new_per_year_24m"]


@case("Path to plan: required net-new/yr matches date formula")
def _path_required():
    acv = _path_scenario()
    latest = pd.Period("2025-01", "M")
    now = latest.to_timestamp(how="end")
    years = max((pd.Timestamp("2027-01-01") - now).days / 365.25, 0.01)
    expected = round((100.0 - 10) / years, 1)
    return expected, acv["required_net_new_per_year"]


@case("Path to plan: required ÷ observed(12m) ratio self-consistent")
def _path_ratio():
    acv = _path_scenario()
    latest = pd.Period("2025-01", "M")
    now = latest.to_timestamp(how="end")
    years = max((pd.Timestamp("2027-01-01") - now).days / 365.25, 0.01)
    raw_required = (100.0 - 10) / years  # unrounded, as the engine uses internally
    expected = round(raw_required / acv["observed_net_new_per_year_12m"], 2)
    return expected, acv["required_vs_observed_12m"]


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
    return 80.0, ge.compute_win_rate(_founder_deals(), True)["by_founder"]["with_founder"]["win_rate_pct"]


@case("Win rate WITHOUT founder = 24.44%")
def _wr_without():
    return 24.44, ge.compute_win_rate(_founder_deals(), True)["by_founder"]["without_founder"]["win_rate_pct"]


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
    mrr, seg, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
    return ge.compute_nrr(mrr, seg, fm), ge.compute_new_mrr_by_quarter(mrr, fm)


@case("NRR overall (mixed cohorts) = 100%")
def _nrr_overall_mixed():
    return 100.0, _nrr_scenario()[0]["overall_pct"]


@case("NRR by segment: Enterprise = 120%")
def _nrr_seg_ent():
    return 120.0, _nrr_scenario()[0]["by_segment"]["Ent"]["nrr_pct"]


@case("NRR by segment: SMB = 80%")
def _nrr_seg_smb():
    return 80.0, _nrr_scenario()[0]["by_segment"]["SMB"]["nrr_pct"]


@case("NRR by cohort: 2023-Q1 = 120%")
def _nrr_cohort_q1():
    return 120.0, _nrr_scenario()[0]["by_cohort"]["2023-Q1"]["nrr_pct"]


@case("NRR by cohort: 2023-Q2 = 80%")
def _nrr_cohort_q2():
    return 80.0, _nrr_scenario()[0]["by_cohort"]["2023-Q2"]["nrr_pct"]


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
    mrr, seg, _, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
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
              "fx": {}, "billing_terms": {}, "default_l": 1}
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
              "fx": {}, "billing_terms": {}, "default_l": 1}
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
              "fx": {}, "billing_terms": {}, "default_l": 1, "as_of_month": str(month(12).to_period("M"))}
    res = ge.compute_all(rev_df([{**r, "invoice_date": r["invoice_date"]} for r in rows]), pd.DataFrame(), pd.DataFrame(), config, {})
    # as-of is index 12 -> MRR must be 112 (not 115 from the latest month)
    return 112.0, res["arr"]["mrr"]


@case("As-of month: charts/series end at as-of month")
def _asof_series_end():
    rows = monthly_lines("A", {i: 100 for i in range(16)})
    config = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None,
              "fx": {}, "billing_terms": {}, "default_l": 1, "as_of_month": str(month(12).to_period("M"))}
    res = ge.compute_all(rev_df(rows), pd.DataFrame(), pd.DataFrame(), config, {})
    return ("2024-01", 13), (res["mrr_series"]["months"][-1], len(res["mrr_series"]["months"]))


@case("As-of month defaults to last P&L month")
def _asof_default_pnl():
    rows = monthly_lines("A", {i: 100 for i in range(16)})
    pnl = pd.DataFrame([{"month": month(i), "sm_expense": 100, "revenue": 100, "cost_of_revenue": 20, "_row": i + 2}
                        for i in range(10)])  # P&L only through index 9
    config = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None,
              "fx": {}, "billing_terms": {}, "default_l": 1, "as_of_month": None}
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
    return (60.0, 3, 2, 2), (wr["win_rate_pct"], wr["won"], wr["lost"], wr["excluded_invalid"])


# ---------------------------------------------------------------------------
# Runner + pytest hooks
# ---------------------------------------------------------------------------

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
