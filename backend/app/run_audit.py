"""The Run audit flow: what each stage reports and which claims need no click (the review screen, the three stages).

Pure functions. The server (`server.py`, "Run audit") reads Mongo and calls them. Nothing here reads a file's rows, calls a
model or changes a threshold: a mapping is auto-accepted by `column_rules.MAPPING_THRESHOLD` before this module sees it, and
a claim is within tolerance by `claim_matching.within_tolerance` (the register's own label, Verified) before it is counted.
"""
from typing import Dict, Iterable, List, Optional

from app import claim_matching as cm
from app import column_rules as cr
from app.decks.claims import CASES, review_flags
from app.structures import sheet as sheet_mod
from schemas.metrics import CONTRACT_VERSION

STAGES = ("mapping", "engine", "claims")
DONE, NEEDS_REVIEW, WAITING, RUNNING, FAILED = "done", "needs_review", "waiting", "running", "failed"

# Plain-English messages (no exception text: it can quote an upload).
NO_FILES = "No file has been uploaded yet. Add the revenue file and run the audit again."
NO_REVENUE = "The revenue file is missing. Add it and run the audit again."
WAIT_MAPPING = "Waiting for the column mapping to be confirmed on the review screen."
WAIT_ENGINE = "Waiting for the calculations."
ENGINE_FAILED = "The calculations could not be completed. Check the mapping on the review screen, then retry this stage."
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


def mapping_counts(datasets: Iterable[dict], recognition_open: Optional[Dict[str, int]] = None) -> Dict:
    """Columns accepted by the rules or a saved mapping (state auto: confidence at or above the threshold, no tie), columns
    waiting for the analyst, and the files with a required field still unmapped. A file read by recognition only has no column: it
    waits for its recognition's choices (`recognition_open`, by file type; revenue-file-recognition.md section 8)."""
    auto = open_ = 0
    missing: List[str] = []
    for ds in datasets:
        if ds.get("recognition_only"):
            open_ += (recognition_open or {}).get(ds["dtype"], 0)
            continue
        if ds.get("sheet_map"):                    # a statement file waits for its lines only (chat-upload.md section 26.6)
            open_ += sheet_mod.pending_count(ds["sheet_map"])
            continue
        states = ds.get("columns_state")
        if states is None:                         # stored before the chat upload: confirmed by the analyst
            continue
        auto += sum(1 for s in states if s.get("state") == "auto")
        open_ += cr.pending_count(states)
        if cr.missing_required(ds["dtype"], states):
            missing.append(ds["dtype"])
    return {"auto": auto, "open": open_, "missing_required": missing}


def engine_stale(audit: dict, datasets: Iterable[dict]) -> bool:
    """True when the stored results are older than the mapping: a column was confirmed or corrected (a file's `mapped_at`) after
    `computed_at`, the audit is flagged `metrics_stale` (an automatic recompute could not run) or its results are of an older engine
    contract version (`results_stale`). Run audit then counts the engine
    stage as not done and calculates again. No results: nothing is stale, the stage is simply not done."""
    if not audit.get("results"):
        return False
    if audit.get("metrics_stale") or results_stale(audit):
        return True
    computed = audit.get("computed_at") or ""
    return any(max(ds.get("mapped_at") or "", ds.get("recognition_decided_at") or "") > computed for ds in datasets)


def never_on_its_own(candidate: dict) -> bool:
    """Issue #155 (George, 2026-10-22, claim-matching.md section 4.1): a claim Run audit leaves to the analyst however close it is: one the
    analyst entered or edited, and one flagged as a deck inconsistency. (A claim in another currency is read from its register row.)
    George, 2026-10-23 (review of PR 164, H1): also a claim the checks flagged for review (`flags` less the informational ones, as Approve all skips it) and a best-case or
    worst-case figure, which the analyst approves one by one. The caller passes `flags` with the ones that depend on the as-of month."""
    return bool(candidate.get("origin") in ("analyst", "deck_analyst") or "parsed" in candidate
                or candidate.get("inconsistent_dates") or candidate.get("inconsistencies")
                or review_flags(candidate.get("flags")) or candidate.get("scenario") in CASES)


def within_tolerance_ids(rows: List[dict], candidate_ids: Iterable[str]) -> List[str]:
    """The candidates whose every register row is Verified within the claim's tolerance: ±5% of the claimed value for
    amounts, counts and durations, ±1 percentage point for rates. A beat (Verified, marked beat, however the analyst answered a
    Definition check) is not within tolerance and stays for the review screen; so does an edited or analyst-entered claim and a claim
    in a currency other than the audit's (issue #155). A table row of several values counts only when all are."""
    wanted = set(candidate_ids)
    labels: Dict[str, List[bool]] = {}
    for r in rows:
        cid = str(r["claim_id"]).split("#")[0]
        if cid in wanted:
            labels.setdefault(cid, []).append(
                r["evidence_label"] == "Verified" and not cm.is_beat(r) and r.get("definition_check") is None
                and r.get("deck_reading") not in (cm.ANALYST_ENTERED, cm.ADDED_FROM_DECK, "edited") and r.get("claimed_converted") is None)
    return [cid for cid, found in labels.items() if found and all(found)]


def stage_result(stage: str, status: str, message: Optional[str] = None, **counts) -> Dict:
    return {"stage": stage, "status": status, "message": message, **counts}
