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

from . import readings

CITATION, DISAGREEMENT, MASKED = "citation_failed_twice", "reviewer_disagreement", "masked_value"
KINDS = (CITATION, DISAGREEMENT, MASKED)
OPEN, DECIDED = "open", "decided"
USE_CELL, USE_READER, TYPED = "use_cell", "use_reader", "type_value"
ACTIONS = (USE_CELL, USE_READER, TYPED)


def card_id(audit_id: str, kind: str, item: str) -> str:
    return hashlib.sha256(f"card\x00{audit_id}\x00{kind}\x00{item}".encode("utf-8")).hexdigest()[:24]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def open_card(db, audit_id: str, *, kind: str, item: str, title: str, source: Dict, reader: Optional[Dict], other: Optional[Dict],
                    cell_value: Optional[float] = None, reading: Optional[str] = None, path: Optional[str] = None) -> Dict:
    """Open the card of (audit, kind, item) unless it exists. `source` is {file, sheet, cell | page, file_hash | deck_id}; `reader` and `other` are
    the two readings to show, each {label, value, unit, currency, period, evidence}. `cell_value` is what the cell holds (for "use the cell"),
    `reading` the key of the stored reading and `path` the place in it a decision overrides."""
    if kind not in KINDS:
        raise ValueError(f"unknown card kind {kind!r}")
    cid = card_id(audit_id, kind, item)
    kept = await db[readings.CARDS].find_one({"id": cid}, {"_id": 0})
    if kept:
        return kept
    doc = {"id": cid, "audit_id": audit_id, "kind": kind, "item": item, "title": title, "source": source, "reader": reader, "other": other,
           "cell_value": cell_value, "reading": reading, "path": path, "status": OPEN, "decision": None, "created_at": _now()}
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
    value = chosen_value(card, action, typed)
    if value is None:
        raise ValueError("no value to use")
    decision = {"action": action, "value": value, "who": who, "at": _now()}
    if card.get("reading") and card.get("path"):
        old = (card.get("reader") or {}).get("value")
        override = await readings.add_override(db, reading=card["reading"], audit_id=audit_id, item=card["item"], path=card["path"], old=old, new=value,
                                               who=who, why=f"card decided: {action}")
        decision["override"] = override["id"]
    await db[readings.CARDS].update_one({"id": cid}, {"$set": {"status": DECIDED, "decision": decision}})
    return {**card, "status": DECIDED, "decision": decision}
