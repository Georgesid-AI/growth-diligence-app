"""The series of a mapped row (docs/design/read-check-review.md sections 4, 9; PR 3 step a).

When a reading is written, each row of its file map gets the series the cells hold: period → value, as read from the cells, at full
precision, with the cell each value came from. Cells after the row's actual/plan boundary go in a separate plan series on the same row:

    row["series"]       {"periods": ["2024-01", ...], "values": [100.0, ...], "refs": ["B4", ...]}      actual
    row["plan_series"]  the same three lists for the cells after the boundary                           plan

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
SERIES_KEYS = ("series", "plan_series")


def _form(smap: Dict) -> str:
    return FORMS.get(smap.get("granularity"), FORMS["monthly"])


def _boundary(smap: Dict, row: Dict) -> Optional[int]:
    """The column number after which the row's cells are plan: its own boundary, else the sheet's last actual column."""
    col = row.get("boundary_col") or (smap.get("last_actual") or {}).get("column")
    return redact.col_number(col) if col else None


def row_series(smap: Dict, row: Dict, sheet: "checks.SheetCells", fye: int = 12) -> Dict[str, Dict[str, List]]:
    """{"series": {...}, "plan_series": {...}} for one row, or {} when the row has no range or is a variance-columns row."""
    rng = checks.parse_range(row.get("cells"))
    if rng is None or row.get("variance_columns"):
        return {}
    form = _form(smap)
    down = row.get("by_column", False)
    label_col = redact.col_number(smap["label_col"])
    mark, boundary = row.get("actual_plan"), _boundary(smap, row)
    out: Dict[str, Dict[str, List]] = {"series": {"periods": [], "values": [], "refs": []}, "plan_series": {"periods": [], "values": [], "refs": []}}
    for r, c in checks.range_cells(rng):
        value = checks.to_number(sheet.get(r, c))
        if value is None:
            continue
        head = sheet.get(r, label_col) if down else sheet.header(smap["header_row"], c)
        period = checks.period_in_form(checks.header_period(head, fye), form)
        if period is None:
            continue
        if mark == "plan":
            after = True
        elif mark == "mixed" and boundary is not None:
            after = (r if down else c) > boundary
        else:
            after = False
        target = out["plan_series" if after else "series"]
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
