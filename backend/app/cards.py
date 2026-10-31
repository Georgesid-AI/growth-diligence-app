"""Cards (docs/design/read-check-review.md section 7.4; PR 3 step c): what the checks, the re-read and the reviewer could not settle.

A card exists for three cases only, and for nothing else:

    citation_failed_twice     an item whose citation was rejected and whose automatic re-read was rejected again
    reviewer_disagreement     a finding of the reviewer the reader did not accept on its re-read (or a finding on a deck figure, which has no re-read)
    masked_value              a value the reading needs that depends on a name masked before reading

A card shows the two readings with their evidence and the cell or page link, and offers "use the cell", "use the reader", "type a value".
The decision is a dated override record of its own (readings.add_override); the reading is never edited. A card is written once per audit, kind
and item (its id is a digest of those), so a second run of the reviewer or the checks does not open it again; a decided card stays decided.
"""
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import checks, readings

CITATION, DISAGREEMENT, MASKED = "citation_failed_twice", "reviewer_disagreement", "masked_value"
KINDS = (CITATION, DISAGREEMENT, MASKED)
OPEN, DECIDED = "open", "decided"
USE_CELL, USE_READER, TYPED = "use_cell", "use_reader", "type_value"
ACTIONS = (USE_CELL, USE_READER, TYPED)


SET_NOTE = "set by analyst"
SET_HOVER = "value set by analyst; the check did not confirm it"


def set_by_analyst(card: Dict) -> Dict:
    """The marker a decided card puts on its figure, wherever the figure is shown or exported: the words, the date and the hover text."""
    decision = card.get("decision") or {}
    return {"note": SET_NOTE, "set_at": str(decision.get("at") or "")[:10] or None, "hover": SET_HOVER, "set_action": decision.get("action")}


def card_id(audit_id: str, kind: str, item: str) -> str:
    return hashlib.sha256(f"card\x00{audit_id}\x00{kind}\x00{item}".encode("utf-8")).hexdigest()[:24]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def open_card(db, audit_id: str, *, kind: str, item: str, title: str, source: Dict, reader: Optional[Dict], other: Optional[Dict],
                    cell_value: Optional[float] = None, reading: Optional[str] = None, path: Optional[str] = None,
                    subject: Optional[Dict] = None, actions: Optional[List[str]] = None) -> Dict:
    """Open the card of (audit, kind, item) unless it exists. `source` is {file, sheet, cell | page, file_hash | deck_id}; `reader` and `other` are
    the two readings to show, each {label, value, unit, currency, period, evidence}. `cell_value` is what the cell holds (for "use the cell"),
    `reading` the key of the stored reading and `path` the place in it a decision overrides, `subject` {metric, period} for the heading and
    `actions` the buttons offered: all three for a value with a cell to use, "use the reader" alone where nothing else can be used."""
    if kind not in KINDS:
        raise ValueError(f"unknown card kind {kind!r}")
    cid = card_id(audit_id, kind, item)
    kept = await db[readings.CARDS].find_one({"id": cid}, {"_id": 0})
    if kept:
        return kept
    doc = {"id": cid, "audit_id": audit_id, "kind": kind, "item": item, "title": title, "source": source, "reader": reader, "other": other,
           "cell_value": cell_value, "reading": reading, "path": path, "subject": subject or {},
           "actions": actions or ([USE_CELL, USE_READER, TYPED] if cell_value is not None else [USE_READER, TYPED]), "status": OPEN, "decision": None, "created_at": _now()}
    await db[readings.CARDS].insert_one(dict(doc))
    return doc


async def for_audit(db, audit_id: str) -> List[Dict]:
    rows = await db[readings.CARDS].find({"audit_id": audit_id}, {"_id": 0}).to_list(1000)
    return sorted(rows, key=lambda r: (r["status"] != OPEN, r.get("created_at") or ""))


def chosen_value(card: Dict, action: str, typed: Optional[float]) -> Optional[float]:
    """The value a decision sets: the cell's, the reader's, or the typed one."""
    if action == USE_CELL:
        return card.get("cell_value")
    if action == USE_READER:
        return (card.get("reader") or {}).get("value")
    return typed


async def decide(db, audit_id: str, cid: str, action: str, typed: Optional[float] = None, who: str = "analyst") -> Optional[Dict]:
    """Record the analyst's decision on an open card: the card is marked decided, and a card that points into a stored reading (`reading` and
    `path`) gets a dated override with the old and the new value. Returns the card, or None when there is none open under the id."""
    if action not in ACTIONS:
        raise ValueError("unknown action")
    card = await db[readings.CARDS].find_one({"id": cid, "audit_id": audit_id, "status": OPEN}, {"_id": 0})
    if not card:
        return None
    if action not in card.get("actions", ACTIONS):
        raise ValueError("this card does not offer that action")
    value = chosen_value(card, action, typed)
    if value is None and action != USE_READER:
        raise ValueError("no value to use")
    decision = {"action": action, "value": value, "who": who, "at": _now()}
    if value is not None and card.get("reading") and card.get("path"):
        old = (card.get("reader") or {}).get("value")
        override = await readings.add_override(db, reading=card["reading"], audit_id=audit_id, item=card["item"], path=card["path"], old=old, new=value,
                                               who=who, why=f"card decided: {action}")
        decision["override"] = override["id"]
    await db[readings.CARDS].update_one({"id": cid}, {"$set": {"status": DECIDED, "decision": decision}})
    return {**card, "status": DECIDED, "decision": decision}


async def open_for_checks(db, audit_id: str, doc: Dict) -> List[Dict]:
    """The cards the checks of one file call for (section 7.4): a citation that failed twice (the item is still rejected after its one automatic
    re-read) and a masked value the reading needs (a figure whose cell holds a name masked before reading). `doc` is the stored outcome
    (sheet_reader.read_file). Nothing else opens a card."""
    out: List[Dict] = []
    reading = await db[readings.READINGS].find_one({"key": doc.get("reading_key")}, {"_id": 0, "file_map": 1}) or {}
    figures = (reading.get("file_map") or {}).get("figures") or []
    by_key = {i["key"]: i for i in doc.get("items") or [] if i["kind"] != "evidence"}

    def figure_path(key: str) -> Optional[str]:
        return next((f"figures.{n}.value" for n, f in enumerate(figures) if checks._figure_key(n, f) == key), None)

    def entry(key: str) -> Optional[Dict]:
        return next((f for n, f in enumerate(figures) if checks._figure_key(n, f) == key), None)

    for again in doc.get("rereads") or []:
        if again.get("action") != "card":
            continue
        item = by_key.get(again["item"]) or {}
        first = again.get("first") or {}
        is_figure = again["item"].startswith("figure:")
        reader = {"label": "Reader, twice" if again.get("second") else "Reader", "value": first.get("value") if is_figure else None,
                  "unit": first.get("unit"), "currency": first.get("currency"), "period": first.get("period"),
                  "evidence": first.get("evidence") if isinstance(first.get("evidence"), str) else None}
        other = {"label": f"Cell {item.get('cell')}" if item.get("cell") else "The file", "value": item.get("found_value"),
                 "period": item.get("found_period"), "evidence": again.get("reason")}
        out.append(await open_card(
            db, audit_id, kind=CITATION, item=again["item"], title="The reader and the file disagree",
            source={"file": doc.get("file"), "file_hash": doc.get("file_hash"), "sheet": item.get("sheet"), "cell": item.get("cell")},
            reader=reader, other=other, cell_value=item.get("found_value") if is_figure else None, reading=doc.get("reading_key"),
            path=figure_path(again["item"]) if is_figure else None, subject={"metric": item.get("metric"), "period": first.get("period")},
            actions=None if is_figure else [USE_READER]))
    for item in doc.get("items") or []:
        if item["kind"] != "figure" or item["outcome"] != "cannot_check" or item.get("reason") != checks.C_MASKED:
            continue
        first = entry(item["key"]) or {}
        out.append(await open_card(
            db, audit_id, kind=MASKED, item=item["key"], title="The reading needs a value that was masked",
            source={"file": doc.get("file"), "file_hash": doc.get("file_hash"), "sheet": item.get("sheet"), "cell": item.get("cell")},
            reader={"label": "Reader", "value": first.get("value"), "unit": first.get("unit"), "currency": first.get("currency"),
                    "period": first.get("period"), "evidence": first.get("evidence") if isinstance(first.get("evidence"), str) else None},
            other={"label": f"Cell {item.get('cell')}", "value": None, "period": None, "evidence": item.get("reason")},
            reading=doc.get("reading_key"), path=figure_path(item["key"]), subject={"metric": item.get("metric"), "period": first.get("period")},
            actions=[USE_READER, TYPED]))
    return out
