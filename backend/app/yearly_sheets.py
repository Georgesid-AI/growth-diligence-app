"""The yearly P&L work in the Excel export: four sheets read from `role_metrics` and the comparison lines, and the true reason for a CAC payback
that a yearly P&L cannot give. Pure functions of the stored results; nothing is computed here and no model is called.

Each sheet is (name, header, rows, kinds): `kinds` is the number kind of the value cell of each row (None: text), so the workbook keeps numeric
cells with the formats of app/formatting.py."""
from typing import Dict, List, Optional, Tuple

from . import formatting as fmt
from . import plan_lines
from .ic_memo import cell_ranges
from .role_engine import ESTIMATE_LABEL

METRICS_SHEET, ESTIMATES_SHEET, TREND_SHEET, ASSUMES_SHEET = "Yearly P&L metrics", "Estimates", "Yearly P&L trend", plan_lines.HEADING
SHEETS = (METRICS_SHEET, ESTIMATES_SHEET, TREND_SHEET, ASSUMES_SHEET)
NEEDS_MONTHLY_PNL = "needs a monthly P&L; the P&L supplied is yearly"
KIND_OF_UNIT = {"money": fmt.CURRENCY, "rate": fmt.PCT, "months": fmt.MONTHS, "count": fmt.COUNT}
METRIC_HEADER = ["Metric", "Year", "Value", "Cells", "Estimate", "Method"]
Sheet = Tuple[str, List[str], List[list], List[Optional[str]]]


def yearly_pnl_read(results: dict) -> bool:
    """A yearly P&L was read: the yearly-basis block holds a year, or the yearly trend holds a row."""
    return bool(((results.get("yearly_basis") or {}).get("years")) or ((results.get("role_metrics") or {}).get("pnl_trend") or {}).get("rows"))


def _cells(file: Optional[str], sheet: Optional[str], cells) -> str:
    """"pnl · P&L!B4, C4": the file, the sheet and the cells, as the memo's tables print them (neighbouring cells as ranges)."""
    cells = ", ".join(cell_ranges(cells or ()))
    return " · ".join(p for p in (file, f"{sheet}!{cells}" if sheet and cells else cells) if p)


def _metric_rows(results: dict, estimates: bool) -> Tuple[List[list], List[Optional[str]]]:
    rows, kinds = [], []
    for m in (results.get("role_metrics") or {}).get("metrics") or ():
        if m["status"] != "computed" or m.get("basis") != "yearly" or bool(m.get("estimate")) != estimates:
            continue
        s = m.get("source") or {}
        rows.append([m.get("name") or m["metric"], m.get("period"), m["value"], _cells(s.get("file"), s.get("sheet"), s.get("cells")),
                     "yes" if m.get("estimate") else "no", s.get("rule") or ""])
        kinds.append(KIND_OF_UNIT.get(m.get("unit")))
    return rows, kinds


def _trend(results: dict) -> Optional[Sheet]:
    trend = (results.get("role_metrics") or {}).get("pnl_trend")
    if not trend or not trend.get("rows"):
        return None
    periods = trend["periods"]
    header = ["Metric", *[p["period"] + (" (plan)" if p["kind"] == "plan" else "") for p in periods]]
    rows = []
    for r in trend["rows"]:
        by_period = {v["period"] + v["kind"]: v for v in r["values"]}
        est = [v["period"] for v in r["values"] if v["estimate"]]
        rows.append([r["name"] + (f" ({ESTIMATE_LABEL}: {', '.join(est)})" if est else ""),
                     *[(by_period[p["period"] + p["kind"]]["value"] if p["period"] + p["kind"] in by_period else None) for p in periods]])
    return TREND_SHEET, header, rows, [KIND_OF_UNIT[r["unit"]] for r in trend["rows"]]


def _yearly_metric_read(results: dict) -> bool:
    """A role metric of yearly basis was computed (the EBITDA margin of twelve months of a monthly file, with no yearly P&L)."""
    return any(m["status"] == "computed" and m.get("basis") == "yearly" for m in (results.get("role_metrics") or {}).get("metrics") or ())


def sheets(results: dict, ccy: Optional[str]) -> List[Sheet]:
    """The four sheets of the yearly P&L work; a sheet with no row is left out. Empty when no yearly P&L was read and no yearly-basis metric
    was computed."""
    if not yearly_pnl_read(results) and not _yearly_metric_read(results):
        return []
    out: List[Sheet] = []
    plain, plain_kinds = _metric_rows(results, False)
    est, est_kinds = _metric_rows(results, True)
    for name, rows, kinds in ((METRICS_SHEET, plain + est, plain_kinds + est_kinds), (ESTIMATES_SHEET, est, est_kinds)):
        if rows:
            out.append((name, METRIC_HEADER, rows, kinds))
    trend = _trend(results)
    if trend:
        out.append(trend)
    lines = plan_lines.lines(results, ccy)
    if lines:
        out.append((ASSUMES_SHEET, ["Line", "Cells"],
                    [[item["text"], _cells(item.get("file"), item.get("sheet"), item["cells"])] for item in lines], [None] * len(lines)))
    return out


def missing_reason(results: dict, item: Dict) -> Dict:
    """A CAC payback that is Missing with a yearly P&L read: the true reason, whatever the engine's wording for it."""
    if item.get("metric") == "CAC payback" and item.get("status", "Missing") == "Missing" and not results.get("cac_payback") and yearly_pnl_read(results):
        return {**item, "reason": NEEDS_MONTHLY_PNL}
    return item


def write(xw, sheet: Sheet) -> None:
    """One sheet into a pandas ExcelWriter: each numeric cell is stored as a number with the Excel format of its row's kind (formatting.py)."""
    import pandas as pd

    name, header, rows, kinds = sheet
    shown = [[fmt.xlsx_value(k, v) if k and isinstance(v, (int, float)) and not isinstance(v, bool) else v for v in row] for row, k in zip(rows, kinds)]
    pd.DataFrame(shown, columns=header).to_excel(xw, sheet_name=name, index=False)
    ws = xw.sheets[name]
    for i, (row, k) in enumerate(zip(shown, kinds), start=2):
        for j, v in enumerate(row, start=1):
            if k and isinstance(v, (int, float)) and not isinstance(v, bool):
                ws.cell(row=i, column=j).number_format = fmt.XLSX_NUMBER_FORMAT[k]
