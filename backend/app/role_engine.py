"""The engine's inputs by role (docs/design/read-check-review.md section 16; PR 4 step a).

Every engine input comes from the stored map and its stored series (app/series.py), by the role the reader gave the row: revenue, bookings, arr,
mrr, churn_rate, customers, forecast (plan), cost_of_revenue, sales_marketing, rnd, ga, opex, ebitda, cash, headcount. Pure functions: no database,
no model, no file. A metric runs when the rows it needs exist; otherwise it says "needs a <role> row" and names the roles, never a line, a
column or a file type.

    build_table(files)   the role table of the audit's stored readings: one record per mapped row that has a series
    compute(...)         the `role_metrics` block (every metric, computed or "needs a <role> row"), the blocks of the contract the map feeds
                         (arr, mrr_series, revenue_series, customers_series) and the yearly P&L the existing yearly-basis block is computed from

Code never reads and never decides what a row means: it picks the row by the reader's role, the total row (no segment) before a split, the
granularity a metric needs, and does arithmetic on the cells the series holds. A row whose check was rejected is not an input.
"""
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

ROLES = ("revenue", "bookings", "arr", "mrr", "churn_rate", "customers", "forecast", "cost_of_revenue", "sales_marketing", "rnd", "ga", "opex",
         "ebitda", "cash", "headcount")
# Metric name -> the roles it needs (section 16). A tuple of alternatives is "one of".
NEEDS = {
    "ending_arr": (("arr", "mrr"),),
    "mrr_series": ("mrr",),
    "monthly_churn": ("churn_rate",),
    "customers": ("customers",),
    "growth": (("revenue", "arr", "mrr"),),
    "plan_to_date": ("revenue", "forecast"),
    "yearly_revenue": ("revenue",),
    "gross_margin": ("revenue", "cost_of_revenue"),
    "sm_share": ("revenue", "sales_marketing"),
    "yearly_cac_payback": ("revenue", "cost_of_revenue", "sales_marketing"),
    "rnd_share": ("revenue", "rnd"),
    "ga_share": ("revenue", "ga"),
    "opex_share": ("revenue", "opex"),
    "ebitda_margin": ("revenue", "ebitda"),
    "bookings": ("bookings",),
    "cash": ("cash",),
    "headcount": ("headcount",),
    "reconciliation": (),
}
NAMES = {
    "ending_arr": "Ending ARR", "mrr_series": "MRR", "monthly_churn": "Monthly churn", "customers": "Customers",
    "growth": "Growth", "plan_to_date": "Plan to date", "yearly_revenue": "Yearly revenue", "gross_margin": "Gross margin",
    "sm_share": "S&M share of revenue", "yearly_cac_payback": "CAC payback (yearly)", "rnd_share": "R&D share of revenue",
    "ga_share": "G&A share of revenue", "opex_share": "Operating expenses share of revenue", "ebitda_margin": "EBITDA margin",
    "bookings": "Bookings", "cash": "Cash", "headcount": "Headcount", "reconciliation": "Reconciliation",
}
YEARLY_LABEL = "yearly"
FORM = {"monthly": "month", "quarterly": "quarter", "yearly": "year"}
DECK_METRICS = {"revenue": "revenue", "arr": "arr", "mrr": "mrr", "customers": "customers", "headcount": "headcount", "cash": "cash",
                "ebitda": "ebitda"}      # a role's name in the deck reader's closed metric list
RECONCILE_ROLES = ("revenue", "arr", "mrr", "customers", "ebitda", "cash", "headcount")
RECONCILE_TOLERANCE = 0.005         # money within 0.5 %, as the cell checks (app/checks.py); a count exact
CUMULATIVE = "cumulative_to_date"


AN = ("mrr", "rnd")         # read letter by letter: "an mrr row"


def _a(name: str) -> str:
    return "an" if name[:1] in "aeiou" or name in AN else "a"


def needs_text(roles) -> str:
    """"needs a revenue row", "needs an arr row", "needs a revenue row and a cost_of_revenue row": the roles by their own names."""
    names = [(r if isinstance(r, str) else " or ".join(r)) for r in roles]
    return "needs " + " and ".join(f"{_a(n)} {n} row" for n in names)


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------
def build_table(files: List[Dict]) -> List[Dict]:
    """The role table: [{"file", "sheet", "row", "role", "metric", "basis", "actual_plan", "granularity", "segment", "unit", "currency",
    "actual": {period: (value, cell)}, "plan": {...}, "unchecked": bool}] of every row of the files' maps that has a series.
    `files` is [{"file", "file_map" (the effective map with its series), "rejected" (row keys the checks rejected), "cannot" (row keys they
    could not check)}]. A rejected row is no input."""
    table: List[Dict] = []
    for f in files:
        rejected, cannot = set(f.get("rejected") or ()), set(f.get("cannot") or ())
        for smap in (f.get("file_map") or {}).get("sheets") or []:
            for row in smap.get("rows") or []:
                if f"row:{smap['sheet']}:{row['row']}" in rejected:
                    continue
                pairs = {key: dict(zip(row[key]["periods"], zip(row[key]["values"], row[key]["refs"]))) for key in ("series", "plan_series")
                         if row.get(key)}
                if not pairs:
                    continue
                table.append({"file": f.get("file"), "sheet": smap["sheet"], "row": row["row"], "role": row["role"], "metric": row.get("metric"),
                              "basis": row.get("basis"), "actual_plan": row.get("actual_plan"), "granularity": smap.get("granularity"),
                              "segment": (row.get("segment") or "").strip() or None, "unit": row.get("unit"), "currency": row.get("currency") or smap.get("currency"),
                              "actual": pairs.get("series", {}), "plan": pairs.get("plan_series", {}),
                              "unchecked": f"row:{smap['sheet']}:{row['row']}" in cannot})
    return table


def _end_month(period: str, fye: int = 12) -> Optional[pd.Period]:
    """The last month a period covers: "2026-03" itself, "2026-Q1" its third month, "2026" the fiscal year's last month."""
    try:
        if re.fullmatch(r"\d{4}-\d{2}", period):
            return pd.Period(period, "M")
        m = re.fullmatch(r"(\d{4})-Q([1-4])", period)
        if m:
            return pd.Period(f"{m.group(1)}-{int(m.group(2)) * 3:02d}", "M")
        if re.fullmatch(r"\d{4}", period):
            return pd.Period(f"{period}-{fye:02d}", "M")
    except Exception:
        return None
    return None


def _months(rec: Dict, key: str = "actual", as_of: Optional[pd.Period] = None, fye: int = 12) -> List[Tuple[pd.Period, float, str]]:
    """[(month, value, cell)] of a row's series in order, to the as-of month when given."""
    out = []
    for period, (value, cell) in rec[key].items():
        month = _end_month(period, fye)
        if month is not None and (as_of is None or month <= as_of):
            out.append((month, value, cell))
    return sorted(out, key=lambda x: x[0])


def pick(table: List[Dict], role: str, granularity: Optional[str] = None, key: str = "actual") -> Optional[Dict]:
    """The row a role is read from: a total (no segment) before a split, the wanted granularity before another, the longer series before the
    shorter, then file order. None when no row of the role holds a series of the kind."""
    found = [r for r in table if r["role"] == role and r[key] and r["segment"] is None]
    if granularity:
        found = [r for r in found if r["granularity"] == granularity] or []
    return max(found, key=lambda r: (len(r[key]), -table.index(r)), default=None)


def _source(rec: Dict, cells: List[str], rule: str) -> Dict:
    return {"file": rec["file"], "sheet": rec["sheet"], "row": rec["row"], "cells": cells, "rule": rule}


def _entry(metric: str, **fields) -> Dict:
    base = {"metric": metric, "name": NAMES[metric], "status": "computed", "reason": None, "needs": _flat(NEEDS[metric]), "period": None,
            "basis": None, "unit": None, "value": None, "label": None, "detail": None, "source": None}
    base.update(fields)
    return base


def _flat(needs) -> List[str]:
    return [r if isinstance(r, str) else "/".join(r) for r in needs]


def _missing(metric: str, reason: Optional[str] = None, needs=None) -> Dict:
    roles = NEEDS[metric] if needs is None else needs
    return _entry(metric, status="needs_row", reason=reason or needs_text(roles))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def _latest(rec: Dict, as_of: pd.Period, fye: int) -> Optional[Tuple[pd.Period, float, str, str]]:
    """(month, value, cell, period text) of the row's last actual value at or before the as-of month."""
    best = None
    for period, (value, cell) in rec["actual"].items():
        month = _end_month(period, fye)
        if month is not None and month <= as_of and (best is None or month > best[0]):
            best = (month, value, cell, period)
    return best


def ending_arr(table, as_of, fye) -> Tuple[Dict, Optional[Dict]]:
    """Ending ARR at the as-of month: the arr row's value, else the mrr row's × 12. The second item is the contract's `arr` block."""
    for role, factor in (("arr", 1), ("mrr", 12)):
        rec = pick(table, role, "monthly") or pick(table, role)
        if rec is None:
            continue
        last = _latest(rec, as_of, fye)
        if last is None:
            continue
        month, value, cell, period = last
        rule = "ARR = the arr row at the latest actual month" if role == "arr" else "ARR = the mrr row at the latest actual month × 12"
        src = _source(rec, [cell], rule)
        entry = _entry("ending_arr", period=period, basis=rec["basis"] or rec["granularity"], unit="money", value=value * factor,
                       label=("from the arr row" if role == "arr" else "from the mrr row × 12"), source=src)
        block = None
        if re.fullmatch(r"\d{4}-\d{2}", period):
            block = {"value": value * factor, "mrr": value * factor / 12 if role == "arr" else value, "month": period,
                     "source": {"file": rec["file"], "sheet": rec["sheet"], "rows": f"row {rec['row']}", "row_numbers": [rec["row"]], "rule": rule}}
        return entry, block
    return _missing("ending_arr", "needs an arr row or an mrr row"), None


def mrr_series(table, as_of, fye) -> Tuple[Dict, Optional[Dict]]:
    rec = pick(table, "mrr", "monthly")
    if rec is None:
        return _missing("mrr_series"), None
    months = _months(rec, "actual", as_of, fye)
    if not months:
        return _missing("mrr_series", "the mrr row holds no value at or before the as-of month"), None
    rule = "MRR = the mrr row, month by month, to the as-of month"
    block = {"months": [str(m) for m, _, _ in months], "segments": [], "data": [{"month": str(m), "total": v} for m, v, _ in months],
             "source": {"file": rec["file"], "sheet": rec["sheet"], "rows": f"row {rec['row']}", "row_numbers": [rec["row"]], "rule": rule}}
    last = months[-1]
    return _entry("mrr_series", period=str(last[0]), basis="monthly", unit="money", value=last[1], label=f"{len(months)} months",
                  source=_source(rec, [c for _, _, c in months], rule)), block


def monthly_churn(table, as_of, fye) -> Dict:
    rec = pick(table, "churn_rate", "monthly")
    if rec is None:
        if pick(table, "churn_rate"):
            return _missing("monthly_churn", "the churn_rate row is not monthly; needs a monthly churn_rate row")
        return _missing("monthly_churn")
    last = _latest(rec, as_of, fye)
    if last is None:
        return _missing("monthly_churn", "the churn_rate row holds no value at or before the as-of month")
    month, value, cell, period = last
    return _entry("monthly_churn", period=period, basis="monthly", unit="rate", value=value,
                  source=_source(rec, [cell], "Monthly churn = the churn_rate row at the latest actual month, as the file states it"))


def customers(table, as_of, fye) -> Tuple[Dict, Optional[Dict]]:
    rec = pick(table, "customers", "monthly") or pick(table, "customers")
    if rec is None:
        return _missing("customers"), None
    last = _latest(rec, as_of, fye)
    if last is None:
        return _missing("customers", "the customers row holds no value at or before the as-of month"), None
    month, value, cell, period = last
    rule = "Customers = the customers row at the latest actual month"
    entry = _entry("customers", period=period, basis=rec["basis"] or rec["granularity"], unit="count", value=value, source=_source(rec, [cell], rule))
    block = None
    if rec["granularity"] == "monthly":
        months = _months(rec, "actual", as_of, fye)
        block = {"months": [str(m) for m, _, _ in months], "segments": [], "data": [{"month": str(m), "total": round(v)} for m, v, _ in months],
                 "source": {"file": rec["file"], "sheet": rec["sheet"], "rows": f"row {rec['row']}", "row_numbers": [rec["row"]], "rule": rule}}
    return entry, block


def revenue_series(table, as_of, fye) -> Optional[Dict]:
    """The contract's `revenue_series` block from the monthly revenue row (a cumulative row is not a monthly series)."""
    rec = pick(table, "revenue", "monthly")
    if rec is None or rec["basis"] in (CUMULATIVE, "last_12_months"):
        return None
    months = _months(rec, "actual", as_of, fye)
    if not months:
        return None
    return {"months": [str(m) for m, _, _ in months], "segments": [], "data": [{"month": str(m), "total": v} for m, v, _ in months],
            "basis": "row", "file_type": "monthly_revenue_report", "growth_label": "Revenue growth",
            "source": {"file": rec["file"], "sheet": rec["sheet"], "rows": f"row {rec['row']}", "row_numbers": [rec["row"]],
                       "rule": "Revenue = the revenue row, month by month, to the as-of month"}}


def growth(table, as_of, fye) -> List[Dict]:
    """Month on month and year on year growth of the revenue row (else the arr row, else the mrr row). A cumulative or last-12-months row is
    not a monthly flow: it gets no month-on-month figure."""
    for role, label in (("revenue", "Revenue growth"), ("arr", "ARR growth"), ("mrr", "MRR growth")):
        rec = pick(table, role, "monthly") or pick(table, role, "yearly") or pick(table, role)
        if rec is None:
            continue
        flow = rec["basis"] not in (CUMULATIVE, "last_12_months")
        pts = _months(rec, "actual", as_of, fye)
        out = []
        if not pts:
            return [_missing("growth", f"the {role} row holds no value at or before the as-of month")]
        last = pts[-1]
        by_month = {m: (v, c) for m, v, c in pts}
        if rec["granularity"] == "monthly":
            prev = by_month.get(last[0] - 1)
            if flow and prev and prev[0]:
                out.append(_entry("growth", period=str(last[0]), basis="monthly", unit="rate", value=last[1] / prev[0] - 1, label=f"{label}, month on month",
                                  source=_source(rec, [prev[1], last[2]], f"{label} = {role} row ÷ the month before − 1")))
            back = by_month.get(last[0] - 12)
            if back and back[0]:
                out.append(_entry("growth", period=str(last[0]), basis="monthly", unit="rate", value=last[1] / back[0] - 1, label=f"{label}, year on year",
                                  source=_source(rec, [back[1], last[2]], f"{label} = {role} row ÷ the same month a year before − 1")))
        elif rec["granularity"] == "yearly" and len(pts) >= 2 and pts[-2][1]:
            out.append(_entry("growth", period=str(last[0]), basis="yearly", unit="rate", value=last[1] / pts[-2][1] - 1,
                              label=f"{label}, year on year ({YEARLY_LABEL})",
                              source=_source(rec, [pts[-2][2], last[2]], f"{label} = {role} row ÷ the year before − 1")))
        if out:
            return out
        return [_missing("growth", f"the {role} row has no earlier period to compare with"
                         + ("" if flow else "; it is cumulative, not monthly"))]
    return [_missing("growth", "needs a revenue row")]


def plan_to_date(table, as_of, fye) -> Tuple[Dict, Optional[Dict]]:
    """Actual to the as-of month against the plan row to the same month. A plan row that is monthly is compared month with month; one that is
    cumulative is compared with the actual accumulated over the same span; a full-year plan is never compared with actual-to-date."""
    actual = pick(table, "revenue", "monthly")
    plan = pick(table, "forecast", key="plan") or pick(table, "forecast")
    if actual is None or plan is None:
        roles = [r for r, found in (("revenue", actual), ("forecast", plan)) if found is None]
        return _missing("plan_to_date", needs_text(roles), roles), None
    plan_key = "plan" if plan["plan"] else "actual"
    if plan["granularity"] != "monthly" or plan["basis"] in ("yearly", "last_12_months"):
        reason = "the forecast row is a full-year plan; there is no plan to the as-of month to compare with"
        return _missing("plan_to_date", reason), None
    plan_pts = {m: (v, c) for m, v, c in _months(plan, plan_key, None, fye)}
    act_pts = {m: (v, c) for m, v, c in _months(actual, "actual", as_of, fye)}
    if not act_pts:
        return _missing("plan_to_date", "the revenue row holds no value at or before the as-of month"), None
    if as_of not in plan_pts:
        return _missing("plan_to_date", "the forecast row holds no value for the as-of month"), None
    if actual["basis"] in (CUMULATIVE, "last_12_months"):
        return _missing("plan_to_date", "the revenue row is not monthly; needs a monthly revenue row"), None
    cumulative = plan["basis"] == CUMULATIVE
    if cumulative:
        start = min(plan_pts)
        span = list(pd.period_range(start, as_of, freq="M"))
        gone = [m for m in span if m not in act_pts]
        if gone:
            return _missing("plan_to_date", f"the revenue row holds no value for {gone[0]}; the cumulative plan cannot be compared"), None
        actual_value = sum(act_pts[m][0] for m in span)
        cells = [act_pts[m][1] for m in span] + [plan_pts[as_of][1]]
        basis, note = "cumulative_to_date", f"actual accumulated from {span[0]} against the cumulative plan"
    else:
        if as_of not in act_pts:
            return _missing("plan_to_date", "the revenue row holds no value for the as-of month"), None
        actual_value = act_pts[as_of][0]
        cells = [act_pts[as_of][1], plan_pts[as_of][1]]
        basis, note = "month", "actual of the as-of month against the plan of the same month"
    plan_value = plan_pts[as_of][0]
    variance = actual_value - plan_value
    block = {"period": str(as_of), "basis": basis, "actual": actual_value, "plan": plan_value, "variance": variance,
             "variance_pct": variance / abs(plan_value) if plan_value else None, "note": note,
             "source": {"file": actual["file"], "sheet": actual["sheet"], "row": actual["row"], "cells": cells,
                        "rule": "Plan to date = actual to the as-of month − the plan row to the same month; cumulative only where the plan row is cumulative"}}
    entry = _entry("plan_to_date", period=str(as_of), basis=basis, unit="money", value=variance, label=note,
                   source=_source(actual, cells, block["source"]["rule"]))
    return entry, block


def _year_fields(table, fye) -> Dict[str, Dict]:
    """{year period: {role field: {"value", "cells"}}} of the yearly rows of revenue, cost_of_revenue and sales_marketing (actual cells only)."""
    out: Dict[str, Dict] = {}
    for role, field in (("revenue", "revenue"), ("cost_of_revenue", "cost_of_revenue"), ("sales_marketing", "sm_expense")):
        rec = pick(table, role, "yearly")
        if rec is None:
            continue
        for period, (value, cell) in rec["actual"].items():
            if re.fullmatch(r"\d{4}", period):
                out.setdefault(period, {})[field] = {"value": value, "cells": [cell], "scope": "unknown"}
    return out


def yearly_input(table, as_of, fye) -> Optional[Dict]:
    """The yearly P&L in the shape the yearly-basis block reads (growth_engine.compute_yearly_basis): the actual fiscal years up to the as-of
    month with revenue, cost of revenue and S&M, each with the cells they were read from. None without a yearly revenue row."""
    rev = pick(table, "revenue", "yearly")
    if rev is None:
        return None
    fields = _year_fields(table, fye)
    actual = []
    for period in sorted(fields):
        end = _end_month(period, fye)
        if end is None or end > as_of or "revenue" not in fields[period]:
            continue
        start = end - 11
        actual.append({"period": period, "year": int(period), "start": str(start), "end": str(end), "fields": fields[period]})
    if not actual:
        return None
    rows = sorted({r["row"] for r in table if r["granularity"] == "yearly" and r["role"] in ("revenue", "cost_of_revenue", "sales_marketing")
                   and r["sheet"] == rev["sheet"]})
    return {"file": rev["file"], "sheet": rev["sheet"], "actual": actual, "planned": [], "reported": [], "rows": rows}


def stock(metric: str, role: str, unit: str, table, as_of, fye) -> Dict:
    rec = pick(table, role, "monthly") or pick(table, role)
    if rec is None:
        return _missing(metric)
    last = _latest(rec, as_of, fye)
    if last is None:
        return _missing(metric, f"the {role} row holds no value at or before the as-of month")
    month, value, cell, period = last
    return _entry(metric, period=period, basis=rec["basis"] or rec["granularity"], unit=unit, value=value,
                  source=_source(rec, [cell], f"{NAMES[metric]} = the {role} row at the latest actual month"))


def share(metric: str, role: str, table, as_of, fye) -> Dict:
    """A cost line (or EBITDA) over revenue, in the latest period both rows hold with the same granularity."""
    cost = pick(table, role, "yearly") or pick(table, role, "monthly")
    rev = pick(table, "revenue", cost["granularity"]) if cost else pick(table, "revenue")
    missing = [r for r, found in (("revenue", rev), (role, cost)) if found is None]
    if missing:
        return _missing(metric, needs_text(missing), missing)
    if rev["basis"] != cost["basis"] and CUMULATIVE in (rev["basis"], cost["basis"]):
        return _missing(metric, f"the {role} row and the revenue row do not accumulate the same way")
    shared = sorted((m for m in {_end_month(p, fye) for p in rev["actual"]} & {_end_month(p, fye) for p in cost["actual"]}
                     if m is not None and m <= as_of))
    if not shared:
        return _missing(metric, f"the revenue row and the {role} row share no period at or before the as-of month")
    m = shared[-1]
    rv = next(v for p, v in rev["actual"].items() if _end_month(p, fye) == m)
    cv = next(v for p, v in cost["actual"].items() if _end_month(p, fye) == m)
    if not rv[0]:
        return _missing(metric, "revenue is zero in the period")
    value = cv[0] / rv[0]
    label = YEARLY_LABEL if cost["granularity"] == "yearly" else None
    return _entry(metric, period=next(p for p in cost["actual"] if _end_month(p, fye) == m), basis=cost["granularity"], unit="rate", value=value,
                  label=label, source=_source(cost, [cv[1], rv[1]], f"{NAMES[metric]} = the {role} row ÷ the revenue row in the same period"))


# ---------------------------------------------------------------------------
# Reconciliation: the same metric in the same period from two or more sources
# ---------------------------------------------------------------------------
def reconcile(table: List[Dict], deck: List[Dict], as_of: pd.Period, fye: int, currency: Optional[str] = None) -> List[Dict]:
    """[{"metric", "period", "basis", "status", "gap", "gap_pct", "sources": [{"kind", "file", "where", "value"}]}] for every metric and period
    that two or more sources state: a sheet row (as the file states it, or the sum of its months for a year), a deck figure. Sources on another
    basis or in another currency are not compared. Actual only, to the as-of month."""
    seen: Dict[Tuple[str, str], List[Dict]] = {}

    def add(metric, period, kind, file, where, value, basis, ccy):
        seen.setdefault((metric, period), []).append({"kind": kind, "file": file, "where": where, "value": value, "basis": basis, "currency": ccy})
    for rec in table:
        if rec["role"] not in RECONCILE_ROLES or rec["segment"] is not None:
            continue
        for period, (value, cell) in rec["actual"].items():
            end = _end_month(period, fye)
            if end is not None and end <= as_of:
                add(rec["role"], period, "file", rec["file"], f"{rec['sheet']}!{cell}", value, rec["basis"] or rec["granularity"], rec["currency"])
        if rec["role"] == "revenue" and rec["granularity"] == "monthly" and rec["basis"] not in (CUMULATIVE, "last_12_months"):
            by_year: Dict[int, List] = {}
            for month, value, cell in _months(rec, "actual", as_of, fye):
                year = month.year if fye == 12 else (month.year + 1 if month.month > fye else month.year)
                by_year.setdefault(year, []).append((month, value, cell))
            for year, pts in by_year.items():
                if len(pts) == 12:
                    add("revenue", str(year), "file", rec["file"], f"{rec['sheet']}!{pts[0][2]}:{pts[-1][2]}", sum(v for _, v, _ in pts), "yearly",
                        rec["currency"])
    for fig in deck:
        role = DECK_METRICS.get(fig.get("metric") or "")
        period = fig.get("period")
        if not role or not period or fig.get("actual_plan") == "plan" or fig.get("value") is None:
            continue
        end = _end_month(period, fye)
        if end is None or end > as_of:
            continue
        basis = "yearly" if re.fullmatch(r"\d{4}", period) else "monthly" if re.fullmatch(r"\d{4}-\d{2}", period) else "quarterly"
        add(role, period, "deck", fig.get("file"), f"page {fig['page']}", fig["value"], basis, fig.get("currency"))
    out = []
    for (metric, period), items in sorted(seen.items()):
        if len(items) < 2 or len({i["kind"] + str(i["file"]) + i["where"] for i in items}) < 2:
            continue
        if len({i["basis"] for i in items}) > 1:
            continue                    # a month and a year, a flow and a cumulative figure, are not the same figure
        ccys = {i["currency"] for i in items if i["currency"]}
        values = [i["value"] for i in items]
        entry = {"metric": metric, "period": period, "basis": items[0]["basis"], "gap": None, "gap_pct": None,
                 "sources": [{k: i[k] for k in ("kind", "file", "where", "value")} for i in items]}
        if len(ccys) > 1:
            entry["status"] = "not_compared"
            entry["reason"] = "the sources state different currencies"
        else:
            gap = max(values) - min(values)
            ref = max(abs(v) for v in values)
            tolerance = 0 if metric in ("customers", "headcount") else RECONCILE_TOLERANCE
            entry["gap"], entry["gap_pct"] = gap, (gap / ref if ref else None)
            entry["status"] = "agrees" if (gap == 0 or (ref and gap / ref <= tolerance)) else "differs"
            entry["reason"] = None
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# The whole
# ---------------------------------------------------------------------------
def compute(table: List[Dict], as_of: Optional[pd.Period], fye: int = 12, deck: Optional[List[Dict]] = None) -> Dict:
    """{"role_metrics": block, "arr", "mrr_series", "customers_series", "revenue_series", "yearly"}: the `role_metrics` block of the contract,
    the legacy blocks the map feeds (None where the rows are missing) and the yearly input of compute_yearly_basis."""
    if as_of is None:
        return {"role_metrics": None, "arr": None, "mrr_series": None, "customers_series": None, "revenue_series": None, "yearly": None}
    metrics: List[Dict] = []
    arr_entry, arr_block = ending_arr(table, as_of, fye)
    mrr_entry, mrr_block = mrr_series(table, as_of, fye)
    cust_entry, cust_block = customers(table, as_of, fye)
    plan_entry, plan_block = plan_to_date(table, as_of, fye)
    metrics += [arr_entry, mrr_entry, monthly_churn(table, as_of, fye), cust_entry, *growth(table, as_of, fye), plan_entry]
    yearly = yearly_input(table, as_of, fye)
    metrics.append(_missing("yearly_revenue") if pick(table, "revenue", "yearly") is None else _entry("yearly_revenue", status="computed"))
    metrics += [share("sm_share", "sales_marketing", table, as_of, fye), share("rnd_share", "rnd", table, as_of, fye),
                share("ga_share", "ga", table, as_of, fye), share("opex_share", "opex", table, as_of, fye),
                share("ebitda_margin", "ebitda", table, as_of, fye), stock("bookings", "bookings", "money", table, as_of, fye),
                stock("cash", "cash", "money", table, as_of, fye), stock("headcount", "headcount", "count", table, as_of, fye)]
    return {"role_metrics": {"as_of_month": str(as_of), "metrics": metrics, "plan_to_date": plan_block, "reconciliation": reconcile(table, deck or [], as_of, fye)},
            "arr": arr_block, "mrr_series": mrr_block, "customers_series": cust_block, "revenue_series": revenue_series(table, as_of, fye),
            "yearly": yearly}


def fill_yearly(role_metrics: Dict, table: List[Dict], yearly_basis: Optional[Dict]) -> None:
    """The yearly metrics of `role_metrics` from the yearly-basis block (growth_engine.compute_yearly_basis), the latest actual year: yearly
    revenue, gross margin and the yearly CAC payback (labelled yearly). A metric the block cannot give says which role row it needs."""
    by_name = {m["metric"]: i for i, m in enumerate(role_metrics["metrics"])}
    years = (yearly_basis or {}).get("years") or []
    last = years[-1] if years else None

    def put(metric: str, entry: Dict) -> None:
        if metric in by_name:
            role_metrics["metrics"][by_name[metric]] = entry
        else:
            role_metrics["metrics"].append(entry)

    def src(rule: str) -> Dict:
        s = last["source"]
        return {"file": s.get("file"), "sheet": s.get("sheet"), "row": (s.get("row_numbers") or [0])[0] if s.get("row_numbers") else 0,
                "cells": list(last.get("revenue_cells") or []), "rule": rule}
    if last is None:
        for metric in ("yearly_revenue", "gross_margin", "yearly_cac_payback"):
            put(metric, _missing(metric))
        return
    put("yearly_revenue", _entry("yearly_revenue", period=last["period"], basis="yearly", unit="money", value=last["revenue"], label=YEARLY_LABEL,
                                 source=src("Yearly revenue = the revenue row of the fiscal year")))
    if last["gross_margin_pct"] is None:
        put("gross_margin", _missing("gross_margin", "needs a cost_of_revenue row" if pick(table, "cost_of_revenue", "yearly") is None else None,
                                     ["cost_of_revenue"] if pick(table, "cost_of_revenue", "yearly") is None else None))
    else:
        put("gross_margin", _entry("gross_margin", period=last["period"], basis="yearly", unit="rate", value=last["gross_margin_pct"], label=YEARLY_LABEL,
                                   source=src("Gross margin = (revenue − cost of revenue) ÷ revenue")))
    if last["cac_payback_months"] is None:
        put("yearly_cac_payback", _missing("yearly_cac_payback", last["cac_payback_reason"] or None))
    else:
        put("yearly_cac_payback", _entry("yearly_cac_payback", period=last["period"], basis="yearly", unit="months", value=last["cac_payback_months"],
                                         label=last.get("cac_payback_label") or "yearly, revenue-based",
                                         source=src("CAC payback = 12 × S&M ÷ (new revenue × gross margin), yearly")))
    sm = last.get("sm_pct_revenue")
    if sm is not None and "sm_share" in by_name and role_metrics["metrics"][by_name["sm_share"]]["status"] != "computed":
        put("sm_share", _entry("sm_share", period=last["period"], basis="yearly", unit="rate", value=sm, label=YEARLY_LABEL,
                               source=src("S&M share = S&M ÷ revenue")))
