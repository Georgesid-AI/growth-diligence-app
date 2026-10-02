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

# (key, display label, low ACV, high ACV exclusive) — ordered lowest to highest ACV.
# Thresholds are annual (ACV = current MRR × 12) in the reporting currency:
# <100, 100–1K, 1K–10K, 10K–100K, 100K+.
ACV_BANDS = [
    ("consumer_viral", "Consumer / Viral", 0, 100),
    ("self_serve", "Self-serve", 100, 1_000),
    ("sales_assisted", "Sales-assisted", 1_000, 10_000),
    ("consultative_sales", "Consultative sales", 10_000, 100_000),
    ("strategic_accounts", "Strategic accounts", 100_000, float("inf")),
]

CCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥"}


def _fmt_k(v: float) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.0f}M" if v % 1_000_000 == 0 else f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.0f}K" if v % 1_000 == 0 else f"{v / 1_000:.1f}K"
    return f"{v:.0f}"


def _acv_range_label(lo: float, hi: float, ccy: str) -> str:
    sym = CCY_SYMBOLS.get(ccy, f"{ccy} " if ccy else "")
    if lo <= 0:
        return f"<{sym}{_fmt_k(hi)}"
    if hi == float("inf"):
        return f"{sym}{_fmt_k(lo)}+"
    return f"{sym}{_fmt_k(lo)}–{_fmt_k(hi)}"


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


def _full(x):
    """Full-precision float for storage (None for missing / non-finite).

    Used where the display layer rounds (app/formatting.py) and needs the true
    value - pre-rounding here would make a round-up rule act on a rounded number.
    """
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return float(x)


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
    notes = {"rows_missing_customer": [], "excluded_one_off": 0, "rows_missing_fx": [], "missing_fx_currencies": set(),
              "rows_missing_amount": [], "rows_missing_date": 0}
    records = []
    seg_map: dict = {}
    contrib_rows: list = []

    has_service = "service_start" in rev.columns and "service_end" in rev.columns
    # rows whose invoice date was left unread as ambiguous day/month: reported once, as such
    ambiguous = set((rev.attrs.get("date_formats", {}).get("invoice_date") or {}).get("row_ids", []))
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
            notes["rows_missing_amount"].append(rownum)
            continue
        currency = str(row.get("currency") or "").strip().upper()
        if currency not in fx:
            # No exchange rate provided for this currency — do NOT guess a 1.0 rate.
            # Exclude the row from MRR and flag it so it surfaces as missing/excluded data.
            notes["rows_missing_fx"].append(rownum)
            notes["missing_fx_currencies"].add(currency or "(blank)")
            continue
        rate = fx[currency]
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
                if rownum not in ambiguous:
                    notes["rows_missing_date"] += 1
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

    notes["missing_fx_currencies"] = sorted(notes["missing_fx_currencies"])

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
    """12-month NRR overall + by segment + by start cohort, plus a time series.

    `nrr_base_customers` is the number of customers who had revenue 12 months before the
    as-of month - the base NRR is measured on. It is 0 for a group that did not exist
    yet, in which case `nrr_pct` is null and `reason` says why: a zero must never reach
    a reader (or the narrative) unexplained. It is not the size of the cohort or segment.
    """
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
    m0_latest = cols[latest - 12]

    def entry(val, base_n, customers, noun):
        row = {"nrr_pct": _round(val * 100) if val is not None else None, "nrr_base_customers": base_n}
        if val is None:
            younger = bool(customers) and all(first_month.get(c) is not None and first_month[c] > m0_latest for c in customers)
            row["reason"] = (
                f"{noun} younger than 12 months: none of its customers had revenue 12 months before the as-of month"
                if younger else
                f"no customer in this {noun} had revenue 12 months before the as-of month"
            )
        return row

    overall, n = nrr_for(latest, list(mrr.index))

    by_segment = {}
    if seg_map:
        segs = sorted(set(seg_map.values()))
        for s_ in segs:
            custs = [c for c in mrr.index if seg_map.get(c) == s_]
            val, cn = nrr_for(latest, custs)
            by_segment[s_] = entry(val, cn, custs, "segment")

    by_cohort = {}
    cohorts = {}
    for c, fm in first_month.items():
        cohorts.setdefault(_quarter_str(fm), []).append(c)
    for q in sorted(cohorts):
        val, cn = nrr_for(latest, cohorts[q])
        by_cohort[q] = entry(val, cn, cohorts[q], "cohort")

    series = []
    for i in range(12, len(cols)):
        v, cn = nrr_for(i, list(mrr.index))
        series.append({"month": _period_str(cols[i]), "nrr_pct": _round(v * 100) if v is not None else None})

    top = {
        "month": _period_str(cols[latest]),
        # NRR is a trailing-12-month figure measured at `month`, never one month's movement.
        "trailing_window_months": 12,
        "overall_pct": _round(overall * 100) if overall is not None else None,
        "nrr_base_customers": n,
        "by_segment": by_segment,
        "by_cohort": by_cohort,
        "series": series,
    }
    if overall is None:
        top["reason"] = "no customer had revenue 12 months before the as-of month"
    return top


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
    # A trailing-12-month figure measured at `month`: MRR lost (churn and contraction, expansion
    # not netted) over the 12 months to that month, as a share of MRR 12 months earlier.
    return {"month": _period_str(cols[latest]), "trailing_window_months": 12,
            "overall_pct": _round(v * 100) if v is not None else None, "series": series}


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
        # A quarter with fewer than three months of data (the as-of month falls inside it,
        # or the data starts inside it) is partial: its new MRR covers only those months.
        out[_quarter_str(q)] = {"new_mrr": _round(val), "n_customers": len(new_custs), "month": _period_str(last_m),
                                "months_in_quarter": len(months), "partial": len(months) < 3}
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
        row = {"new_mrr": info["new_mrr"],
               "months_in_quarter": info.get("months_in_quarter"), "partial": bool(info.get("partial", False))}
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
    # The headline is the latest COMPLETE quarter with a computable figure. A partial
    # quarter pairs a full quarter of lagged S&M with only part of a quarter's new MRR,
    # which overstates payback (no pro-rating is attempted), so it never headlines.
    lag_key = f"L{default_l}"
    complete = [q for q in sorted(results)
                if not results[q]["partial"] and results[q].get(lag_key, {}).get("months") is not None]
    partial_later = [q for q in sorted(results)
                     if results[q]["partial"] and results[q].get(lag_key, {}).get("months") is not None
                     and (not complete or q > complete[-1])]
    return {"default_l": default_l, "quarters": results,
            "headline_quarter": complete[-1] if complete else None,
            "partial_quarter_excluded": partial_later[-1] if partial_later else None}


def _shift_quarter(qstr: str, lag: int) -> str:
    year, q = qstr.split("-Q")
    p = pd.Period(f"{year}Q{q}", freq="Q") - lag
    return f"{p.year}-Q{p.quarter}"


def compute_sales_cycle(deals: pd.DataFrame):
    """Median sales cycle (days) for won deals; report median, IQR, n; by segment."""
    if deals.empty or "stage" not in deals.columns:
        return None
    d = deals.copy()
    d["stage_l"] = d["stage"].astype(str).str.lower().str.strip()
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
            "median_days": _full(s.median()),
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
    if deals.empty or "stage" not in deals.columns:
        return None
    d = deals.copy()
    # Exclude deals whose close date precedes their created date (per approved amendment) —
    # same exclusion applied to sales cycle.
    created = pd.to_datetime(d["created_date"], errors="coerce") if "created_date" in d.columns else pd.Series(pd.NaT, index=d.index)
    closed = pd.to_datetime(d["close_date"], errors="coerce") if "close_date" in d.columns else pd.Series(pd.NaT, index=d.index)
    invalid = created.notna() & closed.notna() & (closed < created)
    excluded = int(invalid.sum())
    d = d[~invalid].copy()
    d["stage_l"] = d["stage"].astype(str).str.lower().str.strip()
    won = d["stage_l"].isin(WON_ALIASES).sum()
    lost = d["stage_l"].isin(LOST_ALIASES).sum()
    total = won + lost
    overall = won / total if total else None
    out = {"won": int(won), "lost": int(lost), "win_rate_pct": _round(overall * 100) if overall is not None else None,
           "excluded_invalid": excluded}

    if founder_available and "founder_involved" in d.columns:
        split = {}
        blank = d["founder_involved"].isna()
        d["founder_l"] = d["founder_involved"].astype(str).str.lower().str.strip()
        yes_like = {"yes", "true", "y", "1"}
        no_like = {"no", "false", "n", "0"}
        unrecognized = ~blank & ~d["founder_l"].isin(yes_like | no_like)
        for key, matches in (("with_founder", yes_like), ("without_founder", no_like)):
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
        rows = d.loc[unrecognized, "_row"].tolist() if "_row" in d.columns else []
        out["founder_involved_excluded"] = {
            "count": int(unrecognized.sum()),
            "rows": [int(r) for r in rows if r is not None and not pd.isna(r)][:200],
            "values": sorted({str(v) for v in d.loc[unrecognized, "founder_l"]}),
        }
    return out


def _years_to_target(latest: pd.Period, target_date):
    """(years, error): exact day count from the as-of month-end to the target date, / 365.

    A target date that isn't strictly after the as-of month, or has an implausible year,
    can't drive a projection, so it comes back as an error message instead of a number.
    Shared by the path-to-plan and segment-path calculations so both use one horizon.
    """
    years = None
    error = None
    if target_date:
        try:
            td = pd.Timestamp(target_date)
        except (ValueError, TypeError):
            td = None
            error = f"Target date '{target_date}' is not a valid date"
        if td is not None and not (2000 <= td.year <= 2100):
            error = f"Target date year ({td.year}) must be between 2000 and 2100"
            td = None
        if td is not None:
            now = latest.to_timestamp(how="end")
            if td <= now:
                error = f"Target date {td.date()} must be after the as-of month ({_period_str(latest)})"
            elif (td - now).days < 1:
                # 0 years would divide every per-year rate by zero
                error = f"Target date {td.date()} is less than a full day after the as-of month ({_period_str(latest)})"
            else:
                years = (td - now).days / 365
    return years, error


def compute_acv_path(mrr: pd.DataFrame, seg_map: dict, first_month: dict, target_arr: float, target_date: str,
                      reporting_currency: str = "EUR"):
    if mrr.empty:
        return None
    cols = list(mrr.columns)
    latest = cols[-1]
    active = [c for c in mrr.index if mrr.at[c, latest] > 0]
    n_cust = len(active)
    total_arr = sum(mrr.at[c, latest] for c in active) * 12
    acv = total_arr / n_cust if n_cust else None

    # bands by annual revenue per customer — thresholds/counting logic unchanged from
    # the original flies/mice/rabbits/deer/elephants bands, only labels/range added.
    band_counts = {key: 0 for key, _, _, _ in ACV_BANDS}
    for c in active:
        annual = mrr.at[c, latest] * 12
        for key, _, lo, hi in ACV_BANDS:
            if lo <= annual < hi:
                band_counts[key] += 1
                break
    bands = [
        {
            "key": key,
            "label": label,
            "low": lo,
            "high": None if hi == float("inf") else hi,
            "range_label": _acv_range_label(lo, hi, reporting_currency),
            "count": band_counts[key],
        }
        for key, label, lo, hi in ACV_BANDS
    ]

    by_segment = {}
    if seg_map:
        for s in sorted(set(seg_map.get(c) for c in active if seg_map.get(c))):
            custs = [c for c in active if seg_map.get(c) == s]
            arr_s = sum(mrr.at[c, latest] for c in custs) * 12
            by_segment[s] = {"customers": len(custs), "acv": _round(arr_s / len(custs)) if custs else None, "arr": _round(arr_s)}

    # Overall ACV band — same bucketing as the per-customer bands above, but for
    # the portfolio's blended ACV, so the panel can show one summary line.
    overall_band = None
    if acv is not None:
        for key, label, lo, hi in ACV_BANDS:
            if lo <= acv < hi:
                sym = CCY_SYMBOLS.get(reporting_currency, f"{reporting_currency} " if reporting_currency else "")
                overall_band = {"key": key, "label": label, "value_label": f"{sym}{_fmt_k(acv)}"}
                break

    customers_needed = target_arr / acv if acv else None
    # Years to target — exact day count between the as-of month-end and the
    # target date, divided by 365 (never a rounded ~1.5). A target date that
    # isn't strictly after the as-of month (or has an implausible year) can't
    # drive this calculation, so it's flagged via target_date_error instead of
    # silently producing an absurd required-net-new figure.
    years, target_date_error = _years_to_target(latest, target_date)
    required_per_year = ((customers_needed - n_cust) / years) if (customers_needed and years) else None

    def observed_net_new(months_back):
        if len(cols) <= months_back:
            return None  # not enough history to know the starting customer count
        ref = cols[-1 - months_back]
        active_then = len([c for c in mrr.index if mrr.at[c, ref] > 0])
        span_years = months_back / 12
        return (n_cust - active_then) / span_years if span_years else None

    obs12 = observed_net_new(12)
    obs24 = observed_net_new(24)
    ratio12, reason12 = _required_vs_observed(required_per_year, obs12, 12)
    ratio24, reason24 = _required_vs_observed(required_per_year, obs24, 24)

    return {
        "current_customers": n_cust,
        "current_arr": _round(total_arr),
        "acv": _round(acv),
        "target_arr": target_arr,
        "target_date": target_date,
        "bands": bands,
        "overall_band": overall_band,
        "by_segment": by_segment,
        # The TOTAL number of customers at the target ARR (existing ones included) if every
        # customer sits at today's blended ACV. Not the number still to acquire: that is
        # `additional_customers_needed`. (Called `customers_needed` in results computed earlier.)
        "total_customers_at_target": _full(customers_needed),
        "additional_customers_needed": _full(max(customers_needed - n_cust, 0.0)) if customers_needed is not None else None,
        "required_net_new_per_year": _round(required_per_year, 1),
        "observed_net_new_per_year_12m": _round(obs12, 1),
        "observed_net_new_per_year_24m": _round(obs24, 1),
        "required_vs_observed_12m": ratio12,
        "required_vs_observed_12m_reason": reason12,
        "required_vs_observed_24m": ratio24,
        "required_vs_observed_24m_reason": reason24,
        "target_date_error": target_date_error,
    }


def _required_vs_observed(required, observed, months):
    """Required ÷ observed net-new customers a year, or (None, reason).

    A ratio is only meaningful when both rates are positive: a shrinking base or a
    target already covered would give a zero or negative ratio, which must never
    reach the reader as a figure.
    """
    if required is None:
        return None, "the required net-new rate could not be computed"
    if observed is None:
        return None, f"less than {months} months of revenue history"
    if required <= 0:
        return None, "today's customers already cover the target at today's ACV; ratio not meaningful"
    if observed <= 0:
        return None, "customer base shrinking or flat; ratio not meaningful"
    return _round(required / observed, 2), None


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

    # revenue rows whose currency has no exchange rate (excluded, never guessed at 1.0)
    flags["revenue_missing_fx_rate"] = {
        "count": len(mrr_notes.get("rows_missing_fx", [])),
        "rows": [int(r) for r in mrr_notes.get("rows_missing_fx", []) if r is not None and not pd.isna(r)][:200],
        "currencies": list(mrr_notes.get("missing_fx_currencies", [])),
    }

    # revenue rows with a blank amount (excluded, never treated as zero)
    flags["revenue_missing_amount"] = {
        "count": len(mrr_notes.get("rows_missing_amount", [])),
        "rows": [int(r) for r in mrr_notes.get("rows_missing_amount", []) if r is not None and not pd.isna(r)][:200],
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
    """Rows = start cohort (quarter), cols = months since start, value = % starting MRR retained.

    Age is measured per-customer from their OWN first month with recurring MRR > 0 (M0),
    not from the cohort quarter's first calendar month — customers who ramp in later in the
    quarter must not be counted as "not yet retained" against a base they never contributed to.
    A cell Mk is only populated once every customer in the cohort has actually reached age k
    as of the last available month, so no cell mixes fully- and partially-observed customers.
    """
    if mrr.empty:
        return {"cohorts": [], "max_offset": 0, "data": []}
    cols = list(mrr.columns)
    col_idx = {m: i for i, m in enumerate(cols)}
    n_cols = len(cols)
    cohorts = {}
    for c, fm in first_month.items():
        cohorts.setdefault(_quarter_str(fm.asfreq("Q")), []).append(c)

    data = []
    max_offset = 0
    for q in sorted(cohorts):
        custs = cohorts[q]
        start_idx = {c: col_idx[first_month[c]] for c in custs}
        start_mrr = sum(mrr.at[c, cols[start_idx[c]]] for c in custs)
        if start_mrr <= 0:
            continue
        max_age_observed = min(n_cols - 1 - start_idx[c] for c in custs)
        row = {"cohort": q, "start_mrr": _round(start_mrr), "n": len(custs), "values": {}}
        for k in range(0, max_age_observed + 1):
            total_k = sum(mrr.at[c, cols[start_idx[c] + k]] for c in custs)
            row["values"][str(k)] = _round((total_k / start_mrr) * 100)
            max_offset = max(max_offset, k)
        data.append(row)
    return {"cohorts": [d["cohort"] for d in data], "max_offset": max_offset, "data": data}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _first_months(mrr: pd.DataFrame) -> dict:
    fm = {}
    for cust in mrr.index:
        active = mrr.columns[(mrr.loc[cust] > 0).values]
        if len(active):
            fm[cust] = active.min()
    return fm


def _resolve_as_of(as_of_str, pnl: pd.DataFrame, mrr: pd.DataFrame):
    """As-of month = explicit override, else last P&L month, else last MRR month."""
    if as_of_str:
        try:
            return pd.Period(str(as_of_str), "M")
        except Exception:
            pass
    if pnl is not None and not pnl.empty and "month" in pnl.columns:
        months = [_month_of(x) for x in pnl["month"]]
        months = [m for m in months if m is not None]
        if months:
            return max(months)
    if mrr is not None and not mrr.empty:
        return mrr.columns[-1]
    return None


# ---------------------------------------------------------------------------
# Segment mix paths to target ARR
# ---------------------------------------------------------------------------
# Runs on SEGMENTS only (the customer-size cut). ACV bands are the monetary cut and
# are not touched here. Two stages:
#   1. existing base: each segment's ARR compounded to the target date at that
#      segment's own trailing-12-month NRR, held flat (an arithmetic projection, not a
#      forecast); erosion in a segment with NRR < 100 shows as a negative change.
#   2. the gap: target ARR - projected base ARR is what new customers must supply.
# New customers count at LANDED ACV (first-month ARR) with no expansion applied.
# Nothing is ever estimated from another figure: a missing input is named, not filled.
SMALL_SEGMENT_N = 10          # base or landing samples below this are flagged
LANDED_WINDOWS = (12, 24)     # months; 12 is primary, 24 secondary where computable
CONSTANT_NRR_ASSUMPTION = (
    "Constant-NRR projection, not a forecast: each segment's trailing-12-month NRR is "
    "held flat from the as-of month to the target date."
)


def _landed(mrr: pd.DataFrame, seg_map: dict, first_month: dict, window: int, segments: list) -> dict:
    """Gross landings in the last `window` months, per segment, at landed (first-month) ARR."""
    cols = list(mrr.columns)
    if len(cols) <= window:
        return {"window_months": window, "computable": False,
                "reason": f"needs more than {window} months of revenue history; have {len(cols)}",
                "segments": {}}
    latest = cols[-1]
    per_seg = {s: [] for s in segments}
    unsegmented = 0
    for c, fm in first_month.items():
        if not (fm > latest - window and fm <= latest):
            continue
        seg = seg_map.get(c)
        if not seg:
            unsegmented += 1
        elif seg in per_seg:
            per_seg[seg].append(float(mrr.at[c, fm]) * 12)
        else:
            per_seg[seg] = [float(mrr.at[c, fm]) * 12]
    segs = {}
    for s, vals in sorted(per_seg.items()):
        segs[s] = {"new_customers": len(vals),
                   "landed_acv": (sum(vals) / len(vals)) if vals else None,
                   "small_sample": len(vals) < SMALL_SEGMENT_N}
    total = sum(v["new_customers"] for v in segs.values())
    return {"window_months": window, "computable": True, "reason": None,
            "gross_new_per_year": total / (window / 12),
            "unsegmented_new_customers": unsegmented,
            "segments": segs}


def _reverse_solve(window: int, landed: dict, gap, years, active_by_seg: dict) -> dict:
    """Hold the observed GROSS landing rate fixed and solve for the mix needed."""
    base = {"window_months": window, "computable": False, "reason": None, "reachable": None}
    if gap is None:
        return {**base, "reason": "the projected base is not available, so there is no gap to solve for"}
    if not landed.get("computable"):
        return {**base, "reason": landed.get("reason")}
    if gap <= 0:
        return {**base, "computable": True, "reachable": True, "target_met_by_base": True,
                "reason": "the projected base alone reaches the target"}
    if not years or years <= 0:
        return {**base, "reason": "no time between the as-of month and the target date to land new customers"}
    rate = landed["gross_new_per_year"]
    new_by_target = rate * years
    out = {**base, "computable": True, "target_met_by_base": False,
           "gross_new_per_year": rate, "new_customers_by_target": new_by_target}
    out["required_blended_landed_acv"] = (gap / new_by_target) if new_by_target > 0 else None

    segs = landed["segments"]
    missing = sorted(s for s in active_by_seg if segs.get(s, {}).get("landed_acv") is None)
    if missing or not active_by_seg:
        out["reason"] = (
            "no landed ACV for " + ", ".join(missing) +
            f" (no customers landed in that segment in the last {window} months)"
        ) if missing else "no active customers by segment"
        return out

    total_active = sum(active_by_seg.values())
    weights = {s: n / total_active for s, n in active_by_seg.items()}
    acv = {s: segs[s]["landed_acv"] for s in active_by_seg}
    current_blended = sum(weights[s] * acv[s] for s in weights)
    best = max(acv, key=acv.get)
    out["best_segment"] = best
    out["best_segment_landed_acv"] = acv[best]
    out["current_mix_landed_acv"] = current_blended
    # Rate needed if the mix stays as it is today.
    need_rate = gap / (current_blended * years) if current_blended > 0 else None
    out["required_new_per_year_at_current_mix"] = need_rate
    out["required_vs_observed_gross"] = (need_rate / rate) if (need_rate is not None and rate > 0) else None

    required = out["required_blended_landed_acv"]
    if required is None:                      # no landings at all: nothing can be delivered
        out["reachable"] = False
        out["computable"] = True
        return out

    new_w = dict(weights)
    if current_blended >= required:
        out["reachable"] = True
    elif required <= acv[best]:
        out["reachable"] = True
        need = required - current_blended
        for s in sorted(weights, key=lambda k: acv[k]):          # cheapest first: fewest points moved
            if s == best or acv[best] <= acv[s]:
                continue
            step = min(new_w[s], need / (acv[best] - acv[s]))
            new_w[s] -= step
            new_w[best] += step
            need -= step * (acv[best] - acv[s])
            if need <= 1e-9:
                break
    else:
        out["reachable"] = False
    if out["reachable"]:
        out["moved_mix_pct"] = sum(abs(new_w[s] - weights[s]) for s in weights) / 2 * 100
    out["by_segment"] = {
        s: {"landed_acv": acv[s],
            "current_mix_pct": weights[s] * 100,
            **({"required_mix_pct": new_w[s] * 100,
                "shift_pct_points": (new_w[s] - weights[s]) * 100} if out["reachable"] else {})}
        for s in sorted(weights)
    }
    return out


def _reconcile(window: int, acv_path: dict, sp: dict, years: float) -> dict:
    """Bridge the simple view (Path to Plan) to the segment view on one axis.

    Both answer "how does the rate needed to reach the target compare with the rate observed?"
    (a ratio; 1.00x means the observed rate is exactly enough, below 1.00x it is more than enough).
    They differ in three assumptions, and the segment ratio is the simple ratio times one factor each:

        compounded base   gap after compounding each segment's NRR / gap with the base held flat
        landed ACV        today's blended ACV / landed ACV at the current mix
        gross rate        observed net-new per year / observed gross landings per year

    Computed from full-precision values (not the rounded ones shown elsewhere) so the product
    closes exactly. Unavailable, with the reason, whenever a piece is missing or the two views
    do not start from the same ARR - it never fills in a figure.
    """
    base = {"window_months": window, "available": False, "reason": None}
    rs = (sp.get("reverse_solve") or {}).get(str(window)) or {}
    landed = (sp.get("landed") or {}).get(str(window)) or {}
    if sp.get("unsegmented_customers"):
        return {**base, "reason": "some active customers have no segment, so the two views start from different ARR"}
    if not sp.get("available") or rs.get("target_met_by_base"):
        return {**base, "reason": "the projected base is unavailable or already reaches the target"}
    if rs.get("required_vs_observed_gross") is None or not landed.get("computable"):
        return {**base, "reason": rs.get("reason") or "the segment view has no ratio for this window"}
    net = acv_path.get(f"observed_net_new_per_year_{window}m")
    gross = landed.get("gross_new_per_year")
    total_needed, n_now, target = acv_path.get("total_customers_at_target"), acv_path.get("current_customers"), sp.get("target_arr")
    if not net or net <= 0 or not gross or not total_needed or not n_now or not target:
        return {**base, "reason": "there is no positive observed net-new rate for this window"}
    if not years or years <= 0 or not rs.get("current_mix_landed_acv"):
        return {**base, "reason": "no time to the target date, or no landed ACV at the current mix"}
    acv_raw = target / total_needed                      # today's blended ACV, unrounded
    gap_flat = target - n_now * acv_raw                  # the gap with the base held flat
    if gap_flat <= 0:
        return {**base, "reason": "today's customers already cover the target at today's ACV"}
    path_ratio = ((total_needed - n_now) / years) / net
    f_base = sp["gap_arr"] / gap_flat
    f_acv = acv_raw / rs["current_mix_landed_acv"]
    f_rate = net / gross
    return {**base, "available": True,
            "path_to_plan_ratio": path_ratio, "factor_compounded_base": f_base,
            "factor_landed_acv": f_acv, "factor_gross_rate": f_rate,
            "segment_ratio": rs["required_vs_observed_gross"]}


def compute_segment_paths(mrr: pd.DataFrame, seg_map: dict, first_month: dict, nrr, acv_path,
                          target_arr: float, target_date):
    """Stage one (existing base), stage two (the gap) and the reverse-solve, by segment."""
    missing = []
    out = {"available": False, "assumption": CONSTANT_NRR_ASSUMPTION, "missing_inputs": missing}
    if mrr.empty or acv_path is None:
        missing.append({"input": "recurring revenue lines",
                        "resolve": "Upload revenue lines with customer ID, invoice date, amount, currency"})
        return out
    if not seg_map:
        missing.append({"input": "customer segments",
                        "resolve": "Map the optional 'segment' column on revenue lines"})
        return out
    latest = mrr.columns[-1]
    years, date_error = _years_to_target(latest, target_date)
    if years is None:
        missing.append({"input": "a valid target date after the as-of month",
                        "resolve": date_error or "Set a target date after the as-of month"})
        return out
    if not nrr or not target_arr:
        missing.append({"input": "12-month NRR by segment" if not nrr else "a target ARR",
                        "resolve": "Provide at least 13 months of revenue lines" if not nrr else "Set a target ARR"})
        return out

    by_seg = acv_path.get("by_segment") or {}
    out.update({"horizon_months": years * 12, "target_arr": float(target_arr), "target_date": target_date})

    # ---- stage one: existing base, each segment at its own NRR ----
    segments, unprojectable, not_positive = {}, [], []
    for s in sorted(by_seg):
        a = by_seg[s]
        n = (nrr.get("by_segment") or {}).get(s) or {}
        pct = n.get("nrr_pct")
        base_n = n.get("nrr_base_customers", n.get("n"))
        row = {"start_arr": a["arr"], "customers": a["customers"],
               "nrr_base_customers": base_n, "nrr_pct": pct,
               "small_base": bool(base_n is not None and base_n < SMALL_SEGMENT_N)}
        if pct is None:
            unprojectable.append(s)
            row.update({"projected_arr": None, "change_arr": None, "arr_change_per_nrr_point": None,
                        "reason": "no customers with revenue 12 months ago in this segment, so no NRR"})
        elif pct <= 0:
            # 0 ** (years - 1) divides by zero for years < 1, and a negative NRR raised to a
            # fractional power is a complex number: neither is a projection
            not_positive.append(f"{s} ({pct:g}%)")
            row.update({"projected_arr": None, "change_arr": None, "arr_change_per_nrr_point": None,
                        "reason": f"NRR is {pct:g}%, so a constant-NRR projection is not meaningful"})
        else:
            factor = pct / 100
            projected = a["arr"] * factor ** years
            row.update({"projected_arr": projected, "change_arr": projected - a["arr"],
                        # ARR at the target date moved by one NRR point, all else equal
                        "arr_change_per_nrr_point": a["arr"] * years * factor ** (years - 1) / 100})
        segments[s] = row
    total_start = sum(v["start_arr"] for v in segments.values())
    stage_one = {"segments": segments, "start_arr_total": total_start}
    active_customers = [c for c in mrr.index if mrr.at[c, latest] > 0]
    unseg = [c for c in active_customers if not seg_map.get(c)]
    out["unsegmented_customers"] = len(unseg)
    out["unsegmented_arr"] = float(sum(mrr.at[c, latest] for c in unseg) * 12)

    gap = None
    if unprojectable:
        missing.append({"input": "12-month NRR for " + ", ".join(unprojectable),
                        "resolve": "Needs customers in that segment with revenue 12 months before the as-of month"})
    if not_positive:
        missing.append({"input": "a positive 12-month NRR for " + ", ".join(not_positive),
                        "resolve": "A constant-NRR projection needs NRR above 0%; not projected, not estimated"})
    unprojectable += not_positive
    if not unprojectable:
        projected_base = sum(v["projected_arr"] for v in segments.values())
        stage_one["projected_base_arr"] = projected_base
        gap = float(target_arr) - projected_base
        out["gap_arr"] = max(gap, 0.0)
        out["target_met_by_base"] = gap <= 0
    out["stage_one"] = stage_one
    out["available"] = not unprojectable

    # ---- stage two: what new customers must supply, at landed ACV ----
    active_by_seg = {s: v["customers"] for s, v in segments.items()}
    seg_names = sorted(by_seg)
    out["landed"], out["reverse_solve"] = {}, {}
    for w in LANDED_WINDOWS:
        landed = _landed(mrr, seg_map, first_month, w, seg_names)
        out["landed"][str(w)] = landed
        out["reverse_solve"][str(w)] = _reverse_solve(w, landed, gap, years, active_by_seg)
    out["reconciliation"] = {str(w): _reconcile(w, acv_path, out, years) for w in LANDED_WINDOWS}
    return out


def _cac_input_gaps(cac: dict, pnl_src: dict) -> list:
    """Missing-data entries for CAC payback quarters that could not be computed because an
    INPUT is absent, as opposed to a genuine zero (no new customers).

    Per-quarter reasons already say "no P&L for 2023-Q2" or "gross margin <= 0 or missing"
    on each row; without this, the Missing Data panel read "all metrics computed" while the
    quarterly table showed n/c.
    """
    lag_key = f"L{cac.get('default_l', 1)}"
    revenue_quarters = set(cac["quarters"])
    no_pnl, no_margin, affected = set(), set(), set()
    for q, row in cac["quarters"].items():
        for lag in ("L0", "L1", "L2"):
            reason = (row.get(lag) or {}).get("reason") or ""
            if reason.startswith("no P&L for "):
                needed = reason[len("no P&L for "):]
                # Only a quarter the company has revenue for can be "missing" a P&L. The quarters
                # before the first revenue quarter (the first quarter's lag) predate the data,
                # so listing them would put a false item on almost every audit.
                if needed in revenue_quarters:
                    no_pnl.add(needed)
                    if lag == lag_key:
                        affected.add(q)
            elif reason.startswith("gross margin"):
                no_margin.add(q)
    out = []
    if no_pnl:
        out.append({
            "metric": "CAC payback (quarters without P&L)",
            "reason": (f"No P&L rows for {', '.join(sorted(no_pnl))}, which CAC payback needs to pair each quarter's new MRR "
                       f"with S&M spend from earlier quarters (lags L0 to L2). At the default lag {lag_key} it cannot be "
                       f"computed for {', '.join(sorted(affected)) or 'any quarter'}."),
            "unlocked_by": f"Upload P&L months covering {', '.join(sorted(no_pnl))}",
            "file": pnl_src.get("file"),
        })
    if no_margin:
        out.append({
            "metric": "CAC payback (quarters without a usable gross margin)",
            "reason": f"Revenue and cost of revenue in the P&L give a gross margin of zero, below zero or none for {', '.join(sorted(no_margin))}",
            "unlocked_by": "Provide revenue and cost of revenue for those quarters in the P&L",
            "file": pnl_src.get("file"),
        })
    return out


def _history_gaps(n_months: int, rev_src: dict) -> list:
    """Observed net-new customer rates need history: 12 or 24 months before the as-of month."""
    windows = [w for w in (12, 24) if n_months <= w]
    if not windows:
        return []
    return [{
        "metric": f"Observed net-new customers ({' and '.join(str(w) for w in windows)} months)",
        "reason": f"Needs {max(windows) + 1}+ months of revenue history; have {n_months}",
        "unlocked_by": f"Provide at least {max(windows) + 1} months of revenue lines",
        "file": rev_src.get("file"),
    }]


def cut_deals_at_as_of(deals: pd.DataFrame, as_of):
    """Apply the as-of cut to CRM deals, like MRR and the P&L.

    A deal created or closed after the as-of month did not exist, or was still open,
    at that date, so it belongs to no closed-deal figure for the period. Deals with no
    date to place them are kept (they cannot be shown to fall outside the period).
    Returns (deals, number dropped).
    """
    if deals is None or deals.empty or as_of is None:
        return deals, 0
    def months(col):
        if col not in deals.columns:
            return pd.Series(pd.NaT, index=deals.index, dtype="period[M]")
        return pd.to_datetime(deals[col], errors="coerce").dt.to_period("M")
    created, closed = months("created_date"), months("close_date")
    after = (closed.notna() & (closed > as_of)) | (created.notna() & (created > as_of))
    return deals[~after].copy(), int(after.sum())


# ---------------------------------------------------------------------------
# Compute before Missing (V6). Before an item stays in missing_data, every uploaded
# file is tested for the columns the analysis needs - not only the file it normally
# comes from. If one can answer it, the figure is computed from that file and
# management is asked to explain it rather than to supply it.
# ---------------------------------------------------------------------------
COMPUTED_STATUS = "Computed – explanation requested"
MISSING_STATUS = "Missing"
DATASET_ORDER = ("revenue", "crm", "pnl")

# What each analysis needs, read as which dataset type.
ANALYSIS_NEEDS = {
    "sales_cycle": {"label": "Sales cycle", "as": "crm",
                    "fields": ("created_date", "close_date", "stage")},
    "win_rate": {"label": "Win rate", "as": "crm", "fields": ("stage",)},
    "founder_win_rate": {"label": "Win rate by founder involvement", "as": "crm",
                         "fields": ("stage", "founder_involved")},
    "nrr": {"label": "NRR (12-month)", "as": "revenue",
            "fields": ("customer_id", "invoice_date", "amount", "currency")},
    "gross_churn": {"label": "Gross revenue churn", "as": "revenue",
                    "fields": ("customer_id", "invoice_date", "amount", "currency")},
    "cac_payback": {"label": "CAC payback", "as": "pnl",
                    "fields": ("month", "sm_expense", "revenue", "cost_of_revenue")},
}

# missing_data metric -> the analyses it stands for
MISSING_ANALYSES = {
    "Sales cycle & win rate": ("sales_cycle", "win_rate"),
    "Sales cycle": ("sales_cycle",),
    "Win rate by founder involvement": ("founder_win_rate",),
    "NRR (12-month)": ("nrr",),
    "Gross revenue churn": ("gross_churn",),
    "CAC payback": ("cac_payback",),
}

_RULES = {
    "sales_cycle": "Median days from created to close, won deals closed by the as-of month",
    "win_rate": "Win rate = won ÷ (won + lost), deals closed by the as-of month; open excluded",
    "founder_win_rate": "Win rate split by founder involvement, deals closed by the as-of month",
    "nrr": "NRR = base-cohort MRR now ÷ MRR 12 months ago",
    "gross_churn": "Gross churn = (churned + contracted MRR) ÷ MRR 12 months ago",
    "cac_payback": "CAC payback = lagged S&M ÷ (new MRR × gross margin %)",
}


def _run_analysis(analysis: str, frame: pd.DataFrame, ctx: dict):
    """Run one analysis on a candidate frame. Returns the result, or None if the rows
    cannot answer it (columns present but no usable values)."""
    as_of = ctx.get("as_of")
    if ANALYSIS_NEEDS[analysis]["as"] == "crm":
        deals, _ = cut_deals_at_as_of(frame, as_of)
        if deals is None or deals.empty:
            return None
        if analysis == "sales_cycle":
            out = compute_sales_cycle(deals)
            return out if out and out.get("n") else None
        out = compute_win_rate(deals, analysis == "founder_win_rate")
        if out is None:
            return None
        if analysis == "win_rate":
            return out if out["won"] + out["lost"] else None
        return out if any(s["n"] for s in out.get("by_founder", {}).values()) else None
    if analysis in ("nrr", "gross_churn"):
        mrr, seg_map, first_month, _, _ = build_mrr_matrix(frame, {}, ctx.get("fx") or {})
        if not mrr.empty and as_of is not None:
            mrr = mrr.loc[:, [c for c in mrr.columns if c <= as_of]]
        if mrr.empty:
            return None
        out = (compute_nrr(mrr, seg_map, _first_months(mrr)) if analysis == "nrr" else compute_gross_churn(mrr))
        return out if out and not out.get("insufficient_history") else None
    if analysis == "cac_payback":
        p = frame
        if as_of is not None and "month" in p.columns:
            p = p[[(_month_of(x) is not None and _month_of(x) <= as_of) for x in p["month"]]]
        out = compute_cac_payback(ctx.get("new_mrr_q") or {}, p, default_l=int(ctx.get("default_l", 1)))
        return out if out and out.get("quarters") else None
    return None


def can_compute(analysis: str, files: dict, expected: str | None = None, **ctx) -> dict:
    """Test whether any uploaded file can answer `analysis`.

    `files` maps dataset type -> {"file", "sheet", "views"}, where views[as_type] holds
    the file read as that type: its own type through the current mapping, the other
    types through the column aliases ({"mapping": {field: column}, "frame": DataFrame}).
    Every file is checked - the expected one first. A file answers the question only if
    it has every needed field and its rows yield a result, so the test is the
    calculation itself.

    Returns {"computable", "analysis", "dataset", "file", "sheet", "columns", "result",
    "absent_fields"}; absent_fields maps each file that cannot answer to the fields it
    lacks (an empty list: the columns are there but no row is usable).
    """
    need = ANALYSIS_NEEDS[analysis]
    order = ([expected] if expected in files else []) + [t for t in DATASET_ORDER if t in files and t != expected]
    order += [t for t in files if t not in order]
    absent = {}
    for dtype in order:
        view = (files[dtype].get("views") or {}).get(need["as"]) or {}
        mapping, frame = view.get("mapping") or {}, view.get("frame")
        lacking = [f for f in need["fields"]
                   if not mapping.get(f) or frame is None or f not in frame.columns or frame[f].notna().sum() == 0]
        if lacking:
            absent[dtype] = lacking
            continue
        result = _run_analysis(analysis, frame, ctx)
        if result is None:
            absent[dtype] = []
            continue
        return {"computable": True, "analysis": analysis, "dataset": dtype,
                "file": files[dtype].get("file"), "sheet": files[dtype].get("sheet"),
                "columns": {f: mapping[f] for f in need["fields"]}, "result": result, "absent_fields": absent}
    return {"computable": False, "analysis": analysis, "dataset": None, "file": None, "sheet": None,
            "columns": {}, "result": None, "absent_fields": absent}


def resolve_missing(missing_data: list, results: dict, files: dict | None, **ctx) -> tuple[list, list]:
    """Apply compute-before-Missing to missing_data.

    Each item that stands for an analysis is tested with can_compute. A computable
    analysis is stored in results under its own key (with its source citation and
    status) and moves to the questions-for-management list; anything else stays
    Missing with the fields each file lacks. Results the engine already produced
    from the expected file are never replaced.
    Returns (missing_data, questions_for_management).
    """
    files = files or {}
    missing, questions = [], []
    for item in missing_data:
        analyses = MISSING_ANALYSES.get(item.get("metric"))
        if not analyses:
            missing.append({**item, "status": MISSING_STATUS})
            continue
        still_missing, absent, answered = [], {}, 0
        for analysis in analyses:
            if results.get(analysis) is not None:
                answered += 1  # the engine already has it from the expected file
                continue
            verdict = can_compute(analysis, files, expected=ANALYSIS_NEEDS[analysis]["as"], **ctx)
            if not verdict["computable"]:
                still_missing.append(analysis)
                for dtype, fields in verdict["absent_fields"].items():
                    absent.setdefault(dtype, [])
                    absent[dtype] += [f for f in fields if f not in absent[dtype]]
                continue
            result = verdict["result"]
            s = SourceRef(verdict["file"] or verdict["dataset"], verdict["sheet"])
            frame = files[verdict["dataset"]]["views"][ANALYSIS_NEEDS[analysis]["as"]]["frame"]
            s.add_rows(frame["_row"].tolist() if "_row" in frame.columns else [])
            result["source"] = {**s.to_dict(_RULES[analysis]), "dataset": verdict["dataset"],
                                "columns": verdict["columns"]}
            result["status"] = COMPUTED_STATUS
            results[analysis] = result
            label = ANALYSIS_NEEDS[analysis]["label"]
            cols = ", ".join(f"{f} = '{c}'" for f, c in verdict["columns"].items())
            questions.append({
                "metric": label,
                "status": COMPUTED_STATUS,
                "result_key": analysis,
                "dataset": verdict["dataset"],
                "file": verdict["file"],
                "columns": verdict["columns"],
                "replaces_missing": item.get("metric"),
                "question": (f"{label} was computed from the {verdict['dataset']} upload ({cols}) because "
                             f"it was not available from the {ANALYSIS_NEEDS[analysis]['as']} upload "
                             f"({item.get('reason')}). Please explain the result and confirm these "
                             f"columns are the right basis for it."),
            })
        if answered == len(analyses):
            missing.append({**item, "status": MISSING_STATUS})
        elif still_missing:
            entry = {**item, "status": MISSING_STATUS, "absent_fields": absent}
            if len(still_missing) < len(analyses):
                entry["metric"] = " & ".join(ANALYSIS_NEEDS[a]["label"] for a in still_missing)
            missing.append(entry)
    return missing, questions


def compute_all(rev: pd.DataFrame, deals: pd.DataFrame, pnl: pd.DataFrame, config: dict, sources: dict,
                files: dict | None = None, on_error=None):
    """Run the full engine. `sources` maps dataset -> {file, sheet}; `files` is every
    upload read as each dataset type (see can_compute), for compute-before-Missing.
    A metric whose calculation raises is reported as Missing and the rest still compute;
    `on_error(exc)`, if given, receives each such exception (the server logs it)."""
    billing_terms = config.get("billing_terms", {})
    fx = config.get("fx", {})
    reporting_currency = config.get("reporting_currency", "EUR")
    target_arr = float(config.get("target_arr") or 0)
    target_date = config.get("target_date")

    rev = rev if rev is not None else pd.DataFrame()
    deals = deals if deals is not None else pd.DataFrame()
    pnl = pnl if pnl is not None else pd.DataFrame()
    # day/month order per date column, found when the upload was read (server.normalize)
    date_formats = {name: frame.attrs.get("date_formats", {})
                    for name, frame in (("revenue", rev), ("crm", deals), ("pnl", pnl))}

    mrr, seg_map, first_month, contrib_rows, mrr_notes = build_mrr_matrix(rev, billing_terms, fx)

    # As-of month: truncate all "current"/time-series views to <= as_of. MRR after the
    # as-of month is deferred revenue and must not appear in current figures.
    as_of = _resolve_as_of(config.get("as_of_month"), pnl, mrr)
    last_revenue_month = mrr.columns[-1] if not mrr.empty else None
    if not mrr.empty and as_of is not None:
        keep = [c for c in mrr.columns if c <= as_of]
        mrr = mrr.loc[:, keep] if keep else mrr.iloc[:, :0]
        first_month = _first_months(mrr)
    if not pnl.empty and as_of is not None and "month" in pnl.columns:
        pnl = pnl[[(_month_of(x) is not None and _month_of(x) <= as_of) for x in pnl["month"]]]
    deals_loaded = len(deals)
    deals, deals_after_as_of = cut_deals_at_as_of(deals, as_of)

    missing_data = []
    rev_src = sources.get("revenue", {"file": "revenue", "sheet": "Sheet1"})
    crm_src = sources.get("crm", {"file": "crm", "sheet": "Sheet1"})
    pnl_src = sources.get("pnl", {"file": "pnl", "sheet": "Sheet1"})

    if mrr_notes.get("rows_missing_fx"):
        missing_data.append({
            "metric": "Revenue rows with unmapped currency",
            "reason": f"{len(mrr_notes['rows_missing_fx'])} row(s) use currency(ies) "
                      f"{', '.join(mrr_notes.get('missing_fx_currencies', []))} with no exchange rate provided — excluded, not guessed at 1.0",
            "unlocked_by": "Provide an FX rate for each currency present in the revenue file",
            "file": rev_src.get("file"),
        })

    if mrr_notes.get("rows_missing_amount"):
        missing_data.append({
            "metric": "Revenue rows with blank amount",
            "reason": f"{len(mrr_notes['rows_missing_amount'])} row(s) have no amount value — excluded from MRR, not treated as zero",
            "unlocked_by": "Fill in the amount for every revenue line, or remove the row",
            "file": rev_src.get("file"),
        })

    if mrr_notes.get("rows_missing_date"):
        missing_data.append({
            "metric": "Revenue rows with no usable invoice date",
            "reason": f"{mrr_notes['rows_missing_date']} row(s) have a blank or unreadable invoice date and no service "
                      f"period — excluded from MRR, not guessed",
            "unlocked_by": "Give every revenue line a valid invoice date (or service start and end dates)",
            "file": rev_src.get("file"),
        })

    if last_revenue_month is not None and as_of is not None and as_of > last_revenue_month:
        gap_months = (as_of - last_revenue_month).n
        missing_data.append({
            "metric": "Revenue up to the as-of month",
            "reason": f"Revenue lines end {_period_str(last_revenue_month)}, {gap_months} month(s) before the as-of "
                      f"month ({_period_str(as_of)}). Current figures are measured at "
                      f"{_period_str(last_revenue_month)}; the months after it are not filled, not guessed",
            "unlocked_by": f"Upload revenue lines through {_period_str(as_of)}, or set the as-of month to "
                           f"{_period_str(last_revenue_month)}",
            "file": rev_src.get("file"),
        })

    # No as-of month set and no P&L months: the as-of month defaults to the last MRR month,
    # which prepaid service periods can push past the last invoice. Those months hold only
    # deferred revenue, so "current" figures there are not the run-rate.
    invoice_months = ([m for m in map(_month_of, rev["invoice_date"]) if m is not None]
                      if "invoice_date" in rev.columns else [])
    last_invoice_month = max(invoice_months) if invoice_months else None
    if (not config.get("as_of_month") and as_of is not None and as_of == last_revenue_month
            and last_invoice_month is not None and as_of > last_invoice_month):
        missing_data.append({
            "metric": "As-of month",
            "reason": f"No as-of month was set and no P&L months were provided, so it defaulted to the last month of "
                      f"service periods ({_period_str(as_of)}), {(as_of - last_invoice_month).n} month(s) after the "
                      f"last invoice ({_period_str(last_invoice_month)}). Those months hold only deferred revenue from "
                      f"prepaid contracts; current figures there are not the run-rate",
            "unlocked_by": f"Set the as-of month on the audit (e.g. {_period_str(last_invoice_month)}), or upload the P&L",
            "file": rev_src.get("file"),
        })

    date_order_notes = []
    for name, fields in date_formats.items():
        file = sources.get(name, {}).get("file", name)
        for field, finding in fields.items():
            if finding["order"]:
                date_order_notes.append({"dataset": name, "field": field, "order": finding["order"],
                                         "rows": finding["rows"]})
                continue
            missing_data.append({
                "metric": f"Date format of {field} ({name})",
                "reason": f"{finding['rows']} row(s) have dates where day and month can't be told apart "
                          f"(the column {finding['reason']}) — not read, not guessed",
                "unlocked_by": f"Management to confirm the date format of {field}: DD/MM/YYYY or MM/DD/YYYY",
                "file": file,
            })

    def guarded(label, file, empty, fn, *args):
        """One metric's calculation; an unexpected error makes it Missing, never the whole run."""
        try:
            return fn(*args)
        except Exception as exc:
            if on_error:
                on_error(exc)
            missing_data.append({
                "metric": f"{label} (calculation error)",
                "reason": f"The calculation stopped on an unexpected {type(exc).__name__}; "
                          f"reported as Missing, not estimated. The other metrics are unaffected",
                "unlocked_by": "Not computable from the data as supplied; the server log has the run id",
                "file": file,
            })
            return empty

    def src(base, rows, rule):
        s = SourceRef(base.get("file", "?"), base.get("sheet"))
        s.add_rows(rows)
        return s.to_dict(rule)

    results = {"reporting_currency": reporting_currency, "as_of_month": _period_str(as_of) if as_of is not None else None}

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

    nrr = guarded("NRR (12-month)", rev_src.get("file"), None, compute_nrr, mrr, seg_map, first_month)
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

    churn = guarded("Gross revenue churn", rev_src.get("file"), None, compute_gross_churn, mrr)
    if churn and churn.get("insufficient_history"):
        missing_data.append({"metric": "Gross revenue churn", "reason": f"Needs 12+ months; have {churn['months_available']}",
                             "unlocked_by": "Provide at least 13 months of revenue lines", "file": rev_src.get("file")})
        churn = None
    if churn:
        churn["source"] = src(rev_src, contrib_rows, "Gross churn = (churned + contracted MRR) ÷ MRR 12 months ago")
    results["gross_churn"] = churn

    new_mrr_q = guarded("New MRR by quarter", rev_src.get("file"), {}, compute_new_mrr_by_quarter, mrr, first_month)
    results["new_mrr_by_quarter"] = new_mrr_q

    if pnl.empty:
        results["cac_payback"] = None
        missing_data.append({"metric": "CAC payback", "reason": "P&L not provided",
                             "unlocked_by": "Upload P&L with month, S&M expense, revenue, cost of revenue", "file": pnl_src.get("file")})
    else:
        cac = guarded("CAC payback", pnl_src.get("file"), None, compute_cac_payback, new_mrr_q, pnl,
                      int(config.get("default_l", 1)))
        if cac:
            cac["source"] = src(pnl_src, pnl.get("_row", []).tolist() if "_row" in pnl.columns else [],
                                 "CAC payback = lagged S&M ÷ (new MRR × gross margin %)")
        results["cac_payback"] = cac
        if cac:
            missing_data.extend(_cac_input_gaps(cac, pnl_src))

    if deals.empty:
        results["sales_cycle"] = None
        results["win_rate"] = None
        missing_data.append({"metric": "Sales cycle & win rate",
                             "reason": ("CRM deals not provided" if not deals_loaded else
                                        f"All {deals_loaded} CRM deals were created or closed after the as-of month"),
                             "unlocked_by": "Upload CRM deals with deal ID, created date, close date, stage, amount", "file": crm_src.get("file")})
    else:
        absent_dates = [f for f in ("created_date", "close_date")
                        if f not in deals.columns or deals[f].notna().sum() == 0]
        sc = None if absent_dates else guarded("Sales cycle", crm_src.get("file"), None, compute_sales_cycle, deals)
        if absent_dates:
            missing_data.append({"metric": "Sales cycle",
                                 "reason": f"CRM deals have no {' or '.join(f.replace('_', ' ') for f in absent_dates)}",
                                 "unlocked_by": "Map the created date and close date columns on CRM deals",
                                 "file": crm_src.get("file")})
        if sc is not None:
            sc["source"] = src(crm_src, deals.get("_row", []).tolist() if "_row" in deals.columns else [],
                               "Median days from created to close, won deals closed by the as-of month")
        results["sales_cycle"] = sc
        if sc is not None and "segment" not in deals.columns:
            missing_data.append({"metric": "Sales cycle by segment", "reason": "Segment column not mapped on CRM deals",
                                 "unlocked_by": "Map optional 'segment' column on CRM deals", "file": crm_src.get("file")})

        if "stage" not in deals.columns:
            missing_data.append({"metric": "Sales cycle & win rate", "reason": "Stage column not mapped on CRM deals",
                                 "unlocked_by": "Map the stage column on CRM deals", "file": crm_src.get("file")})
        founder_available = "founder_involved" in deals.columns and deals["founder_involved"].notna().any()
        wr = guarded("Win rate", crm_src.get("file"), None, compute_win_rate, deals, founder_available)
        if wr is not None:
            wr["excluded_after_as_of"] = deals_after_as_of
            wr["source"] = src(crm_src, deals.get("_row", []).tolist() if "_row" in deals.columns else [],
                               "Win rate = won ÷ (won + lost), deals closed by the as-of month; open excluded")
        results["win_rate"] = wr
        if wr is not None and not founder_available:
            missing_data.append({"metric": "Win rate by founder involvement", "reason": "'Founder involved' column not mapped",
                                 "unlocked_by": "Map optional 'founder involved' column on CRM deals", "file": crm_src.get("file")})
        if wr is not None and wr.get("founder_involved_excluded", {}).get("count"):
            fie = wr["founder_involved_excluded"]
            missing_data.append({
                "metric": "CRM rows with unrecognized founder-involved value",
                "reason": f"{fie['count']} row(s) have a founder-involved value that isn't yes/no-like "
                          f"({', '.join(fie['values'])}) — excluded from the founder split, not guessed",
                "unlocked_by": "Use a yes/no style value for founder involvement (yes/no, true/false, y/n, 1/0)",
                "file": crm_src.get("file"),
            })

    acv = guarded("Path to Plan", rev_src.get("file"), None, compute_acv_path, mrr, seg_map, first_month, target_arr, target_date,
                  reporting_currency)
    if acv:
        acv["source"] = src(rev_src, contrib_rows, "ACV = ARR ÷ active customers; path compares required vs observed net-new")
        if acv.get("target_date_error"):
            missing_data.append({
                "metric": "Path to Plan (required net-new)",
                "reason": acv["target_date_error"],
                "unlocked_by": "Set a target date with a year between 2000 and 2100, after the as-of month",
                "file": rev_src.get("file"),
            })
        for window in (12, 24):
            reason = acv.get(f"required_vs_observed_{window}m_reason")
            if reason and not acv.get("target_date_error"):
                missing_data.append({
                    "metric": f"Required vs observed net-new customers ({window}m)",
                    "reason": reason,
                    "unlocked_by": "Not computable from the supplied data; reported as Missing",
                    "file": rev_src.get("file"),
                })
    results["acv_path"] = acv
    if acv:
        missing_data.extend(_history_gaps(len(mrr.columns), rev_src))

    results["segment_paths"] = guarded(
        "Segment paths to target ARR", rev_src.get("file"),
        {"available": False, "assumption": CONSTANT_NRR_ASSUMPTION, "missing_inputs": []},
        compute_segment_paths, mrr, seg_map, first_month, nrr, acv, target_arr, target_date)
    sp = results["segment_paths"]
    if not sp["available"] and sp["missing_inputs"]:
        missing_data.append({
            "metric": "Segment paths to target ARR",
            "reason": "; ".join(m["input"] for m in sp["missing_inputs"]) + " not available",
            "unlocked_by": "; ".join(m["resolve"] for m in sp["missing_inputs"]),
            "file": rev_src.get("file"),
        })

    # None after a failure, never zero counts: the dashboard shows the calculation error instead
    results["anomalies"] = guarded("Anomaly flags", rev_src.get("file"), None,
                                   compute_anomalies, mrr, rev, deals, mrr_notes)
    if results["anomalies"] is not None:
        results["anomalies"]["date_order_from_data"] = date_order_notes
    results["mrr_series"] = guarded("MRR by segment", rev_src.get("file"), {"months": [], "segments": [], "data": []},
                                    compute_mrr_series, mrr, seg_map)
    results["cohort_retention"] = guarded("Cohort retention", rev_src.get("file"), {"cohorts": [], "max_offset": 0, "data": []},
                                          compute_cohort_retention, mrr, first_month)
    results["missing_data"], results["questions_for_management"] = resolve_missing(
        missing_data, results, files, as_of=as_of, fx=fx, new_mrr_q=new_mrr_q,
        default_l=config.get("default_l", 1))
    return results
