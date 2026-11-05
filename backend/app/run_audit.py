"""The Run audit flow: what each stage reports and which claims enter the register on their own (the three stages).

Pure functions. The server (`server.py`, "Run audit") reads Mongo and calls them. Nothing here reads a file's rows, calls a
model or changes a threshold: nothing waits for a confirmation of a mapping (there is none; the map is the reading), and
a claim enters the register on its own unless a check asks about it (`needs_a_word`).
"""
from typing import Dict, Optional

from app.decks.claims import review_flags
from app.structures import page_check, verify
from app.structures.completeness import (TIMEOUT_BASE_SECONDS, TIMEOUT_PER_PAGE_READ_SECONDS, claims_record, record_complete,  # noqa: F401
                                         stage_timeout)
from schemas.metrics import CONTRACT_VERSION

# Order (George, 2026-11-05, results stage ordering): the deck claims are done for every deck with figures before the results are calculated,
# so a result never rests on partial deck figures.
STAGES = ("mapping", "claims", "engine")
DONE, WAITING, RUNNING, FAILED = "done", "waiting", "running", "failed"      # never needs_review: nothing waits for a confirmation (PR 4)

# Plain-English messages (no exception text: it can quote an upload).
NO_FILES = "No file has been uploaded yet. Add the revenue file and run the audit again."
FILES_READING = "The files are still being read."
NO_AS_OF = "As-of month: not determined. Everything that does not depend on it was calculated; type the month under the files to calculate the rest."
WAIT_CLAIMS = "Waiting for the deck claims."
ENGINE_FAILED = "The calculations could not be completed. Retry this stage."
CLAIMS_FAILED = "The claims could not be read from the decks. Retry this stage; the figures above are unaffected."
DECKS_READING = "The decks are still being read."
NO_DECKS = "No deck was uploaded: there are no claims to read."
CLAIMS_INCOMPLETE = "Deck claims incomplete: {n} of {m} pages. Retry this stage."
RESULTS_OLDER = "Results are older than the latest reading – run Calculating results again."
NOT_RATED_INCOMPLETE = "not rated – deck claims incomplete"
# George, 2026-10-20: results stored under an older engine contract are marked, not recomputed on a read, until Run audit calculates again.
STALE_LABEL = "Stale – re-run audit"
STALE_CODE = "results_stale"


def results_stale(audit: dict) -> bool:
    """True when the stored results were computed under another engine contract version than the code now running, or a set-up input
    they were computed with changed since (`setup_stale`: Target ARR, Target date, As-of month, fiscal year-end, FX; George, 2026-10-24).
    Run audit calculates again and clears both."""
    results = audit.get("results")
    return bool(results) and (results.get("contract_version") != CONTRACT_VERSION or bool(audit.get("setup_stale")))


def engine_stale(audit: dict) -> bool:
    """True when the stored results are older than the engine or a set-up input: the audit is flagged `metrics_stale` (an automatic recompute
    could not run) or its results are of an older engine contract version or a set-up input changed since (`results_stale`). Run audit then
    calculates again. No results: nothing is stale, the stage is simply not done."""
    if not audit.get("results"):
        return False
    return bool(audit.get("metrics_stale")) or results_stale(audit)


# George, 2026-10-25 (simplified-flow.md section 2): the claim approval is gone. Python enters every claim it matched to its page when no check
# asks about it; the analyst is asked only where a check failed or a question is open.
MATCHED_STATUSES = (verify.VERIFIED, page_check.MATCHED)


def needs_a_word(candidate: dict) -> bool:
    """True when a claim waits for the analyst instead of entering the register on its own: the model's reading is not matched to its page
    ("AI suggestion, not matched"), or the checks flagged it for review (`flags` less the informational ones; the caller passes `flags`
    with the ones that depend on the as-of month). A best or worst case, a deck inconsistency and an open Definition check do not wait:
    they enter and are listed as the register lists them; a turnover question is asked by the caller (it needs the stored results)."""
    return bool((candidate.get("origin") == "ai" and candidate.get("ai_status") not in MATCHED_STATUSES) or review_flags(candidate.get("flags")))


# --- the completeness record of a deck's claims, and the order and age of the results (Architecture change, rule 32) -----------------------

# The record, the timeout and their words live in structures/completeness.py (the page reader writes the record; this module reads it).


def decks_gate(decks: list) -> Dict:
    """Whether the deck claims are done, from the decks' documents (`ai_status`, `file`, `claims_record`).
    state "reading": a deck is still being read; "incomplete": a deck's record has pages missing; else "clear". `incomplete` lists
    [{"file", "missing", "expected"}], `pages` is the pages with figures over all decks, `reads` the reads per page (1 or 2).
    A deck no page reader applies to (consent off, a model off the list, no prompt) or one read before the record existed has no record and
    stands as the status line says; its message is the stage's own."""
    reading = any(d.get("ai_status") == "reading" for d in decks)
    records = [(d, d.get("claims_record")) for d in decks if d.get("claims_record") and d.get("ai_status") not in ("blocked", "prompt_missing", "python_only")]
    incomplete = [{"file": d.get("file"), "missing": len(r.get("missing") or ()), "expected": len(r.get("expected") or ())}
                  for d, r in records if not record_complete(r)]
    pages = sum(len(r.get("expected") or ()) for _, r in records)
    return {"state": "reading" if reading else "incomplete" if incomplete else "clear", "incomplete": incomplete, "pages": pages,
            "reads": 2 if any(r.get("second_required") for _, r in records) else 1, "decks_with_figures": [d.get("file") for d, r in records if r.get("expected")]}


def pages_summary(decks: list) -> str:
    """The log's account of the decks' claims: per deck id, pages read in the first and the second read over the pages with figures. Counts only."""
    out = []
    for d in decks:
        r = d.get("claims_record")
        if r:
            out.append(f"{d.get('deck_id')}:first={len(r.get('first') or ())}/{len(r.get('expected') or ())},second={len(r.get('second') or ())}/{len(r.get('first') or ())}")
    return ";".join(out) or "-"


def incomplete_message(gate: Dict) -> str:
    """"Deck claims incomplete: N of M pages. Retry this stage." N is the pages missing and M the pages with figures, over the decks that are not done."""
    return CLAIMS_INCOMPLETE.format(n=sum(i["missing"] for i in gate["incomplete"]), m=sum(i["expected"] for i in gate["incomplete"]))


def results_older(audit: dict, latest: Optional[str]) -> bool:
    """True when something was read after the stored results were built: `latest` (the newest reading or deck claims now) is later than the
    `results_basis.latest` stored with the results (no input then: anything now is later). Results with no basis (an older version) are not
    called older."""
    basis = audit.get("results_basis")
    return bool(audit.get("results") and basis is not None and latest and latest > (basis.get("latest") or ""))


def decks_missing_from(audit: dict, now_files: list) -> list:
    """The decks with figures now that the stored results were not built with (`results_basis.decks`), in order. Results with no basis: none."""
    basis = audit.get("results_basis")
    if not audit.get("results") or basis is None:
        return []
    built = set(basis.get("decks") or ())
    return [f for f in now_files if f not in built]


def stage_result(stage: str, status: str, message: Optional[str] = None, **counts) -> Dict:
    return {"stage": stage, "status": status, "message": message, **counts}
