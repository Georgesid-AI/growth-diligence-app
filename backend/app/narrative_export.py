"""Layout helpers for the narrative sheets in the xlsx export.

Each generated narrative gets its own sheet: what it was written against (as-of month,
target), then headline, what this means, the evidence table, worth flagging, next
actions and source keys. The evidence table's last column names the sheet of THIS
workbook where the cited number sits, so prose can be traced to data without leaving
the file. That link is decided here, from the cited path and the results, and only ever
names a sheet that really carries the value.
"""
import calendar
from typing import Any, List, Optional

from . import disclosure, formatting

# Sheet names the data sheets are written under in server.build_export_workbook. A test
# checks every name used here exists in a full export, so the two cannot drift apart.
HEADLINE = "Headline"
BY_SEGMENT = "By Segment"
NRR_BY_COHORT = "NRR by Cohort"
NRR_SERIES = "NRR Series"
CAC_BY_QUARTER = "CAC by Quarter"
PATH_TO_PLAN = "Path to Plan"
ACV_BANDS = "ACV Bands"
SEGMENT_BASE = "Segment Base"
SEGMENT_MIX = "Segment Mix"
SEGMENT_MIX_DETAIL = "Segment Mix Detail"
ANOMALIES = "Anomalies"
MISSING_DATA = "Missing Data"
DATA_SHEETS = (HEADLINE, BY_SEGMENT, NRR_BY_COHORT, NRR_SERIES, CAC_BY_QUARTER, PATH_TO_PLAN,
               ACV_BANDS, SEGMENT_BASE, SEGMENT_MIX, SEGMENT_MIX_DETAIL, ANOMALIES, MISSING_DATA)

NOT_ON_A_SHEET = "not on a data sheet"

_PATH_TO_PLAN_LEAVES = {
    "current_customers", "current_arr", "acv", "target_arr", "target_date",
    "total_customers_at_target", "additional_customers_needed", "customers_needed",
    "required_net_new_per_year", "observed_net_new_per_year_12m", "observed_net_new_per_year_24m",
    "required_vs_observed_12m", "required_vs_observed_24m",
}
_MIX_LEAVES = {
    "gap_arr", "horizon_months", "target_arr", "unsegmented_arr", "unsegmented_customers",
    "gross_new_per_year", "new_customers_by_target", "required_blended_landed_acv",
    "best_segment_landed_acv", "reachable", "current_mix_landed_acv", "moved_mix_pct",
    "required_new_per_year_at_current_mix", "required_vs_observed_gross",
}
_BASE_LEAVES = {
    "start_arr", "customers", "nrr_pct", "nrr_base_customers", "projected_arr", "change_arr",
    "arr_change_per_nrr_point", "small_base", "start_arr_total", "projected_base_arr",
}
_RECONCILIATION_LEAVES = {"path_to_plan_ratio", "factor_compounded_base", "factor_landed_acv",
                          "factor_gross_rate", "segment_ratio"}
_DETAIL_LEAVES = {"landed_acv", "current_mix_pct", "required_mix_pct", "shift_pct_points", "new_customers"}


def _segments(source_key: str) -> List[str]:
    segs = [s for s in str(source_key).split(".") if s]
    return segs[1:] if segs and segs[0] == "metrics" else segs


def data_sheet_for(source_key: str, results: Optional[dict] = None) -> str:
    """The sheet of this workbook that carries the cited value, or NOT_ON_A_SHEET.

    Never guesses: a value the export does not write (cohort grids, interquartile ranges,
    won/lost counts, monthly churn) is reported as not on a data sheet rather than
    pointed at a nearby one.
    """
    p = _segments(source_key)
    if not p:
        return NOT_ON_A_SHEET
    head, leaf = p[0], p[-1]
    # A bare leaf the guard also accepts ("acv", "customers_needed"): unambiguous ones only.
    if len(p) == 1:
        if leaf in _PATH_TO_PLAN_LEAVES:
            return PATH_TO_PLAN
        return {"arr": HEADLINE, "nrr": HEADLINE, "gross_churn": HEADLINE, "win_rate": HEADLINE,
                "sales_cycle": HEADLINE, "cac_payback": CAC_BY_QUARTER, "acv_path": PATH_TO_PLAN,
                "segment_paths": SEGMENT_BASE, "anomalies": ANOMALIES}.get(head, NOT_ON_A_SHEET)

    if head == "arr":
        return HEADLINE if leaf in ("value", "mrr", "month") else NOT_ON_A_SHEET
    if head == "nrr":
        if p[1] == "overall_pct":
            return HEADLINE
        if p[1] == "by_segment" and leaf in ("nrr_pct", "n", "nrr_base_customers"):
            return BY_SEGMENT
        if p[1] == "by_cohort" and leaf in ("nrr_pct", "n", "nrr_base_customers", "reason"):
            return NRR_BY_COHORT
        if p[1] == "series" and leaf in ("nrr_pct", "month"):
            return NRR_SERIES
        return NOT_ON_A_SHEET
    if head == "gross_churn":
        return HEADLINE if p[1] == "overall_pct" else NOT_ON_A_SHEET
    if head == "sales_cycle":
        if p[1] == "median_days":
            return HEADLINE
        if p[1] == "by_segment" and leaf in ("median_days", "n"):
            return BY_SEGMENT
        return NOT_ON_A_SHEET
    if head == "win_rate":
        return HEADLINE if p[1] in ("win_rate_pct", "excluded_invalid") else NOT_ON_A_SHEET
    if head == "cac_payback":
        if p[1] in ("default_l", "headline_quarter"):
            return HEADLINE
        if p[1] == "quarters" and leaf in ("months", "sm_expense", "new_mrr", "gross_margin_pct",
                                           "months_in_quarter", "partial"):
            return CAC_BY_QUARTER
        return NOT_ON_A_SHEET
    if head == "acv_path":
        if p[1] in _PATH_TO_PLAN_LEAVES and len(p) == 2:
            return PATH_TO_PLAN
        if p[1] == "by_segment" and leaf in ("customers", "acv", "arr"):
            return BY_SEGMENT
        if p[1] == "bands" and leaf in ("count", "label", "range_label", "low", "high"):
            return ACV_BANDS
        return NOT_ON_A_SHEET
    if head == "segment_paths":
        if p[1] == "stage_one" and leaf in _BASE_LEAVES:
            return SEGMENT_BASE
        if p[1] == "reconciliation" and leaf in _RECONCILIATION_LEAVES:
            return SEGMENT_MIX
        if len(p) == 2 and leaf in _MIX_LEAVES:
            return SEGMENT_MIX
        if p[1] == "reverse_solve" and len(p) >= 4:
            if "by_segment" in p and leaf in _DETAIL_LEAVES:
                return SEGMENT_MIX_DETAIL
            if len(p) == 4 and leaf in _MIX_LEAVES:
                return SEGMENT_MIX
        if p[1] == "landed" and "segments" in p and leaf in ("new_customers", "landed_acv") and results:
            # Written to the detail sheet only for windows that have a reverse-solve breakdown.
            window = p[2]
            rs = ((results.get("segment_paths") or {}).get("reverse_solve") or {}).get(window) or {}
            return SEGMENT_MIX_DETAIL if rs.get("by_segment") else NOT_ON_A_SHEET
        return NOT_ON_A_SHEET
    if head == "anomalies":
        return ANOMALIES
    if head == "missing_data":
        return MISSING_DATA
    return NOT_ON_A_SHEET


def month_end_date(month: Optional[str]) -> Optional[str]:
    """"2025-02" -> "2025-02-28": data runs through the last day of the as-of month."""
    try:
        year, mon = str(month).split("-")[:2]
        return f"{int(year):04d}-{int(mon):02d}-{calendar.monthrange(int(year), int(mon))[1]:02d}"
    except (ValueError, TypeError):
        return None


def written_against(meta: dict, results: dict) -> List[tuple]:
    """(label, text) rows saying which period and target the narrative describes."""
    ccy = results.get("reporting_currency") or meta.get("reporting_currency") or ""
    as_of = meta.get("as_of_month") or results.get("as_of_month")
    ap = results.get("acv_path") or {}
    target_arr = meta.get("target_arr") if meta.get("target_arr") is not None else ap.get("target_arr")
    target_date = meta.get("target_date") or ap.get("target_date")
    end = month_end_date(as_of)
    rows = [("As-of month", f"{as_of} (data through {end})" if as_of and end else (as_of or "not set"))]
    if target_arr is not None:
        rows.append(("Target ARR and date",
                     f"{formatting.fmt_currency(target_arr, ccy)} by {target_date}" if target_date
                     else formatting.fmt_currency(target_arr, ccy)))
    else:
        rows.append(("Target ARR and date", "not set"))
    return rows


def sheet_name(step: str) -> str:
    return f"Narrative - {disclosure.STEP_LABELS.get(step, step.replace('_', ' ').capitalize())}"[:31]
