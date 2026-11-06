"""Reading consistency (the second read of the same input; docs/design/reading-consistency.md).

A spreadsheet is read twice, on the same input, with the same prompt and model (gateway.read_structure, `second_read`). The first read is the
stored reading; the second is stored beside it (readings.put_second). Here the two file maps are compared, in code:

    * a row both reads give with the same role, metric, series (actual and plan), segment flag, parent row, unit, currency and basis is stored as it is;
    * a row that differs, or that only one read gives, stays stored with the first read's values and is marked "Reading uncertain – confirm" on
      the mapping page with both candidates; nothing is picked automatically;
    * a sheet-level field that differs (granularity, header row, last actual column) is marked the same way on the Detected layout block.

The analyst picks one candidate: a dated override record (`readings.add_override`, item `uncertain:...`), exactly like a Change. The reading is not
edited. An item is pending until an override of its key exists. No cell value of the file is read here beyond the series the readings already hold.
"""
import json
import re
from typing import Dict, List, Optional

from . import lines as lines_mod, readings

UNCERTAIN = "Reading uncertain – confirm"
PICKS = ("first", "second")
WHY = "uncertain: kept the first reading"
WHY_SECOND = "uncertain: picked the second reading"
SHEET_FIELDS = ("granularity", "header_row", "last_actual")      # last_actual compares its column
# unit, currency and basis added 2026-11-05 (George): they are read into the figures (the fx, the form of the series), so a difference is one.
# The segment flag left out 2026-11-05 (second pass, A1): two reads that differ in it alone are not a disagreement.
ROW_FIELDS = ("role", "metric", "series", "plan_series", "parent_row", "unit", "currency", "basis")


def _scenario(row: Dict) -> Optional[str]:
    return lines_mod.scenario_of(row.get("segment"))


def _segment_flag(row: Dict) -> bool:
    """A product or region split; a scenario ("scenario: Best case") is not one."""
    return bool((row.get("segment") or "").strip()) and _scenario(row) is None


SERIES_FIELDS = ("series", "plan_series")
REL_TOLERANCE, ABS_TOLERANCE = 0.005, 1.0       # two values are equal within 0.5% or 1 unit (George, 2026-11-05)


def _period(p) -> str:
    """A period in one form: "2021-3" is "2021-03" (a formatting difference is none)."""
    text = str(p).strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", text)
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else text


def _same_value(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()
    gap = abs(x - y)
    return gap <= ABS_TOLERANCE or gap <= REL_TOLERANCE * max(abs(x), abs(y))


def series_diff(first: Optional[Dict], second: Optional[Dict]) -> Optional[Dict]:
    """None when two series are equal (every period matches, every value within the tolerance); else the first period (in time) where they
    differ with both values (None where a read lacks the period), the number of periods that differ and the number of periods in both."""
    def table(s):
        return {_period(p): v for p, v in zip((s or {}).get("periods") or [], (s or {}).get("values") or [])}
    a, b = table(first), table(second)
    periods = sorted({*a, *b})
    bad = [p for p in periods if p not in a or p not in b or not _same_value(a[p], b[p])]
    if not bad:
        return None
    return {"period": bad[0], "first": a.get(bad[0]), "second": b.get(bad[0]), "differing": len(bad), "total": len(periods)}


def with_series_diffs(items: List[Dict], first: Optional[Dict], second: Optional[Dict]) -> List[Dict]:
    """The items as served: a row item that differs in `series` or `plan_series` and was stored before the difference was kept (no `series_diff` for that
    field) gets it from the two stored reads, so the list never falls back to a bare period count (combined fixes, 2026-11-05). `first` and `second` are
    the stored file maps with their series; an item the maps do not settle is returned as it is. Stored items are never edited."""
    if not first or not second:
        return items
    a = {(s["sheet"], r["row"]): r for s in first.get("sheets") or [] for r in s.get("rows") or []}
    b = {(s["sheet"], r["row"]): r for s in second.get("sheets") or [] for r in s.get("rows") or []}
    out = []
    for item in items:
        wanted = [f for f in SERIES_FIELDS if item.get("kind") == "row" and f in (item.get("fields") or []) and f not in (item.get("series_diff") or {})]
        ra, rb = a.get((item.get("sheet"), item.get("row"))), b.get((item.get("sheet"), item.get("row")))
        if not wanted or ra is None or rb is None:
            out.append(item)
            continue
        found = {f: d for f in wanted if (d := series_diff(ra.get(f), rb.get(f)))}
        out.append({**item, "series_diff": {**(item.get("series_diff") or {}), **found}} if found else item)
    return out


def _signature(row: Dict) -> Dict:
    return {"role": row.get("role"), "metric": row.get("metric"), "series": row.get("series"), "plan_series": row.get("plan_series"),
            "parent_row": row.get("parent_row"), "unit": row.get("unit"), "currency": row.get("currency"), "basis": row.get("basis")}


def row_view(row: Optional[Dict]) -> Optional[Dict]:
    """The candidate as the screen shows it: the closed fields of the row and the range it covers (no label text, no value)."""
    if row is None:
        return None
    return {"role": row.get("role"), "metric": row.get("metric"), "basis": row.get("basis"), "cells": row.get("cells"),
            "unit": row.get("unit"), "currency": row.get("currency"),
            "segment": _segment_flag(row), "scenario": _scenario(row), "parent_row": row.get("parent_row"),
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
        groups: Dict[str, Dict] = {}
        for number in sorted({*rows_a, *rows_b}):
            ra, rb = rows_a.get(number), rows_b.get(number)
            if ra is not None and rb is not None:
                sa, sb = _signature(ra), _signature(rb)
                diffs = {f: d for f in SERIES_FIELDS if (d := series_diff(sa[f], sb[f]))}
                differing = [f for f in ROW_FIELDS if (f in diffs if f in SERIES_FIELDS else sa[f] != sb[f])]
                if not differing:
                    continue
            else:
                differing, diffs = ["row"], {}
            item = {"key": row_key(name, number), "kind": "row", "sheet": name, "row": number, "rows": [number], "fields": differing,
                    "first": row_view(ra), "second": row_view(rb)}
            if diffs:
                item["series_diff"] = diffs
            # Rows of one sheet with identical candidate pairs are one item with one pick (second pass, A5); the position of a row (its cells) is no part of the pair.
            same = json.dumps([differing, _pair(item["first"]), _pair(item["second"]), diffs], sort_keys=True, default=str)
            if same in groups:
                groups[same]["rows"].append(number)
            else:
                groups[same] = item
                items.append(item)
    return items


def _pair(view: Optional[Dict]) -> Optional[Dict]:
    return None if view is None else {k: v for k, v in view.items() if k != "cells"}


def decided_keys(overrides: List[Dict]) -> set:
    return {o["item"] for o in overrides if str(o.get("item", "")).startswith("uncertain:") and str(o.get("why", "")).startswith("uncertain:")}


def _set_by_analyst(overrides: List[Dict]) -> Dict[str, set]:
    """{"row:<sheet>:<row>": the row fields an override (an analyst's Change, a reviewer's correction) has set}: the last part of its path."""
    out: Dict[str, set] = {}
    for o in overrides:
        item = str(o.get("item", ""))
        if item.startswith("row:") and not str(o.get("why", "")).startswith("uncertain:"):
            out.setdefault(item, set()).add(str(o.get("path", "")).rsplit(".", 1)[-1])
    return out


def pending(consistency: Optional[Dict], overrides: List[Dict]) -> List[Dict]:
    """The items of a file's consistency record that no override has settled yet. An override already on a row (an analyst's Change) settles the
    fields it sets (second pass, A4): the item keeps the fields it left open, or goes when it left none."""
    done, set_by = decided_keys(overrides), _set_by_analyst(overrides)
    out = []
    for i in (consistency or {}).get("items") or []:
        if i["key"] in done:
            continue
        if i["kind"] == "row" and i.get("fields") != ["row"]:
            rows = i.get("rows") or [i["row"]]
            settled = set.intersection(*[set_by.get(f"row:{i['sheet']}:{n}", set()) for n in rows])
            left = [f for f in i.get("fields") or [] if f not in settled]
            if not left:
                continue
            i = {**i, "fields": left}
        out.append(i)
    return out


def held_rows(file_map: Dict, waiting: List[Dict]) -> List[str]:
    """The "sheet:row" keys of the rows the calculations hold out while an item waits (review of commit 2, 2026-11-05): the row of a row item,
    and every row of a sheet with a pending sheet-level item (the sheet only one read gives, or a layout field the reads disagree on: the
    rows' series and the as-of month are read under that layout, so they are in doubt with it)."""
    sheets = {i["sheet"] for i in waiting if i["kind"] in ("sheet", "field")}
    out = [f"{i['sheet']}:{n}" for i in waiting if i["kind"] == "row" for n in i.get("rows") or [i["row"]]]
    out += [f"{s['sheet']}:{r['row']}" for s in file_map.get("sheets") or [] if s["sheet"] in sheets for r in s.get("rows") or []]
    return list(dict.fromkeys(out))


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
        # Picking the second reading of a sheet only the first gave removes the sheet; of a sheet only the second gave adds it.
        path, old = "sheets", [s["sheet"] for s in effective.get("sheets") or []]
        new = list(effective.get("sheets") or [])
        if pick == "second" and si is None:
            new.append(next(s for s in second["file_map"]["sheets"] if s["sheet"] == item["sheet"]))
        elif pick == "second" and item["second"] is None:
            new = [s for s in new if s["sheet"] != item["sheet"]]
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
            for number in item.get("rows") or [item["row"]]:         # one pick applies to every row of a group
                candidate = next((r for r in theirs.get("rows") or [] if r["row"] == number), None)
                rows = [r for r in rows if r["row"] != number]
                if candidate is not None:
                    rows = sorted([*rows, candidate], key=lambda r: r["row"])
        new = rows
    return await readings.add_override(db, reading=reading["key"], audit_id=audit_id, item=key, path=path, old=old, new=new, who=who, why=why)
