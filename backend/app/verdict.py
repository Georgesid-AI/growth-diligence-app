"""Gates, data gaps, the analyst's top 5 and the verdict (docs/specs/verdict-and-memo.md, method A9, A10).

A pure module: it reads register rows (app.claim_matching), `audits.results` and the analyst's inputs, and returns
dicts. It imports nothing from `app.llm`, calls no model and writes nothing. The verdict is a function of the top 5 the
analyst confirms; Python never rates and never proposes a gate (CLAUDE.md rules 14, 17, 18).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app import claim_matching as cm

TOP_N = 5
MAX_KEY_GATES = 5
MIN_KEY_GATES = 3
RATINGS = ("Strong", "Adequate", "Weak")
RATED_ROWS = ("data_reliability", "growth_engine")
THESIS_PARTS = ("plan", "evidence", "condition")
THESIS_MAX = 300
UNVERIFIED_LABELS = ("Unverified", "Unsupported")

# Screen wording W1-W25 (verdict-and-memo.md section 11), as approved.
W4_GATE_NEEDED = "Gate needed"
W5_SIXTH = "At most 5 key gates."
W8_UNDERWRITE = "All top-5 claims are Verified."
W9_BLOCKED = "Verdict blocked: set a gate on {ranks} (top-5 claims that are not Verified)."
W10_NO_CLAIMS = "No verdict: the register has no claims."
W10_NOT_COMPUTED = "No verdict: compute the audit first."
W12_NO_KEY_GATES = "No key gates marked."
W13_DEAL_TERMS = "Deal terms: not available – the execution capacity review has not been run."
W14_OTHER_GATES = "{n} other claims still need a gate."
W23_PROPOSED = "Proposed by shortfall – confirm or replace."
W23_NONE = "No verdict until the top 5 is confirmed."
W23_VOID = "A claim of the confirmed top 5 left the register – confirm the top 5 again."
W23_MEMO = "confirm the top 5."
W24_STATEMENT = "Top 5 set by the analyst pending ARR bridge."
W25_FEW_GATES = "{n} gates set; all are key gates."
W7_AFTER_REVIEW = "The target date must be on or before the first quarterly review ({date})."
W7_REVIEW_FIRST = "Set the first quarterly review first."
W7_REVIEW_BEFORE_GAP = "The first quarterly review cannot be before a gap's target date ({date})."

OUTCOMES = {"replan": "Re-plan", "underwrite": "Underwrite", "underwrite_with_gates": "Underwrite with gates"}

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_date(value: Optional[str]) -> bool:
    if not isinstance(value, str) or not _ISO.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


# --- claim wording --------------------------------------------------------------------------------------------------------

def claim_name(row: dict) -> str:
    """How a register row is called in a sentence: its metric (or claim type), the segment when not the whole company, the period."""
    name = row.get("metric") or str(row.get("claim_type") or "claim").replace("_", " ").capitalize()
    if row.get("segment") not in (None, cm.WHOLE):
        name = f"{name} · {row['segment']}"
    if row.get("period"):
        name = f"{name}, {row['period']}"
    return name


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


def reason_text(row: dict, reporting_currency: Optional[str]) -> str:
    """One reason of the verdict, citing its evidence (W11)."""
    head = f"#{row['rank']} {claim_name(row)}: {row['evidence_label']}"
    if row.get("observed_value") is None:
        text = f"{head}, {row['reason']}."
        return f"{text} No figure in the supplied files." if row["evidence_label"] == "Unsupported" else text
    gap = f" ({row['gloss']})" if row.get("gloss") else ""
    text = f"{head}, {observed_text(row, reporting_currency)} against {claimed_text(row, reporting_currency)}{gap}."
    src = row.get("observed_source") or {}
    if row.get("evidence_analysis") and src:
        text += f" Evidence: {row['evidence_analysis']} · {row['evidence_source_key']} ({src.get('file')} · {src.get('sheet')} · {src.get('rows')})."
    return text


# --- gates ----------------------------------------------------------------------------------------------------------------

def key_gates(rows: List[dict]) -> dict:
    """The key gates of the register (decision Q2). With 3 or more saved gates the analyst's marks decide; with fewer, every saved
    gate counts as key. `ok` is whether the memo may be built: 3 to 5 marked, or fewer than 3 saved."""
    saved = [r for r in rows if r["gate_saved"]]
    marked = [r for r in saved if r["key_gate"]]
    all_key = len(saved) < MIN_KEY_GATES
    effective = saved if all_key else marked
    if all_key:
        note = W25_FEW_GATES.format(n=len(saved)) if saved else W12_NO_KEY_GATES
    else:
        note = None if marked else W12_NO_KEY_GATES
    return {"saved": len(saved), "marked": [r["claim_id"] for r in marked], "gates": effective, "all_key": all_key,
            "note": note, "ok": all_key or MIN_KEY_GATES <= len(marked) <= MAX_KEY_GATES}


def marked_count_after(rows: List[dict], claim_id: str) -> int:
    """Key gates marked, counting this claim as marked."""
    return len({r["claim_id"] for r in rows if r["key_gate"]} | {claim_id})


# --- the top 5 ------------------------------------------------------------------------------------------------------------

def sortable(rows: List[dict]) -> List[dict]:
    """The rows the top 5 is taken from: a use-of-funds row is an allocation share of the raise, never one of them."""
    return [r for r in rows if r.get("claim_type") != "use_of_funds"]


def proposal(rows: List[dict]) -> List[str]:
    """Rows 1 to 5 of the pre-sort, or every row when there are fewer than 5 (decision of 2026-10-08). Use of funds is left out."""
    return [r["claim_id"] for r in sortable(rows)[:TOP_N]]


def banner_ids(rows: List[dict]) -> List[str]:
    """The banner (CLAUDE.md rule 21) keeps rows 1 to 5 of the pre-sort whatever the analyst confirmed."""
    return proposal(rows)


def top5_state(rows: List[dict], stored: Optional[dict]) -> dict:
    """The top 5 in force. Confirmed when the analyst has stored a set that holds min(5, rows) claims, all in the register. Void
    when a stored claim has left the register (or the size no longer fits); a new rank order alone does not void it."""
    proposed = proposal(rows)
    rows = sortable(rows)
    present = {r["claim_id"] for r in rows}
    ids = list((stored or {}).get("claim_ids") or [])
    void = bool(ids) and (not set(ids) <= present or len(ids) != min(TOP_N, len(rows)))
    confirmed = bool(ids) and not void
    rank = {r["claim_id"]: r["rank"] for r in rows}
    ids = sorted(ids, key=lambda i: rank.get(i, 10 ** 9)) if confirmed else []
    return {"proposed": proposed, "confirmed": confirmed, "void": void, "claim_ids": ids,
            "set_at": (stored or {}).get("set_at") if confirmed else None, "in_force": ids if confirmed else proposed}


def check_top5(rows: List[dict], ids: List[str]) -> None:
    """Refuse a set that is not min(5, rows) distinct register claims (use of funds is none of them)."""
    rows = sortable(rows)
    if len(set(ids)) != len(ids) or len(ids) != min(TOP_N, len(rows)) or not set(ids) <= {r["claim_id"] for r in rows}:
        raise ValueError(f"The top 5 holds {min(TOP_N, len(rows))} different claims of the register")


# --- the verdict ----------------------------------------------------------------------------------------------------------

def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def verdict(rows: List[dict], results: Optional[dict], stored_top5: Optional[dict]) -> dict:
    """The verdict of the confirmed top 5 (section 6). `status`: no_verdict (W10), unconfirmed or void (W23), blocked (W9), ok."""
    state = top5_state(rows, stored_top5)
    rows = sortable(rows)
    reporting = (results or {}).get("reporting_currency")
    base = {"top5": state, "outcome": None, "outcome_code": None, "rule": None, "message": None, "blocked": [], "five": [],
            "reasons": [], "fewer": None}
    if not results:
        return {**base, "status": "no_verdict", "message": W10_NOT_COMPUTED}
    if not rows:
        return {**base, "status": "no_verdict", "message": W10_NO_CLAIMS}
    if not state["confirmed"]:
        return {**base, "status": "void" if state["void"] else "unconfirmed",
                "message": W23_VOID if state["void"] else W23_NONE}
    by_id = {r["claim_id"]: r for r in rows}
    five = [by_id[i] for i in state["claim_ids"]]
    summary = [{"claim_id": r["claim_id"], "rank": r["rank"], "claim": claim_name(r), "evidence_label": r["evidence_label"],
                "reason": r["reason"]} for r in five]
    blocked = [r for r in five if r["evidence_label"] != "Verified" and not r["gate_saved"]]
    if blocked:
        return {**base, "status": "blocked", "five": summary, "blocked": [r["claim_id"] for r in blocked],
                "message": W9_BLOCKED.format(ranks=ranks_text(blocked))}

    labels = [r["evidence_label"] for r in five]
    contradicted = [r for r in five if r["evidence_label"] == "Contradicted"]
    unsupported = [r for r in five if r["evidence_label"] == "Unsupported"]
    open_ = [r for r in five if r["evidence_label"] in UNVERIFIED_LABELS]
    if contradicted or len(unsupported) >= 3:
        code, parts = "replan", []
        if contradicted:
            parts.append(f"{len(contradicted)} top-5 {_plural(len(contradicted), 'claim', 'claims')} Contradicted.")
        if len(unsupported) >= 3:
            parts.append(f"{len(unsupported)} top-5 claims Unsupported (3 or more).")
        rule, lead = " ".join(parts), contradicted + unsupported
    elif all(label == "Verified" for label in labels):
        code, rule, lead = "underwrite", W8_UNDERWRITE, [r for r in five if r["evidence_label"] == "Verified"]
    else:
        code, lead = "underwrite_with_gates", open_
        rule = f"No top-5 claim is Contradicted; {len(open_)} {'is' if len(open_) == 1 else 'are'} Unverified or Unsupported."
    fewer = None
    if len(rows) < TOP_N:
        fewer = f"Top {len(rows)} (the register has {len(rows)} claims)."
        rule = f"{rule} {fewer}"
    ordered = lead + [r for r in five if r not in lead]
    return {**base, "status": "ok", "outcome": OUTCOMES[code], "outcome_code": code, "rule": rule, "fewer": fewer,
            "five": summary, "reasons": [reason_text(r, reporting) for r in ordered[:3]]}


def gates_still_needed(rows: List[dict], top5_ids: List[str]) -> int:
    """Rows outside the top 5 that need a gate (W14)."""
    return sum(1 for r in rows if r["gate_needed"] and r["claim_id"] not in set(top5_ids))


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
    if "ratings" in changes:
        merged = {**ic.get("ratings", {}), **(changes["ratings"] or {})}
        ic["ratings"] = {k: v for k, v in merged.items() if v is not None}
    if "thesis" in changes:
        merged = {**ic.get("thesis", {}), **(changes["thesis"] or {})}
        ic["thesis"] = {k: v.strip() for k, v in merged.items() if isinstance(v, str) and v.strip()}
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
