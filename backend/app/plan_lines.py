"""The memo's "What the plan assumes" (docs/design/pnl-lines.md, "The comparison lines"): the yearly P&L trend table and the comparison lines.

Every line is a fixed string template in this file, filled from values the engine computed (`role_metrics.pnl_trend`, `plan_to_date`,
`reconciliation`); each line comes with the cells it was built from. No model writes a line, and an input that is missing, or an estimate whose
checks failed, gives no line (it is never replaced by a guess). Numbers go through the one formatter (app/formatting.py).
"""
from typing import Dict, List, Optional

from . import formatting as fmt
from .claim_matching import AMOUNT_TOLERANCE

HEADING = "What the plan assumes"
RATE_STABLE = 0.02          # shares and margins: within ±2 points is "stable"
MONEY_STABLE = AMOUNT_TOLERANCE      # money: within ±5% (claim matching's amount tolerance) is "stable"
ESTIMATE_WORD = ", estimate"
PLAN_RISES = "Plan assumes {metric} rises from {a} ({year_a}{label}) to {p} ({year_p})."
PLAN_FALLS = "Plan assumes {metric} falls from {a} ({year_a}{label}) to {p} ({year_p})."
PLAN_HOLDS = "Plan holds {metric} at about {a} ({year_a}{label}) through {year_p}."
TREND_ROSE = "{metric} rose from {first} ({year_first}) to {last} ({year_last})."
TREND_FELL = "{metric} fell from {first} ({year_first}) to {last} ({year_last})."
TREND_MOVED = "{metric} moved between {low} and {high} over {year_first}–{year_last}."
PLAN_TO_DATE_BEHIND = "Revenue is {gap} ({gap_pct}) behind plan to {month}."
PLAN_TO_DATE_AHEAD = "Revenue is {gap} ({gap_pct}) ahead of plan to {month}."
PLAN_TO_DATE_ON = "Revenue is on plan to {month}."
RECONCILIATION = "{metric} {year} differs across sources by {diff} ({pct}): {list}."
RECON_NAMES = {"revenue": "Revenue", "arr": "ARR", "mrr": "MRR", "customers": "Customers", "ebitda": "EBITDA", "cash": "Cash", "headcount": "Headcount"}
COUNTS = ("customers", "headcount")
MISSING = "—"


def _shown(unit: str, value: float, ccy: Optional[str]) -> str:
    return fmt.fmt_currency(value, ccy) if unit == "money" else fmt.fmt_pct(value)


def _lower(name: str) -> str:
    """"Gross margin" for the middle of a sentence; "S&M share of revenue", "EBITDA margin" keep their capitals."""
    return name if name.split(" ")[0].isupper() or "&" in name.split(" ")[0] else name[:1].lower() + name[1:]


def _stable(unit: str, a: float, b: float) -> bool:
    """Within ±2 points for a share or a margin, within ±5% of the first figure for money (the boundary is stable)."""
    gap = abs(b - a)
    return round(gap, 9) <= (RATE_STABLE if unit == "rate" else MONEY_STABLE * abs(a) + 1e-9)


def _line(kind: str, text: str, cells: List[str], where: Optional[Dict] = None, beyond: bool = False) -> Dict:
    return {"kind": kind, "text": text, "cells": list(dict.fromkeys(cells)), "file": (where or {}).get("file"), "sheet": (where or {}).get("sheet"),
            "beyond_tolerance": beyond}


def trend_lines(trend: Optional[Dict], ccy: Optional[str]) -> List[Dict]:
    """Plan against the latest actual year, and the movement over the actual years, for each row of the trend."""
    out: List[Dict] = []
    for row in (trend or {}).get("rows") or ():
        unit, name = row["unit"], row["name"]
        actual = [v for v in row["values"] if v["kind"] == "actual"]
        plans = [v for v in row["values"] if v["kind"] == "plan"]
        last_actual = next((p["period"] for p in reversed(trend["periods"]) if p["kind"] == "actual"), None)
        last_plan = next((p["period"] for p in reversed(trend["periods"]) if p["kind"] == "plan"), None)
        a = next((v for v in actual if v["period"] == last_actual), None)
        p = next((v for v in plans if v["period"] == last_plan), None)
        if a is not None and p is not None:
            if _stable(unit, a["value"], p["value"]):
                template = PLAN_HOLDS
            else:
                template = PLAN_RISES if p["value"] > a["value"] else PLAN_FALLS
            text = template.format(metric=_lower(name), a=_shown(unit, a["value"], ccy), year_a=a.get("label") or a["period"],
                                   label=ESTIMATE_WORD if a["estimate"] else "", p=_shown(unit, p["value"], ccy), year_p=p["period"])
            out.append(_line("plan_vs_past", text, [*a["cells"], *p["cells"]], trend))
        stated = [v for v in actual if not v["estimate"]]        # an estimate is not a trend: it is the plan's split on one year's OPEX
        if len(stated) >= 2:
            first, last = stated[0], stated[-1]
            if _stable(unit, first["value"], last["value"]):
                low, high = min(v["value"] for v in stated), max(v["value"] for v in stated)
                text = TREND_MOVED.format(metric=name, low=_shown(unit, low, ccy), high=_shown(unit, high, ccy),
                                          year_first=first["period"], year_last=last.get("label") or last["period"])
            else:
                template = TREND_ROSE if last["value"] > first["value"] else TREND_FELL
                text = template.format(metric=name, first=_shown(unit, first["value"], ccy), year_first=first["period"],
                                       last=_shown(unit, last["value"], ccy), year_last=last.get("label") or last["period"])
            out.append(_line("trend", text, [c for v in stated for c in v["cells"]], trend))
    return out


def plan_to_date_line(plan: Optional[Dict], ccy: Optional[str]) -> Optional[Dict]:
    """Revenue against the plan to the as-of month. No percentage (a plan of zero) = no line. Beyond ±5% the line is also a Worth flagging line."""
    if not plan or plan.get("variance_pct") is None:
        return None
    month = fmt.fmt_month_name(plan["period"])
    src = plan.get("source") or {}
    if round(abs(plan["variance_pct"]), 9) <= MONEY_STABLE:
        return _line("plan_to_date", PLAN_TO_DATE_ON.format(month=month), src.get("cells") or [], src)
    template = PLAN_TO_DATE_AHEAD if plan["variance"] > 0 else PLAN_TO_DATE_BEHIND
    return _line("plan_to_date", template.format(gap=fmt.fmt_currency(abs(plan["variance"]), ccy), gap_pct=fmt.fmt_pct(abs(plan["variance_pct"])),
                                                 month=month), src.get("cells") or [], src, beyond=True)


def reconciliation_lines(reconciliation: List[Dict], ccy: Optional[str]) -> List[Dict]:
    out = []
    for r in reconciliation or ():
        if r.get("status") != "differs" or r.get("gap") is None or r.get("gap_pct") is None or r["metric"] not in RECON_NAMES:
            continue
        shown = (lambda v: fmt.fmt_count(v)) if r["metric"] in COUNTS else (lambda v: fmt.fmt_currency(v, ccy))      # noqa: E731
        listed = "; ".join(f"{s['file']} {s['where']} {shown(s['value'])}" for s in r["sources"])
        out.append(_line("reconciliation", RECONCILIATION.format(metric=RECON_NAMES[r["metric"]], year=r["period"], diff=shown(r["gap"]),
                                                                 pct=fmt.fmt_pct(r["gap_pct"]), list=listed), [s["where"] for s in r["sources"]]))
    return out


def lines(results: dict, ccy: Optional[str]) -> List[Dict]:
    """Every comparison line of the results: plan against the past and the trend of each row, plan to date, reconciliation."""
    rm = results.get("role_metrics") or {}
    out = trend_lines(rm.get("pnl_trend"), ccy)
    pd_line = plan_to_date_line(rm.get("plan_to_date"), ccy)
    return out + ([pd_line] if pd_line else []) + reconciliation_lines(rm.get("reconciliation") or [], ccy)


def table(trend: Optional[Dict], ccy: Optional[str]):
    """(header, rows) of the yearly trend: one row per metric, actual years first, then plan years; an estimate carries the suffix ", estimate" (the full label is in the Estimates block and the method text)."""
    if not trend:
        return None
    header = ["Metric", *[(p.get("label") or p["period"]) + (" (plan)" if p["kind"] == "plan" else "") for p in trend["periods"]]]
    rows = []
    for row in trend["rows"]:
        by_period = {v["period"] + v["kind"]: v for v in row["values"]}
        cells = []
        for p in trend["periods"]:
            v = by_period.get(p["period"] + p["kind"])
            cells.append(MISSING if v is None else _shown(row["unit"], v["value"], ccy) + (ESTIMATE_WORD if v["estimate"] else ""))
        rows.append([row["name"], *cells])
    return header, rows
