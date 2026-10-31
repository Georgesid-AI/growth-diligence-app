"""The reading register (docs/design/read-check-review.md sections 5, 7.4, 11; PR 3 step c): what the audit page shows.

Every figure with a check outcome lands here on its own, with no click: Confirmed, Rejected or Cannot check, across all files, spreadsheets
and decks. Cards exist only for the three cases of section 7.4 (app/cards.py). The register is the stored reading plus its overrides
(`readings.effective`): a reviewer's correction, an analyst's Change or a card's decision shows here, and the reading itself is never edited.

    {"files": [file blocks, in upload order: spreadsheets, then decks],
     "tables": {"confirmed": [...], "rejected": [...], "cannot_check": [...]},
     "cards": [...], "review": {...}}

Numbers are raw here, at full precision; the screen formats them (one formatter, section 11.5). Nothing in this module reads a file.
"""
import re
from typing import Dict, List, Optional

from . import cards, checks, deck_figures, lines as lines_mod, readings
from .structures import redact

USED_IN = {"revenue": "Revenue series", "arr": "ARR", "mrr": "MRR series", "new_arr": "New MRR by quarter", "churn_rate": "Churn by month",
           "churned_mrr": "Churn by month", "customers": "Customers series", "bookings": "Bookings", "acv": "ACV path"}
KIND_NAMES = {"periods": "Period columns", "currency": "Currency", "last_actual": "Last actual column", "evidence": "Evidence, as-of month",
              "variance": "Variance check", "parts": "Parts check"}
PERSONAL_KEYS = ("email", "phone", "iban", "id", "person")


def _figures(file_map: Dict) -> Dict[str, Dict]:
    return {checks._figure_key(i, f): f for i, f in enumerate(file_map.get("figures") or [])}


def _row_role(file_map: Dict, sheet: str, cell: Optional[str]) -> Optional[str]:
    pos = checks.parse_ref(cell)
    if not pos:
        return None
    for smap in file_map.get("sheets") or []:
        if smap["sheet"] == sheet:
            row = next((r for r in smap.get("rows") or [] if r["row"] == pos[0] and not r.get("by_column")), None)
            return lines_mod.role_name(row.get("role")) if row else None
    return None


def _label_of(doc: Dict, sheet: str, row: Optional[int]) -> Optional[str]:
    for entry in doc.get("lines") or []:
        if entry["sheet"] == sheet:
            return next((ln["label"] for ln in entry["lines"] if ln["row"] == row), None)
    return None


def _item_name(item: Dict, doc: Dict) -> str:
    if item["kind"] == "figure":
        return item.get("metric") or "Figure"
    if item["kind"] == "row":
        label = _label_of(doc, item.get("sheet"), item.get("row"))
        return label or f"Row {item.get('row')}"
    return KIND_NAMES.get(item["kind"], item["kind"])


def sheet_rows(doc: Dict, file_map: Dict, decided: Dict[str, Dict], card_ids: Dict[str, str]) -> Dict[str, List[Dict]]:
    """The three tables' rows for one spreadsheet's outcome. A figure the analyst decided on a card is Confirmed, marked as set by the analyst."""
    figures = _figures(file_map)
    rereads = {r["item"]: r for r in doc.get("rereads") or []}
    out: Dict[str, List[Dict]] = {"confirmed": [], "rejected": [], "cannot_check": []}
    seen = set()
    for item in doc.get("items") or []:
        if item["kind"] != "figure":
            continue                                  # the three tables and the file's counts hold figures only; other outcomes are notes (item_notes)
        key = f"last_actual:{item['sheet']}" if item["kind"] == "evidence" else item["key"]
        figure = figures.get(item["key"]) or {}
        row = {"key": item["key"], "kind": item["kind"], "metric": _item_name(item, doc), "value": item.get("value", figure.get("value")),
               "unit": figure.get("unit"), "currency": figure.get("currency"), "period": figure.get("period"), "label": figure.get("label_text"),
               "basis": figure.get("basis"),
               "actual_plan": figure.get("actual_plan"), "row_role": _row_role(file_map, item.get("sheet"), item.get("cell")),
               "source": {"file": doc.get("file"), "file_hash": doc.get("file_hash"), "sheet": item.get("sheet"), "cell": item.get("cell")},
               "reason": item.get("reason"), "note": None}
        if (item["key"], item["kind"]) in seen:
            continue
        seen.add((item["key"], item["kind"]))
        if item["outcome"] == checks.CONFIRMED:
            again = rereads.get(item["key"])
            row["note"] = "corrected automatically" if again and again.get("action") == "corrected automatically" else None
            if any(c["item"] == item["key"] for c in doc.get("corrections") or []):
                row["note"] = "corrected on review"
            out["confirmed"].append(row)
        elif item["outcome"] == checks.REJECTED:
            card = decided.get(key)
            if card:
                d = card["decision"]
                out["confirmed"].append({**row, "value": d["value"], **cards.set_by_analyst(card), "reason": None})
                continue
            again = rereads.get(key, {})
            out["rejected"].append({**row, "cell_value": item.get("found_value"), "cell_period": item.get("found_period"),
                                    "reread": again.get("reread") or "not read again", "action": again.get("action") or "card",
                                    "card_id": card_ids.get(key)})
        else:
            card = decided.get(key)
            if card:
                d = card["decision"]
                out["confirmed"].append({**row, "value": d["value"], **cards.set_by_analyst(card), "reason": None})
                continue
            out["cannot_check"].append({**row, "used_in": USED_IN.get(figure.get("metric") or item.get("metric")) or "—", "card_id": card_ids.get(item["key"])})
    return out


ROW_KINDS = ("row", "variance", "parts")


def item_notes(doc: Dict) -> Dict:
    """The check outcomes that are not figures: {"rows": {(sheet, row): reason}, "file": [{"name", "outcome", "reason"}]}. A row-level outcome
    (a row, its variance or its parts) is a note on that row of the lines table; the rest (periods, currency, last actual, evidence) are notes of the file.
    Neither is counted: the summary line and the three tables count figures only."""
    rows: Dict = {}
    file_notes: List[Dict] = []
    for item in doc.get("items") or []:
        if item["kind"] == "figure" or item["outcome"] == checks.CONFIRMED:
            continue
        reason = item.get("reason") or item["outcome"].replace("_", " ")
        if item["kind"] in ROW_KINDS and item.get("row") is not None:
            rows.setdefault((item["sheet"], item["row"]), []).append(reason)
        else:
            file_notes.append({"name": _item_name(item, doc), "outcome": item["outcome"], "reason": reason})
    return {"rows": rows, "file": file_notes}


_MONTH = re.compile(r"^\d{4}-\d{2}$")


def first_actual(file_map: Dict) -> Optional[str]:
    """The earliest month (YYYY-MM) of any actual series in the file's map, or None (a quarterly or yearly file has no month to give)."""
    found = [p for smap in file_map.get("sheets") or [] for row in smap.get("rows") or [] for p in (row.get("series") or {}).get("periods") or []
             if _MONTH.match(str(p))]
    return min(found) if found else None


def reporting_period(files: List[Dict]) -> Optional[Dict]:
    """{"first", "last"}: the first and the last actual month across the spreadsheets, or None when no file gives a last actual month.
    A file with a last actual month and no series gives that month for both ends."""
    firsts, lasts = [], []
    for f in files:
        last = f["kind"] == "sheet" and f["summary"].get("last_actual")
        if last and _MONTH.match(str(last)):
            lasts.append(last)
            firsts.append(f["summary"].get("first_actual") or last)
    return {"first": min(firsts), "last": max(lasts)} if lasts else None


def deck_rows(deck: Dict) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {"confirmed": [], "rejected": [], "cannot_check": []}
    for f in deck["figures"]:
        row = {"key": f["key"], "kind": "deck_figure", "metric": f.get("metric"), "value": f.get("value"), "unit": f.get("unit"),
               "currency": f.get("currency"), "period": f.get("period"), "label": f.get("label"), "basis": None, "actual_plan": f.get("actual_plan"), "row_role": None,
               "source": {"file": deck.get("file"), "deck_id": deck["deck_id"], "page": f["source"]["page"]}, "reason": f.get("reason"), "note": None}
        if f["outcome"] == checks.CONFIRMED:
            out["confirmed"].append(row)
        elif f["outcome"] == checks.REJECTED:
            out["rejected"].append({**row, "cell_value": None, "cell_period": None, "reread": "no re-read for a page", "action": "card", "card_id": None})
        else:
            out["cannot_check"].append({**row, "used_in": "—", "card_id": None})
    return out


def privacy_counts(masked: Dict) -> Dict[str, int]:
    return {"personal_removed": sum(int((masked or {}).get(k) or 0) for k in PERSONAL_KEYS),
            "company_coded": int((masked or {}).get("company") or 0)}


CHANGE_REVENUE = "Change: revenue row"


def named_revenue_row(overrides: List[Dict]) -> Optional[tuple]:
    """(sheet, row) of the revenue row the analyst last named with Change, or None. Only the row they named is touched by a Change; this is how the
    anchor line follows it while the row that was the revenue row keeps the role the reader gave it."""
    named = [o for o in overrides if o.get("why") == CHANGE_REVENUE and str(o.get("path", "")).endswith(".role") and o.get("new") == "revenue"]
    if not named:
        return None
    _, sheet, row = str(max(named, key=lambda o: o.get("at") or "")["item"]).split(":", 2)
    return sheet, int(row)


def anchors(doc: Dict, effective_map: Dict, lines: List[Dict], overrides: Optional[List[Dict]] = None) -> Dict:
    """The three anchor lines of a spreadsheet (section 11.2): the as-of month with its evidence, the revenue row, the actual / plan boundary."""
    best = max(doc.get("months") or [], key=lambda m: m["month"], default=None)
    revenue = None
    named = named_revenue_row(overrides or [])
    for entry in lines:
        found = next((ln for ln in entry["lines"] if named and (entry["sheet"], ln["row"]) == named), None) or \
            next((ln for ln in entry["lines"] if ln.get("role") == "revenue" and not ln.get("parent_row")), None)
        if found:
            revenue = {"sheet": entry["sheet"], "row": found["row"], "label": found["label"], "basis": found["basis"]}
            break
    boundary = None
    if best:
        smap = next((s for s in effective_map.get("sheets") or [] if s["sheet"] == best["sheet"]), {})
        column = (smap.get("last_actual") or {}).get("column") or best["column"]          # an analyst's Change shows here
        boundary = {"sheet": best["sheet"], "last_actual": column, "plan_from": redact.col_letters(redact.col_number(column) + 1)}
    return {"as_of": {"month": doc.get("month"), "evidence": doc.get("evidence")} if best else None, "revenue_row": revenue, "actual_plan": boundary}


async def build(db, audit_id: str) -> Dict:
    all_cards = await cards.for_audit(db, audit_id)
    decided = {c["item"]: c for c in all_cards if c["status"] == cards.DECIDED}
    card_ids = {c["item"]: c["id"] for c in all_cards if c["status"] == cards.OPEN}
    files: List[Dict] = []
    tables: Dict[str, List[Dict]] = {"confirmed": [], "rejected": [], "cannot_check": []}
    datasets = {d.get("file_hash"): d for d in await db.datasets.find({"audit_id": audit_id}, {"_id": 0, "file_hash": 1, "size": 1}).to_list(20)}
    for doc in sorted([c for c in await readings.checks_for(db, audit_id) if c.get("status") == "read"], key=lambda c: c.get("file") or ""):
        reading = await db[readings.READINGS].find_one({"key": doc.get("reading_key")}, {"_id": 0})
        if not reading:
            continue
        overrides = await readings.overrides_for(db, audit_id, reading["key"])
        effective = readings.effective(reading["file_map"], overrides)
        rows = sheet_rows(doc, effective, decided, card_ids)
        for name in tables:
            tables[name] += rows[name]
        notes = item_notes(doc)
        shown = _effective_lines(doc, effective)
        for entry in shown:
            for ln in entry["lines"]:
                ln["note"] = "; ".join(notes["rows"].get((entry["sheet"], ln["row"]), [])) or None
        files.append({"kind": "sheet", "file": doc.get("file"), "file_hash": doc["file_hash"], "size": (datasets.get(doc["file_hash"]) or {}).get("size"),
                      "summary": {"period_columns": doc.get("period_columns"), "rows_mapped": doc.get("rows_mapped"), "last_actual": doc.get("month"), "first_actual": first_actual(effective),
                                  "granularity": next((x.get("granularity") for x in effective.get("sheets") or []), None),
                                  "confirmed": len(rows["confirmed"]), "rejected": len(rows["rejected"]),
                                  "cannot_check": len(rows["cannot_check"]), **privacy_counts(doc.get("masked"))},
                      "notes": notes["file"],
                      "anchors": anchors(doc, effective, shown, overrides), "lines": shown, "overrides": len(overrides)})
    deck_docs = {d["deck_id"]: d for d in await db["deck_text"].find({"audit_id": audit_id}, {"_id": 0, "blocks": 0, "structures": 0, "layout": 0}).to_list(100)}
    for deck in await deck_figures.checked(db, audit_id):
        rows = deck_rows(deck)
        for name in tables:
            tables[name] += rows[name]
        meta = deck_docs.get(deck["deck_id"], {})
        reads = meta.get("page_reads") or []
        masked = {k: sum((r.get("masked") or {}).get(k, 0) for r in reads) for k in ("personal", "names")}
        n = {o: len(rows[o if o != "cannot_check" else "cannot_check"]) for o in rows}
        files.append({"kind": "deck", "file": deck["file"], "deck_id": deck["deck_id"], "pages": deck.get("pages"),
                      "summary": {"pages": deck.get("pages"), "pages_with_figures": meta.get("figure_pages"),
                                  "confirmed": n["confirmed"], "rejected": n["rejected"], "cannot_check": n["cannot_check"],
                                  "personal_removed": masked["personal"], "company_coded": masked["names"],
                                  "skipped_pages": meta.get("skipped_pages") or []},
                      "anchors": {"figures": {"read": len(deck["figures"]), "found_on_page": n["confirmed"], "from_image": n["cannot_check"]}}})
    review = await db[readings.REVIEWS].find_one({"audit_id": audit_id}, {"_id": 0})
    status = (review or {}).get("status")
    summary = {"status": status, "reason": (review or {}).get("reason"),
               "not_completed": f"review not completed: {review.get('reason') or 'not read'}" if review and status not in ("read", "none") else None,
               "findings": sum(1 for f in (review or {}).get("findings") or [] if f.get("state") == "valid"), "dropped": (review or {}).get("dropped", 0)}
    return {"files": files, "period": reporting_period(files), "tables": tables, "counts": {k: len(v) for k, v in tables.items()}, "cards": all_cards, "review": summary}


def _effective_lines(doc: Dict, effective: Dict) -> List[Dict]:
    """The stored lines rebuilt from the effective map (overrides applied), with the labels the reader was sent."""
    out = []
    smaps = {s["sheet"]: s for s in effective.get("sheets") or []}
    for entry in doc.get("lines") or []:
        smap = smaps.get(entry["sheet"])
        if smap is None:
            out.append(entry)
            continue
        labels = {ln["row"]: ln["label"] for ln in entry["lines"]}
        outcomes = {ln["row"]: ln.get("outcome") for ln in entry["lines"]}
        built = lines_mod.build(smap, labels)
        for ln in built:
            ln["outcome"] = outcomes.get(ln["row"])
        out.append({"sheet": entry["sheet"], "lines": built})
    return out


# ---------------------------------------------------------------------------
# The analyst's Change on a spreadsheet's anchors (section 11.2): a dated override record of its own; the reading is never edited
# ---------------------------------------------------------------------------
class ChangeRefused(ValueError):
    pass


async def _stored(db, audit_id: str, file_hash: str):
    doc = next((c for c in await readings.checks_for(db, audit_id) if c.get("file_hash") == file_hash and c.get("status") == "read"), None)
    reading = await db[readings.READINGS].find_one({"key": doc.get("reading_key")}, {"_id": 0}) if doc else None
    if not reading:
        raise ChangeRefused("No reading of this file in this audit.")
    return doc, reading


async def change_revenue_row(db, audit_id: str, file_hash: str, sheet: str, row: int, who: str = "analyst") -> List[Dict]:
    """Make a mapped row the sheet's revenue row: it is read as revenue. The row that was the revenue row keeps the role the reader gave it: the
    analyst named one row, and no other row is retyped."""
    _, reading = await _stored(db, audit_id, file_hash)
    effective = readings.effective(reading["file_map"], await readings.overrides_for(db, audit_id, reading["key"]))
    si = next((i for i, s in enumerate(effective.get("sheets") or []) if s["sheet"] == sheet), None)
    if si is None or not any(r["row"] == row for r in effective["sheets"][si].get("rows") or []):
        raise ChangeRefused("That row is not one of the mapped rows.")
    out = []
    for ri, r in enumerate(effective["sheets"][si]["rows"]):
        if r["row"] != row or r.get("role") == "revenue":
            continue
        changes = {"role": "revenue", "metric": "revenue"}
        for field, new in changes.items():
            out.append(await readings.add_override(db, reading=reading["key"], audit_id=audit_id, item=f"row:{sheet}:{r['row']}",
                                                   path=f"sheets.{si}.rows.{ri}.{field}", old=r.get(field), new=new, who=who, why=CHANGE_REVENUE))
    return out


async def change_boundary(db, audit_id: str, file_hash: str, sheet: str, column: str, who: str = "analyst") -> List[Dict]:
    """Move a sheet's last actual column: the sheet's `last_actual.column` and the boundary of each row that names one."""
    _, reading = await _stored(db, audit_id, file_hash)
    effective = readings.effective(reading["file_map"], await readings.overrides_for(db, audit_id, reading["key"]))
    si = next((i for i, s in enumerate(effective.get("sheets") or []) if s["sheet"] == sheet), None)
    column = (column or "").strip().upper()
    if si is None or not column.isalpha():
        raise ChangeRefused("Name a column of the sheet, such as AP.")
    smap = effective["sheets"][si]
    if not redact.col_number(smap["first_period_col"]) <= redact.col_number(column) <= redact.col_number(smap["last_period_col"]):
        raise ChangeRefused("That column is not one of the period columns.")
    out = []
    if smap.get("last_actual"):
        out.append(await readings.add_override(db, reading=reading["key"], audit_id=audit_id, item=f"last_actual:{sheet}",
                                               path=f"sheets.{si}.last_actual.column", old=smap["last_actual"]["column"], new=column, who=who,
                                               why="Change: actual / plan boundary"))
    for ri, r in enumerate(smap.get("rows") or []):
        if r.get("boundary_col") and r["boundary_col"] != column:
            out.append(await readings.add_override(db, reading=reading["key"], audit_id=audit_id, item=f"row:{sheet}:{r['row']}",
                                                   path=f"sheets.{si}.rows.{ri}.boundary_col", old=r["boundary_col"], new=column, who=who,
                                                   why="Change: actual / plan boundary"))
    return out


# ---------------------------------------------------------------------------
# The link of a Source (section 11.3): the cell, in its neighbourhood, as the file holds it
# ---------------------------------------------------------------------------
WINDOW_ROWS, WINDOW_COLS = 3, 4


async def cell_window(db, audit_id: str, file_hash: str, sheet: str, cell: str) -> Optional[Dict]:
    """The cited cell and the cells around it (three rows each way, four columns each way) from the stored sheets of the audit's file, for the
    screen's "Click to see the cell". Names are the file's own: this goes to the analyst's browser only, as the dataset does. None when the file
    or the cell is not there."""
    from . import recognition as rec
    from .structures import reading_input
    pos = checks.parse_ref(cell)
    ds = await db.datasets.find_one({"audit_id": audit_id, "file_hash": file_hash}, {"_id": 0, "recognition_sheets": 1})
    if not ds or not pos:
        return None
    found = next((s for s in rec.unpack_sheets(ds.get("recognition_sheets") or []) if s.sheet == sheet), None)
    if found is None:
        return None
    grid = {(c["row"], c["col"]): c["text"] for c in reading_input.sheet_cells(found)}
    rows = []
    for r in range(max(1, pos[0] - WINDOW_ROWS), pos[0] + WINDOW_ROWS + 1):
        rows.append({"row": r, "cells": [{"ref": checks.ref_of(r, c), "text": grid.get((r, c), ""), "cited": (r, c) == pos}
                                         for c in range(max(1, pos[1] - WINDOW_COLS), pos[1] + WINDOW_COLS + 1)]})
    return {"sheet": sheet, "cell": cell, "rows": rows}
