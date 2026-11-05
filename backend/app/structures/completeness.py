"""The completeness record of a deck's claims and the time a stage is given (results stage ordering, 2026-11-05; Architecture change, rule 32).

Pure functions; page numbers and counts only (rule 17). The page reader (pages.process_deck_pages) writes the record on the deck's document, page by
page; Run audit (app/run_audit.py) reads it to decide whether the deck claims are done before the results are calculated.
"""
import os
from typing import Dict, Optional

# Timeouts scale with the work: a base plus an allowance per page and per read of it. The allowance is a page's own timeout (60 s) shared by the
# pages read at a time (8), rounded up. A 44-page audit read twice: 120 + 44 * 2 * 8 = 824 s.
TIMEOUT_BASE_SECONDS = 120
TIMEOUT_PER_PAGE_READ_SECONDS = 8


def stage_timeout(pages: int, reads: int) -> int:
    """Seconds a stage is given: base + per-page allowance x pages x reads per page. No deck pages: the base."""
    return TIMEOUT_BASE_SECONDS + TIMEOUT_PER_PAGE_READ_SECONDS * max(0, int(pages)) * max(1, int(reads))


# A page the reader will never read again: the call is refused for its size, cut at the output limit or refused by the model (the statuses outside
# pages.RETRY_STATUSES). The analyst may continue without it ("Continue without page N"); the words are plain, for the screen and the memo.
UNREADABLE = {"too_large": "too large for the token cap", "truncated": "reply cut at the output limit", "refused": "refused by the model"}


# A page the token cap refused: marked "cap" in the record's `unreadable` list, with the tokens used and the cap in the record's `cap`. Unlike the pages above it
# cannot be continued without and a read will not be tried again: the same cap refuses it (combined fixes, 2026-11-05).
CAP = "cap"


def second_read_required() -> bool:
    """Whether each page is read twice (the consistency read, docs/design/reading-consistency.md). On by default; PAGE_SECOND_READ=0 turns the
    second read off for a deployment that must hold the page-read cost down. The one reading of the switch: the page reader and the gate share it."""
    return os.environ.get("PAGE_SECOND_READ", "1").strip() != "0"


def claims_record(expected, first, second, second_required: bool, at: str, unreadable=(), capped=(), cap: Optional[Dict] = None) -> Dict:
    """What one deck's claims step stores: the pages with figures (`expected`), the pages read in the first and in the second read, and the pages
    still missing: a page with no first read, and, when the second read is on, a page read once whose second read is not stored. `capped`: the pages
    a read was refused for the token cap, marked "cap"; `cap` is {"used", "cap"} then. Page numbers and counts only."""
    expected, first, second = sorted(set(expected)), sorted(set(first)), sorted(set(second))
    missing = set(expected) - set(first)
    if second_required:
        missing |= set(first) - set(second)
    listed = [(p, r) for p, r in unreadable if p in missing and r in UNREADABLE] + [(p, CAP) for p in set(capped) if p in missing]
    record = {"expected": expected, "first": first, "second": second, "second_required": bool(second_required), "missing": sorted(missing), "at": at,
              "unreadable": [{"page": int(p), "reason": r} for p, r in sorted(set(listed))]}
    if cap and any(r == CAP for _, r in listed):
        record["cap"] = {"used": int(cap["used"]), "cap": int(cap["cap"])}
    return record


def still_missing(record: Optional[Dict], overrides=(), second_on: Optional[bool] = None) -> list:
    """The pages missing from a record, judged as the second-read switch stands now (`second_on`; None reads it), not as it stood when the record was
    written: a page with no first read, and, when the second read is on, a page read once. An override (`overrides`: [{"page", "reason", "at"}],
    "Continue without page N") covers a page only while the record still lists it as one that can never be read: a page a later read left missing
    for a reason that can be retried is read again, whatever was continued without before (review of #240, 2026-11-05)."""
    if not record:
        return []
    required = second_read_required() if second_on is None else bool(second_on)
    first, second = set(record.get("first") or ()), set(record.get("second") or ())
    missing = set(record.get("expected") or ()) - first
    if required:
        missing |= first - second
    never = {u.get("page") for u in record.get("unreadable") or ()}
    skipped = {o.get("page") for o in overrides or ()} & never
    return sorted(p for p in missing if p not in skipped)


def record_complete(record: Optional[Dict], overrides=(), second_on: Optional[bool] = None) -> bool:
    """Done: first-read coverage of every page with figures and, when the second read is on, second-read coverage equal to the first; a page the
    analyst continued without counts as covered while it can never be read."""
    return bool(record) and not still_missing(record, overrides, second_on)
