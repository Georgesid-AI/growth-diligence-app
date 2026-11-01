"""The Run audit flow: what each stage reports and which claims enter the register on their own (the three stages).

Pure functions. The server (`server.py`, "Run audit") reads Mongo and calls them. Nothing here reads a file's rows, calls a
model or changes a threshold: nothing waits for a confirmation of a mapping (there is none; the map is the reading), and
a claim enters the register on its own unless a check asks about it (`needs_a_word`).
"""
from typing import Dict, Optional

from app.decks.claims import review_flags
from app.structures import page_check, verify
from schemas.metrics import CONTRACT_VERSION

STAGES = ("mapping", "engine", "claims")
DONE, NEEDS_REVIEW, WAITING, RUNNING, FAILED = "done", "needs_review", "waiting", "running", "failed"

# Plain-English messages (no exception text: it can quote an upload).
NO_FILES = "No file has been uploaded yet. Add the revenue file and run the audit again."
FILES_READING = "The files are still being read."
NO_AS_OF = "As-of month: not determined. Everything that does not depend on it was calculated; type the month under the files to calculate the rest."
WAIT_ENGINE = "Waiting for the calculations."
ENGINE_FAILED = "The calculations could not be completed. Retry this stage."
CLAIMS_FAILED = "The claims could not be read from the decks. Retry this stage; the figures above are unaffected."
DECKS_READING = "The decks are still being read."
NO_DECKS = "No deck was uploaded: there are no claims to read."
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


def stage_result(stage: str, status: str, message: Optional[str] = None, **counts) -> Dict:
    return {"stage": stage, "status": status, "message": message, **counts}
