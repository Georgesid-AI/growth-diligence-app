"""The top 5, the verdict, the key gates, the ratings and the data gaps (docs/design/simplified-flow.md, method A9, A10).

A pure module: it reads register rows (app.claim_matching), `audits.results` and the analyst's inputs, and returns
dicts. It imports nothing from `app.llm`, calls no model and writes nothing. The top 5 is selected by the app (value at stake, then
normalised shortfall) and is in force without a confirmation; the verdict is always computed; the ratings
are computed from the integrity checks and the metrics (CLAUDE.md rules 14, 17, 18).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from app import claim_matching as cm
from app.decks import claims as deck_claims

TOP_N = 5
MAX_KEY_GATES = 5
MIN_KEY_GATES = 3
RATINGS = ("Strong", "Adequate", "Weak")
RATED_ROWS = ("data_reliability", "growth_engine")
THESIS_PARTS = ("plan", "evidence", "condition")
THESIS_MAX = 300
NOTE_MAX = 1000
UNVERIFIED_LABELS = ("Unverified", "Inconclusive", "Unsupported")    # Inconclusive counts with Unverified (evidence-labels.md section 4)

# Screen wording (verdict-and-memo.md section 11), as approved and as the simplified flow leaves it.
W12_NO_KEY_GATES = "No key gates: every selected claim is Verified."
W13_DEAL_TERMS = "Deal terms: not available – the execution capacity review has not been run."
W25_FEW_GATES = "{n} gates set; all are key gates."
W7_AFTER_REVIEW = "The target date must be on or before the first quarterly review ({date})."
W7_REVIEW_FIRST = "Set the first quarterly review first."
W7_REVIEW_BEFORE_GAP = "The first quarterly review cannot be before a gap's target date ({date})."
W10_NO_CLAIMS = "No testable claims found. Upload a deck or plan with revenue targets."
W10_NOT_COMPUTED = "No conclusion: compute the audit first."
SELECTION_SENTENCE = "Selected by the app by value at stake; the analyst may change the selection"
SELECTION_CHANGED = "Top 5 changed by the analyst — reset"
NOT_RATED = "not rated – data missing"
BENCHMARK = "benchmark, not company data"
DEFINITION_CONFIRMED = "Same metric and period confirmed by the analyst."
GATE_TAGS = {cm.GATE_PROPOSED: "(proposed)", cm.GATE_SET: "(set by the analyst)"}

# docs/specs/claim-review-conclusion.md: the outcome describes the five selected claims, never a recommendation.
HEADING = "Claim-review conclusion — assessment of the five selected claims"
SCOPE_SENTENCE = "This assesses the five claims selected by the app by value at stake; the analyst may change the selection. It is not an investment recommendation."
OUTCOMES = {"not_supported": "Selected claims not supported", "insufficient": "Insufficient evidence",
            "supported": "Selected claims supported", "partly_supported": "Selected claims partly supported"}
INSUFFICIENT_UNTESTED = 3               # this many untested selected claims, with none Contradicted, is insufficient evidence
RULE_CONTRADICTED = "{n} selected {claim} Contradicted."
RULE_INSUFFICIENT = "No selected claim is Contradicted; {u} of {n} are untested (Unverified, Inconclusive or Unsupported)."
RULE_SUPPORTED = "All {n} selected claims are Verified."
RULE_PARTLY = "No selected claim is Contradicted; {v} of {n} are Verified, {u} untested."
NO_OTHER_CONTRADICTIONS = "None found among tested claims."
OPEN_QUESTION = "{n} question open."
OPEN_QUESTIONS = "{n} questions open."

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_date(value: Optional[str]) -> bool:
    if not isinstance(value, str) or not _ISO.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


REVIEW_DEFAULT_DAYS = 90


def default_review(created_at: Optional[str]) -> Optional[str]:
    """The first quarterly review when the analyst has not set one: the audit's creation date plus 90 days (an audit-set-up field)."""
    try:
        return (datetime.fromisoformat(str(created_at)).date() + timedelta(days=REVIEW_DEFAULT_DAYS)).isoformat()
    except ValueError:
        return None


def with_review(audit: dict, ic: Optional[dict]) -> dict:
    """The analyst's inputs with the first quarterly review always present: the stored date, else the default."""
    ic = dict(ic or {})
    if not ic.get("first_quarterly_review"):
        default = default_review(audit.get("created_at"))
        if default:
            ic["first_quarterly_review"] = default
    return ic


# --- claim wording --------------------------------------------------------------------------------------------------------

def _type_words(claim_type) -> str:
    """"Ltv cac" for a stored word; the five recurring types by their label ("CAC payback", "NRR")."""
    return deck_claims.TYPE_NAMES.get(claim_type) or str(claim_type or "claim").replace("_", " ").capitalize()


claim_name = cm.claim_name


def claimed_text(row: dict, reporting_currency: Optional[str] = None) -> str:
    """The claimed figure as the register words it: in a currency other than the audit's, both figures; a direction with no
    figure as such (claim-matching.md section 2)."""
    text = cm._claimed_text({"unit": row.get("unit"), "currency": row.get("currency"), "claim_direction": row.get("claim_direction"),
                             "value": row.get("claimed_value"), "value_high": row.get("claimed_high")})
    return text + cm.converted_note(row, lambda v: cm._money(v, reporting_currency))


def observed_text(row: dict, reporting_currency: Optional[str]) -> str:
    spec = cm.METRICS.get(row.get("metric") or "")
    return cm.format_figure(spec["unit"] if spec else None, row["observed_value"], reporting_currency)


def ranks_text(rows: List[dict]) -> str:
    return ", ".join(f"#{r['rank']}" for r in rows)


MISSING_PREFIX = "Missing:"        # the reason of a claim whose metric the supplied files cannot give (claim_matching `Missing: {unlock}`)
NO_FIGURE_IN_FILES = "No figure in the supplied files."


def reason_text(row: dict, reporting_currency: Optional[str]) -> str:
    """One reason of the verdict, citing its evidence (W11)."""
    head = f"#{row['rank']} {claim_name(row)}: {row['evidence_label'] or 'Definition check open'}"
    if row.get("observed_value") is None:
        text = f"{head}, {row['reason']}."
        return f"{text} {NO_FIGURE_IN_FILES}" if str(row["reason"]).startswith(MISSING_PREFIX) else text
    gap = f" ({row['gloss']})" if row.get("gloss") else ""
    text = f"{head}, {observed_text(row, reporting_currency)} against {claimed_text(row, reporting_currency)}{gap}."
    src = row.get("observed_source") or {}
    if row.get("evidence_analysis") and row.get("observed_citation"):      # issue #136: source key, sheet, rows and the period
        text += f" Evidence: {row['evidence_analysis']} {row['observed_citation']}."
    elif row.get("evidence_analysis") and src:
        text += f" Evidence: {row['evidence_analysis']} · {row['evidence_source_key']} ({src.get('file')} · {src.get('sheet')} · {src.get('rows')})."
    return text


def flagged_rows(rows: List[dict], listed: Iterable[str] = ()) -> List[dict]:
    """The register rows Worth flagging names, by rank: every Verified beat outside tolerance, and every row whose Definition check
    the analyst answered Yes (claim-matching.md section 4.1), except the ones already `listed` (by the banner)."""
    skip = set(listed)
    return [r for r in rows if r["claim_id"] not in skip and (cm.is_beat(r) or r.get("definition_check") == "yes")]


def flag_text(row: dict) -> str:
    """A row of `flagged_rows` with its label and gloss: "#14 Customer count, Feb 2024: Verified, 1 customer more (beat)."; a confirmed
    definition says so after it. The gloss is the register's own text, so the memo's number check reads its figures as stored."""
    text = f"#{row['rank']} {claim_name(row)}: {row['evidence_label']}, {row['gloss']}."
    return f"{text} {DEFINITION_CONFIRMED}" if row.get("definition_check") == "yes" else text


# --- gates ----------------------------------------------------------------------------------------------------------------

def key_gates(rows: List[dict], five_ids: Iterable[str]) -> dict:
    """The key gates (simplified-flow.md section 3): the gates of the non-Verified rows of the five in force, never padded; a Verified row has
    none and a gate outside the five is not promoted. Fewer than 3 prints W25; none, W12. `all_key` is true below 3."""
    five = set(five_ids)
    gates = [r for r in rows if r["claim_id"] in five and r.get("gate_sentence")]
    gates.sort(key=lambda r: r["rank"])
    if not gates:
        note = W12_NO_KEY_GATES
    else:
        note = W25_FEW_GATES.format(n=len(gates)) if len(gates) < MIN_KEY_GATES else None
    return {"saved": len(gates), "marked": [r["claim_id"] for r in gates], "gates": gates, "all_key": len(gates) < MIN_KEY_GATES,
            "note": note, "ok": True}


def mark_key_gates(rows: List[dict], five_ids: Iterable[str]) -> List[dict]:
    """The rows with `key_gate` set on the gates of the five in force (the register, the CSV and the memo read it)."""
    keys = set(key_gates(rows, five_ids)["marked"])
    return [{**r, "key_gate": r["claim_id"] in keys} for r in rows]


def gate_text(row: dict) -> str:
    """A gate sentence with its status: "(proposed)" until the analyst edits it, then "(set by the analyst)"."""
    tag = GATE_TAGS.get(row.get("gate_status"))
    return f"{row['gate_sentence']} {tag}" if tag and row.get("gate_sentence") else row.get("gate_sentence") or ""


def budget_decisions(rows: List[dict]) -> List[str]:
    """The budget decisions already saved in this audit, once each, in order of first use: the dropdown's list ("Other" follows). The
    field is optional and never required (simplified-flow.md)."""
    seen: List[str] = []
    for row in rows:
        text = row.get("gate_budget_decision")
        if text and text not in seen:
            seen.append(text)
    return seen


# --- the top 5 ------------------------------------------------------------------------------------------------------------

def sortable(rows: List[dict]) -> List[dict]:
    """The rows the top 5 is taken from: a use-of-funds row (an allocation share of the raise), an acquisition-channels row (a count per
    platform) or a claim read from a forecast table (chat-upload.md section 20) is never one of them."""
    return [r for r in rows if not cm.is_untested(r)]


# George, 2026-10-24: the selection leaves out claims about the market, prices, the use of funds, people and the product; it takes the testable
# plan claims first. George, 2026-10-25 (simplified-flow.md section 3): the app selects the five by value at stake, then normalised shortfall;
# the set is in force without a confirmation. Every Contradicted claim is shown in the contradiction lines, so the ranking needs no label.
PROPOSAL_EXCLUDED = ("market", "pricing", "use_of_funds", "other", "people", "product")
PLAN_TYPES = ("revenue", "arr", "mrr", "churn", "nrr", "revenue_growth", "sales", "customers")


def selection_key(r: dict) -> tuple:
    """A plan claim before any other; then value at stake (a claim with none after those with one), the normalised
    shortfall, the claimed amount; the register rank breaks a tie."""
    amount = abs(r["claimed_converted"] if r.get("claimed_converted") is not None else r.get("claimed_value") or 0)
    vas = r.get("value_at_stake_arr")
    return (r.get("claim_type") not in PLAN_TYPES, vas is None, -(vas or 0),
            -(r.get("shortfall") or 0), -amount, r.get("rank") or 0)


def proposal(rows: List[dict]) -> List[str]:
    """The five the app selects: min(5, rows) claims of the register, in the order of `selection_key`."""
    eligible = [r for r in sortable(rows) if r.get("claim_type") not in PROPOSAL_EXCLUDED]
    return [r["claim_id"] for r in sorted(eligible, key=selection_key)[:TOP_N]]


def banner_ids(rows: List[dict], stored: Optional[dict] = None) -> List[str]:
    """The banner (CLAUDE.md rule 21) reads the five in force: the app's selection, or the set the analyst changed. A Contradicted claim
    that leaves the five stays in the contradiction lines ("Other contradictions")."""
    return top5_state(rows, stored)["in_force"]


def top5_state(rows: List[dict], stored: Optional[dict]) -> dict:
    """The top 5 in force: the analyst's changed set when it is stored, differs from the app's selection and still holds min(5, rows) claims
    of the register; otherwise the app's selection (a stored set that no longer fits is dropped, a stored set equal to the selection is the
    selection). `changed` says the analyst's set is in force. No confirmation exists."""
    proposed = proposal(rows)
    rows = sortable(rows)
    present = {r["claim_id"] for r in rows}
    ids = list((stored or {}).get("claim_ids") or [])
    fits = bool(ids) and set(ids) <= present and len(ids) == min(TOP_N, len(rows))
    changed = fits and set(ids) != set(proposed)
    rank = {r["claim_id"]: r["rank"] for r in rows}
    ids = sorted(ids, key=lambda i: rank.get(i, 10 ** 9)) if changed else []
    return {"proposed": proposed, "changed": changed, "claim_ids": ids, "set_at": (stored or {}).get("set_at") if changed else None,
            "in_force": ids if changed else proposed}


def check_top5(rows: List[dict], ids: List[str]) -> None:
    """Refuse a set that is not min(5, rows) distinct register claims (use of funds and acquisition channels are none of them)."""
    rows = sortable(rows)
    if len(set(ids)) != len(ids) or len(ids) != min(TOP_N, len(rows)) or not set(ids) <= {r["claim_id"] for r in rows}:
        raise ValueError(f"The top 5 holds {min(TOP_N, len(rows))} different claims of the register")


# --- the verdict ----------------------------------------------------------------------------------------------------------

def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _source_text(row: dict) -> str:
    """Where a contradiction's figures come from: the analysis, the figure's citation (source key, sheet, rows, period; issue #136) and
    its file, then the deck and its page. A row with no citation names analysis · source key · file · sheet · rows."""
    src = row.get("observed_source") or {}
    parts = [row.get("evidence_analysis"), row.get("observed_citation"), src.get("file")] if row.get("observed_citation") else \
        [row.get("evidence_analysis"), row.get("evidence_source_key"), src.get("file"), src.get("sheet"), src.get("rows")]
    deck = " ".join(str(x) for x in (row.get("deck_file"), row.get("page_ref")) if x)
    return " · ".join(str(p) for p in parts + [deck] if p)


def other_contradictions(rows: List[dict], five_ids: Iterable[str]) -> List[dict]:
    """Every Contradicted register row outside the five, by rank, with its metric, its gap and its source (claim-review-conclusion.md
    section 3)."""
    five = set(five_ids)
    return [{"claim_id": r["claim_id"], "rank": r["rank"], "metric": claim_name(r), "gap": r.get("gloss"), "source": _source_text(r)}
            for r in rows if r["evidence_label"] == "Contradicted" and r["claim_id"] not in five]


def verdict(rows: List[dict], results: Optional[dict], stored_top5: Optional[dict], open_questions: int = 0) -> dict:
    """The claim-review conclusion of the five in force (claim-review-conclusion.md, simplified-flow.md): always computed, never blocked.
    `status`: no_verdict (nothing computed, or no testable claim) or ok. An open question is a count on the explanation line
    (`open_questions`: the claim questions the Audit page lists), not a state; a row with an open Definition check counts as untested."""
    state = top5_state(rows, stored_top5)
    rows = sortable(rows)
    reporting = (results or {}).get("reporting_currency")
    others = other_contradictions(rows, state["in_force"]) if results else []
    base = {"top5": state, "outcome": None, "outcome_code": None, "rule": None, "message": None, "five": [],
            "reasons": [], "fewer": None, "heading": HEADING, "scope_sentence": SCOPE_SENTENCE, "other_contradictions": others,
            "other_contradictions_text": None if others else NO_OTHER_CONTRADICTIONS, "open_questions": open_questions}
    if not results:
        return {**base, "status": "no_verdict", "message": W10_NOT_COMPUTED}
    if not rows:
        return {**base, "status": "no_verdict", "message": W10_NO_CLAIMS}
    by_id = {r["claim_id"]: r for r in rows}
    five = [by_id[i] for i in state["in_force"]]
    summary = [{"claim_id": r["claim_id"], "rank": r["rank"], "claim": claim_name(r), "evidence_label": r["evidence_label"],
                "reason": r["reason"], "definition_check": r.get("definition_check")} for r in five]
    # In this order: Contradicted, Insufficient evidence, Supported, Partly supported. A beat is Verified; a row with an open
    # Definition check has no label yet and counts as untested.
    n = len(five)
    contradicted = [r for r in five if r["evidence_label"] == "Contradicted"]
    untested = [r for r in five if r["evidence_label"] in UNVERIFIED_LABELS or r["evidence_label"] is None]
    verified = [r for r in five if r["evidence_label"] == "Verified"]
    if contradicted:
        code, lead = "not_supported", contradicted
        rule = RULE_CONTRADICTED.format(n=len(contradicted), claim=_plural(len(contradicted), "claim is", "claims are"))
    elif len(untested) >= INSUFFICIENT_UNTESTED:
        code, lead, rule = "insufficient", untested, RULE_INSUFFICIENT.format(u=len(untested), n=n)
    elif len(verified) == n:
        code, lead, rule = "supported", verified, RULE_SUPPORTED.format(n=n)
    else:
        code, lead, rule = "partly_supported", untested, RULE_PARTLY.format(v=len(verified), n=n, u=len(untested))
    if open_questions:
        rule = f"{rule} {(OPEN_QUESTION if open_questions == 1 else OPEN_QUESTIONS).format(n=open_questions)}"
    fewer = None
    if len(rows) < TOP_N:
        fewer = f"Top {len(rows)} (the register has {len(rows)} claims)."
        rule = f"{rule} {fewer}"
    ordered = lead + [r for r in five if r not in lead]
    return {**base, "status": "ok", "outcome": OUTCOMES[code], "outcome_code": code, "rule": rule, "fewer": fewer,
            "five": summary, "reasons": [reason_text(r, reporting) for r in ordered[:3]]}


# --- data gaps (section 4) -------------------------------------------------------------------------------------------------

# Missing Data items that name an analysis: (metric prefix, the Dashboard analysis it blocks). Row-quality items, settings and
# calculation errors are fixes for the analyst and stay in the Missing Data card.
GAP_ANALYSES: Tuple[Tuple[str, str], ...] = (
    ("ARR / MRR", "Monthly MRR by Segment"),
    ("NRR (12-month)", "NRR"),
    ("NRR by segment", "NRR by Segment"),
    ("Gross revenue churn", "Gross revenue churn"),
    ("CAC payback", "CAC Payback by Quarter"),
    ("Sales cycle & win rate", "Sales cycle and Win rate"),
    ("Sales cycle by segment", "Sales Cycle by Segment"),
    ("Sales cycle", "Sales cycle"),
    ("Win rate by founder involvement", "Win Rate by Founder Involvement"),
    ("Required vs observed net-new customers", "Path to Plan"),
    ("Observed net-new customers", "Path to Plan"),
    ("Segment paths to target ARR", "Segment paths to target ARR"),
)
CALCULATION_ERROR = "(calculation error)"

# The gaps that growth_engine.ANALYSIS_NEEDS does not cover (the engine's V6 pass tests those six against every upload). Each needs
# fields that exactly one upload type carries, so no other upload could answer it; a test pins this against FIELD_DEFS.
SINGLE_TYPE_NEEDS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "ARR / MRR": ("revenue", ("customer_id", "invoice_date", "amount", "currency")),
    "NRR by segment": ("revenue", ("customer_id", "segment")),
    "Sales cycle by segment": ("crm", ("created_date", "close_date", "segment")),
    "Required vs observed net-new customers": ("revenue", ("customer_id", "invoice_date")),
    "Observed net-new customers": ("revenue", ("customer_id", "invoice_date")),
    "Segment paths to target ARR": ("revenue", ("customer_id", "segment")),
}


def _gap_analysis(metric: str) -> Optional[str]:
    if CALCULATION_ERROR in metric:
        return None
    return next((analysis for prefix, analysis in GAP_ANALYSES if metric.startswith(prefix)), None)


def is_gap(item: dict) -> bool:
    return item.get("status") == "Missing" and _gap_analysis(str(item.get("metric") or "")) is not None


def data_gaps(results: Optional[dict], rows: List[dict], top5_ids: List[str], target_dates: Optional[dict] = None) -> List[dict]:
    """What the company cannot measure: one row per Missing Data item that names an analysis, ordered by the top-5 claims it
    blocks, then all register claims it blocks, then engine order."""
    target_dates = target_dates or {}
    top = set(top5_ids)
    out = []
    for index, item in enumerate((results or {}).get("missing_data") or ()):
        if not is_gap(item):
            continue
        metric = str(item["metric"])
        blocked = [r for r in rows if r.get("evidence_source_key") == cm.MISSING_KEY and r.get("evidence_analysis") == metric]
        analysis = _gap_analysis(metric)
        claims = "; claims " + ranks_text(blocked) if blocked else ""
        reason = str(item.get("reason") or "").strip()
        reason = reason if not reason or reason[-1] in ".!?" else reason + "."
        out.append({"item": metric, "analysis": analysis, "claims": [r["claim_id"] for r in blocked],
                    "ranks": [r["rank"] for r in blocked], "blocks_top5": sum(1 for r in blocked if r["claim_id"] in top),
                    "why": f"Blocks {analysis}{claims}. {reason}".rstrip(),
                    "requested": item.get("unlocked_by"), "target_date": target_dates.get(metric), "index": index})
    out.sort(key=lambda g: (-g["blocks_top5"], -len(g["claims"]), g["index"]))
    return out


NOT_MEASURED_REASON = "not tested against data"


def unmeasured_claims(rows: List[dict]) -> List[dict]:
    """The register rows that are never tested (use of funds, acquisition channels, pricing, unit economics, pipeline, best and worst cases,
    forecast-file figures), each with the reason it cannot be measured: the memo's Data gaps table lists them (simplified-flow.md section 3)."""
    return [{"claim_id": r["claim_id"], "rank": r["rank"], "item": f"#{r['rank']} {claim_name(r)}",
             "why": str(r.get("reason") or NOT_MEASURED_REASON).rstrip(".") + "."} for r in rows if cm.is_untested(r)]


def top_gaps(gaps: List[dict]) -> List[dict]:
    return gaps[:3]


def other_requests(results: Optional[dict]) -> List[dict]:
    """Missing Data items that are not gaps (row quality, settings, calculation errors), each with what unlocks it."""
    return [{"item": str(i.get("metric")), "reason": i.get("reason"), "requested": i.get("unlocked_by")}
            for i in (results or {}).get("missing_data") or () if not is_gap(i)]


def management_questions(results: Optional[dict]) -> List[str]:
    """V6 requests: an item the engine computed from another file is a question for management, not a gap."""
    return [str(q.get("question")) for q in (results or {}).get("questions_for_management") or () if q.get("question")]


# --- the analyst's inputs (audits.ic_inputs) ------------------------------------------------------------------------------------

def apply_ic_inputs(current: Optional[dict], changes: dict, rows: List[dict], gaps: List[dict], now: str) -> dict:
    """The stored inputs after a PUT. A key sent as null clears it; a key not sent stays. Raises ValueError with the
    wording of W7 for a date that breaks the order of the review and the gap dates."""
    ic = {k: (dict(v) if isinstance(v, dict) else v) for k, v in (current or {}).items()}
    if "top5" in changes:
        if changes["top5"] is None:
            ic.pop("top5", None)
        else:
            ids = list(changes["top5"])
            check_top5(rows, ids)
            rank = {r["claim_id"]: r["rank"] for r in rows}
            ic["top5"] = {"claim_ids": sorted(ids, key=rank.get), "set_at": now}
    if "thesis" in changes:
        merged = {**ic.get("thesis", {}), **(changes["thesis"] or {})}
        ic["thesis"] = {k: v.strip() for k, v in merged.items() if isinstance(v, str) and v.strip()}
    if "note" in changes:
        text = (changes["note"] or "").strip()
        if text:
            ic["note"] = text
        else:
            ic.pop("note", None)
    if "first_quarterly_review" in changes:
        if changes["first_quarterly_review"] is None:
            ic.pop("first_quarterly_review", None)
        else:
            ic["first_quarterly_review"] = changes["first_quarterly_review"]
    if "gap_target_dates" in changes:
        merged = {**ic.get("gap_target_dates", {}), **(changes["gap_target_dates"] or {})}
        ic["gap_target_dates"] = {k: v for k, v in merged.items() if v is not None}
    known = {g["item"] for g in gaps}
    dates = {k: v for k, v in (ic.get("gap_target_dates") or {}).items() if k in known}
    review = ic.get("first_quarterly_review")
    if "gap_target_dates" in changes and any(k not in known for k in (changes["gap_target_dates"] or {})):
        raise ValueError("Choose a data gap of the list")
    if dates and not review:
        raise ValueError(W7_REVIEW_FIRST)
    if review:
        late = [d for d in dates.values() if d > review]
        if late and "gap_target_dates" in changes:
            raise ValueError(W7_AFTER_REVIEW.format(date=review))
        if late:
            raise ValueError(W7_REVIEW_BEFORE_GAP.format(date=max(late)))
    return ic


# --- the ratings (simplified-flow.md section 3) ---------------------------------------------------------------------------------

# The Dashboard's own colours: green = NRR at least 100%, gross churn at most 8%, payback at most 12 months; red = churn above 15% or payback
# above 18 months. NRR has no red. These are industry thresholds, not company data.
NRR_GREEN, CHURN_GREEN, CHURN_RED, PAYBACK_GREEN, PAYBACK_RED = 1.0, 0.08, 0.15, 12, 18
RELIABILITY_RULES = {"reliable": ("Strong", "every completed check Green, {x} of {y} completed"),
                     "needs_clarification": ("Adequate", "no check Red, not every completed check Green, {x} of {y} completed"),
                     "material_concerns": ("Weak", "at least one check Red, {x} of {y} completed")}


def cac_headline_months(results: dict) -> Optional[float]:
    """The headline CAC payback in months, as the Dashboard picks it: the stored headline quarter, else the latest complete quarter with a
    computable payback (default lag)."""
    cp = (results or {}).get("cac_payback")
    if not cp:
        return None
    lag = f"L{cp.get('default_l', 1)}"
    quarters = cp.get("quarters") or {}
    computable = lambda q: (quarters[q].get(lag) or {}).get("months") is not None            # noqa: E731
    if "headline_quarter" in cp:
        picked = cp["headline_quarter"]
    else:
        picked = next((q for q in sorted(quarters, reverse=True) if quarters[q].get("partial") is not True and computable(q)), None)
    return quarters[picked][lag]["months"] if picked and picked in quarters and computable(picked) else None


def rate_reliability(integrity: Optional[dict]) -> dict:
    """Data reliability from the integrity conclusion: Reliable is Strong, Needs clarification Adequate, Material concerns Weak, Insufficient
    assessment coverage not rated."""
    integrity = integrity or {}
    code = integrity.get("code")
    if code in RELIABILITY_RULES:
        rating, rule = RELIABILITY_RULES[code]
        return {"rating": rating, "line": f"{rating} ({integrity['conclusion']}; {integrity['completed']} of {integrity['applicable']} checks)",
                "rule": f"{rating}: " + rule.format(x=integrity["completed"], y=integrity["applicable"]), "benchmark": False, "missing": []}
    return {"rating": None, "line": NOT_RATED, "benchmark": False, "missing": ["integrity checks"],
            "rule": f"{NOT_RATED}: {integrity.get('completed', 0)} of {integrity.get('applicable', 0)} integrity checks completed"}


def rate_growth(results: Optional[dict], fmt_pct, fmt_months) -> dict:
    """Growth engine from NRR, gross revenue churn and CAC payback. NRR or churn absent: not rated. Weak when churn or payback is red;
    Strong only when all three inputs are present and green; Adequate otherwise. The label "benchmark, not company data" goes with it."""
    results = results or {}
    nrr, churn = (results.get("nrr") or {}).get("overall_pct"), (results.get("gross_churn") or {}).get("overall_pct")
    months = cac_headline_months(results)
    missing = [name for name, v in (("NRR", nrr), ("gross revenue churn", churn)) if v is None]
    if missing:
        return {"rating": None, "line": NOT_RATED, "benchmark": True, "missing": missing,
                "rule": f"{NOT_RATED}: {', '.join(missing)} not computed"}
    figures = f"NRR {fmt_pct(nrr)}, gross churn {fmt_pct(churn)}, CAC payback " + (fmt_months(months) if months is not None else "not computed")
    red = churn > CHURN_RED or (months is not None and months > PAYBACK_RED)
    green = nrr >= NRR_GREEN and churn <= CHURN_GREEN and months is not None and months <= PAYBACK_GREEN
    rating = "Weak" if red else "Strong" if green else "Adequate"
    return {"rating": rating, "line": f"{rating} ({figures})", "rule": f"{rating}: {figures}", "benchmark": True, "missing": []}


def ratings(results: Optional[dict], integrity: Optional[dict], fmt_pct, fmt_months) -> dict:
    return {"data_reliability": rate_reliability(integrity), "growth_engine": rate_growth(results, fmt_pct, fmt_months)}


# --- the computed Reasons and Unresolved questions, and the thesis draft -------------------------------------------------------

UNRESOLVED_SHOWN = 5
OPEN_CARDS = "{n} claim {noun} open on the Audit page."


def unresolved_questions(gaps: List[dict], open_cards: int, integrity: Optional[dict], results: Optional[dict]) -> List[str]:
    """One list, in this order: the top data gaps, the open claim questions, the integrity checks that were Blocked, the questions for
    management (simplified-flow.md section 3). Texts only; the memo prints five and counts the rest."""
    out = [f"{g['item']}: {g['why']}" for g in top_gaps(gaps)]
    if open_cards:
        out.append(OPEN_CARDS.format(n=open_cards, noun="question" if open_cards == 1 else "questions"))
    out += [f"{b}: not assessed" for b in (integrity or {}).get("blocked") or ()]
    out += management_questions(results)
    return out


def default_thesis(audit: dict, ver: dict, key: dict, currency_text) -> Dict[str, str]:
    """The three-sentence deal thesis drafted from computed text (simplified-flow.md decision 6): Plan = Target ARR by Target date,
    Evidence = the verdict rule, Condition = the first key gate. The analyst may edit each part."""
    target, day = audit.get("target_arr"), audit.get("target_date")
    plan = f"The plan targets ARR of {currency_text(target)} by {day}." if target and day else "Target ARR and Target date are not set."
    evidence = f"{ver['outcome']}: {ver['rule']}" if ver.get("outcome") else "No conclusion yet."
    gate = key["gates"][0] if key.get("gates") else None
    condition = gate_text(gate) if gate else "No condition: every selected claim is Verified."
    return {"plan": plan, "evidence": evidence, "condition": condition}


# --- the baseline CSV (section 5) ----------------------------------------------------------------------------------------------

GAP_COLUMNS = ("gap_item", "gap_why", "gap_requested", "gap_target_date")
CSV_HEADER = ("row_type", *cm.FIELDS, "in_top5", *GAP_COLUMNS, "first_quarterly_review")


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, dict):
        return " · ".join("" if value.get(k) is None else str(value[k]) for k in ("file", "sheet", "rows", "rule"))
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value)


def baseline_csv(rows: List[dict], gaps: List[dict], top5_ids: List[str], first_review: Optional[str]) -> str:
    """One CSV: the register's rows in rank order, then the data gaps. Cells follow claim-matching.md section 7; lists are joined
    by '; '."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_HEADER)
    top = set(top5_ids)
    for r in rows:
        writer.writerow(["claim", *(_cell(r[f]) for f in cm.FIELDS), _cell(r["claim_id"] in top), "", "", "", "",
                         _cell(first_review)])
    for g in gaps:
        writer.writerow(["data_gap", *([""] * len(cm.FIELDS)), "", g["item"], g["why"], g["requested"] or "",
                         g["target_date"] or "", _cell(first_review)])
    return out.getvalue()


def _read(field: str, text: str):
    if text == "":
        return [] if field in cm.LIST_FIELDS else None
    if field in cm.LIST_FIELDS:
        return text.split("; ")
    if field in cm.BOOL_FIELDS:
        return text == "true"
    if field in cm.SOURCE_FIELDS:
        parts = (text.split(" · ", 3) + ["", "", "", ""])[:4]
        return dict(zip(("file", "sheet", "rows", "rule"), (p or None for p in parts)))
    if field in cm.INT_FIELDS:
        return int(text)
    if field in cm.FLOAT_FIELDS:
        return int(text) if re.fullmatch(r"-?\d+", text) else float(text)
    return text


def parse_baseline(text: str) -> Tuple[List[dict], List[dict], Optional[str]]:
    """The baseline read back with each column's type: (register rows with `in_top5`, gap rows, first quarterly review)."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    assert tuple(header) == CSV_HEADER, "not a baseline CSV"
    claims, gaps, review = [], [], None
    for line in reader:
        cells = dict(zip(header, line))
        review = cells["first_quarterly_review"] or review
        if cells["row_type"] == "claim":
            row = {f: _read(f, cells[f]) for f in cm.FIELDS}
            row["in_top5"] = cells["in_top5"] == "true"
            claims.append(row)
        else:
            gaps.append({"item": cells["gap_item"], "why": cells["gap_why"], "requested": cells["gap_requested"] or None,
                         "target_date": cells["gap_target_date"] or None})
    return claims, gaps, review


def rewrite_baseline(claims: List[dict], gaps: List[dict], review: Optional[str]) -> str:
    """Write parsed rows again: the same bytes as the file they were read from."""
    top = [c["claim_id"] for c in claims if c["in_top5"]]
    return baseline_csv([{k: v for k, v in c.items() if k != "in_top5"} for c in claims],
                        [{**g, "why": g["why"]} for g in gaps], top, review)
