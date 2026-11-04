"""Reading consistency (the second read of the same input; docs/design/reading-consistency.md).

A spreadsheet is read twice, on the same input, with the same prompt and model (gateway.read_structure, `second_read`). The first read is the
stored reading; the second is stored beside it (readings.put_second). Here the two file maps are compared, in code:

    * a row both reads give with the same role, metric, series (actual and plan), segment flag and parent row is stored as it is;
    * a row that differs, or that only one read gives, stays stored with the first read's values and is marked "Reading uncertain – confirm" on
      the mapping page with both candidates; nothing is picked automatically;
    * a sheet-level field that differs (granularity, header row, last actual column) is marked the same way on the Detected layout block.

The analyst picks one candidate: a dated override record (`readings.add_override`, item `uncertain:...`), exactly like a Change. The reading is not
edited. An item is pending until an override of its key exists. No cell value of the file is read here beyond the series the readings already hold.
"""
from typing import Dict, List, Optional

from . import readings

UNCERTAIN = "Reading uncertain – confirm"
PICKS = ("first", "second")
WHY = "uncertain: kept the first reading"
WHY_SECOND = "uncertain: picked the second reading"
SHEET_FIELDS = ("granularity", "header_row", "last_actual")      # last_actual compares its column
ROW_FIELDS = ("role", "metric", "series", "plan_series", "segment", "parent_row")


def _segment_flag(row: Dict) -> bool:
    return bool((row.get("segment") or "").strip())


def _signature(row: Dict) -> Dict:
    return {"role": row.get("role"), "metric": row.get("metric"), "series": row.get("series"), "plan_series": row.get("plan_series"),
            "segment": _segment_flag(row), "parent_row": row.get("parent_row")}


def row_view(row: Optional[Dict]) -> Optional[Dict]:
    """The candidate as the screen shows it: the closed fields of the row and the range it covers (no label text, no value)."""
    if row is None:
        return None
    return {"role": row.get("role"), "metric": row.get("metric"), "basis": row.get("basis"), "cells": row.get("cells"),
            "segment": _segment_flag(row), "parent_row": row.get("parent_row"),
            "periods": len((row.get("series") or {}).get("periods") or []) + len((row.get("plan_series") or {}).get("periods") or [])}


def _last_actual(smap: Dict) -> Optional[str]:
    return (smap.get("last_actual") or {}).get("column")


def row_key(sheet: str, row: int) -> str:
    return f"uncertain:row:{sheet}:{row}"


def field_key(sheet: str, field: str) -> str:
    return f"uncertain:field:{sheet}:{field}"


def sheet_key(sheet: str) -> str:
    return f"uncertain:sheet:{sheet}"


def compare(first: Dict, second: Dict) -> List[Dict]:
    """The items on which two file maps (with their series) differ. [] when the reads agree on everything compared."""
    items: List[Dict] = []
    a = {s["sheet"]: s for s in first.get("sheets") or []}
    b = {s["sheet"]: s for s in second.get("sheets") or []}
    for name in dict.fromkeys([*a, *b]):
        if name not in a or name not in b:
            items.append({"key": sheet_key(name), "kind": "sheet", "sheet": name, "first": name if name in a else None,
                          "second": name if name in b else None})
            continue
        fa, fb = a[name], b[name]
        for field in SHEET_FIELDS:
            one, two = (_last_actual(fa), _last_actual(fb)) if field == "last_actual" else (fa.get(field), fb.get(field))
            if one != two:
                items.append({"key": field_key(name, field), "kind": "field", "sheet": name, "field": "last actual column" if field == "last_actual" else field.replace("_", " "),
                              "name": field, "first": one, "second": two})
        rows_a = {r["row"]: r for r in fa.get("rows") or []}
        rows_b = {r["row"]: r for r in fb.get("rows") or []}
        for number in sorted({*rows_a, *rows_b}):
            ra, rb = rows_a.get(number), rows_b.get(number)
            if ra is not None and rb is not None:
                sa, sb = _signature(ra), _signature(rb)
                if sa == sb:
                    continue
                differing = [f for f in ROW_FIELDS if sa[f] != sb[f]]
            else:
                differing = ["row"]
            items.append({"key": row_key(name, number), "kind": "row", "sheet": name, "row": number, "fields": differing,
                          "first": row_view(ra), "second": row_view(rb)})
    return items


def decided_keys(overrides: List[Dict]) -> set:
    return {o["item"] for o in overrides if str(o.get("item", "")).startswith("uncertain:") and str(o.get("why", "")).startswith("uncertain:")}


def pending(consistency: Optional[Dict], overrides: List[Dict]) -> List[Dict]:
    """The items of a file's consistency record that no override has settled yet."""
    done = decided_keys(overrides)
    return [i for i in (consistency or {}).get("items") or [] if i["key"] not in done]


def _sheet_index(file_map: Dict, name: str) -> Optional[int]:
    return next((i for i, s in enumerate(file_map.get("sheets") or []) if s["sheet"] == name), None)


class DecisionRefused(ValueError):
    pass


async def decide(db, audit_id: str, file_hash: str, key: str, pick: str, who: str = "analyst") -> Dict:
    """The analyst's pick of one candidate of an uncertain item: a dated override record. Picking the first reading records the decision and
    changes nothing in the effective map; picking the second applies its candidate. The stored reading is never edited."""
    if pick not in PICKS:
        raise DecisionRefused("Pick the first or the second reading.")
    check = next((c for c in await readings.checks_for(db, audit_id) if c.get("file_hash") == file_hash and c.get("status") == "read"), None)
    reading = await db[readings.READINGS].find_one({"key": (check or {}).get("reading_key")}, {"_id": 0})
    if not check or not reading:
        raise DecisionRefused("No reading of this file in this audit.")
    overrides = await readings.overrides_for(db, audit_id, reading["key"])
    item = next((i for i in pending(check.get("consistency"), overrides) if i["key"] == key), None)
    if item is None:
        raise DecisionRefused("That item is not waiting for confirmation.")
    second = await readings.get_second(db, reading["key"])
    if pick == "second" and not second:
        raise DecisionRefused("The second reading is not stored.")
    effective = readings.effective(reading["file_map"], overrides)
    si = _sheet_index(effective, item["sheet"])
    why = WHY_SECOND if pick == "second" else WHY
    if item["kind"] == "sheet":
        path, old = "sheets", [s["sheet"] for s in effective.get("sheets") or []]
        new = list(effective.get("sheets") or [])
        if pick == "second" and si is None:
            new.append(next(s for s in second["file_map"]["sheets"] if s["sheet"] == item["sheet"]))
    elif si is None:
        raise DecisionRefused("The sheet is not in the reading.")
    elif item["kind"] == "field":
        smap = effective["sheets"][si]
        theirs = next(s for s in second["file_map"]["sheets"] if s["sheet"] == item["sheet"]) if pick == "second" else smap
        field = item["name"]
        path, old = f"sheets.{si}.{field}", smap.get(field)
        new = theirs.get(field) if pick == "second" else old
    else:
        smap = effective["sheets"][si]
        rows = list(smap.get("rows") or [])
        path, old = f"sheets.{si}.rows", [r["row"] for r in rows]
        if pick == "second":
            theirs = next((s for s in second["file_map"]["sheets"] if s["sheet"] == item["sheet"]), {})
            candidate = next((r for r in theirs.get("rows") or [] if r["row"] == item["row"]), None)
            rows = [r for r in rows if r["row"] != item["row"]]
            if candidate is not None:
                rows = sorted([*rows, candidate], key=lambda r: r["row"])
        new = rows
    return await readings.add_override(db, reading=reading["key"], audit_id=audit_id, item=key, path=path, old=old, new=new, who=who, why=why)
