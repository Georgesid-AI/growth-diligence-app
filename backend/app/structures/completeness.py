"""The completeness record of a deck's claims and the time a stage is given (results stage ordering, 2026-11-05; Architecture change, rule 32).

Pure functions; page numbers and counts only (rule 17). The page reader (pages.process_deck_pages) writes the record on the deck's document, page by
page; Run audit (app/run_audit.py) reads it to decide whether the deck claims are done before the results are calculated.
"""
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


def claims_record(expected, first, second, second_required: bool, at: str, unreadable=()) -> Dict:
    """What one deck's claims step stores: the pages with figures (`expected`), the pages read in the first and in the second read, and the pages
    still missing: a page with no first read, and, when the second read is on, a page read once whose second read is not stored. Page numbers only."""
    expected, first, second = sorted(set(expected)), sorted(set(first)), sorted(set(second))
    missing = set(expected) - set(first)
    if second_required:
        missing |= set(first) - set(second)
    return {"expected": expected, "first": first, "second": second, "second_required": bool(second_required), "missing": sorted(missing), "at": at,
            "unreadable": [{"page": int(p), "reason": r} for p, r in sorted(unreadable) if p in missing and r in UNREADABLE]}


def still_missing(record: Optional[Dict], overrides=()) -> list:
    """The pages missing from a record that the analyst has not chosen to continue without (`overrides`: [{"page", "reason", "at"}])."""
    skipped = {o.get("page") for o in overrides or ()}
    return [p for p in (record or {}).get("missing") or () if p not in skipped]


def record_complete(record: Optional[Dict], overrides=()) -> bool:
    """Done: first-read coverage of every page with figures and, when the second read is on, second-read coverage equal to the first; a page the
    analyst continued without counts as covered."""
    return bool(record) and not still_missing(record, overrides)
