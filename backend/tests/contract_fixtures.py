"""Hand-built engine output that satisfies schemas.metrics.MetricsPayload, for tests that need a stored result
without running the engine. `stored(**blocks)` is a complete payload: every block not given is the empty one the
engine produces when it could not compute it. Percents are fractions, counts and days are integers.

A fixture that breaks the contract is a test of the contract; build it with `broken(...)` so the break is visible."""
import copy
from typing import Any, Dict, Optional

from schemas import metrics
from schemas.metrics import CONTRACT_VERSION


def cite(file: str = "revenue.csv", sheet: str = "Sheet1", rows=(2, 3, 4), rule: str = "rule") -> dict:
    rows = list(rows)
    label = "no rows" if not rows else f"row {rows[0]}" if len(rows) == 1 else f"rows {rows[0]}–{rows[-1]} ({len(rows)} rows)"
    return {"file": file, "sheet": sheet, "rows": label, "row_numbers": rows, "rule": rule}


def arr(value: float = 3129600.0, mrr: float = 260800.0, month: str = "2026-06", **more) -> dict:
    return {"value": value, "mrr": mrr, "month": month, "source": cite(), **more}


def nrr(overall: Optional[float] = 1.042, base: int = 110, month: str = "2026-06", by_segment=None, by_cohort=None,
        series=None, **more) -> dict:
    return {"month": month, "trailing_window_months": 12, "overall_pct": overall, "nrr_base_customers": base,
            "by_segment": by_segment or {}, "by_cohort": by_cohort or {}, "series": series or [], "source": cite(), **more}


def nrr_group(pct: Optional[float], base: int = 20, **more) -> dict:
    return {"nrr_pct": pct, "nrr_base_customers": base, **more}


def gross_churn(overall: Optional[float] = 0.061, month: str = "2026-06", series=None) -> dict:
    return {"month": month, "trailing_window_months": 12, "overall_pct": overall, "series": series or [],
            "source": cite()}


def win_rate(rate: Optional[float] = 0.287, won: int = 269, lost: int = 667, **more) -> dict:
    return {"won": won, "lost": lost, "win_rate_pct": rate, "excluded_invalid": 0, "source": cite("crm.csv"), **more}


def sales_cycle(median: Optional[int] = 43, n: int = 12, **more) -> dict:
    return {"median_days": median, "iqr": [30, 60], "n": n, "source": cite("crm.csv"), **more}


def lag(months: Optional[float] = None, reason: Optional[str] = "no P&L", sm: Optional[float] = None) -> dict:
    return {"months": months, "reason": reason, **({"sm_expense": sm} if sm is not None else {})}


def cac_quarter(new_mrr: float = 1000.0, gm: Optional[float] = 0.7, partial: bool = False, months_in_quarter: int = 3,
                L0=None, L1=None, L2=None) -> dict:
    return {"new_mrr": new_mrr, "months_in_quarter": months_in_quarter, "partial": partial, "gross_margin_pct": gm,
            "L0": L0 or lag(), "L1": L1 or lag(), "L2": L2 or lag()}


def cac_payback(quarters: Dict[str, dict], headline: Optional[str] = None, default_l: int = 1, **more) -> dict:
    return {"default_l": default_l, "quarters": quarters, "headline_quarter": headline,
            "partial_quarter_excluded": None, "source": cite("pnl.csv"), **more}


def acv_path(**more) -> dict:
    base = {"current_customers": 24, "current_arr": 3129600.0, "acv": 130400.0, "target_arr": 6000000.0,
            "target_date": "2027-12-31", "bands": [], "overall_band": None, "by_segment": {},
            "total_customers_at_target": 47, "additional_customers_needed": 23, "required_net_new_per_year": 15,
            "observed_net_new_per_year_12m": 6, "observed_net_new_per_year_24m": 3,
            "required_vs_observed_12m": 2.5, "required_vs_observed_12m_reason": None,
            "required_vs_observed_24m": 5.0, "required_vs_observed_24m_reason": None,
            "target_date_error": None, "source": cite()}
    return {**base, **more}


def seg_base(start_arr: float, customers: int, nrr_pct: Optional[float] = None, base: Optional[int] = None, **more) -> dict:
    """One segment of segment_paths.stage_one: nothing projected unless given."""
    return {"start_arr": start_arr, "customers": customers, "nrr_base_customers": base, "nrr_pct": nrr_pct,
            "small_base": False, "projected_arr": None, "change_arr": None, "arr_change_per_nrr_point": None, **more}


def segment_paths(**more) -> dict:
    return {"available": False, "assumption": "Constant-NRR projection, not a forecast.", "missing_inputs": [], **more}


def anomalies(**more) -> dict:
    base = {"negative_mrr_months": [], "revenue_gap_then_resume": [],
            "revenue_missing_customer_id": {"count": 0, "rows": []},
            "revenue_missing_fx_rate": {"count": 0, "rows": [], "currencies": []},
            "revenue_missing_amount": {"count": 0, "rows": []},
            "deals_close_before_created": {"excluded_count": 0, "rows": []},
            "date_order_from_data": []}
    return {**base, **more}


def conformed(model: type, block: dict) -> dict:
    """A block as the engine stores it: raw metric-function output rounded by the contract (counts to nearest,
    required counts and days up), for tests that call a metric function directly."""
    return model.model_validate(block, context={"conform": True}).model_dump(mode="json", exclude_unset=True)


def series(months=(), segments=(), data=()) -> dict:
    return {"months": list(months), "segments": list(segments), "data": list(data)}


def stored(**blocks: Any) -> dict:
    """A complete stored payload. Keyword arguments replace whole blocks (`nrr=nrr(...)`)."""
    base = {
        "contract_version": CONTRACT_VERSION, "reporting_currency": "EUR", "as_of_month": "2026-06",
        "arr": None, "nrr": None, "gross_churn": None, "new_mrr_by_quarter": {}, "cac_payback": None,
        "sales_cycle": None, "win_rate": None, "acv_path": None, "segment_paths": segment_paths(),
        "anomalies": None, "mrr_series": series(), "revenue_series": {**series(), "source": cite()},
        "revenue_reconciliation": None, "customers_series": {**series(), "source": cite()},
        "cohort_retention": {"cohorts": [], "max_offset": 0, "data": []},
        "missing_data": [], "questions_for_management": [],
    }
    base.update(copy.deepcopy(blocks))
    return base


def broken(payload: dict, path: str, value: Any = None, drop: bool = False) -> dict:
    """A copy of `payload` with one key changed or removed: path is dotted ("nrr.overall_pct")."""
    out = copy.deepcopy(payload)
    node = out
    *head, last = path.split(".")
    for part in head:
        node = node[part]
    if drop:
        del node[last]
    else:
        node[last] = value
    return out
