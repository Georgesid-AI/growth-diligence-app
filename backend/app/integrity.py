"""Data integrity: results of the completed checks and the assessment coverage (docs/specs/integrity-coverage.md).

Pure: reads the stored engine results, the audit's deck count and its deck candidates; computes nothing new from the files,
calls no model, imports nothing from the gateway and logs nothing. Block A lists the checks that ran with their result; Block B
lists the six checks of the method with their status; the conclusion is Python's, by the fixed rule of section 2.
"""
from statistics import pstdev
from typing import List, Optional

COMPLETED = "Completed"
NOT_APPLICABLE = "Not applicable"
BLOCKED = "Blocked — company data missing"
NOT_AVAILABLE = "Not available in the app"
GREEN, AMBER, RED = "Green", "Amber", "Red"

RECONCILIATION, GAPS, CLUSTERING, SMOOTHNESS, BENFORD, DECKS = (
    "Revenue reconciliation", "Gaps in customer data", "Quarter-end clustering", "Smoothness", "Benford on transactions",
    "Deck-vs-deck figures")
CHECKS = (RECONCILIATION, GAPS, CLUSTERING, SMOOTHNESS, BENFORD, DECKS)
# Section 1: the reason each status prints, word for word. A Blocked reason is a data request.
REASONS = {
    RECONCILIATION: "P&L with a revenue line, overlapping the revenue file's months",
    GAPS: "Revenue file mapped (customer ID, invoice date, amount)",
    CLUSTERING: "The app does not compute quarter-end clustering of deals yet.",
    SMOOTHNESS: "Revenue file with at least 13 consecutive months of revenue",
    BENFORD: "No transaction-level file: the app ingests revenue by customer and month, not transactions.",
    DECKS: "At least one board deck",
}
SMOOTHNESS_MONTHS = 13              # smoothness.md section 1: 12 month-on-month changes need 13 consecutive months
SMOOTHNESS_LABEL = "provisional threshold, 3 synthetic series"    # shown beside the result, on screen and in the memo (George, 15 Oct 2026)
SMOOTHNESS_LIMIT_POINTS = 0.5       # below this deviation of the growth rate, in points, revenue is unusually smooth (provisional, section 1)
MIN_COMPLETED = 4                   # section 2: fewer completed applicable checks is insufficient coverage
INSUFFICIENT = "Insufficient assessment coverage ({x} of {y})"
INSUFFICIENT_NOTE = ("Insufficient assessment coverage is not a finding about the company: {n} of the {y} applicable checks could not "
                     "be completed.")
CONCLUSIONS = {"reliable": "Reliable", "needs_clarification": "Needs clarification", "material_concerns": "Material concerns"}
COMPLETED_TEXT = "Completed {x} of {y} applicable checks"


def _cite(source: Optional[dict]) -> str:
    """"revenue.csv · CSV · rows 2–71 (70 rows)": a stored citation as one line."""
    return " · ".join(str(source[k]) for k in ("file", "sheet", "rows") if (source or {}).get(k))


def _reconciliation(results: dict) -> Optional[dict]:
    rec = results.get("revenue_reconciliation") or {}
    if not rec.get("available"):
        return None
    tolerance = rec.get("tolerance_pct") or 0
    months_beyond = [m for m in rec.get("by_month") or () if m.get("gap_pct") is not None and abs(m["gap_pct"]) > tolerance]
    result = RED if rec.get("blocker") else AMBER if months_beyond else GREEN
    pct = "—" if rec.get("gap_pct") is None else f"{abs(rec['gap_pct']) * 100:g}"
    src = rec.get("source") or {}
    return {"result": result, "finding": f"Revenue file and P&L differ by {pct}% over {rec.get('first')}–{rec.get('last')}",
            "source": "; ".join(s for s in (_cite(src.get("revenue_file")), _cite(src.get("pnl"))) if s)}


def _gaps(results: dict) -> Optional[dict]:
    a = results.get("anomalies")
    if not a:
        return None
    resumed = len(a.get("revenue_gap_then_resume") or ())
    no_id = (a.get("revenue_missing_customer_id") or {}).get("count") or 0
    return {"result": AMBER if resumed or no_id else GREEN,
            "finding": f"{resumed} customers whose revenue stops for over two months and resumes; {no_id} revenue lines without a "
                       f"customer ID",
            "source": _cite(a.get("source"))}


def _month_index(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def smoothness(results: dict) -> Optional[dict]:
    """Smoothness (smoothness.md): the deviation, in points, of the last 12 month-on-month growth rates of the latest run of
    consecutive months with revenue, a Possibly partial last month left out. None when 13 such months do not exist. The one
    calculation: the integrity block and the data-integrity narrative's payload both read it."""
    series = results.get("revenue_series") or {}
    partial = results.get("source_period") or {}
    skip = partial.get("month") if partial.get("status") == "Possibly partial" else None
    points = sorted((_month_index(d["month"]), d["month"], d["total"]) for d in series.get("data") or ()
                    if d.get("month") != skip and isinstance(d.get("total"), (int, float)) and d["total"] > 0)
    run: list = []
    for point in points:
        run = run + [point] if run and point[0] == run[-1][0] + 1 else [point]
    if len(run) < SMOOTHNESS_MONTHS:
        return None
    window = run[-SMOOTHNESS_MONTHS:]
    deviation = pstdev([window[i][2] / window[i - 1][2] - 1 for i in range(1, len(window))]) * 100
    return {"deviation": deviation, "first": window[0][1], "last": window[-1][1], "smooth": deviation < SMOOTHNESS_LIMIT_POINTS,
            "limit": SMOOTHNESS_LIMIT_POINTS, "label": SMOOTHNESS_LABEL}


def _smoothness(results: dict) -> Optional[dict]:
    read = smoothness(results)
    if read is None:
        return None
    finding = (f"Month-on-month revenue growth varies by {read['deviation']:.1f} points (standard deviation) over "
               f"{read['first']}–{read['last']}" + (f"; below {SMOOTHNESS_LIMIT_POINTS:g} points is unusually smooth" if read["smooth"] else "") +
               f" ({SMOOTHNESS_LABEL})")
    return {"result": AMBER if read["smooth"] else GREEN, "finding": finding, "source": _cite((results.get("revenue_series") or {}).get("source"))}


def _where(source: Optional[dict]) -> str:
    s = source or {}
    page = f"slide {s['slide']}" if s.get("slide") is not None else f"page {s['page']}" if s.get("page") is not None else None
    return " · ".join(x for x in (s.get("file"), page) if x)


def _decks(candidates: List[dict]) -> dict:
    """Deck-vs-deck: the parser's inconsistency rule read across every deck of the audit (section 7)."""
    from .decks.claims import cross_deck_inconsistencies
    pairs = cross_deck_inconsistencies([c for c in candidates if c.get("status") != "rejected"])
    if not pairs:
        return {"result": GREEN, "finding": "No deck figure differs from another of the same type, label and stated period",
                "source": ""}
    first = pairs[0]
    where = f"{_where(first['this'].get('source'))} and {_where(first['other'].get('source'))}"
    return {"result": AMBER, "finding": f"{len(pairs)} deck figures differ from another of the same type, label and stated period; "
                                        f"first: {where}", "source": where}


def overall(rows: List[dict]) -> dict:
    """Section 2: the conclusion over the coverage rows ({check, status, result}). The denominator is the applicable checks."""
    applicable = [r for r in rows if r["status"] != NOT_APPLICABLE]
    done = [r for r in applicable if r["status"] == COMPLETED]
    x, y = len(done), len(applicable)
    if x < MIN_COMPLETED or not any(r["check"] == RECONCILIATION for r in done):
        code = "insufficient"
        conclusion = INSUFFICIENT.format(x=x, y=y)
    else:
        results = {r.get("result") for r in done}
        code = "material_concerns" if RED in results else "reliable" if results == {GREEN} else "needs_clarification"
        conclusion = CONCLUSIONS[code]
    return {"conclusion": conclusion, "code": code, "completed": x, "applicable": y}


def assess(results: Optional[dict], deck_count: int, candidates: List[dict]) -> dict:
    """Both blocks, the conclusion, the data requests and the memo's sentence for one audit. `results` may be None (not computed):
    every check that reads it is then Blocked."""
    results = results or {}
    ran = {RECONCILIATION: _reconciliation(results), GAPS: _gaps(results), SMOOTHNESS: _smoothness(results), DECKS: _decks(candidates) if deck_count else None}
    coverage = []
    for check in CHECKS:
        if check == BENFORD:
            status = NOT_APPLICABLE
        elif check == CLUSTERING:
            status = NOT_AVAILABLE
        else:
            status = COMPLETED if ran[check] else BLOCKED
        coverage.append({"check": check, "status": status, "reason": None if status == COMPLETED else REASONS[check],
                         "result": ran[check]["result"] if status == COMPLETED else None})
    block_a = [{"check": check, **ran[check]} for check in CHECKS if ran.get(check)]
    out = overall(coverage)
    blocked = [r["check"] for r in coverage if r["status"] == BLOCKED]
    return {
        **out,
        "results": block_a,
        "coverage": coverage,
        "completed_text": COMPLETED_TEXT.format(x=out["completed"], y=out["applicable"]),
        "blocked": blocked,
        "data_requests": [f"{r['check']}: {r['reason']}" for r in coverage if r["status"] == BLOCKED],
        "memo_sentence": INSUFFICIENT_NOTE.format(n=out["applicable"] - out["completed"], y=out["applicable"]) if out["code"] == "insufficient"
        else None,
    }
