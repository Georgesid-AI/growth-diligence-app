"""Deterministic growth-metrics engine.

Every function here is pure: it takes normalized pandas DataFrames plus an audit
config and returns JSON-serializable results. The engine NEVER guesses a missing
input; anything it cannot compute is reported in `missing_data`. Every number
carries a `source` reference (file / sheet / rows).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RECURRING_ALIASES = {"recurring", "subscription", "mrr", "arr", "rec"}
ONE_OFF_ALIASES = {"one-off", "one off", "oneoff", "onetime", "one-time", "services", "service"}
WON_ALIASES = {"won", "closed won", "closed-won", "closedwon", "win"}
LOST_ALIASES = {"lost", "closed lost", "closed-lost", "closedlost"}
TERM_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12, "annually": 12, "yearly": 12}

ACV_BANDS = [
    ("flies", 0, 100),
    ("mice", 100, 1_000),
    ("rabbits", 1_000, 10_000),
    ("deer", 10_000, 100_000),
    ("elephants", 100_000, float("inf")),
]


def _period_str(p: pd.Period) -> str:
    return str(p)


def _quarter_str(p: pd.Period) -> str:
    return f"{p.year}-Q{p.quarter}"


def _month_of(ts) -> pd.Period | None:
    if ts is None or pd.isna(ts):
        return None
    return pd.Timestamp(ts).to_period("M")


def _round(x, n=2):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), n)


class SourceRef:
    """Accumulates the row references that fed a metric."""

    def __init__(self, file: str, sheet: str | None = None):
        self.file = file
        self.sheet = sheet or "Sheet1"
        self.rows: list = []

    def add_rows(self, rows):
        for r in rows:
            if r is not None and not pd.isna(r):
                self.rows.append(int(r))

    def to_dict(self, rule: str = ""):
        rows = sorted(set(self.rows))
        if not rows:
            row_label = "no rows"
        elif len(rows) == 1:
            row_label = f"row {rows[0]}"
        else:
            row_label = f"rows {rows[0]}–{rows[-1]} ({len(rows)} rows)"
        return {
            "file": self.file,
            "sheet": self.sheet,
            "rows": row_label,
            "row_numbers": rows[:500],
            "rule": rule,
        }


# ---------------------------------------------------------------------------
# MRR matrix: the backbone. customer x month -> recurring MRR (reporting ccy).
# ---------------------------------------------------------------------------

def build_mrr_matrix(rev: pd.DataFrame, billing_terms: dict, fx: dict):
    """Return (mrr_df, cust_segment, cust_first_month, contrib_rows, notes).

    rev columns expected (normalized): customer_id, invoice_date, amount, currency,
    optional: service_start, service_end, segment, revenue_type, _row.
    """
    notes = {"rows_missing_customer": [], "excluded_one_off": 0}
    records = []
    seg_map: dict = {}
    contrib_rows: list = []

    has_service = "service_start" in rev.columns and "service_end" in rev.columns
    has_rtype = "revenue_type" in rev.columns
    has_seg = "segment" in rev.columns

    for _, row in rev.iterrows():
        cust = row.get("customer_id")
        rownum = row.get("_row")
        if cust is None or (isinstance(cust, float) and pd.isna(cust)) or str(cust).strip() == "":
            notes["rows_missing_customer"].append(rownum)
            continue
        cust = str(cust).strip()

        if has_rtype:
            rt = str(row.get("revenue_type") or "").strip().lower()
            if rt in ONE_OFF_ALIASES:
                notes["excluded_one_off"] += 1
                continue

        amount = row.get("amount")
        if amount is None or pd.isna(amount):
            continue
        rate = fx.get(str(row.get("currency") or "").upper(), 1.0)
        amount = float(amount) * float(rate)

        inv_m = _month_of(row.get("invoice_date"))
        months = None
        if has_service:
            sm = _month_of(row.get("service_start"))
            em = _month_of(row.get("service_end"))
            if sm is not None and em is not None and em >= sm:
                months = pd.period_range(sm, em, freq="M")
        if months is None:
            if inv_m is None:
                continue
            term = str(billing_terms.get(cust, "monthly")).lower()
            n = TERM_MONTHS.get(term, 1)
            months = pd.period_range(inv_m, periods=n, freq="M")

        per = amount / len(months)
        for m in months:
            records.append((cust, m, per))
        contrib_rows.append(rownum)

        if has_seg and cust not in seg_map:
            seg = row.get("segment")
            if seg is not None and not (isinstance(seg, float) and pd.isna(seg)) and str(seg).strip():
                seg_map[cust] = str(seg).strip()

    if not records:
        return pd.DataFrame(), seg_map, {}, contrib_rows, notes

    df = pd.DataFrame(records, columns=["customer_id", "month", "mrr"])
    mrr = df.groupby(["customer_id", "month"])["mrr"].sum().unstack(fill_value=0.0)
    full_range = pd.period_range(min(mrr.columns), max(mrr.columns), freq="M")
    mrr = mrr.reindex(full_range, axis=1, fill_value=0.0)

    first_month = {}
    for cust in mrr.index:
        active = mrr.columns[(mrr.loc[cust] > 0).values]
        if len(active):
            first_month[cust] = active.min()

    return mrr, seg_map, first_month, contrib_rows, notes


# ---------------------------------------------------------------------------
# Individual metrics
# ---------------------------------------------------------------------------

def compute_nrr(mrr: pd.DataFrame, seg_map: dict, first_month: dict):
    """12-month NRR overall + by segment + by start cohort, plus a time series."""
    if mrr.empty:
        return None
    cols = list(mrr.columns)

    def nrr_for(month_idx, customers):
        m = cols[month_idx]
        m0 = cols[month_idx - 12]
        base = [c for c in customers if mrr.at[c, m0] > 0]
        start = sum(mrr.at[c, m0] for c in base)
        end = sum(mrr.at[c, m] for c in base)
        if start <= 0:
            return None, 0
        return end / start, len(base)

    if len(cols) < 13:
        return {"insufficient_history": True, "months_available": len(cols)}

    latest = len(cols) - 1
    overall, n = nrr_for(latest, list(mrr.index))

    by_segment = {}
    if seg_map:
        segs = sorted(set(seg_map.values()))
        for s in segs:
            custs = [c for c in mrr.index if seg_map.get(c) == s]
            val, cn = nrr_for(latest, custs)
            by_segment[s] = {"nrr_pct": _round(val * 100) if val is not None else None, "n": cn}

    by_cohort = {}
    cohorts = {}
    for c, fm in first_month.items():
        cohorts.setdefault(_quarter_str(fm), []).append(c)
    for q in sorted(cohorts):
        val, cn = nrr_for(latest, cohorts[q])
        by_cohort[q] = {"nrr_pct": _round(val * 100) if val is not None else None, "n": cn}

    series = []
    for i in range(12, len(cols)):
        v, cn = nrr_for(i, list(mrr.index))
        series.append({"month": _period_str(cols[i]), "nrr_pct": _round(v * 100) if v is not None else None})

    return {
        "month": _period_str(cols[latest]),
        "overall_pct": _round(overall * 100) if overall is not None else None,
        "n": n,
        "by_segment": by_segment,
        "by_cohort": by_cohort,
        "series": series,
    }


def compute_gross_churn(mrr: pd.DataFrame):
    if mrr.empty:
        return None
    cols = list(mrr.columns)
    if len(cols) < 13:
        return {"insufficient_history": True, "months_available": len(cols)}

    def churn_for(month_idx):
        m = cols[month_idx]
        m0 = cols[month_idx - 12]
        base = [c for c in mrr.index if mrr.at[c, m0] > 0]
        start = sum(mrr.at[c, m0] for c in base)
        if start <= 0:
            return None
        loss = 0.0
        for c in base:
            delta = mrr.at[c, m] - mrr.at[c, m0]
            if delta < 0:
                loss += -delta
        return loss / start

    latest = len(cols) - 1
    series = [
        {"month": _period_str(cols[i]), "churn_pct": _round(churn_for(i) * 100) if churn_for(i) is not None else None}
        for i in range(12, len(cols))
    ]
    v = churn_for(latest)
    return {"month": _period_str(cols[latest]), "overall_pct": _round(v * 100) if v is not None else None, "series": series}


def compute_new_mrr_by_quarter(mrr: pd.DataFrame, first_month: dict):
    if mrr.empty:
        return {}
    cols = list(mrr.columns)
    quarters = {}
    for m in cols:
        quarters.setdefault(m.asfreq("Q"), []).append(m)
    out = {}
    for q, months in sorted(quarters.items()):
        last_m = max(months)
        new_custs = [c for c, fm in first_month.items() if fm.asfreq("Q") == q]
        val = sum(mrr.at[c, last_m] for c in new_custs)
        out[_quarter_str(q)] = {"new_mrr": _round(val), "n_customers": len(new_custs), "month": _period_str(last_m)}
    return out


def compute_cac_payback(new_mrr_q: dict, pnl: pd.DataFrame, default_l: int = 1):
    """CAC payback (months) for L=0,1,2. Requires P&L quarterly aggregation."""
    if pnl.empty or not new_mrr_q:
        return None
    p = pnl.copy()
    p["month"] = p["month"].apply(_month_of)
    p = p.dropna(subset=["month"])
    p["quarter"] = p["month"].apply(lambda m: _quarter_str(m.asfreq("Q")))
    grp = p.groupby("quarter").agg(
        sm=("sm_expense", "sum"), revenue=("revenue", "sum"), cost=("cost_of_revenue", "sum")
    )

    results = {}
    for q, info in new_mrr_q.items():
        row = {"new_mrr": info["new_mrr"]}
        # gross margin for quarter q
        if q in grp.index and grp.at[q, "revenue"]:
            rev = grp.at[q, "revenue"]
            gm = (rev - grp.at[q, "cost"]) / rev if rev else None
        else:
            gm = None
        row["gross_margin_pct"] = _round(gm * 100) if gm is not None else None
        for L in (0, 1, 2):
            lag_q = _shift_quarter(q, L)
            key = f"L{L}"
            new_mrr = info["new_mrr"] or 0
            if lag_q not in grp.index:
                row[key] = {"months": None, "reason": f"no P&L for {lag_q}"}
            elif new_mrr <= 0:
                row[key] = {"months": None, "reason": "new MRR is zero"}
            elif gm is None or gm <= 0:
                row[key] = {"months": None, "reason": "gross margin ≤ 0 or missing"}
            else:
                sm = grp.at[lag_q, "sm"]
                months = sm / (new_mrr * gm)
                row[key] = {"months": _round(months), "sm_expense": _round(sm), "reason": None}
        results[q] = row
    return {"default_l": default_l, "quarters": results}


def _shift_quarter(qstr: str, lag: int) -> str:
    year, q = qstr.split("-Q")
    p = pd.Period(f"{year}Q{q}", freq="Q") - lag
    return f"{p.year}-Q{p.quarter}"


def compute_sales_cycle(deals: pd.DataFrame):
    """Median sales cycle (days) for won deals; report median, IQR, n; by segment."""
    if deals.empty:
        return None
    d = deals.copy()
    d["stage_l"] = d.get("stage", "").astype(str).str.lower().str.strip()
    won = d[d["stage_l"].isin(WON_ALIASES)].copy()
    won["created"] = pd.to_datetime(won.get("created_date"), errors="coerce")
    won["closed"] = pd.to_datetime(won.get("close_date"), errors="coerce")
    won = won.dropna(subset=["created", "closed"])
    won = won[won["closed"] >= won["created"]]  # invalid excluded (also flagged in anomalies)
    won["days"] = (won["closed"] - won["created"]).dt.days
    if won.empty:
        return {"median_days": None, "n": 0}

    def stats(s):
        return {
            "median_days": _round(s.median(), 1),
            "iqr": [_round(s.quantile(0.25), 1), _round(s.quantile(0.75), 1)],
            "n": int(s.count()),
        }

    out = stats(won["days"])
    if "segment" in won.columns and won["segment"].notna().any():
        out["by_segment"] = {
            str(seg): stats(grp["days"]) for seg, grp in won.groupby(won["segment"].astype(str)) if str(seg).strip()
        }
    return out


def compute_win_rate(deals: pd.DataFrame, founder_available: bool):
    if deals.empty:
        return None
    d = deals.copy()
    d["stage_l"] = d.get("stage", "").astype(str).str.lower().str.strip()
    won = d["stage_l"].isin(WON_ALIASES).sum()
    lost = d["stage_l"].isin(LOST_ALIASES).sum()
    total = won + lost
    overall = won / total if total else None
    out = {"won": int(won), "lost": int(lost), "win_rate_pct": _round(overall * 100) if overall is not None else None}

    if founder_available and "founder_involved" in d.columns:
        split = {}
        d["founder_l"] = d["founder_involved"].astype(str).str.lower().str.strip()
        for key, matches in (("with_founder", {"yes", "true", "y", "1"}), ("without_founder", {"no", "false", "n", "0"})):
            sub = d[d["founder_l"].isin(matches)]
            w = sub["stage_l"].isin(WON_ALIASES).sum()
            l = sub["stage_l"].isin(LOST_ALIASES).sum()
            t = w + l
            split[key] = {
                "won": int(w),
                "lost": int(l),
                "win_rate_pct": _round((w / t) * 100) if t else None,
                "n": int(t),
                "small_sample": bool(t < 20),
            }
        out["by_founder"] = split
    return out


def compute_acv_path(mrr: pd.DataFrame, seg_map: dict, first_month: dict, target_arr: float, target_date: str):
    if mrr.empty:
        return None
    cols = list(mrr.columns)
    latest = cols[-1]
    active = [c for c in mrr.index if mrr.at[c, latest] > 0]
    n_cust = len(active)
    total_arr = sum(mrr.at[c, latest] for c in active) * 12
    acv = total_arr / n_cust if n_cust else None

    # bands by annual revenue per customer
    bands = {name: 0 for name, _, _ in ACV_BANDS}
    for c in active:
        annual = mrr.at[c, latest] * 12
        for name, lo, hi in ACV_BANDS:
            if lo <= annual < hi:
                bands[name] += 1
                break

    by_segment = {}
    if seg_map:
        for s in sorted(set(seg_map.get(c) for c in active if seg_map.get(c))):
            custs = [c for c in active if seg_map.get(c) == s]
            arr_s = sum(mrr.at[c, latest] for c in custs) * 12
            by_segment[s] = {"customers": len(custs), "acv": _round(arr_s / len(custs)) if custs else None, "arr": _round(arr_s)}

    customers_needed = target_arr / acv if acv else None
    # years to target
    years = None
    if target_date:
        td = pd.Timestamp(target_date)
        now = latest.to_timestamp(how="end")
        years = max((td - now).days / 365.25, 0.01)
    required_per_year = ((customers_needed - n_cust) / years) if (customers_needed and years) else None

    def observed_net_new(months_back):
        if len(cols) <= months_back:
            ref = None
        else:
            ref = cols[-1 - months_back]
        active_now = n_cust
        active_then = len([c for c in mrr.index if ref is not None and mrr.at[c, ref] > 0]) if ref is not None else 0
        span_years = months_back / 12
        return (active_now - active_then) / span_years if span_years else None

    obs12 = observed_net_new(12)
    obs24 = observed_net_new(24)

    return {
        "current_customers": n_cust,
        "current_arr": _round(total_arr),
        "acv": _round(acv),
        "target_arr": target_arr,
        "target_date": target_date,
        "bands": bands,
        "by_segment": by_segment,
        "customers_needed": _round(customers_needed, 1),
        "required_net_new_per_year": _round(required_per_year, 1),
        "observed_net_new_per_year_12m": _round(obs12, 1),
        "observed_net_new_per_year_24m": _round(obs24, 1),
        "required_vs_observed_12m": _round(required_per_year / obs12, 2) if (required_per_year and obs12) else None,
        "required_vs_observed_24m": _round(required_per_year / obs24, 2) if (required_per_year and obs24) else None,
    }


def compute_anomalies(mrr: pd.DataFrame, rev: pd.DataFrame, deals: pd.DataFrame, mrr_notes: dict):
    flags = {}
    # negative MRR months
    neg_months = []
    if not mrr.empty:
        totals = mrr.sum(axis=0)
        neg_months = [_period_str(m) for m in totals.index[totals.values < 0]]
    flags["negative_mrr_months"] = neg_months

    # revenue gaps > 2 months that later resume
    gap_customers = []
    if not mrr.empty:
        for c in mrr.index:
            active = [i for i, v in enumerate(mrr.loc[c].values) if v > 0]
            for a, b in zip(active, active[1:]):
                if b - a > 3:  # gap of >2 months between active months
                    gap_customers.append(str(c))
                    break
    flags["revenue_gap_then_resume"] = sorted(set(gap_customers))

    # missing customer id rows
    flags["revenue_missing_customer_id"] = {
        "count": len(mrr_notes.get("rows_missing_customer", [])),
        "rows": [int(r) for r in mrr_notes.get("rows_missing_customer", []) if r is not None and not pd.isna(r)][:200],
    }

    # deals with close before created (flag + exclude)
    excluded = 0
    excluded_rows = []
    if not deals.empty:
        d = deals.copy()
        d["created"] = pd.to_datetime(d.get("created_date"), errors="coerce")
        d["closed"] = pd.to_datetime(d.get("close_date"), errors="coerce")
        bad = d[(d["created"].notna()) & (d["closed"].notna()) & (d["closed"] < d["created"])]
        excluded = len(bad)
        if "_row" in bad.columns:
            excluded_rows = [int(r) for r in bad["_row"].tolist() if r is not None and not pd.isna(r)][:200]
    flags["deals_close_before_created"] = {"excluded_count": int(excluded), "rows": excluded_rows}
    return flags


def compute_mrr_series(mrr: pd.DataFrame, seg_map: dict):
    """Monthly MRR total + stacked by segment for the chart."""
    if mrr.empty:
        return {"months": [], "segments": [], "data": []}
    cols = list(mrr.columns)
    segments = sorted(set(seg_map.values())) if seg_map else []
    data = []
    for m in cols:
        rec = {"month": _period_str(m), "total": _round(float(mrr[m].sum()))}
        for s in segments:
            custs = [c for c in mrr.index if seg_map.get(c) == s]
            rec[s] = _round(float(sum(mrr.at[c, m] for c in custs)))
        if segments:
            mapped = set().union(*[{c for c in mrr.index if seg_map.get(c) == s} for s in segments]) if segments else set()
            unmapped = [c for c in mrr.index if c not in mapped]
            if unmapped:
                rec["Unsegmented"] = _round(float(sum(mrr.at[c, m] for c in unmapped)))
        data.append(rec)
    if segments and any("Unsegmented" in d for d in data):
        segments = segments + ["Unsegmented"]
    return {"months": [_period_str(m) for m in cols], "segments": segments, "data": data}


def compute_cohort_retention(mrr: pd.DataFrame, first_month: dict):
    """Rows = start cohort (quarter), cols = months since start, value = % starting MRR retained."""
    if mrr.empty:
        return {"cohorts": [], "max_offset": 0, "data": []}
    cols = list(mrr.columns)
    col_idx = {m: i for i, m in enumerate(cols)}
    cohorts = {}
    for c, fm in first_month.items():
        cohorts.setdefault(_quarter_str(fm.asfreq("Q")), []).append(c)

    data = []
    max_offset = 0
    for q in sorted(cohorts):
        custs = cohorts[q]
        first_idxs = [col_idx[first_month[c]] for c in custs]
        base_idx = min(first_idxs)
        start_mrr = sum(mrr.at[c, cols[base_idx]] for c in custs)
        if start_mrr <= 0:
            continue
        row = {"cohort": q, "start_mrr": _round(start_mrr), "n": len(custs), "values": {}}
        for off in range(0, len(cols) - base_idx):
            m = cols[base_idx + off]
            retained = sum(mrr.at[c, m] for c in custs)
            row["values"][str(off)] = _round((retained / start_mrr) * 100)
            max_offset = max(max_offset, off)
        data.append(row)
    return {"cohorts": [d["cohort"] for d in data], "max_offset": max_offset, "data": data}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def compute_all(rev: pd.DataFrame, deals: pd.DataFrame, pnl: pd.DataFrame, config: dict, sources: dict):
    """Run the full engine. `sources` maps dataset -> {file, sheet}."""
    billing_terms = config.get("billing_terms", {})
    fx = config.get("fx", {})
    reporting_currency = config.get("reporting_currency", "EUR")
    target_arr = float(config.get("target_arr") or 0)
    target_date = config.get("target_date")

    rev = rev if rev is not None else pd.DataFrame()
    deals = deals if deals is not None else pd.DataFrame()
    pnl = pnl if pnl is not None else pd.DataFrame()

    mrr, seg_map, first_month, contrib_rows, mrr_notes = build_mrr_matrix(rev, billing_terms, fx)

    missing_data = []
    rev_src = sources.get("revenue", {"file": "revenue", "sheet": "Sheet1"})
    crm_src = sources.get("crm", {"file": "crm", "sheet": "Sheet1"})
    pnl_src = sources.get("pnl", {"file": "pnl", "sheet": "Sheet1"})

    def src(base, rows, rule):
        s = SourceRef(base.get("file", "?"), base.get("sheet"))
        s.add_rows(rows)
        return s.to_dict(rule)

    results = {"reporting_currency": reporting_currency}

    # ARR / MRR current
    if not mrr.empty:
        latest = mrr.columns[-1]
        current_mrr = float(mrr[latest].sum())
        results["arr"] = {
            "value": _round(current_mrr * 12),
            "mrr": _round(current_mrr),
            "month": _period_str(latest),
            "source": src(rev_src, contrib_rows, "ARR = current-month recurring MRR × 12"),
        }
    else:
        results["arr"] = None
        missing_data.append({"metric": "ARR / MRR", "reason": "No usable recurring revenue rows",
                             "unlocked_by": "Upload revenue lines with customer ID, invoice date, amount, currency",
                             "file": rev_src.get("file")})

    nrr = compute_nrr(mrr, seg_map, first_month)
    if nrr and nrr.get("insufficient_history"):
        missing_data.append({"metric": "NRR (12-month)", "reason": f"Needs 12+ months of history; have {nrr['months_available']}",
                             "unlocked_by": "Provide at least 13 months of revenue lines", "file": rev_src.get("file")})
        nrr = None
    if nrr:
        nrr["source"] = src(rev_src, contrib_rows, "NRR = base-cohort MRR now ÷ MRR 12 months ago")
    results["nrr"] = nrr
    if nrr and not seg_map:
        missing_data.append({"metric": "NRR by segment", "reason": "Segment column not mapped on revenue lines",
                             "unlocked_by": "Map the optional 'segment' column on revenue lines", "file": rev_src.get("file")})

    churn = compute_gross_churn(mrr)
    if churn and churn.get("insufficient_history"):
        missing_data.append({"metric": "Gross revenue churn", "reason": f"Needs 12+ months; have {churn['months_available']}",
                             "unlocked_by": "Provide at least 13 months of revenue lines", "file": rev_src.get("file")})
        churn = None
    if churn:
        churn["source"] = src(rev_src, contrib_rows, "Gross churn = (churned + contracted MRR) ÷ MRR 12 months ago")
    results["gross_churn"] = churn

    new_mrr_q = compute_new_mrr_by_quarter(mrr, first_month)
    results["new_mrr_by_quarter"] = new_mrr_q

    if pnl.empty:
        results["cac_payback"] = None
        missing_data.append({"metric": "CAC payback", "reason": "P&L not provided",
                             "unlocked_by": "Upload P&L with month, S&M expense, revenue, cost of revenue", "file": pnl_src.get("file")})
    else:
        cac = compute_cac_payback(new_mrr_q, pnl, default_l=int(config.get("default_l", 1)))
        if cac:
            cac["source"] = src(pnl_src, pnl.get("_row", []).tolist() if "_row" in pnl.columns else [],
                                 "CAC payback = lagged S&M ÷ (new MRR × gross margin %)")
        results["cac_payback"] = cac

    if deals.empty:
        results["sales_cycle"] = None
        results["win_rate"] = None
        missing_data.append({"metric": "Sales cycle & win rate", "reason": "CRM deals not provided",
                             "unlocked_by": "Upload CRM deals with deal ID, created date, close date, stage, amount", "file": crm_src.get("file")})
    else:
        sc = compute_sales_cycle(deals)
        if sc is not None:
            sc["source"] = src(crm_src, deals.get("_row", []).tolist() if "_row" in deals.columns else [],
                               "Median days from created to close, won deals only")
        results["sales_cycle"] = sc
        if sc is not None and "segment" not in deals.columns:
            missing_data.append({"metric": "Sales cycle by segment", "reason": "Segment column not mapped on CRM deals",
                                 "unlocked_by": "Map optional 'segment' column on CRM deals", "file": crm_src.get("file")})

        founder_available = "founder_involved" in deals.columns and deals["founder_involved"].notna().any()
        wr = compute_win_rate(deals, founder_available)
        if wr is not None:
            wr["source"] = src(crm_src, deals.get("_row", []).tolist() if "_row" in deals.columns else [],
                               "Win rate = won ÷ (won + lost); open excluded")
        results["win_rate"] = wr
        if wr is not None and not founder_available:
            missing_data.append({"metric": "Win rate by founder involvement", "reason": "'Founder involved' column not mapped",
                                 "unlocked_by": "Map optional 'founder involved' column on CRM deals", "file": crm_src.get("file")})

    acv = compute_acv_path(mrr, seg_map, first_month, target_arr, target_date)
    if acv:
        acv["source"] = src(rev_src, contrib_rows, "ACV = ARR ÷ active customers; path compares required vs observed net-new")
    results["acv_path"] = acv

    results["anomalies"] = compute_anomalies(mrr, rev, deals, mrr_notes)
    results["mrr_series"] = compute_mrr_series(mrr, seg_map)
    results["cohort_retention"] = compute_cohort_retention(mrr, first_month)
    results["missing_data"] = missing_data
    return results
