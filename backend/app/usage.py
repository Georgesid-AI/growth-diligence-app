"""Usage counters and the "Other" note check (docs/specs/chat-upload.md sections 4.3, 7 and 8).

The counters hold counts and codes: never a file name, a cell value or a company name. The one free-text
field is the kept "Other" note, which may quote a column header and nothing else (a digit, a file name, a cell
text, the company or client name is refused).
"""
import re
import statistics
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from .structures import redact

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
            "other_notes": [], "steps": {"compute": {"runs": 0, "failures": {}}, "mapping_ai": {}}}


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


def record_columns(usage: Dict, kind: str, n: int = 1) -> None:
    _bump(usage["columns"], kind, n)


def record_reason(usage: Dict, code: str) -> None:
    _bump(usage["columns"]["reasons"], code)


def record_compute(usage: Dict, failures: Iterable[str]) -> None:
    usage["steps"]["compute"]["runs"] += 1
    for name in failures:
        _bump(usage["steps"]["compute"]["failures"], name)


def keep_note(usage: Dict, note: str) -> None:
    """A kept "Other" note, on its own: no column, file or field beside it. At most 50, the oldest dropped."""
    usage["other_notes"] = (usage["other_notes"] + [{"note": note, "at": now()}])[-NOTES_KEPT:]


class NoteRefused(Exception):
    """The note holds something it may not (S21). `code` is a closed word."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def clean_note(note: Optional[str]) -> str:
    return _CONTROL.sub("", note or "").strip()


def check_note(note: str, *, headers: Iterable[str], file_names: Iterable[str], cell_texts: Iterable[str],
               names: Iterable[str]) -> None:
    """Raise NoteRefused unless the note is at most 60 characters and, after its headers are set aside, holds no
    digit, file name, cell text, company name or client name. A digit is refused anywhere,
    also inside a header ("Revenue 2024" cannot be quoted). Headers are set aside whole, in any case, before the
    other checks, so a header that contains a cell word still passes."""
    if len(note) > NOTE_MAX:
        return _refuse("too_long")
    if any(ch.isdigit() for ch in note):
        return _refuse("digit")
    rest = note
    for h in sorted({h.strip() for h in headers if h and h.strip()}, key=len, reverse=True):
        rest = re.sub(re.escape(h), " ", rest, flags=re.IGNORECASE)
    low = rest.lower()
    for name in file_names:
        stem = (name or "").rsplit(".", 1)[0] if "." in (name or "") else (name or "")
        if name and (name.lower() in low or redact.has_word(rest, name) or (stem and redact.has_word(rest, stem))):
            return _refuse("file_name")
    for name in names:
        if name and str(name).strip() and redact.has_word(rest, str(name).strip()):
            return _refuse("name")
    seen = set()
    for text in cell_texts:
        for candidate in (text, *re.findall(r"[^\W\d_]+", text)):
            c = candidate.strip()
            if len(c) < MIN_CELL_WORD or c in seen:
                continue
            seen.add(c)
            if c.lower() in low and redact.has_word(rest, c):
                return _refuse("cell_text")


def _refuse(code: str):
    raise NoteRefused(code)


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
