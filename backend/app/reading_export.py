"""Export of a stored reading (docs/design/read-check-review.md section 9; PR 3 step a): the full file map with its series, as JSON and as CSV.

The JSON is the reading as stored (names restored, series beside each row's map entry) with the overrides made on it, each as its own
record. The CSV has one line per row-period: the effective map's row fields (the reading with its overrides applied, `readings.effective`)
and one value of the row's series or plan series, at full precision. This is the stored data, so no value is rounded; the display rounding
of section 11.5 is for screens and the memo.
"""
import csv
import io
from typing import Dict, List, Optional

from . import cards, readings

COLUMNS = ["file", "sheet", "row", "label_cell", "role", "metric", "basis", "unit", "currency", "actual_plan", "period", "value", "cell", "note"]
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _safe(text) -> str:
    """A text cell that a spreadsheet would read as a formula is written with a leading apostrophe."""
    s = "" if text is None else str(text)
    return f"'{s}" if s.startswith(_FORMULA) else s


def decisions_of(decided: List[Dict]) -> List[Dict]:
    """The figures an analyst set on a card, each with the marker the screen shows (words, date, hover text): the check did not confirm them."""
    return [{"item": c["item"], "metric": (c.get("subject") or {}).get("metric"), "period": (c.get("subject") or {}).get("period"),
             "sheet": (c.get("source") or {}).get("sheet"), "cell": (c.get("source") or {}).get("cell"),
             "value": (c.get("decision") or {}).get("value"), **cards.set_by_analyst(c)} for c in decided]


def as_json(doc: Dict, overrides: List[Dict], decided: Optional[List[Dict]] = None) -> Dict:
    return {"file": doc.get("file"), "file_hash": doc.get("file_hash"), "reading": doc.get("key"), "prompt_version": doc.get("prompt_version"),
            "model": doc.get("model"), "file_map": doc["file_map"], "overrides": overrides, "set_by_analyst": decisions_of(decided or [])}


def as_csv(doc: Dict, overrides: List[Dict], file: str = "", decided: Optional[List[Dict]] = None) -> str:
    file_map = readings.effective(doc["file_map"], overrides)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for smap in file_map.get("sheets") or []:
        for row in smap.get("rows") or []:
            for kind, label in (("series", None), ("plan_series", "plan")):
                part = row.get(kind)
                if not part:
                    continue
                for period, value, ref in zip(part["periods"], part["values"], part["refs"]):
                    writer.writerow([_safe(file or doc.get("file")), _safe(smap["sheet"]), row["row"], row.get("label_cell") or "", row.get("role") or "",
                                     row.get("metric") or "", row.get("basis") or "", row.get("unit") or "", row.get("currency") or "",
                                     label or ("actual" if row.get("actual_plan") != "plan" else "plan"), period, repr(float(value)), ref, ""])
    for d in decisions_of(decided or []):        # a figure set on a card is a line of its own, carrying the screen's marker
        writer.writerow([_safe(file or doc.get("file")), _safe(d["sheet"]), "", "", "", _safe(d["metric"]), "", "", "", "", d["period"] or "",
                         "" if d["value"] is None else repr(float(d["value"])), d["cell"] or "", f"{d['note']}, {d['set_at']}: {d['hover']}"])
    return out.getvalue()
