"""Usage counters and the "Other" note check (docs/specs/chat-upload.md sections 4.3, 7 and 8).

The counters hold counts and codes: never a file name, a cell value or a company name. The one free-text
field is the kept "Other" note, which may quote a column header and nothing else (a digit, a file name, a cell
text, the company name is refused).
"""
import re
import statistics
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional



SCREENS = ("mapping", "dashboard", "diagnostics")
NOTE_MAX = 60
NOTES_KEPT = 50
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_EXTENSION = re.compile(r"^[a-z0-9]{1,6}$")
MIN_CELL_WORD = 4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty() -> Dict:
    return {"first_upload_at": None, "first_export_at": None, "last_screen": None,
            "files": {"uploaded": {}, "rejected": {}},
            "columns": {"rules": 0, "saved": 0, "ai": 0, "confirmed": 0, "corrected": 0, "reasons": {}},
            "other_notes": [], "steps": {"compute": {"runs": 0, "failures": {}}, "mapping_ai": {}, "recognition": {}}}


def _bump(counts: Dict, key: str, n: int = 1) -> None:
    counts[key] = counts.get(key, 0) + n


def get(audit: Optional[Dict]) -> Dict:
    """The audit's counters with every key present (audits created before the counters existed have none)."""
    base = empty()
    stored = (audit or {}).get("usage") or {}
    for key, value in stored.items():
        if isinstance(base.get(key), dict) and isinstance(value, dict):
            base[key].update(value)
        else:
            base[key] = value
    for key in ("uploaded", "rejected"):
        base["files"].setdefault(key, {})
    for key in ("runs", "failures"):
        base["steps"]["compute"].setdefault(key, 0 if key == "runs" else {})
    return base


def extension_of(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return ext if _EXTENSION.match(ext) else "other"


def record_upload(usage: Dict, dtype: str) -> None:
    usage["first_upload_at"] = usage["first_upload_at"] or now()
    _bump(usage["files"]["uploaded"], dtype)


def record_rejected(usage: Dict, ext: str) -> None:
    _bump(usage["files"]["rejected"], ext if _EXTENSION.match(ext or "") else "other")






def record_compute(usage: Dict, failures: Iterable[str]) -> None:
    usage["steps"]["compute"]["runs"] += 1
    for name in failures:
        _bump(usage["steps"]["compute"]["failures"], name)












# ---------------------------------------------------------------------------
# Totals across audits (section 7): sums, one median, the newest notes. No per-audit rows, names or ids.
# ---------------------------------------------------------------------------
def _add(into: Dict, other: Dict) -> None:
    for k, v in (other or {}).items():
        if isinstance(v, dict):
            _add(into.setdefault(k, {}), v)
        elif isinstance(v, (int, float)):
            into[k] = into.get(k, 0) + v


def totals(usages: List[Dict], extras: Dict) -> Dict:
    """Sums of the counters; the median days from first upload to first export; the 50 newest notes. `extras`
    holds what is computed on read (tokens and cost per step, evidence labels, analyst changes)."""
    summed, days, notes = {"files": {}, "columns": {}, "steps": {}}, [], []
    for u in usages:
        _add(summed["files"], u["files"])
        _add(summed["columns"], u["columns"])
        _add(summed["steps"], u["steps"])
        notes += u["other_notes"]
        try:
            first, export = (datetime.fromisoformat(u[k]) for k in ("first_upload_at", "first_export_at"))
            days.append((export - first).total_seconds() / 86400)
        except (TypeError, ValueError):
            pass
    notes.sort(key=lambda n: n["at"], reverse=True)
    return {"audits": len(usages), **summed,
            "median_days_to_export": round(statistics.median(days), 2) if days else None,
            "other_notes": [{"note": n["note"], "at": n["at"]} for n in notes[:NOTES_KEPT]], **extras}
