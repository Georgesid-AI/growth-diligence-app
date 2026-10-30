"""The fixture set of the sheet reader (docs/design/read-check-review.md section 10): locating the files, their expected maps, and the comparison
the live job makes between a reading and its expected map. Shared by tests/test_reading_fixtures.py (offline) and
scripts/run_reading_fixtures.py (the job that reads each fixture once with the real model)."""
import json
import sys
from pathlib import Path
from typing import Dict, List

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

REPO = BACKEND.parent
FIXTURES = BACKEND / "tests" / "fixtures" / "reading"
COMPANY = "Fixture Co"
MONEY_TOLERANCE = 0.005


def manifest() -> List[Dict]:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def expected(name: str) -> Dict:
    return json.loads((FIXTURES / f"{name}.expected.json").read_text(encoding="utf-8"))


def path_of(entry: Dict) -> Path:
    """Where a fixture's file is: beside its expected map, or (the test company's files) under sample_data/ at the repository root."""
    file = entry["file"]
    return REPO / file if "/" in file else FIXTURES / file


def sheet_fixtures() -> List[Dict]:
    """The fixtures the sheet reader reads: the workbooks and the test company's P&L. Not the deck (read by the page reader) and not the
    records file, which is not a recognised sheet."""
    out = []
    for entry in manifest():
        exp = expected(entry["name"])
        if exp.get("kind") != "deck" and exp.get("read", True) is not False:
            out.append({**entry, "expected_map": exp, "path": path_of(entry)})
    return out


def deck_fixtures() -> List[Dict]:
    """The fixtures the page reader reads: the decks of the manifest, each with its expected figures (PR 3, item 4 of the build plan)."""
    return [{**entry, "expected_map": expected(entry["name"]), "path": path_of(entry)} for entry in manifest()
            if expected(entry["name"]).get("kind") == "deck"]


def compare_deck(exp: Dict, figures: List[Dict]) -> List[str]:
    """The differences between the figures the page reader read and checked (deck_figures.checked) and the expected deck; [] when they agree.
    Each expected figure (metric, value, page) must be among them, within the money tolerance and confirmed by the page text; the parts of
    the expected sum must add up to the headline in what was read. Figures read beyond the expected ones are no difference."""
    out: List[str] = []
    for want in exp.get("figures") or []:
        found = [f for f in figures if f.get("source", {}).get("page") == want["page"] and f.get("value") is not None
                 and _close(float(f["value"]), want["value"])]
        if not found:
            out.append(f"page {want['page']}: no figure {want['value']:g} read")
        elif not any(f.get("outcome") == "confirmed" for f in found):
            out.append(f"page {want['page']}: figure {want['value']:g} not confirmed by the page text ({found[0].get('outcome')})")
    sums = exp.get("parts_sum")
    if sums:
        parts = [want for want in sums["parts"]]
        read = sorted(float(f["value"]) for f in figures if f.get("source", {}).get("page") == sums["page"] and f.get("value") is not None
                      and any(_close(float(f["value"]), p) for p in parts))
        if not _close(sum(read), sums["headline"]):
            out.append(f"page {sums['page']}: the parts read add up to {sum(read):g}, not {sums['headline']:g}")
    return out


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= MONEY_TOLERANCE * abs(b) + 1e-9


def compare(exp: Dict, month, file_map: Dict) -> List[str]:
    """The differences between a reading (its confirmed as-of month and its file map) and the expected map; [] when they agree. The free
    text of the reading is not compared. Rows are found by their sheet row number, the revenue row by its role."""
    out: List[str] = []
    want = exp.get("as_of_month")
    if exp.get("as_of_source") == "rules":
        if month not in (None, want):
            out.append(f"as-of month {month}, expected {want} or none")
    elif month != want:
        out.append(f"as-of month {month}, expected {want}")
    sheets = {s["sheet"]: s for s in file_map.get("sheets") or []}
    for want_sheet in exp.get("sheets") or []:
        got = sheets.get(want_sheet["sheet"])
        if got is None:
            out.append(f"sheet {want_sheet['sheet']!r} missing")
            continue
        last = (got.get("last_actual") or {}).get("column")
        if last != want_sheet["last_actual_column"]:
            out.append(f"{want_sheet['sheet']}: last actual column {last}, expected {want_sheet['last_actual_column']}")
        if got.get("granularity") != want_sheet["granularity"]:
            out.append(f"{want_sheet['sheet']}: granularity {got.get('granularity')}, expected {want_sheet['granularity']}")
        if want_sheet.get("revenue_row"):
            revenue = [r["row"] for r in got.get("rows") or [] if r.get("role") == "revenue"]
            if want_sheet["revenue_row"] not in revenue:
                out.append(f"{want_sheet['sheet']}: revenue row {revenue}, expected {want_sheet['revenue_row']}")
    for want_role in exp.get("roles") or []:
        got = sheets.get(want_role["sheet"])
        role = next((r.get("role") for r in (got or {}).get("rows") or [] if r["row"] == want_role["row"]), None)
        if role != want_role["role"]:
            out.append(f"{want_role['sheet']} row {want_role['row']}: role {role}, expected {want_role['role']}")
    for want_fig in exp.get("figures") or []:        # a required subset: figures returned beyond these are no difference
        found = [f for f in file_map.get("figures") or []
                 if (f.get("source") or {}).get("cell") == want_fig["cell"] and (f.get("source") or {}).get("sheet") == want_fig["sheet"]
                 and f.get("metric") == want_fig["metric"]]
        if not found:
            out.append(f"figure {want_fig['metric']} at {want_fig['sheet']}!{want_fig['cell']} missing")
        elif not any(f.get("value") is not None and _close(f["value"], want_fig["value"]) and f.get("period") == want_fig["period"] for f in found):
            out.append(f"figure {want_fig['metric']} at {want_fig['cell']}: {found[0].get('value')} / {found[0].get('period')}, "
                       f"expected {want_fig['value']} / {want_fig['period']}")
    return out
