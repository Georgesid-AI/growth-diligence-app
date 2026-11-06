"""The series of a mapped row (docs/design/read-check-review.md sections 4, 9; PR 3 step a).

When a reading is written, each row of its file map gets the series the cells hold: period → value, as read from the cells, at full
precision, with the cell each value came from. Cells after the row's actual/plan boundary go in a separate plan series on the same row:

    row["series"]       {"periods": ["2024-01", ...], "values": [100.0, ...], "refs": ["B4", ...]}      actual
    row["plan_series"]  the same three lists for the cells after the boundary                           plan
    row["subtotal_series"], row["plan_subtotal_series"]    the same for the quarter and year columns of a monthly sheet (or the year columns
                        of a quarterly one): periods "2024-Q1", "2021"; they feed the quarterly and yearly metrics (role_engine.build_table)

The series are written once, with the reading (readings.put), and never edited: the reading is immutable, and a reviewer's correction or an
analyst's Change is an override record of its own. The checks keep opening the file (app/checks.py); they never read these series.

A cell that holds no number, or whose column header names no period, is not in the series (the checks reject a row whose range holds text,
and a header that names no period). A row that holds actual, budget and variance side by side per period (`variance_columns`) has no one
series per period and gets none.
"""
import copy
from typing import Dict, List, Optional

from . import checks
from .structures import redact

FORMS = {"monthly": "2000-01", "quarterly": "2000-Q1", "yearly": "2000"}      # the form a granularity writes its periods in
GRAINS = {"monthly": "month", "quarterly": "quarter", "yearly": "year"}
ORDER = {"month": 0, "quarter": 1, "year": 2}              # a column coarser than the sheet's grain is a subtotal; a finer one is detail
FORM_OF_GRAIN = {"month": FORMS["monthly"], "quarter": FORMS["quarterly"], "year": FORMS["yearly"]}
SERIES_KEYS = ("series", "plan_series", "subtotal_series", "plan_subtotal_series")


def _form(smap: Dict) -> str:
    return FORMS.get(smap.get("granularity"), FORMS["monthly"])


def _boundary(smap: Dict, row: Dict) -> Optional[int]:
    """The column number after which the row's cells are plan: its own boundary, else the sheet's last actual column."""
    col = row.get("boundary_col") or (smap.get("last_actual") or {}).get("column")
    return redact.col_number(col) if col else None


def row_series(smap: Dict, row: Dict, sheet: "checks.SheetCells", fye: int = 12) -> Dict[str, Dict[str, List]]:
    """{"series": {...}, "plan_series": {...}, "subtotal_series": {...}, "plan_subtotal_series": {...}} for one row (a key with no cell is left out),
    or {} when the row has no range or is a variance-columns row.

    Every period column is classified from its header as a month, a quarter ("Q1 2024") or a year ("TOTAL 2021", "FY 2021", "2021"; a datetime
    header is a month). The series holds the columns of the sheet's own grain only; the columns of a coarser grain are subtotals and go to the
    subtotal series, each period in its own form ("2024-Q1", "2021"), so that a quarter or a year never lands on a month's key."""
    rng = checks.parse_range(row.get("cells"))
    if rng is None or row.get("variance_columns"):
        return {}
    form = _form(smap)
    down = row.get("by_column", False)
    label_col = redact.col_number(smap["label_col"])
    mark, boundary = row.get("actual_plan"), _boundary(smap, row)
    own = ORDER[GRAINS.get(smap.get("granularity"), "month")]
    out: Dict[str, Dict[str, List]] = {k: {"periods": [], "values": [], "refs": []} for k in SERIES_KEYS}
    for r, c in checks.range_cells(rng):
        value = checks.to_number(sheet.get(r, c))
        if value is None:
            continue
        head = sheet.get(r, label_col) if down else sheet.header(smap["header_row"], c)
        found = checks.header_period(head, fye)
        grain = (found or {}).get("grain")
        if grain not in ORDER or ORDER[grain] < own:
            continue                # no period, a half or year to date, or a column finer than the sheet's grain: no part of the series
        subtotal = ORDER[grain] > own
        period = checks.period_in_form(found, FORM_OF_GRAIN[grain] if subtotal else form)
        if period is None:
            continue
        if mark == "plan":
            after = True
        elif mark == "mixed" and boundary is not None:
            after = (r if down else c) > boundary
        else:
            after = False
        target = out[("plan_" if after else "") + ("subtotal_series" if subtotal else "series")]
        target["periods"].append(period)
        target["values"].append(value)
        target["refs"].append(checks.ref_of(r, c))
    return {k: v for k, v in out.items() if v["periods"]}


def attach(file_map: Dict, payload_text: str, fye: int = 12) -> Dict:
    """A copy of the file map with the series of every row written beside its map entry. `payload_text` is the masked text the reader was
    sent, which holds exactly the cells the reader read."""
    out = copy.deepcopy(file_map)
    cells = checks.Cells(payload_text)
    for smap in out.get("sheets") or []:
        sheet = cells.sheet(smap["sheet"])
        if sheet is None:
            continue
        for row in smap.get("rows") or []:
            for key in SERIES_KEYS:
                row.pop(key, None)
            row.update(row_series(smap, row, sheet, fye))
    return out


def strip(file_map: Dict) -> Dict:
    """The map without its series (what the reader's schema describes)."""
    out = copy.deepcopy(file_map)
    for smap in out.get("sheets") or []:
        for row in smap.get("rows") or []:
            for key in SERIES_KEYS:
                row.pop(key, None)
    return out


def of_row(file_map: Dict, sheet: str, row: int) -> Dict[str, Dict]:
    """The stored series of one row of a stored map: {"series", "plan_series"} (either may be missing)."""
    for smap in file_map.get("sheets") or []:
        if smap["sheet"] == sheet:
            for r in smap.get("rows") or []:
                if r["row"] == row:
                    return {k: r[k] for k in SERIES_KEYS if k in r}
    return {}
