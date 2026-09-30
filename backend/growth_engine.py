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
              "rows_missing_amount": []}
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
    if deals.empty:
        return None
    d = deals.copy()
    # Exclude deals whose close date precedes their created date (per approved amendment) —
    # same exclusion applied to sales cycle.
    created = pd.to_datetime(d["created_date"], errors="coerce") if "created_date" in d.columns else pd.Series(pd.NaT, index=d.index)
    closed = pd.to_datetime(d["close_date"], errors="coerce") if "close_date" in d.columns else pd.Series(pd.NaT, index=d.index)
    invalid = created.notna() & closed.notna() & (closed < created)
    excluded = int(invalid.sum())
    d = d[~invalid].copy()
    d["stage_l"] = d.get("stage", "").astype(str).str.lower().str.strip()
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
    years = None
    target_date_error = None
    if target_date:
        try:
            td = pd.Timestamp(target_date)
        except (ValueError, TypeError):
            td = None
            target_date_error = f"Target date '{target_date}' is not a valid date"
        if td is not None and not (2000 <= td.year <= 2100):
            target_date_error = f"Target date year ({td.year}) must be between 2000 and 2100"
            td = None
        if td is not None:
            now = latest.to_timestamp(how="end")
            if td <= now:
                target_date_error = f"Target date {td.date()} must be after the as-of month ({_period_str(latest)})"
            else:
                years = (td - now).days / 365
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

    return {
        "current_customers": n_cust,
        "current_arr": _round(total_arr),
        "acv": _round(acv),
        "target_arr": target_arr,
        "target_date": target_date,
        "bands": bands,
        "overall_band": overall_band,
        "by_segment": by_segment,
        "customers_needed": _full(customers_needed),
        "required_net_new_per_year": _round(required_per_year, 1),
        "observed_net_new_per_year_12m": _round(obs12, 1),
        "observed_net_new_per_year_24m": _round(obs24, 1),
        "required_vs_observed_12m": _round(required_per_year / obs12, 2) if (required_per_year and obs12) else None,
        "required_vs_observed_24m": _round(required_per_year / obs24, 2) if (required_per_year and obs24) else None,
        "target_date_error": target_date_error,
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
            return pd.Series(pd.NaT, index=deals.index)
        return pd.to_datetime(deals[col], errors="coerce").dt.to_period("M")
    created, closed = months("created_date"), months("close_date")
    after = (closed.notna() & (closed > as_of)) | (created.notna() & (created > as_of))
    return deals[~after].copy(), int(after.sum())


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

    # As-of month: truncate all "current"/time-series views to <= as_of. MRR after the
    # as-of month is deferred revenue and must not appear in current figures.
    as_of = _resolve_as_of(config.get("as_of_month"), pnl, mrr)
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
        missing_data.append({"metric": "Sales cycle & win rate",
                             "reason": ("CRM deals not provided" if not deals_loaded else
                                        f"All {deals_loaded} CRM deals were created or closed after the as-of month"),
                             "unlocked_by": "Upload CRM deals with deal ID, created date, close date, stage, amount", "file": crm_src.get("file")})
    else:
        sc = compute_sales_cycle(deals)
        if sc is not None:
            sc["source"] = src(crm_src, deals.get("_row", []).tolist() if "_row" in deals.columns else [],
                               "Median days from created to close, won deals closed by the as-of month")
        results["sales_cycle"] = sc
        if sc is not None and "segment" not in deals.columns:
            missing_data.append({"metric": "Sales cycle by segment", "reason": "Segment column not mapped on CRM deals",
                                 "unlocked_by": "Map optional 'segment' column on CRM deals", "file": crm_src.get("file")})

        founder_available = "founder_involved" in deals.columns and deals["founder_involved"].notna().any()
        wr = compute_win_rate(deals, founder_available)
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

    acv = compute_acv_path(mrr, seg_map, first_month, target_arr, target_date, reporting_currency)
    if acv:
        acv["source"] = src(rev_src, contrib_rows, "ACV = ARR ÷ active customers; path compares required vs observed net-new")
        if acv.get("target_date_error"):
            missing_data.append({
                "metric": "Path to Plan (required net-new)",
                "reason": acv["target_date_error"],
                "unlocked_by": "Set a target date with a year between 2000 and 2100, after the as-of month",
                "file": rev_src.get("file"),
            })
    results["acv_path"] = acv

    results["anomalies"] = compute_anomalies(mrr, rev, deals, mrr_notes)
    results["mrr_series"] = compute_mrr_series(mrr, seg_map)
    results["cohort_retention"] = compute_cohort_retention(mrr, first_month)
    results["missing_data"] = missing_data
    return results
