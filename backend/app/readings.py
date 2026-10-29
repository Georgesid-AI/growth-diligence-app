"""Stored readings (docs/design/read-check-review.md section 9): written once, never edited.

A reading is the reader's file map (schemas/metrics.FileMap) for one file, keyed on the file's hash, the reading prompt's version and the
model's version. The same file uploaded again, in any audit, gets the stored reading and makes no model call. A new prompt or model
version is a new key, stored beside the old reading; re-reading is an explicit action, never automatic.

Nothing here updates a stored document. What changes later is written as a record of its own:

    readings          the reading: file map, prompt version, model, tokens, cost. Insert-only.
    reading_uses      which audits use a reading (so Delete audit can remove a reading no audit uses any more, rule 22).
    reading_rereads   the automatic second reading of a rejected item, with the reason attached. Insert-only, beside the first reading.
    reading_overrides a reviewer correction or an analyst Change: reading, item, old value, new value, who, when, why. Insert-only.
    reading_checks    the outcome of the checks for one audit and file. Derived (app/checks.py), rewritten for the audit at each upload.

The register is the reading plus its overrides (`effective`). Rule 17: the stored reading is the model's JSON output with names restored
(display un-masks on the server); never the text that was sent.
"""
import copy
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

READINGS = "readings"
USES = "reading_uses"
REREADS = "reading_rereads"
OVERRIDES = "reading_overrides"
CHECKS = "reading_checks"
COLLECTIONS = (READINGS, USES, REREADS, OVERRIDES, CHECKS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def reading_key(file_hash: str, prompt_version: str, model: str) -> str:
    """The identity of a reading: the file's bytes, the prompt version, the model version."""
    return _digest("reading", file_hash, prompt_version, model)


async def get(db, file_hash: str, prompt_version: str, model: str) -> Optional[dict]:
    """The stored reading for this file, prompt version and model, or None. A hit makes no provider call."""
    return await db[READINGS].find_one({"key": reading_key(file_hash, prompt_version, model)}, {"_id": 0})


async def put(db, *, file_hash: str, prompt_version: str, model: str, reading: dict, input_tokens: int = 0, output_tokens: int = 0,
              cost: float = 0.0) -> dict:
    """Store a reading once. A reading already stored under the key is returned as it stands and nothing is written."""
    key = reading_key(file_hash, prompt_version, model)
    kept = await db[READINGS].find_one({"key": key}, {"_id": 0})
    if kept:
        return kept
    doc = {"key": key, "file_hash": file_hash, "prompt_version": prompt_version, "model": model, "file_map": copy.deepcopy(reading),
           "input_tokens": int(input_tokens), "output_tokens": int(output_tokens), "estimated_cost_usd": round(float(cost), 6),
           "created_at": _now()}
    try:
        await db[READINGS].insert_one(dict(doc))
    except Exception as exc:        # a second writer won the unique index: its reading stands
        if type(exc).__name__ != "DuplicateKeyError":
            raise
        return await db[READINGS].find_one({"key": key}, {"_id": 0}) or doc
    return doc


async def use(db, audit_id: str, key: str) -> None:
    """Note that an audit uses a reading. Once per audit and reading."""
    if not await db[USES].find_one({"audit_id": audit_id, "key": key}, {"_id": 0, "key": 1}):
        await db[USES].insert_one({"audit_id": audit_id, "key": key, "at": _now()})


def reread_key(reading: str, item: str, reason: str) -> str:
    return _digest("reread", reading, item, reason)


async def get_reread(db, reading: str, item: str, reason: str) -> Optional[dict]:
    return await db[REREADS].find_one({"key": reread_key(reading, item, reason)}, {"_id": 0})


async def put_reread(db, *, reading: str, item: str, reason: str, prompt_version: str, model: str, output: dict, input_tokens: int = 0,
                     output_tokens: int = 0, cost: float = 0.0) -> dict:
    """Store the second reading of a rejected item beside the first, once. The same item with the same reason is never read again."""
    key = reread_key(reading, item, reason)
    kept = await db[REREADS].find_one({"key": key}, {"_id": 0})
    if kept:
        return kept
    doc = {"key": key, "reading": reading, "item": item, "reason": reason, "prompt_version": prompt_version, "model": model,
           "output": copy.deepcopy(output), "input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
           "estimated_cost_usd": round(float(cost), 6), "created_at": _now()}
    await db[REREADS].insert_one(dict(doc))
    return doc


async def add_override(db, *, reading: str, audit_id: str, item: str, path: str, old: Any, new: Any, who: str, why: str) -> dict:
    """A dated override of one item of a reading: a reviewer correction or an analyst Change. Insert-only; the reading is not touched."""
    doc = {"id": _digest("override", reading, audit_id, item, path, _now(), str(new)), "reading": reading, "audit_id": audit_id, "item": item,
           "path": path, "old": old, "new": new, "who": who, "at": _now(), "why": why}
    await db[OVERRIDES].insert_one(dict(doc))
    return doc


async def overrides_for(db, audit_id: str, reading: Optional[str] = None) -> List[dict]:
    flt = {"audit_id": audit_id, **({"reading": reading} if reading else {})}
    rows = await db[OVERRIDES].find(flt, {"_id": 0}).to_list(100000)
    return sorted(rows, key=lambda r: r.get("at") or "")


def _walk(node: Any, parts: List[str]):
    for part in parts:
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def effective(reading: dict, overrides: List[dict]) -> dict:
    """The register's view of a reading: a copy with each override applied in the order it was made. The stored reading is not changed.
    An override whose path no longer leads anywhere in the reading is skipped."""
    out = copy.deepcopy(reading)
    for o in sorted(overrides, key=lambda r: r.get("at") or ""):
        parts = str(o.get("path") or "").split(".")
        try:
            parent = _walk(out, parts[:-1])
            parent[int(parts[-1]) if isinstance(parent, list) else parts[-1]] = o["new"]
        except (KeyError, IndexError, ValueError, TypeError):
            continue
    return out


async def save_checks(db, audit_id: str, file_hash: str, doc: dict) -> None:
    """The check outcome of one file for one audit (derived, so rewritten at each upload of the file)."""
    await db[CHECKS].delete_many({"audit_id": audit_id, "file_hash": file_hash})
    await db[CHECKS].insert_one({**doc, "audit_id": audit_id, "file_hash": file_hash, "checked_at": _now()})


async def checks_for(db, audit_id: str) -> List[dict]:
    return await db[CHECKS].find({"audit_id": audit_id}, {"_id": 0}).to_list(1000)


async def purge_audit(db, audit_id: str) -> Dict[str, int]:
    """Delete audit (rule 22): this audit's uses, checks and overrides go, and a reading no audit uses any more goes with its rereads.
    A reading another audit still uses stays for it."""
    used = [u["key"] for u in await db[USES].find({"audit_id": audit_id}, {"_id": 0, "key": 1}).to_list(100000)]
    uses = await db[USES].delete_many({"audit_id": audit_id})
    checks = await db[CHECKS].delete_many({"audit_id": audit_id})
    overrides = await db[OVERRIDES].delete_many({"audit_id": audit_id})
    readings = rereads = 0
    for key in dict.fromkeys(used):
        if await db[USES].count_documents({"key": key}) == 0:
            readings += getattr(await db[READINGS].delete_many({"key": key}), "deleted_count", 0)
            rereads += getattr(await db[REREADS].delete_many({"reading": key}), "deleted_count", 0)
    return {"reading_uses": getattr(uses, "deleted_count", 0), "reading_checks": getattr(checks, "deleted_count", 0),
            "reading_overrides": getattr(overrides, "deleted_count", 0), "readings": readings, "reading_rereads": rereads}
