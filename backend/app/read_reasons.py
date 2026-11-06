"""The plain-words reasons the Upload page's file lines give for a file that was not read, or read in part (George, 2026-11-05).

One place for the sentences, so the sheet reader, the deck reader and the server say the same thing and a test can name them. Seconds and sheet
names only: no cell, no deck text (CLAUDE.md rule 17). The stored reason (a closed word or a number) is the record; these are what the analyst reads."""
from typing import Dict, List, Optional

from .llm import gateway

CUT_LINE = "Reply cut at the output limit – read sheet by sheet failed on {sheets}"
INPUT_LINE = "Too large to read in one call (input limit) – {sheets} not read"
NOT_SENT_LINE = "Page reads were not sent (waited {seconds} s)"
TIMEOUT_LINE = "Timed out after {seconds} s"


def _sheets(names: List[str]) -> str:
    return ("sheet " if len(names) == 1 else "sheets ") + ", ".join(names)


def sheets_line(unread: Optional[List[Dict]]) -> Optional[str]:
    """The line for sheets lost alone ([{"sheet", "reason"}] as the reading stores them), or None when none was lost."""
    cut = [u["sheet"] for u in unread or [] if u.get("reason") == gateway.SHEET_CUT_REASON]
    big = [u["sheet"] for u in unread or [] if u.get("reason") == gateway.SHEET_INPUT_CAP_REASON]
    lines = ([CUT_LINE.format(sheets=_sheets(cut))] if cut else []) + ([INPUT_LINE.format(sheets=_sheets(big))] if big else [])
    return ". ".join(lines) or None


def seconds_text(seconds: float) -> str:
    return str(max(0, int(round(seconds))))


def timeout_line(seconds: float) -> str:
    return TIMEOUT_LINE.format(seconds=seconds_text(seconds))


def not_sent_line(seconds: float) -> str:
    return NOT_SENT_LINE.format(seconds=seconds_text(seconds))


def pages_line(reads: List[Dict]) -> Optional[str]:
    """The line for a deck's page reads that ended without a call or without an answer ("page_reads" entries: status, reason, seconds), or None.
    The longest wait or clock is named; "not sent" comes before "timed out" when both happened (the page never reached the model)."""
    unread = [r for r in reads or [] if r.get("status") != "read"]
    sent = [r for r in unread if r.get("reason") == gateway.NOT_SENT]
    late = [r for r in unread if r.get("reason") == "timeout"]
    if sent:
        return not_sent_line(max(r.get("seconds") or 0 for r in sent))
    if late:
        return timeout_line(max(r.get("seconds") or 0 for r in late))
    return None
