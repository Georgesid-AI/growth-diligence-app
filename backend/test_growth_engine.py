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


@case("Cohort retention starts at 100%")
def _cohort():
    rows = monthly_lines("A", {i: 100 for i in range(6)})
    mrr, _, fm, _, _ = ge.build_mrr_matrix(rev_df(rows), {}, {})
    coh = ge.compute_cohort_retention(mrr, fm)
    return 100.0, coh["data"][0]["values"]["0"]


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
