"""Payload builders for the data inventory (A1) and data integrity (A2) narratives.

Both read the stored engine output (`audits.results`, already validated against MetricsPayload by the gateway) and
nothing else: no file content, file name, sheet name, column header or raw cell, no customer or segment name, no row
number. What goes out is the audit's source keys (S1, S2 ...) with the engine's generic description of each file, closed
sentences that carry a count or a status, and figures as finished display strings (app/formatting.py), like every other
step. The builders calculate nothing the engine did not: a count is the length or the `count` of a stored block, and the
reconciliation is read as stored (window total and the months over its own tolerance). A check the engine does not store
reads "not computed" with a closed reason, never an estimate.

Pure functions: no I/O, no Mongo, no model (docs/architecture.md, "Data boundary").
"""
import re
from typing import Any, Dict, List, Optional

from .. import formatting as fmt

STEPS = ("data_inventory", "data_integrity")

# Months of revenue the NRR and gross churn need ("Provide at least 13 months of revenue lines", growth_engine.py);
# tests/test_step_payloads.py fails if the engine's wording moves.
REVENUE_MONTHS_REQUIRED = 13
# The reconciliation window is the last 12 months both files cover (growth_engine.RECONCILIATION_MAX_MONTHS).
PNL_MONTHS_REQUIRED = 12

# Statuses of the inventory. "Not ingested": the app cannot take that file type yet.
PROVIDED, PARTIAL, MISSING, NOT_INGESTED = "Provided", "Partial", "Missing", "Not ingested"

# One source key per file type the app ingests, fixed so a key means the same file in every narrative and in the memo.
SOURCES = {"revenue": ("S1", "revenue by customer file"), "crm": ("S2", "CRM export"), "pnl": ("S3", "P&L file")}

# (id, name the analyst reads, file type) of the evidence categories. Board decks are not engine output: their status comes
# from the number of decks the audit holds (the gateway counts them; no deck text is read), and the row is left out when
# that count is unavailable.
CATEGORIES = (
    ("revenue", "Revenue by customer", "revenue"),
    ("crm", "CRM", "crm"),
    ("pnl", "P&L", "pnl"),
    ("headcount", "Headcount", None),
    ("usage", "Product usage", None),
    ("decks", "Board decks", "decks"),
    ("roadmap", "Roadmap", None),
)
NOT_INGESTED_NAMES = tuple(name for _, name, kind in CATEGORIES if kind is None)

# Engine blocks that need a category's file, named as the dashboard names them.
BLOCKS_BY_CATEGORY = {
    "revenue": (("arr", "ARR"), ("nrr", "NRR"), ("gross_churn", "Gross revenue churn"), ("acv_path", "Path to Plan")),
    "crm": (("sales_cycle", "Sales cycle"), ("win_rate", "Win rate")),
    "pnl": (("cac_payback", "CAC payback"), ("revenue_reconciliation", "Revenue reconciliation")),
}

NOT_COMPUTED = "not computed"
COMPUTED = "computed"
REASONS = {
    "no_pnl": "no P&L was uploaded or it has no revenue column",
    "not_stored": "the engine does not store this check",
    "no_transactions": "the engine stores no transaction-level result",
    "no_anomalies": "the engine could not compute the anomaly flags",
    "no_common_month": "the revenue file and the P&L have no month in common up to the as-of month",
}
DATA_INTEGRITY_VERDICTS = ("Reliable", "Needs clarification", "Material concerns")


def _count(n: Any) -> str:
    return fmt.fmt_count(n)


def _plural(n: int, one: str, many: str) -> str:
    return f"{_count(n)} {one if n == 1 else many}"


def source_list(results: dict) -> List[dict]:
    """The source keys of the files the stored results show to be present, with the engine's generic description."""
    present = _present(results)
    return [{"source_key": key, "description": text} for kind, (key, text) in SOURCES.items() if kind in present]


def _block(results: dict, key: str) -> dict:
    """A stored block, or {} when the engine stored none (null) or something that is not a block."""
    value = results.get(key)
    return value if isinstance(value, dict) else {}


def _present(results: dict) -> set:
    """The file types the stored results show: a block or a series built from the file exists."""
    out = set()
    if _block(results, "mrr_series").get("months") or _block(results, "arr"):
        out.add("revenue")
    if _block(results, "sales_cycle") or _block(results, "win_rate") or _block(results, "anomalies").get("deals_source"):
        out.add("crm")
    if _block(results, "cac_payback") or _block(results, "revenue_reconciliation"):
        out.add("pnl")
    return out


def _months_supplied(kind: str, results: dict) -> Optional[int]:
    if kind == "revenue":
        return len(_block(results, "mrr_series").get("months") or ())
    if kind == "pnl":
        rec = _block(results, "revenue_reconciliation")
        return len(rec.get("by_month") or ()) if rec.get("available") else None
    return None


def _blocked(kind: str, results: dict) -> List[str]:
    out = []
    for key, name in BLOCKS_BY_CATEGORY.get(kind, ()):
        block = results.get(key)
        if not block or (key == "revenue_reconciliation" and not block.get("available")):
            out.append(name)
    if kind == "revenue" and not _block(results, "segment_paths").get("available"):
        out.append("Segment paths")
    return out


def _quality_issues(kind: str, results: dict) -> List[str]:
    a = _block(results, "anomalies")
    if not a:
        return []
    out = []
    order = [d for d in a.get("date_order_from_data") or () if isinstance(d, dict)]
    if kind == "revenue":
        for n, text in ((len(a.get("negative_mrr_months") or ()), "month(s) with negative MRR"),
                        (len(a.get("revenue_gap_then_resume") or ()), "customer(s) whose revenue stops for over two months and resumes"),
                        ((a.get("revenue_missing_customer_id") or {}).get("count") or 0, "revenue line(s) without a customer ID, excluded"),
                        ((a.get("revenue_missing_fx_rate") or {}).get("count") or 0, "revenue line(s) with no exchange rate, excluded"),
                        ((a.get("revenue_missing_amount") or {}).get("count") or 0, "revenue line(s) with a blank amount, excluded")):
            if n:
                out.append(f"{_count(n)} {text}")
    if kind == "crm":
        n = (a.get("deals_close_before_created") or {}).get("excluded_count") or 0
        if n:
            out.append(f"{_count(n)} deal(s) closing before they were created, excluded")
        wr = _block(results, "win_rate")
        for key, text in (("excluded_invalid", "deal(s) with an invalid entry, excluded"),
                          ("excluded_after_as_of", "deal(s) created or closed after the as-of month, excluded")):
            if wr.get(key):
                out.append(f"{_count(wr[key])} {text}")
    n = sum(1 for d in order if d.get("dataset") == kind)
    if n:
        out.append(f"{_count(n)} date column(s) whose day/month order was inferred from the data")
    return out


def _status(kind: str, results: dict, months: Optional[int], blocked: List[str]) -> str:
    if kind not in _present(results):
        return MISSING
    short = kind == "revenue" and (months or 0) < REVENUE_MONTHS_REQUIRED
    short = short or (kind == "pnl" and (months is None or months < PNL_MONTHS_REQUIRED))
    return PARTIAL if blocked or short else PROVIDED


def _deck_row(deck_count: int) -> dict:
    missing = deck_count == 0
    row: Dict[str, Any] = {"category": "Board decks", "status": MISSING if missing else PROVIDED, "in_request_list": missing,
                           "quality_issues": [], "analyses_blocked": ["Claim register"] if missing else []}
    if not missing:
        row["count"] = _count(deck_count)
    return row


def build_inventory(results: dict, deck_count: Optional[int] = None) -> dict:
    """The data-inventory slice: per evidence category its status, months supplied against required, the quality issues
    the engine already detected and the analyses the category blocks. A category that is not ingested is marked so, and
    is not on the data request list."""
    keys = {kind: key for kind, (key, _) in SOURCES.items()}
    rows = []
    for ident, name, kind in CATEGORIES:
        if kind == "decks":
            if deck_count is not None:
                rows.append(_deck_row(deck_count))
            continue
        if kind is None:
            rows.append({"category": name, "status": NOT_INGESTED, "in_request_list": False,
                         "quality_issues": [], "analyses_blocked": []})
            continue
        months = _months_supplied(kind, results)
        blocked = _blocked(kind, results)
        status = _status(kind, results, months, blocked)
        row: Dict[str, Any] = {"category": name, "status": status, "in_request_list": status in (MISSING, PARTIAL),
                               "quality_issues": _quality_issues(kind, results) if status != MISSING else [],
                               "analyses_blocked": blocked}
        if status != MISSING:
            row["source_key"] = keys[kind]
        required = {"revenue": REVENUE_MONTHS_REQUIRED, "pnl": PNL_MONTHS_REQUIRED}.get(kind)
        if months is not None and required:
            row["months_supplied"] = _count(months)
            row["months_required"] = _count(required)
        rows.append(row)
    return {"source_list": source_list(results), "inventory": rows}


def _check(name: str, status: str, **more) -> dict:
    return {"check": name, "status": status, **more}


def _reconciliation(results: dict) -> dict:
    rec = results.get("revenue_reconciliation")
    key = SOURCES["revenue"][0]
    if not isinstance(rec, dict):
        return _check("Revenue file against P&L", NOT_COMPUTED, reason=REASONS["no_pnl"])
    if not rec.get("available"):
        return _check("Revenue file against P&L", NOT_COMPUTED, reason=REASONS["no_common_month"])
    ccy = results.get("reporting_currency")
    tol = rec.get("tolerance_pct")
    over = [m for m in rec.get("by_month") or () if m.get("gap_pct") is not None and tol is not None and abs(m["gap_pct"]) > tol]
    out = _check(
        "Revenue file against P&L", COMPUTED, source_key=key, first_month=rec.get("first"), last_month=rec.get("last"),
        revenue_file_total=fmt.fmt_currency(rec.get("file_total"), ccy), pnl_total=fmt.fmt_currency(rec.get("pnl_total"), ccy),
        gap=fmt.fmt_currency(rec.get("gap"), ccy), gap_pct="—" if rec.get("gap_pct") is None else fmt.fmt_pct(rec["gap_pct"]),
        tolerance=fmt.fmt_pct(tol), window_over_tolerance=bool(rec.get("blocker")),
        months_over_tolerance=[{"month": m["month"], "gap_pct": fmt.fmt_pct(m["gap_pct"])} for m in over])
    return out


def build_integrity(results: dict) -> dict:
    """The data-integrity slice: the stored reconciliation (window total and the months over its tolerance), the stored
    count of revenue lines without a customer ID, and, for every other check, "not computed" or "not ingested" with a
    closed reason. Nothing is calculated here."""
    a = results.get("anomalies")
    if not isinstance(a, dict):
        missing_ids = _check("Revenue lines without a customer ID", NOT_COMPUTED, reason=REASONS["no_anomalies"])
    else:
        missing_ids = _check("Revenue lines without a customer ID", COMPUTED, source_key=SOURCES["revenue"][0],
                             count=_count((a.get("revenue_missing_customer_id") or {}).get("count") or 0))
    checks = [_reconciliation(results), missing_ids]
    checks += [_check(name, NOT_COMPUTED, reason=REASONS[why]) for name, why in (
        ("Cohorts starting mid-period", "not_stored"), ("Quarter-end clustering of deals", "not_stored"),
        ("Month-on-month revenue smoothness", "not_stored"), ("Figures that differ from an approved deck claim", "not_stored"),
        ("Benford test", "no_transactions"))]
    checks.append(_check("Bank data", NOT_INGESTED))
    return {"source_list": source_list(results), "integrity": checks}


def build(step: str, results: dict, deck_count: Optional[int] = None) -> dict:
    if step == "data_inventory":
        return build_inventory(results, deck_count)
    return build_integrity(results)


# --- guards that read the payload the model was sent ----------------------------------------------------------------------

_TIER_CODE = re.compile(r"\btier[\s-]*[0-9a-z]\b|\bT[0-9]\b", re.IGNORECASE)


def tier_code_problem(texts: List[str]) -> Optional[str]:
    """The narrative uses the labels Verified / Unverified / Unsupported / Contradicted, never a tier code."""
    if any(_TIER_CODE.search(t or "") for t in texts):
        return "narrative uses a tier code; only the labels Verified, Unverified, Unsupported and Contradicted are allowed"
    return None


def request_list_problem(payload: Any, next_actions: List[str]) -> Optional[str]:
    """A category the app cannot ingest is not on the data request list."""
    rows = ((payload.get("metrics") or {}).get("inventory") or []) if isinstance(payload, dict) else []
    barred = [r["category"] for r in rows if isinstance(r, dict) and r.get("status") == NOT_INGESTED]
    hit = sorted({name for name in barred for text in next_actions if name.lower() in (text or "").lower()})
    return f"next actions request a category the app cannot ingest: {', '.join(hit)}" if hit else None


def verdict_problem(payload: Any, verdict: Optional[str]) -> Optional[str]:
    """The integrity verdict is one of three labels and agrees with the stored reconciliation: Reliable needs a computed
    reconciliation inside its tolerance, and a window gap over the tolerance (a hard blocker, CLAUDE.md rule 21) is
    Material concerns."""
    if verdict not in DATA_INTEGRITY_VERDICTS:
        return f"verdict is not one of {', '.join(DATA_INTEGRITY_VERDICTS)}"
    checks = ((payload.get("metrics") or {}).get("integrity") or []) if isinstance(payload, dict) else []
    rec = next((c for c in checks if isinstance(c, dict) and c.get("check") == "Revenue file against P&L"), {})
    if rec.get("window_over_tolerance") and verdict != "Material concerns":
        return "verdict must be Material concerns: the revenue file and the P&L differ by more than the tolerance"
    if verdict == "Reliable" and (rec.get("status") != COMPUTED or rec.get("months_over_tolerance")):
        return "verdict cannot be Reliable: the reconciliation is not computed or has months over the tolerance"
    return None
