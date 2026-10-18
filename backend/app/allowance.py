"""Per-tester usage ledger and monthly AI allowance (docs/specs/usage-and-allowance.md).

The ledger lives on the tester's record in `access_tokens`, keyed by tester id and not by audit, so deleting an audit does not reset it.
It holds counts and USD only: never a company name, file name, audit name, audit id or figure.
"""
from datetime import datetime, timezone
from typing import Optional

from . import access

DEFAULT_ALLOWANCE_USD = 10.0
MAX_ALLOWANCE_USD = 1000.0
WARN_AT = 0.8
FIELDS = ("files", "calls", "tokens", "cost_usd")
OK, WARN, BLOCKED = "ok", "warn", "blocked"


def month_key(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _bucket(ledger: Optional[dict], key: str) -> dict:
    found = (ledger or {}).get(key) or {}
    return {"files": int(found.get("files", 0)), "calls": int(found.get("calls", 0)),
            "tokens": int(found.get("tokens", 0)), "cost_usd": round(float(found.get("cost_usd", 0.0)), 6)}


def allowance_of(doc: dict) -> float:
    value = doc.get("allowance_usd")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else DEFAULT_ALLOWANCE_USD


def status(doc: dict, now: Optional[datetime] = None) -> dict:
    """{allowance_usd, used_usd, percent, state} of a tester record for the current month. The percent is rounded down."""
    allowance = allowance_of(doc)
    used = _bucket(doc.get("ledger"), month_key(now))["cost_usd"]
    if used >= allowance:
        state = BLOCKED
    elif used >= WARN_AT * allowance:
        state = WARN
    else:
        state = OK
    percent = 100 if state == BLOCKED else int(used * 100 / allowance + 1e-9)
    return {"allowance_usd": allowance, "used_usd": round(used, 2), "percent": percent, "state": state}


async def tester_of(db, audit_id: str) -> Optional[str]:
    audit = await db.audits.find_one({"id": audit_id}, {"owner": 1})
    return (audit or {}).get("owner") or None


async def record(db, tester_id: Optional[str], *, files: int = 0, calls: int = 0, tokens: int = 0, cost_usd: float = 0.0,
                 now: Optional[datetime] = None) -> None:
    """Add to this month and to all time. No tester (access control off): nothing is counted."""
    if not tester_id:
        return
    amounts = {"files": files, "calls": calls, "tokens": tokens, "cost_usd": cost_usd}
    inc = {f"ledger.{key}.{name}": value for key in ("all", month_key(now)) for name, value in amounts.items() if value}
    if inc:
        await db[access.COLLECTION].update_one({"id": tester_id}, {"$inc": inc})


async def record_for_audit(db, audit_id: str, **amounts) -> None:
    await record(db, await tester_of(db, audit_id), **amounts)


async def status_for_audit(db, audit_id: str) -> Optional[dict]:
    tester_id = await tester_of(db, audit_id)
    doc = await db[access.COLLECTION].find_one({"id": tester_id}) if tester_id else None
    return status(doc) if doc else None


async def set_allowance(db, tester_id: str, value: float) -> bool:
    found = await db[access.COLLECTION].find_one({"id": tester_id})
    if not found:
        return False
    await db[access.COLLECTION].update_one({"id": tester_id}, {"$set": {"allowance_usd": round(float(value), 2)}})
    return True


async def report(db, now: Optional[datetime] = None) -> dict:
    """The owner's Usage section: totals across testers and one row per tester link, this month and all time."""
    month = month_key(now)
    docs = await db[access.COLLECTION].find({}, {"_id": 0, "hash": 0}).to_list(1000)
    totals = {"this_month": dict.fromkeys(FIELDS, 0), "all_time": dict.fromkeys(FIELDS, 0)}
    rows = []
    for d in docs:
        row = {"this_month": _bucket(d.get("ledger"), month), "all_time": _bucket(d.get("ledger"), "all")}
        for scope in totals:
            for name in FIELDS:
                totals[scope][name] += row[scope][name]
        rows.append({"id": d["id"], "label": d["label"], "status": access.status_of(d), "allowance_usd": allowance_of(d), **row})
    for scope in totals:
        totals[scope]["cost_usd"] = round(totals[scope]["cost_usd"], 6)
    return {"month": month, "totals": totals, "testers": rows}
