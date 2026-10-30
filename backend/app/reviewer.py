"""Review, re-read, correct (docs/design/read-check-review.md sections 3, 7, 9; PR 3 step b).

One review per audit:

    1. the input: the stored file maps of every spreadsheet (with their series and overrides, without the readers' evidence lines), the deck
       figures, the computed results and the list of cannot-check items;
    2. one model call through the gateway (gateway.run_reviewer: masked there, the prompt `reviewer` of the store, the reader's model allow-list);
    3. the findings, each reference opened by code: a finding that cites a file, sheet, cell or page that does not exist is dropped and logged;
    4. a valid finding about a spreadsheet item is read again once, with the finding attached, through the gateway's recheck path. The reader
       agrees when its second reading differs from its first and passes the cell checks: the change is written as override records "corrected
       on review" (the reading itself is never edited). The reader disagrees when it repeats itself, or gives something the checks reject:
       a card with both readings. A finding on a deck figure has no re-read: it is a card.

Scope is reading errors only (section 7.3). The review is stored once per audit and input: the same input is not reviewed again unless the
analyst asks (`force`); a new input, a new prompt or a new model is a new review.
"""
import copy
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import cards, checks, deck_figures, readings, series
from .llm import cache, gateway, redaction
from .llm.schemas import SHEET_READING
from .structures import reading_input, redact

logger = logging.getLogger("growth.reviewer")

WHO = "reviewer"
CORRECTED = "corrected on review"
D_FILE, D_SHEET, D_CELL, D_PAGE, D_KIND = "no_such_file", "no_such_sheet", "cell_outside_sheet", "no_such_page", "wrong_kind"
AGREES, REPEATS, THIRD, UNREAD, NO_ITEM = "agrees", "repeats the first reading", "gives a third value", "not read", "no item"
ROW_FIELDS = ("role", "metric", "basis", "actual_plan", "boundary_col", "segment", "parent_row", "unit", "currency", "cells", "variance_of",
              "variance_columns", "label_cell", "by_column")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def strip_evidence(file_map: Dict) -> Dict:
    """The map as the reviewer sees it: the readers' evidence lines (the reason for a role, a basis or a boundary) left out. Series stay."""
    out = copy.deepcopy(file_map)
    for smap in out.get("sheets") or []:
        if smap.get("last_actual"):
            smap["last_actual"].pop("evidence", None)
        for row in smap.get("rows") or []:
            row.pop("evidence", None)
    for figure in out.get("figures") or []:
        figure.pop("evidence", None)
    return out


class Files:
    """The audit's files as the reviewer numbers them: spreadsheets first (by file name), then decks (in upload order). Holds what the
    references of a finding are opened against."""

    def __init__(self):
        self.items: List[Dict] = []

    def add(self, **fields) -> int:
        self.items.append({"n": len(self.items) + 1, **fields})
        return len(self.items)

    def get(self, n: int) -> Optional[Dict]:
        return self.items[n - 1] if 1 <= n <= len(self.items) else None


async def collect(db, audit: Dict) -> Tuple[Dict, Files]:
    """(the review input, the files). The input is unmasked here: the gateway masks every string of it as it goes out."""
    audit_id = audit["id"]
    files, payload, cannot = Files(), {"files": [], "cannot_check": []}, []
    for check in sorted([c for c in await readings.checks_for(db, audit_id) if c.get("status") == "read"], key=lambda c: c.get("file") or ""):
        reading = await db[readings.READINGS].find_one({"key": check.get("reading_key")}, {"_id": 0})
        if not reading:
            continue
        overrides = await readings.overrides_for(db, audit_id, reading["key"])
        file_map = readings.effective(reading["file_map"], overrides)
        n = files.add(kind="sheet", file=check.get("file"), file_hash=check["file_hash"], check=check, reading=reading,
                      sheets={s["sheet"]: s for s in file_map.get("sheets") or []}, dims=check.get("dims") or {})
        payload["files"].append({"file": n, "kind": "sheet", "map": strip_evidence(file_map)})
        for item in check.get("items") or []:
            if item["outcome"] == checks.CANNOT:
                cannot.append({"file": n, "sheet": item.get("sheet"), "cell": item.get("cell"), "reason": item.get("reason")})
    for deck in await deck_figures.checked(db, audit_id):
        n = files.add(kind="deck", file=deck["file"], deck_id=deck["deck_id"], pages=deck.get("pages"), figures=deck["figures"])
        shown = [{k: f.get(k) for k in ("metric", "value", "unit", "currency", "period", "actual_plan", "segment")} | {"page": f["source"]["page"]}
                 for f in deck["figures"]]
        payload["files"].append({"file": n, "kind": "deck", "pages": deck.get("pages"), "figures": shown})
        cannot += [{"file": n, "page": f["source"]["page"], "metric": f.get("metric"), "reason": f.get("reason")}
                   for f in deck["figures"] if f["outcome"] == checks.CANNOT]
    payload["cannot_check"] = cannot
    payload["computed"] = await _computed(db, audit_id)
    return payload, files


async def _computed(db, audit_id: str) -> Optional[Dict]:
    """The computed results as the narratives see them (display strings, allow-listed, pseudonymised), or None before the engine has run."""
    try:
        computed = await gateway.load_computed_results(db, audit_id, "growth_engine")
        return gateway.build_outbound(computed, await redaction.get_map(db, audit_id))
    except gateway.GatewayError:
        return None


def input_hash(payload: Dict) -> str:
    return hashlib.sha256(cache.canonical_json(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# References: every one is opened
# ---------------------------------------------------------------------------
def check_ref(ref: Dict, files: Files) -> Optional[str]:
    """None when the reference exists, else the closed word that names why not. A cell is inside its sheet's extent (the last row and column
    the reader was sent); a page is inside its deck."""
    f = files.get(ref["file"])
    if f is None:
        return D_FILE
    if ref.get("page") is not None:
        if f["kind"] != "deck":
            return D_KIND
        return None if 1 <= ref["page"] <= int(f.get("pages") or 0) else D_PAGE
    if f["kind"] != "sheet":
        return D_KIND
    if ref["sheet"] not in f["sheets"]:
        return D_SHEET
    dims = f["dims"].get(ref["sheet"])
    rng = checks.parse_range(ref["cell"])
    if rng is None:
        return D_CELL
    if dims and (max(rng[0], rng[2]) > dims[0] or max(rng[1], rng[3]) > dims[1]):
        return D_CELL
    return None


def validate(findings: List[Dict], files: Files) -> Tuple[List[Dict], List[Dict]]:
    """(valid, dropped): a finding with any reference that does not exist is dropped with the closed word of the first that fails."""
    valid, dropped = [], []
    for i, finding in enumerate(findings):
        why = next((w for w in (check_ref(r, files) for r in finding["refs"]) if w), None)
        (dropped if why else valid).append({**finding, "id": f"f{i + 1}", **({"drop_reason": why} if why else {})})
    return valid, dropped


def items_of(finding: Dict, files: Files) -> List[Tuple[int, str]]:
    """[(file number, item key)] a finding is about: the mapped rows whose range holds a cited cell, the figures cited, the sheet's last actual
    column when its header is cited. Keys are the checks' (app/checks.py)."""
    out: List[Tuple[int, str]] = []
    for ref in finding["refs"]:
        f = files.get(ref["file"])
        if f["kind"] != "sheet":
            continue
        smap = f["sheets"][ref["sheet"]]
        rng = checks.parse_range(ref["cell"])
        for row in smap.get("rows") or []:
            span = checks.parse_range(row.get("cells"))
            cited = checks.parse_ref(row.get("label_cell"))
            hit = (span and not (span[2] < rng[0] or span[0] > rng[2] or span[3] < rng[1] or span[1] > rng[3])) or \
                  (cited and rng[0] <= cited[0] <= rng[2] and rng[1] <= cited[1] <= rng[3]) or \
                  (span and rng[0] == rng[2] == row["row"] and rng[1] <= span[1] <= rng[3])
            if hit:
                out.append((ref["file"], f"row:{ref['sheet']}:{row['row']}"))
        for i, figure in enumerate(f["reading"]["file_map"].get("figures") or []):
            src = figure.get("source") or {}
            pos = checks.parse_ref(src.get("cell"))
            if src.get("sheet") == ref["sheet"] and pos and rng[0] <= pos[0] <= rng[2] and rng[1] <= pos[1] <= rng[3]:
                out.append((ref["file"], checks._figure_key(i, figure)))
        la = smap.get("last_actual")
        if la and rng[0] <= smap["header_row"] <= rng[2] and rng[1] <= redact.col_number(la["column"]) <= rng[3]:
            out.append((ref["file"], f"last_actual:{ref['sheet']}"))
    return list(dict.fromkeys(out))


def finding_reason(finding: Dict) -> str:
    """The text attached to a re-read: what the reviewer says is wrong and how it reads it. The reviewer's own words, masked by the caller."""
    return f"Reviewer: {finding['what']} Reviewer's reading: {finding['reading']}"


def _plain(reading: Optional[Dict]) -> Optional[Dict]:
    """A reading without its evidence line and its series: the part that says what a row or figure is."""
    if reading is None:
        return None
    out = {k: v for k, v in reading.items() if k not in ("evidence", *series.SERIES_KEYS)}
    if isinstance(out.get("evidence"), list):
        out.pop("evidence", None)
    if "last_actual" in out or "column" in out:
        out = {k: v for k, v in out.items() if k != "evidence"}
    return out


# ---------------------------------------------------------------------------
# The re-read of one file's flagged items
# ---------------------------------------------------------------------------
async def _dataset_sheets(db, audit_id: str, file_hash: str):
    from . import recognition as rec
    ds = await db.datasets.find_one({"audit_id": audit_id, "file_hash": file_hash}, {"_id": 0, "recognition_sheets": 1})
    return rec.unpack_sheets((ds or {}).get("recognition_sheets") or []) if ds else []


def _paths(reading: Dict, key: str) -> Optional[Tuple[str, Dict]]:
    """(the path of the item's entry in the stored reading, the entry) for an item key, or None."""
    fmap = reading["file_map"]
    if key.startswith("figure:"):
        for i, figure in enumerate(fmap.get("figures") or []):
            if checks._figure_key(i, figure) == key:
                return f"figures.{i}", figure
        return None
    kind, _, rest = key.partition(":")
    for si, smap in enumerate(fmap.get("sheets") or []):
        name = smap["sheet"]
        if not rest.startswith(name):
            continue
        tail = rest[len(name):]
        if kind == "row" and tail.startswith(":") and tail[1:].isdigit():
            for ri, row in enumerate(smap.get("rows") or []):
                if row["row"] == int(tail[1:]):
                    return f"sheets.{si}.rows.{ri}", row
        if kind == "last_actual" and not tail and smap.get("last_actual"):
            return f"sheets.{si}.last_actual", smap["last_actual"]
    return None


async def reread_file(db, audit: Dict, f: Dict, asks: List[Dict], adapter, company: Optional[str], mapping: Dict[str, str]) -> Dict[str, Dict]:
    """Read one file's flagged items again, once, with the findings attached. Returns {item key: {"result", ...}} where result is AGREES,
    REPEATS, THIRD or UNREAD; on AGREES the overrides are written and the audit's stored check outcome of the file is rewritten."""
    audit_id, file_hash, reading = audit["id"], f["file_hash"], f["reading"]
    fye = int(audit.get("fiscal_year_end") or 12)
    sheets = await _dataset_sheets(db, audit_id, file_hash)
    text = reading_input.reading_text(sheets)
    result: Dict[str, Dict] = {a["item"]: {"result": UNREAD} for a in asks}
    if text is None:
        return result
    masked = [{"item": a["item"], "reason": redact.mask_text(a["reason"], company, mapping)} for a in asks]
    first = await gateway.read_structure(db, audit_id, text, SHEET_READING, file_hash=file_hash, adapter=adapter, fiscal_year_end=fye)
    if first.status != "read" or not first.file_map:
        return result
    second = await gateway.read_structure(db, audit_id, text, SHEET_READING, file_hash=file_hash, adapter=adapter, recheck=masked,
                                          fiscal_year_end=fye)
    if second.status != "read" or second.file_map is None:
        return result
    cells = checks.Cells(first.payload)
    keys = [a["item"] for a in asks]
    changed = [k for k in keys if _plain(checks.reading_of(first.file_map, k)) != _plain(checks.reading_of(second.file_map, k))
               and checks.reading_of(second.file_map, k) is not None]
    for k in keys:
        result[k] = {"result": REPEATS if k not in changed else THIRD}
    if not changed:
        return result
    merged = checks.merge_reread(first.file_map, second.file_map, changed)
    final = checks.check_map(cells, merged, fye)
    by_key = {}
    for item in final["items"]:
        key = f"last_actual:{item['sheet']}" if item["kind"] == "evidence" else item["key"]
        by_key.setdefault(key, []).append(item)
    agreed = [k for k in changed if k in by_key and all(i["outcome"] == checks.CONFIRMED for i in by_key[k] if i["kind"] != "evidence")]
    for k in changed:
        result[k] = {"result": AGREES if k in agreed else THIRD, "second": checks.reading_of(second.file_map, k)}
    if not agreed:
        return result
    why = {a["item"]: a["why"] for a in asks}
    for k in agreed:
        where = _paths(reading, k)
        if not where:
            result[k]["result"] = THIRD
            continue
        path, old_entry = where
        new_entry = redaction.restore_deep(checks.reading_of(merged, k), mapping)
        ids = []
        if k.startswith("last_actual:"):
            ids.append((await readings.add_override(db, reading=reading["key"], audit_id=audit_id, item=k, path=path, old=old_entry, new=new_entry,
                                                    who=WHO, why=f"{CORRECTED}: {why[k]}"))["id"])
        else:
            if k.startswith("row:"):
                row_entry = checks.reading_of(merged, k)
                smap = next(s for s in merged["sheets"] if k.startswith(f"row:{s['sheet']}:"))
                new_series = series.row_series(smap, row_entry, cells.sheet(smap["sheet"]), fye)
                new_entry = {**new_entry, **{key: new_series.get(key) for key in series.SERIES_KEYS}}
            for field in sorted(set(old_entry) | set(new_entry)):
                if field == "evidence" or old_entry.get(field) == new_entry.get(field):
                    continue
                ids.append((await readings.add_override(db, reading=reading["key"], audit_id=audit_id, item=k, path=f"{path}.{field}",
                                                        old=old_entry.get(field), new=new_entry.get(field), who=WHO,
                                                        why=f"{CORRECTED}: {why[k]}"))["id"])
        result[k]["overrides"] = ids
    doc = redaction.restore_deep({"items": final["items"], "counts": final["counts"], "months": final["months"]}, mapping)
    best = max(final["months"], key=lambda m: m["month"], default=None)
    stored = dict(f["check"])
    stored.update(doc, month=best["month"] if best else None,
                  evidence=redaction.restore_deep(f"{best['evidence']} (confirmed on sheet {best['sheet']}, column {best['column']})", mapping)
                  if best else None,
                  corrections=[*stored.get("corrections", []), *({"item": k, "why": why[k], "at": _now()} for k in agreed if result[k]["result"] == AGREES)])
    for key in ("audit_id", "checked_at"):
        stored.pop(key, None)
    await readings.save_checks(db, audit_id, file_hash, stored)
    return result


# ---------------------------------------------------------------------------
# The review
# ---------------------------------------------------------------------------
def _reader_side(entry: Optional[Dict], second: Optional[Dict] = None) -> Dict:
    entry = entry or {}
    return {"label": "Reader", "value": entry.get("value"), "unit": entry.get("unit"), "currency": entry.get("currency"), "period": entry.get("period"),
            "evidence": entry.get("evidence") if isinstance(entry.get("evidence"), str) else None,
            "role": entry.get("role"), "second_role": (second or {}).get("role")}


async def review_audit(db, audit: Dict, adapter=None, force: bool = False) -> Dict:
    """Run the review of one audit and everything that follows from it. Returns the stored review document."""
    audit_id = audit["id"]
    payload, files = await collect(db, audit)
    if not payload["files"]:
        return {"audit_id": audit_id, "status": "none", "reason": "Nothing has been read yet.", "findings": []}
    digest = input_hash(payload)
    kept = await db[readings.REVIEWS].find_one({"audit_id": audit_id}, {"_id": 0})
    if kept and kept.get("input_hash") == digest and kept.get("status") == "read" and not force:
        return kept
    ran = await gateway.run_reviewer(db, audit_id, payload, adapter=adapter)
    doc = {"audit_id": audit_id, "input_hash": digest, "status": ran.status, "reason": ran.reason, "prompt_version": ran.prompt_version,
           "model": ran.model, "input_tokens": ran.input_tokens, "output_tokens": ran.output_tokens, "estimated_cost_usd": ran.estimated_cost_usd,
           "findings": [], "dropped": 0, "created_at": _now()}
    if ran.status != "read":
        await _save(db, doc)
        return doc
    valid, dropped = validate(ran.findings, files)
    doc["dropped"] = len(dropped)
    for d in dropped:
        logger.warning("finding dropped: run_id=%s finding=%s reason=%s", audit_id, d["id"], d["drop_reason"])     # closed words only
    company = audit.get("company_name")
    mapping = await redaction.get_map(db, audit_id)
    # One re-read per file, for all the items its findings are about.
    asks: Dict[int, List[Dict]] = {}
    plan: Dict[str, List[Tuple[int, str]]] = {}
    for finding in valid:
        plan[finding["id"]] = items_of(finding, files)
        for n, key in plan[finding["id"]]:
            if not any(a["item"] == key for a in asks.get(n, [])):
                asks.setdefault(n, []).append({"item": key, "reason": finding_reason(finding), "why": finding["what"]})
    outcomes: Dict[Tuple[int, str], Dict] = {}
    for n, ask in asks.items():
        for key, res in (await reread_file(db, audit, files.get(n), ask, adapter, company, mapping)).items():
            outcomes[(n, key)] = res
    for finding in valid:
        entry = {**finding, "items": [], "state": "valid"}
        for n, key in plan[finding["id"]]:
            res = outcomes.get((n, key), {"result": UNREAD})
            f = files.get(n)
            item = {"file": n, "key": key, "result": res["result"], "overrides": res.get("overrides", [])}
            if res["result"] != AGREES:
                await _card_for(db, audit_id, finding, f, key, res)
            entry["items"].append(item)
        if not plan[finding["id"]]:
            await _card_without_item(db, audit_id, finding, files)
            entry["items"].append({"file": finding["refs"][0]["file"], "key": None, "result": NO_ITEM, "overrides": []})
        doc["findings"].append(entry)
    doc["findings"] += [{**d, "state": "dropped", "items": []} for d in dropped]
    await _save(db, doc)
    return doc


async def _save(db, doc: Dict) -> None:
    await db[readings.REVIEWS].delete_many({"audit_id": doc["audit_id"]})
    await db[readings.REVIEWS].insert_one(dict(doc))


def _title(finding: Dict) -> str:
    return finding["what"][:160]


async def _card_for(db, audit_id: str, finding: Dict, f: Dict, key: str, res: Dict) -> None:
    """The reader–reviewer disagreement that survived the re-read: both readings, the cell or page."""
    path = _paths(f["reading"], key) if f["kind"] == "sheet" else None
    entry = (path or (None, None))[1]
    ref = finding["refs"][0]
    source = {"file": f["file"], "file_hash": f.get("file_hash"), "sheet": ref.get("sheet"), "cell": ref.get("cell")}
    reader = _reader_side(entry, res.get("second"))
    reader["label"] = "Reader, twice" if res["result"] in (REPEATS, THIRD) else "Reader"
    other = {"label": "Reviewer", "evidence": finding["reading"], "confidence": finding["confidence"], "what": finding["what"]}
    await cards.open_card(db, audit_id, kind=cards.DISAGREEMENT, item=f"{finding['id']}:{key}", title=_title(finding), source=source, reader=reader,
                          other=other, reading=f["reading"]["key"] if path else None, path=path[0] if path else None)


async def _card_without_item(db, audit_id: str, finding: Dict, files: Files) -> None:
    """A valid finding about a cell no mapped row holds, or about a deck page: nothing to read again, so the card shows what the reviewer reads."""
    ref = finding["refs"][0]
    f = files.get(ref["file"])
    source = {"file": f["file"], "file_hash": f.get("file_hash"), "deck_id": f.get("deck_id"), "sheet": ref.get("sheet"), "cell": ref.get("cell"),
              "page": ref.get("page")}
    figure = next((x for x in f.get("figures") or [] if x["source"]["page"] == ref.get("page")), None) if f["kind"] == "deck" else None
    reader = {"label": "Reader", "value": (figure or {}).get("value"), "unit": (figure or {}).get("unit"), "currency": (figure or {}).get("currency"),
              "period": (figure or {}).get("period"), "evidence": None}
    other = {"label": "Reviewer", "evidence": finding["reading"], "confidence": finding["confidence"], "what": finding["what"]}
    await cards.open_card(db, audit_id, kind=cards.DISAGREEMENT, item=f"{finding['id']}:{ref.get('cell') or 'p' + str(ref.get('page'))}",
                          title=_title(finding), source=source, reader=reader, other=other)
