"""The Run audit flow: what each stage reports and which claims enter the register on their own (the three stages).

Pure functions. The server (`server.py`, "Run audit") reads Mongo and calls them. Nothing here reads a file's rows, calls a
model or changes a threshold: nothing waits for a confirmation of a mapping (there is none; the map is the reading), and
a claim enters the register on its own unless a check asks about it (`needs_a_word`).
"""
from typing import Dict, Optional

from app.formatting import fmt_count
from app.decks.claims import review_flags
from app.structures import page_check, verify
from app.structures.completeness import (TIMEOUT_BASE_SECONDS, TIMEOUT_PER_PAGE_READ_SECONDS, claims_record, record_complete,  # noqa: F401
                                         stage_timeout, still_missing, UNREADABLE, CAP)
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
CLAIMS_INCOMPLETE = "Deck claims incomplete: {n} of {m} pages. Retry this stage."       # (the older wording; the failure now names the deck, the reason and the action)
TOKEN_CAP_WORDS = "token cap"
CAP_FAILED = ("Audit token cap reached: {used} of {cap} tokens used. Retrying will not help. "
              "Options: turn off the second deck read (PAGE_SECOND_READ=0) or raise the cap.")
RETRY_ACTION = "Press Retry stage — it reads only the missing pages, then calculates the results. Nothing already read is lost."
SKIP_ACTION = ("Press Continue without {pages} to go on; the memo will say {skipped} skipped. "
               "Or remove the deck and upload a version without {that}.")
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


def _reason_by_page(deck: Dict, record: Dict, missing: list) -> Dict:
    """The plain-words reason each missing page is missing for, from the record's unreadable list and the deck's stored page entries (codes only)."""
    never = {u["page"]: u["reason"] for u in record.get("unreadable") or ()}
    last = {}
    for entry in deck.get("page_reads") or []:
        for n in entry.get("pages") or ():
            last[n] = entry
    out = {}
    for p in missing:
        if p in never:
            out[p] = TOKEN_CAP_WORDS if never[p] == CAP else UNREADABLE.get(never[p], never[p])
        elif last.get(p, {}).get("status") == "read":
            out[p] = "second read timed out"
        elif last.get(p, {}).get("reason") == "timeout":
            out[p] = "page read timed out"
        elif last.get(p, {}).get("provider"):
            out[p] = "the model returned an error"
        else:
            out[p] = "page not read"
    return out


def _pages(numbers: list) -> str:
    return f"page {numbers[0]}" if len(numbers) == 1 else f"pages {', '.join(str(n) for n in numbers)}"


def decks_gate(decks: list) -> Dict:
    """Whether the deck claims are done, from the decks' documents (`ai_status`, `file`, `claims_record`, `page_overrides`, `page_reads`).
    state "reading": a deck is still being read; "incomplete": a deck's record has pages missing that the analyst has not continued without;
    else "clear". `incomplete` lists [{"deck_id", "file", "missing", "expected", "can_continue", "reasons", "capped", "cap"}] (`can_continue`: the missing
    pages that can never be read, with a plain reason; `reasons`: {page: plain reason} of every missing page; `capped`: the pages the token cap refused,
    which cannot be continued without; `cap`: {"used", "cap"} then), `pages` is the pages with figures over all decks, `reads` the reads per page (1 or 2),
    `skipped` the pages continued without that are still missing ([{"deck_id", "file", "page", "reason"}]).
    A deck no page reader applies to (consent off, a model off the list, no prompt) or one read before the record existed has no record and
    stands as the status line says; its message is the stage's own."""
    reading = any(d.get("ai_status") == "reading" for d in decks)
    records = [(d, d.get("claims_record")) for d in decks if d.get("claims_record") and d.get("ai_status") not in ("blocked", "prompt_missing", "python_only")]
    incomplete, skipped = [], []
    for d, r in records:
        overrides = d.get("page_overrides") or []
        missing = still_missing(r, overrides)
        never = {u["page"]: u["reason"] for u in r.get("unreadable") or () if u["reason"] != CAP}
        capped = [u["page"] for u in r.get("unreadable") or () if u["reason"] == CAP and u["page"] in missing]
        if missing:
            incomplete.append({"deck_id": d.get("deck_id"), "file": d.get("file"), "missing": len(missing), "expected": len(r.get("expected") or ()),
                               "can_continue": [{"page": p, "reason": UNREADABLE.get(never[p], never[p])} for p in missing if p in never],
                               "reasons": _reason_by_page(d, r, missing), "capped": capped, "cap": r.get("cap") if capped else None})
        skipped += [{"deck_id": d.get("deck_id"), "file": d.get("file"), "page": o["page"], "reason": UNREADABLE.get(o.get("reason"), o.get("reason") or "unreadable")}
                    for o in overrides if o.get("page") in (r.get("missing") or ())]
    pages = sum(len(r.get("expected") or ()) for _, r in records)
    return {"state": "reading" if reading else "incomplete" if incomplete else "clear", "incomplete": incomplete, "pages": pages, "skipped": skipped,
            "reads": 2 if any(r.get("second_required") for _, r in records) else 1, "decks_with_figures": [d.get("file") for d, r in records if r.get("expected")]}


def pages_summary(decks: list) -> str:
    """The log's account of the decks' claims: per deck id, pages read in the first and the second read over the pages with figures. Counts only."""
    out = []
    for d in decks:
        r = d.get("claims_record")
        if r:
            out.append(f"{d.get('deck_id')}:first={len(r.get('first') or ())}/{len(r.get('expected') or ())},second={len(r.get('second') or ())}/{len(r.get('first') or ())}")
    return ";".join(out) or "-"


def claims_failure(gate: Dict) -> Dict:
    """The claims stage's failure for an incomplete gate: {"message", "retryable"}. Each deck is named with its count ("5 of 19 pages") and the reason in
    plain words, then the action in one sentence: Retry stage for a page a read can still get, Continue without page N for a page that can never be read.
    A page the token cap refused is not retryable: the message says so and names the options (combined fixes, 2026-11-05)."""
    capped = [i for i in gate["incomplete"] if i["capped"]]
    if capped:
        cap = next(i["cap"] for i in capped if i["cap"]) if any(i["cap"] for i in capped) else {"used": 0, "cap": 0}
        return {"message": CAP_FAILED.format(used=fmt_count(cap["used"]), cap=fmt_count(cap["cap"])), "retryable": False}
    parts, retry, skip = [], False, []
    for i in gate["incomplete"]:
        by_reason, never = {}, {c["page"] for c in i["can_continue"]}
        for p, why in sorted(i["reasons"].items()):
            by_reason.setdefault(why, []).append(p)
            retry = retry or p not in never
        skip += [p for p in sorted(never)]
        counted = f"{i['missing']} of {i['expected']} pages are missing" if i["missing"] != 1 else f"1 of {i['expected']} pages is missing"
        why = "; ".join(f"{w} on {_pages(ps)}" if w in ("second read timed out", "page read timed out", "page not read", "the model returned an error")
                        else f"{_pages(ps)} {w}" for w, ps in by_reason.items())
        parts.append(f"{i['file']}: {counted}: {why}.")
    if retry:
        parts.append(RETRY_ACTION)
    if skip:
        skip = sorted(set(skip))
        named = ", ".join(str(n) for n in skip)
        parts.append(SKIP_ACTION.format(pages=f"page {named}" if len(skip) == 1 else f"pages {named}", skipped="the page was" if len(skip) == 1 else "the pages were",
                                        that="that page" if len(skip) == 1 else "those pages"))
    return {"message": " ".join(parts), "retryable": True}


def incomplete_message(gate: Dict) -> str:
    """The claims-stage failure's text (`claims_failure`)."""
    return claims_failure(gate)["message"]


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
