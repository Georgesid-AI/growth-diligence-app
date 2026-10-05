"""Deterministic synthetic company data so the dashboard is populated on first load.

build(spec) -> (datasets, meta) where datasets maps dtype -> (DataFrame, mapping).
Column headers are realistic so the mapping wizard demos naturally.
"""

import numpy as np
import pandas as pd

# Fictional companies, clients and engagements: no client data (CLAUDE.md rule 15).
DEMO_AUDITS = [
    {"company_name": "Apex Cloud — Series B Diligence", "reporting_currency": "EUR",
     "target_arr": 40_000_000, "target_date": "2027-12-31", "seed": 7,
     "n_customers": 68, "months": 26, "start": "2023-01", "multi_ccy": True,
     "client_name": "Demo Growth Partners", "engagement_reference": "DEMO-ENG-001", "fiscal_year_end": 12},
    {"company_name": "OmniData Systems — Growth Buyout Review", "reporting_currency": "USD",
     "target_arr": 25_000_000, "target_date": "2027-06-30", "seed": 21,
     "n_customers": 52, "months": 24, "start": "2023-03", "multi_ccy": False,
     "client_name": "Demo Buyout Fund", "engagement_reference": "DEMO-ENG-002", "fiscal_year_end": 12},
]

SEGMENTS = [
    ("Enterprise", 4500, 9500, 0.020, 0.010),   # base low/high, monthly expansion rate, monthly churn prob
    ("Mid-Market", 1200, 3200, 0.015, 0.018),
    ("SMB", 120, 600, 0.008, 0.030),
]

REV_MAP = {"customer_id": "Customer", "invoice_date": "Invoice Date", "amount": "Amount",
           "currency": "Currency", "segment": "Segment", "revenue_type": "Revenue Type",
           "service_start": None, "service_end": None}
CRM_MAP = {"deal_id": "Deal ID", "created_date": "Created", "close_date": "Close Date",
           "stage": "Stage", "amount": "Amount", "segment": "Segment", "founder_involved": "Founder Involved"}
PNL_MAP = {"month": "Month", "sm_expense": "S&M Expense", "revenue": "Revenue", "cost_of_revenue": "Cost of Revenue"}


def build(spec):
    rng = np.random.default_rng(spec["seed"])
    n_months = spec["months"]
    start = pd.Period(spec["start"], freq="M")
    months = [start + i for i in range(n_months)]

    rev_rows, pnl_new_mrr = [], {}
    seg_pick = rng.choice(len(SEGMENTS), size=spec["n_customers"], p=[0.25, 0.4, 0.35])

    for ci in range(spec["n_customers"]):
        seg_name, lo, hi, exp_rate, churn_p = SEGMENTS[seg_pick[ci]]
        cust = f"CUST-{1000 + ci}"
        mrr = float(rng.uniform(lo, hi))
        first_i = int(rng.integers(0, n_months - 6))
        churned_at = None
        currency = spec["reporting_currency"]
        foreign_ccy = spec["multi_ccy"] and rng.random() < 0.25
        if foreign_ccy:
            currency = "USD"
        for i in range(first_i, n_months):
            if churned_at is not None:
                break
            m = months[i]
            amt = mrr
            if foreign_ccy:
                amt = mrr / 0.92  # invoiced in USD, converts back near base
            rev_rows.append({"Customer": cust, "Invoice Date": m.to_timestamp().date().isoformat(),
                             "Amount": round(amt, 2), "Currency": currency, "Segment": seg_name,
                             "Revenue Type": "recurring"})
            # occasional one-off services line (excluded from MRR)
            if rng.random() < 0.05:
                rev_rows.append({"Customer": cust, "Invoice Date": m.to_timestamp().date().isoformat(),
                                 "Amount": round(amt * 0.4, 2), "Currency": currency, "Segment": seg_name,
                                 "Revenue Type": "one-off"})
            mrr *= (1 + rng.normal(exp_rate, 0.01))
            if rng.random() < churn_p and i > first_i + 3:
                churned_at = i

    rev = pd.DataFrame(rev_rows)

    # ---- CRM deals ----
    crm_rows = []
    n_deals = spec["n_customers"] * 7
    for d in range(n_deals):
        seg = SEGMENTS[rng.integers(0, 3)][0]
        created = months[int(rng.integers(0, n_months))].to_timestamp() + pd.Timedelta(days=int(rng.integers(0, 27)))
        cycle = int(max(7, rng.normal({"Enterprise": 92, "Mid-Market": 58, "SMB": 28}[seg], 18)))
        r = rng.random()
        stage = "won" if r < 0.28 else ("lost" if r < 0.78 else "open")
        founder = "yes" if (seg == "Enterprise" and rng.random() < 0.6) else "no"
        close = (created + pd.Timedelta(days=cycle)) if stage in ("won", "lost") else None
        # inject a few invalid rows (close before created)
        if rng.random() < 0.01 and close is not None:
            close = created - pd.Timedelta(days=int(rng.integers(1, 10)))
        crm_rows.append({
            "Deal ID": f"D-{5000 + d}", "Created": created.date().isoformat(),
            "Close Date": close.date().isoformat() if close is not None else None,
            "Stage": stage, "Amount": round(float(rng.uniform(5000, 120000)), 2),
            "Segment": seg, "Founder Involved": founder,
        })
    crm = pd.DataFrame(crm_rows)

    # ---- P&L ----
    rev_by_month = rev[rev["Revenue Type"] == "recurring"].copy()
    rev_by_month["m"] = pd.to_datetime(rev_by_month["Invoice Date"]).dt.to_period("M").astype(str)
    monthly_rev = rev_by_month.groupby("m")["Amount"].sum()
    pnl_rows = []
    for m in months:
        key = str(m)
        rec_rev = float(monthly_rev.get(key, 0.0))
        total_rev = rec_rev * 1.15  # incl services
        pnl_rows.append({
            "Month": m.to_timestamp().date().isoformat(),
            "S&M Expense": round(rec_rev * float(rng.uniform(0.45, 0.75)), 2),
            "Revenue": round(total_rev, 2),
            "Cost of Revenue": round(total_rev * float(rng.uniform(0.18, 0.28)), 2),
        })
    pnl = pd.DataFrame(pnl_rows)

    datasets = {"revenue": (rev, REV_MAP), "crm": (crm, CRM_MAP), "pnl": (pnl, PNL_MAP)}
    meta = {
        "revenue": {"file": "Revenue_Lines.xlsx", "sheet": "Billing"},
        "crm": {"file": "CRM_Deals.csv", "sheet": "CSV"},
        "pnl": {"file": "PnL_Monthly.xlsx", "sheet": "PL"},
        "fx": {"USD": 0.92} if spec["multi_ccy"] else {},
    }
    return datasets, meta
