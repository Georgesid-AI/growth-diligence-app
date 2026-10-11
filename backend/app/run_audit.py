"""The Run audit flow: what each stage reports and which claims need no click (the review screen, the three stages).

Pure functions. The server (`server.py`, "Run audit") reads Mongo and calls them. Nothing here reads a file's rows, calls a
model or changes a threshold: a mapping is auto-accepted by `column_rules.MAPPING_THRESHOLD` before this module sees it, and
a claim is within tolerance by `claim_matching.within_tolerance` (the register's own label, Verified) before it is counted.
"""
from typing import Dict, Iterable, List, Optional

from app import column_rules as cr

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


def mapping_counts(datasets: Iterable[dict]) -> Dict:
    """Columns accepted by the rules or a saved mapping (state auto: confidence at or above the threshold, no tie), columns
    waiting for the analyst, and the files with a required field still unmapped."""
    auto = open_ = 0
    missing: List[str] = []
    for ds in datasets:
        states = ds.get("columns_state")
        if states is None:                         # stored before the chat upload: confirmed by the analyst
            continue
        auto += sum(1 for s in states if s.get("state") == "auto")
        open_ += cr.pending_count(states)
        if cr.missing_required(ds["dtype"], states):
            missing.append(ds["dtype"])
    return {"auto": auto, "open": open_, "missing_required": missing}


def within_tolerance_ids(rows: List[dict], candidate_ids: Iterable[str]) -> List[str]:
    """The candidates whose every register row is Verified (within the claim's tolerance: ±5% of the claimed value for
    amounts, counts and durations, ±1 percentage point for rates). A table row of several values counts only when all are."""
    wanted = set(candidate_ids)
    labels: Dict[str, List[str]] = {}
    for r in rows:
        cid = str(r["claim_id"]).split("#")[0]
        if cid in wanted:
            labels.setdefault(cid, []).append(r["evidence_label"])
    return [cid for cid, found in labels.items() if found and all(label == "Verified" for label in found)]


def stage_result(stage: str, status: str, message: Optional[str] = None, **counts) -> Dict:
    return {"stage": stage, "status": status, "message": message, **counts}
