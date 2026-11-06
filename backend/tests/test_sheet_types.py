"""Sheet type from the sheet's name or title (P&L, cash flow, balance sheet), the reconciliation sources, and the parts-counted-twice wording.

Synthetic workbook only: PNL, CASHFLOW (a "revenue" receipts row and a cash row) and BALANCE SHEET. The model's roles are given as a reader would
give them (receipts as revenue, a cash movement as OPEX); the rule is applied at register time to the stored map (checks.retype_by_sheet), as
the label rule is. No network, no MongoDB, no company's figures."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import checks, ic_memo, role_engine, series  # noqa: E402
from app.structures import redact  # noqa: E402
from test_role_engine import metric, run  # noqa: E402

YEARS = ["2023", "2024", "2025"]


def grid(rows, title=None):
    """A yearly sheet: header in row 2 (a title in row 1 when given), the label in column A, the years in B:D."""
    cells = [{"row": 2, "col": 1, "text": "Metric"}] + [{"row": 2, "col": 2 + i, "text": y} for i, y in enumerate(YEARS)]
    if title:
        cells.append({"row": 1, "col": 1, "text": title})
    for n, (label, values) in rows.items():
        cells.append({"row": n, "col": 1, "text": label})
        cells += [{"row": n, "col": 2 + i, "text": str(v)} for i, v in enumerate(values)]
    return cells


def entry(n, role, parent=None):
    return {"row": n, "label_cell": f"A{n}", "role": role, "metric": None if role == "other" else role, "basis": "yearly", "actual_plan": "actual",
            "boundary_col": None, "segment": None, "parent_row": parent, "unit": "money", "currency": "EUR", "cells": f"B{n}:D{n}", "variance_of": None,
            "by_column": False, "evidence": "x"}


def smap(name, rows):
    return {"sheet": name, "header_row": 2, "label_col": "A", "first_period_col": "B", "last_period_col": "D", "granularity": "yearly", "last_actual": None,
            "rows": rows}


PNL = {3: ("Revenue", [1000, 1500, 2400]), 4: ("Total opex", [400, 500, 600]),
       5: ("Sales and marketing", [200, 250, 300]), 6: ("Research", [120, 150, 200]), 7: ("Admin", [80, 100, 100]),    # breakdown by function
       8: ("Personnel", [250, 300, 350]), 9: ("Premises", [100, 120, 150]), 10: ("Other", [50, 80, 100]),               # breakdown by nature
       11: ("Cash per forecast", [700, 750, 999])}                                                                       # a stray cash row on the P&L, first in file order
CASHFLOW = {3: ("Revenue receipts", [900, 1400, 2200]), 4: ("Operating cash outflow", [350, 450, 550]), 5: ("Closing cash", [800, 900, 1100])}
BALANCE = {3: ("Cash", [800, 900, 1100]), 4: ("Total assets", [2000, 2500, 3000])}


def workbook(sheet_names=("PNL", "CASHFLOW", "BALANCE SHEET"), titles=(None, None, None)):
    pnl, cf, bs = sheet_names
    sheets = [{"name": pnl, "cells": grid(PNL, titles[0])}, {"name": cf, "cells": grid(CASHFLOW, titles[1])}, {"name": bs, "cells": grid(BALANCE, titles[2])}]
    text = redact.reading_text(sheets)
    maps = [smap(pnl, [entry(3, "revenue"), entry(4, "opex")] + [entry(n, "other", parent=4) for n in range(5, 11)] + [entry(11, "cash")]),
            smap(cf, [entry(3, "revenue"), entry(4, "opex"), entry(5, "cash")]),
            smap(bs, [entry(3, "cash"), entry(4, "other")])]
    return text, {"map_version": 1, "kind": "sheet", "figures": [], "sheets": maps}


def register(text, fmap):
    """What the register does to a stored reading: the sheet-type rule, the label rule, then the series from the cells."""
    cells = checks.Cells(text)
    typed = checks.classify_by_label(checks.retype_by_sheet(fmap, cells), cells)
    return series.attach(typed, text), typed


def files_of(text, fmap):
    effective, typed = register(text, fmap)
    return [{"file": "workbook", "file_map": effective, "rejected": [], "cannot": [], "totals": checks.check_map(checks.Cells(text), typed)["totals"]}]


def role_of(fmap, sheet, row):
    return next(r for s in fmap["sheets"] if s["sheet"] == sheet for r in s["rows"] if r["row"] == row)


@pytest.mark.parametrize("name,title,expected", [
    ("PNL", None, "pnl"), ("P&L 2025", None, "pnl"), ("Profit and loss", None, "pnl"), ("Income Statement", None, "pnl"), ("Sheet1", "Group P&L", "pnl"),
    ("CASHFLOW", None, "cashflow"), ("Cash Flow", None, "cashflow"), ("Sheet2", "Cash flow statement", "cashflow"),
    ("BALANCE SHEET", None, "balance"), ("Balance", None, "balance"), ("Report", None, None), ("Data", "Monthly KPIs", None)])
def test_the_sheet_type_comes_from_the_name_then_the_title(name, title, expected):
    assert checks.sheet_type(name, title) == expected


def test_a_cash_flow_or_balance_sheet_row_with_a_p_and_l_role_is_relabelled_other_with_a_note():
    text, fmap = workbook()
    _, typed = register(text, fmap)
    for sheet, rows in (("CASHFLOW", (3, 4)), ("BALANCE SHEET", ())):
        for n in rows:
            r = role_of(typed, sheet, n)
            assert r["role"] == "other" and r["note"] == "cash movement, not a P&L line" and r["classified_by"] == "sheet_type", (sheet, n)
    assert role_of(typed, "CASHFLOW", 5)["role"] == "cash" and role_of(typed, "BALANCE SHEET", 3)["role"] == "cash", "cash is kept"
    assert role_of(typed, "PNL", 3)["role"] == "revenue" and role_of(typed, "PNL", 4)["role"] == "opex", "the P&L sheet is untouched"
    assert checks.retype_by_sheet(typed, checks.Cells(text)) == typed, "idempotent"
    assert role_of(fmap, "CASHFLOW", 3)["role"] == "revenue", "the input is not changed"


def test_an_untyped_sheet_keeps_its_roles():
    text, fmap = workbook(("Sheet1", "Sheet2", "Sheet3"))
    _, typed = register(text, fmap)
    assert role_of(typed, "Sheet2", 3)["role"] == "revenue" and role_of(typed, "Sheet2", 4)["role"] == "opex"


def test_a_title_row_types_a_sheet_whose_name_says_nothing():
    text, fmap = workbook(("Sheet1", "Sheet2", "Sheet3"), titles=("Group P&L", "Cash flow statement", "Balance sheet"))
    _, typed = register(text, fmap)
    assert role_of(typed, "Sheet2", 3)["role"] == "other" and role_of(typed, "Sheet1", 3)["role"] == "revenue"


def test_the_engine_reads_p_and_l_roles_from_the_pnl_and_cash_from_the_cash_flow():
    text, fmap = workbook()
    r = run(files_of(text, fmap), as_of="2025-12")
    rm = r["role_metrics"]
    opex = metric(r, "opex_share")
    assert opex["status"] != "needs_row" and "PNL" in str(opex["source"]) and "CASHFLOW" not in str(opex["source"]), opex
    assert "CASHFLOW" not in str(rm["metrics"][0]["source"] if rm["metrics"] else "")
    cash = metric(r, "cash")
    assert cash["value"] == 1100 and "CASHFLOW" in str(cash["source"]), "cash from the cash-flow sheet, before the P&L sheet's stray row"
    assert rm["reconciliation"] == [], "receipts on the cash flow are no second source for revenue"
    assert not any("CASHFLOW" in f["text"] for f in rm["mapping_flags"]), rm["mapping_flags"]


def test_no_total_vs_months_flag_comes_from_the_cash_flow():
    text, fmap = workbook()
    cf = next(s for s in fmap["sheets"] if s["sheet"] == "CASHFLOW")
    cf["granularity"] = "monthly"
    _, typed = register(text, fmap)
    table = role_engine.build_table([{"file": "w", "file_map": series.attach(typed, text), "rejected": [], "cannot": []}])
    assert not [r for r in table if r["sheet"] == "CASHFLOW" and r["role"] == "revenue"], "no revenue record from the cash flow, so no TOTAL-vs-months check"


def test_two_sheets_of_one_file_are_not_two_sources_for_the_reconciliation():
    text, fmap = workbook()
    for s in fmap["sheets"]:
        s["rows"][0]["role"] = "revenue"
    # both PNL and an untyped second sheet state revenue 2025 in the same file
    second = {"name": "Summary", "cells": grid({3: ("Revenue", [1000, 1500, 2300])})}
    more = redact.reading_text([{"name": "PNL", "cells": grid(PNL)}, second])
    both = {"map_version": 1, "kind": "sheet", "figures": [], "sheets": [smap("PNL", [entry(3, "revenue")]), smap("Summary", [entry(3, "revenue")])]}
    effective, _ = register(more, both)
    r = run([{"file": "w", "file_map": effective, "rejected": [], "cannot": []}], as_of="2025-12")
    assert r["role_metrics"]["reconciliation"] == []
    other = run([{"file": "w", "file_map": effective, "rejected": [], "cannot": []}, {"file": "x", "file_map": effective, "rejected": [], "cannot": []}],
                as_of="2025-12")
    assert other["role_metrics"]["reconciliation"], "two files are still two sources"


def test_parts_that_sum_to_double_the_total_read_counted_twice_and_stay_out_of_worth_flagging():
    text, fmap = workbook()
    r = run(files_of(text, fmap), as_of="2025-12")
    flags = [f for f in r["role_metrics"]["integrity_flags"] if f["kind"] == "totals_mismatch"]
    assert flags, "the OPEX total with two breakdowns is a finding"
    f = flags[0]
    assert f["sheet"] == "PNL" and f["row"] == 4 and f["double_counted"] is True
    assert f["text"] == "PNL row 4: parts counted twice — the sheet has two breakdowns of this total; the calculation uses the total"
    worth = ic_memo.role_flags({"role_metrics": r["role_metrics"]}, None, "EUR", ic_memo.Notes())
    assert not any("counted twice" in x for x in worth) and not any("PNL row 4" in x for x in worth)


def test_parts_that_miss_the_total_by_another_amount_keep_the_old_wording():
    t = {"sheet": "PNL", "cell": "D4", "row": 4, "total": 600.0, "parts_sum": 900.0, "difference": 300.0, "pct": 0.5}
    f = role_engine.totals_flags([{"file": "w", "totals": [t]}])[0]
    assert f["double_counted"] is False and "counted twice" not in f["text"] and "part row may be unmapped" in f["text"]
    near = role_engine.totals_flags([{"file": "w", "totals": [{**t, "parts_sum": 1260.0, "difference": 660.0, "pct": 1.1}]}])[0]
    assert near["double_counted"] is True, "within 5 % of the double"
    far = role_engine.totals_flags([{"file": "w", "totals": [{**t, "parts_sum": 1300.0, "difference": 700.0, "pct": 1.17}]}])[0]
    assert far["double_counted"] is False, "more than 5 % from the double"
