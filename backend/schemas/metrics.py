"""The calc engine's output, described once (docs/specs/interface-contracts.md).

`MetricsPayload` is the only description of what `growth_engine.compute_all` hands over. The engine validates
its result into it and stores the dump; the LLM gateway and the export validate what they read from MongoDB
against it. Every figure is declared with a unit type, so the unit is read from the model, never guessed:

    Fraction   a percent as its fraction: 1.0641 is 106.41%. Field names keep their historical `_pct` suffix.
    Count      an observed count, an integer, rounded to nearest by the engine
    CountUp    a required or implied count, an integer, rounded UP by the engine
    Days       a duration in days, full precision (the display and the export round up when they write it)
    Currency   an amount in the top-level `reporting_currency`, full precision
    Months     a duration in months, full precision
    Ratio      a quotient
    Plain      an identifier or a setting, an integer

Validation is structural (names, types, finite numbers, integers). The range of a Fraction is the unit check
(`unit_violations`), run by the export; the gateway does not run it, because a legitimate 1200% cohort must not
silence a narrative.
"""
import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Dict, Iterator, List, Literal, Optional, Tuple, get_args, get_origin

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, ValidationInfo

CONTRACT_VERSION = 2

# Display kinds: the same names app/formatting.py and frontend/src/lib/format.js use.
CURRENCY, COUNT, COUNT_UP, DAYS, MONTHS, PCT, RATIO, PLAIN = (
    "currency", "count", "count_up", "days", "months", "pct", "ratio", "plain",
)
INTEGER_KINDS = frozenset({COUNT, COUNT_UP, DAYS, PLAIN})     # DAYS is whole only where a field says so (none today)

# A binary float that is "really" 43.0 can arrive as 43.00000000000001, and ceil would then say 44.
_EPSILON = Decimal("1e-9")


def round_nearest(value: Any) -> int:
    """Half away from zero: the display rule of a Count."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_up(value: Any) -> int:
    """Up to the next whole number, noise absorbed: the display rule of a CountUp and of Days."""
    return int((Decimal(str(value)) - _EPSILON).to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class Unit:
    """What a field measures. `lo` and `hi` bound a Fraction for the unit check; None is unbounded."""
    kind: str
    lo: Optional[float] = None
    hi: Optional[float] = None
    whole: bool = True              # an integer kind is held as an integer unless this says otherwise


def _conform(rounder):
    """The engine's rounding, applied only when the model is built from engine output (context conform=True).
    A stored payload is validated without it, so a fractional count fails instead of being rounded."""
    def apply(value, info: ValidationInfo):
        if (info.context and info.context.get("conform") and isinstance(value, (int, float))
                and not isinstance(value, bool) and math.isfinite(value)):
            return rounder(value)
        return value
    return apply


# Strict: a number is a number, never text that reads as one ("5", "0.4").
_FINITE = Field(allow_inf_nan=False, strict=True)
_INTEGER = Field(strict=True)

Fraction = Annotated[float, Unit(PCT, 0.0, 10.0), _FINITE]
SignedFraction = Annotated[float, Unit(PCT, -10.0, 10.0), _FINITE]          # gross margin, mix shift, NRR (a credit note can sink it)
GapFraction = Annotated[float, Unit(PCT), _FINITE]                            # a gap against the P&L: no natural bound
Count = Annotated[int, Unit(COUNT), BeforeValidator(_conform(round_nearest)), _INTEGER]
CountUp = Annotated[int, Unit(COUNT_UP), BeforeValidator(_conform(round_up)), _INTEGER]
Days = Annotated[float, Unit(DAYS, whole=False), _FINITE]
Currency = Annotated[float, Unit(CURRENCY), _FINITE]
Months = Annotated[float, Unit(MONTHS), _FINITE]
Ratio = Annotated[float, Unit(RATIO), _FINITE]
Plain = Annotated[int, Unit(PLAIN), _INTEGER]


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Citation
# ---------------------------------------------------------------------------
class Citation(Block):
    """Where a figure comes from: file, sheet, rows and the rule (growth_engine.SourceRef)."""
    file: Optional[str] = None
    sheet: Optional[str] = None
    rows: str
    row_numbers: List[Plain]
    rule: str
    dataset: Optional[str] = None                   # a metric computed from another upload (compute-before-Missing)
    columns: Optional[Dict[str, str]] = None


# ---------------------------------------------------------------------------
# Recurring-revenue metrics
# ---------------------------------------------------------------------------
class Arr(Block):
    value: Currency
    mrr: Currency
    month: str
    source: Citation


class NrrGroup(Block):
    nrr_pct: Optional[SignedFraction]
    nrr_base_customers: Count
    reason: Optional[str] = None


class NrrPoint(Block):
    month: str
    nrr_pct: Optional[SignedFraction]


class Nrr(Block):
    month: str
    trailing_window_months: Plain
    overall_pct: Optional[SignedFraction]
    nrr_base_customers: Count
    by_segment: Dict[str, NrrGroup]
    by_cohort: Dict[str, NrrGroup]
    series: List[NrrPoint]
    reason: Optional[str] = None
    source: Citation
    status: Optional[str] = None


class ChurnPoint(Block):
    month: str
    churn_pct: Optional[Fraction]


class GrossChurn(Block):
    month: str
    trailing_window_months: Plain
    overall_pct: Optional[Fraction]
    series: List[ChurnPoint]
    source: Citation
    status: Optional[str] = None


class NewMrrQuarter(Block):
    new_mrr: Optional[Currency]
    n_customers: Count
    month: str
    months_in_quarter: Plain
    partial: bool


class CacLag(Block):
    months: Optional[Months]
    reason: Optional[str] = None
    sm_expense: Optional[Currency] = None


class CacQuarter(Block):
    new_mrr: Optional[Currency]
    months_in_quarter: Optional[Plain] = None
    partial: bool
    gross_margin_pct: Optional[SignedFraction]
    L0: CacLag
    L1: CacLag
    L2: CacLag


class CacPayback(Block):
    default_l: Plain
    quarters: Dict[str, CacQuarter]
    headline_quarter: Optional[str]
    partial_quarter_excluded: Optional[str]
    source: Citation
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# Sales metrics
# ---------------------------------------------------------------------------
class CycleStats(Block):
    median_days: Optional[Days]
    iqr: List[Days]
    n: Count


class SalesCycle(Block):
    median_days: Optional[Days]
    iqr: Optional[List[Days]] = None
    n: Count
    by_segment: Optional[Dict[str, CycleStats]] = None
    source: Citation
    status: Optional[str] = None


class FounderSplit(Block):
    won: Count
    lost: Count
    win_rate_pct: Optional[Fraction]
    n: Count
    small_sample: bool


class FounderSplits(Block):
    with_founder: FounderSplit
    without_founder: FounderSplit


class FounderExcluded(Block):
    count: Count
    rows: List[Plain]
    values: List[str]


class WinRate(Block):
    won: Count
    lost: Count
    win_rate_pct: Optional[Fraction]
    excluded_invalid: Count
    excluded_after_as_of: Optional[Count] = None
    by_founder: Optional[FounderSplits] = None
    founder_involved_excluded: Optional[FounderExcluded] = None
    source: Citation
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# Path to plan
# ---------------------------------------------------------------------------
class Band(Block):
    key: str
    label: str
    low: Currency
    high: Optional[Currency]
    range_label: str                                # display text built by the engine; the formatter rebuilds it
    count: Count


class OverallBand(Block):
    key: str
    label: str
    value_label: str


class AcvSegment(Block):
    customers: Count
    acv: Optional[Currency]
    arr: Currency


class AcvPath(Block):
    current_customers: Count
    current_arr: Currency
    acv: Optional[Currency]
    target_arr: Currency
    target_date: Optional[str]
    bands: List[Band]
    overall_band: Optional[OverallBand]
    by_segment: Dict[str, AcvSegment]
    total_customers_at_target: Optional[CountUp]
    additional_customers_needed: Optional[CountUp]
    required_net_new_per_year: Optional[CountUp]
    observed_net_new_per_year_12m: Optional[Count]
    observed_net_new_per_year_24m: Optional[Count]
    required_vs_observed_12m: Optional[Ratio]
    required_vs_observed_12m_reason: Optional[str]
    required_vs_observed_24m: Optional[Ratio]
    required_vs_observed_24m_reason: Optional[str]
    target_date_error: Optional[str]
    source: Citation


class SegmentBase(Block):
    start_arr: Currency
    customers: Count
    nrr_base_customers: Optional[Count]
    nrr_pct: Optional[SignedFraction]
    small_base: bool
    projected_arr: Optional[Currency]
    change_arr: Optional[Currency]
    arr_change_per_nrr_point: Optional[Currency]
    reason: Optional[str] = None


class StageOne(Block):
    segments: Dict[str, SegmentBase]
    start_arr_total: Currency
    projected_base_arr: Optional[Currency] = None


class LandedSegment(Block):
    new_customers: Count
    landed_acv: Optional[Currency]
    small_sample: bool


class Landed(Block):
    window_months: Plain
    computable: bool
    reason: Optional[str]
    segments: Dict[str, LandedSegment]
    gross_new_per_year: Optional[Count] = None
    unsegmented_new_customers: Optional[Count] = None


class MixRow(Block):
    landed_acv: Currency
    current_mix_pct: Fraction
    required_mix_pct: Optional[Fraction] = None
    shift_pct_points: Optional[SignedFraction] = None


class ReverseSolve(Block):
    window_months: Plain
    computable: bool
    reason: Optional[str]
    reachable: Optional[bool]
    target_met_by_base: Optional[bool] = None
    gross_new_per_year: Optional[Count] = None
    new_customers_by_target: Optional[CountUp] = None
    required_blended_landed_acv: Optional[Currency] = None
    best_segment: Optional[str] = None
    best_segment_landed_acv: Optional[Currency] = None
    current_mix_landed_acv: Optional[Currency] = None
    required_new_per_year_at_current_mix: Optional[CountUp] = None
    required_vs_observed_gross: Optional[Ratio] = None
    moved_mix_pct: Optional[Fraction] = None
    by_segment: Optional[Dict[str, MixRow]] = None


class Reconciliation(Block):
    window_months: Plain
    available: bool
    reason: Optional[str]
    path_to_plan_ratio: Optional[Ratio] = None
    factor_compounded_base: Optional[Ratio] = None
    factor_landed_acv: Optional[Ratio] = None
    factor_gross_rate: Optional[Ratio] = None
    segment_ratio: Optional[Ratio] = None


class MissingInput(Block):
    input: str
    resolve: str


class SegmentPaths(Block):
    available: bool
    assumption: str
    missing_inputs: List[MissingInput]
    horizon_months: Optional[Months] = None
    target_arr: Optional[Currency] = None
    target_date: Optional[str] = None
    unsegmented_customers: Optional[Count] = None
    unsegmented_arr: Optional[Currency] = None
    gap_arr: Optional[Currency] = None
    target_met_by_base: Optional[bool] = None
    stage_one: Optional[StageOne] = None
    landed: Optional[Dict[str, Landed]] = None
    reverse_solve: Optional[Dict[str, ReverseSolve]] = None
    reconciliation: Optional[Dict[str, Reconciliation]] = None
    source: Citation


# ---------------------------------------------------------------------------
# Flags, series, cohorts
# ---------------------------------------------------------------------------
class RowCount(Block):
    count: Count
    rows: List[Plain]


class MissingFx(RowCount):
    currencies: List[str]


class DealsExcluded(Block):
    excluded_count: Count
    rows: List[Plain]


class DateOrder(Block):
    dataset: str
    field: str
    order: str
    rows: Plain


class Anomalies(Block):
    negative_mrr_months: List[str]
    revenue_gap_then_resume: List[str]
    revenue_missing_customer_id: RowCount
    revenue_missing_fx_rate: MissingFx
    revenue_missing_amount: RowCount
    deals_close_before_created: DealsExcluded
    date_order_from_data: List[DateOrder]
    source: Citation                                # the revenue file: MRR flags and excluded revenue lines
    deals_source: Optional[Citation] = None         # the CRM file: deals closing before they were created; absent without a CRM


class AmountRow(BaseModel):
    """One month: the total and one amount per segment (segment names are data, so they are extras)."""
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: Dict[str, Currency]
    month: str
    total: Currency


class CountRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: Dict[str, Count]
    month: str
    total: Count


class MrrSeries(Block):
    months: List[str]
    segments: List[str]
    data: List[AmountRow]
    source: Citation


class RevenueSeries(MrrSeries):
    pass


class CustomersSeries(Block):
    months: List[str]
    segments: List[str]
    data: List[CountRow]
    source: Citation


class ReconciliationSource(Block):
    revenue_file: Citation
    pnl: Citation


class ReconciliationMonth(Block):
    month: str
    revenue_file: Currency
    pnl: Currency
    gap: Currency
    gap_pct: Optional[GapFraction]
    source: ReconciliationSource


class RevenueReconciliation(Block):
    available: bool
    reason: Optional[str] = None
    by_month: List[ReconciliationMonth]
    first: Optional[str] = None
    last: Optional[str] = None
    tolerance_pct: Optional[Fraction] = None
    file_total: Optional[Currency] = None
    pnl_total: Optional[Currency] = None
    gap: Optional[Currency] = None
    gap_pct: Optional[GapFraction] = None
    blocker: Optional[bool] = None
    source: Optional[ReconciliationSource] = None


class CohortRow(Block):
    cohort: str
    start_mrr: Currency
    n: Count
    values: Dict[str, Fraction]


class CohortRetention(Block):
    cohorts: List[str]
    max_offset: Plain
    data: List[CohortRow]
    source: Citation


# ---------------------------------------------------------------------------
# What could not be computed
# ---------------------------------------------------------------------------
class MissingItem(Block):
    metric: str
    reason: str
    unlocked_by: str
    file: Optional[str] = None
    status: str
    absent_fields: Optional[Dict[str, List[str]]] = None


class Question(Block):
    metric: str
    status: str
    result_key: str
    dataset: str
    file: Optional[str] = None
    columns: Dict[str, str]
    replaces_missing: Optional[str] = None
    question: str


# ---------------------------------------------------------------------------
# The payload
# ---------------------------------------------------------------------------
class MetricsPayload(Block):
    """The full engine output. A block the engine could not compute is null; the reason is in `missing_data`."""
    contract_version: Literal[2]
    reporting_currency: str                         # the one currency code; no value repeats it
    as_of_month: Optional[str]
    arr: Optional[Arr]
    nrr: Optional[Nrr]
    gross_churn: Optional[GrossChurn]
    new_mrr_by_quarter: Dict[str, NewMrrQuarter]
    new_mrr_by_quarter_source: Citation             # beside the block: its keys are quarters
    cac_payback: Optional[CacPayback]
    sales_cycle: Optional[SalesCycle]
    win_rate: Optional[WinRate]
    founder_win_rate: Optional[WinRate] = None
    acv_path: Optional[AcvPath]
    segment_paths: SegmentPaths
    anomalies: Optional[Anomalies]
    mrr_series: MrrSeries
    revenue_series: RevenueSeries
    revenue_reconciliation: Optional[RevenueReconciliation]
    customers_series: CustomersSeries
    cohort_retention: CohortRetention
    missing_data: List[MissingItem]
    questions_for_management: List[Question]


def build(raw: dict) -> dict:
    """The engine's output as the contract stores it: `raw` validated with the engine's rounding (Count to
    nearest, CountUp and Days up), then dumped with exactly the keys the engine set."""
    payload = MetricsPayload.model_validate({"contract_version": CONTRACT_VERSION, **raw}, context={"conform": True})
    return payload.model_dump(mode="json", exclude_unset=True)


# ---------------------------------------------------------------------------
# Reading the model: units
# ---------------------------------------------------------------------------
def _find_unit(annotation: Any, metadata=()) -> Optional[Unit]:
    for item in metadata:
        if isinstance(item, Unit):
            return item
    if get_origin(annotation) is Annotated:
        base, *meta = get_args(annotation)
        found = _find_unit(base, meta)
        if found:
            return found
    for arg in get_args(annotation):
        found = _find_unit(arg)
        if found:
            return found
    return None


def _field_unit(field) -> Optional[Unit]:
    return _find_unit(field.annotation, field.metadata)


def _extra_unit(cls) -> Optional[Unit]:
    return _find_unit(cls.__annotations__.get("__pydantic_extra__"))


def _models_in(annotation: Any) -> Iterator[type]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
    for arg in get_args(annotation):
        yield from _models_in(arg)


def _all_models(root: type = MetricsPayload) -> List[type]:
    seen, stack = [], [root]
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.append(cls)
        for field in cls.model_fields.values():
            stack.extend(_models_in(field.annotation))
    return seen


def kinds_by_name() -> Tuple[Dict[str, str], Dict[str, str], Dict[str, set]]:
    """(kind by field name, kind by container name, names that mean two kinds).

    The container map covers `Dict[str, <unit>]` fields, whose keys are data (`values`: {"0": ..., "3": ...}).
    A name that two models declare with different kinds is ambiguous and left out of the first map."""
    by_name: Dict[str, set] = {}
    by_parent: Dict[str, str] = {}
    for cls in _all_models():
        for name, field in cls.model_fields.items():
            unit = _field_unit(field)
            if unit is None:
                continue
            by_name.setdefault(name, set()).add(unit.kind)
            if _is_plain_dict(field.annotation):
                by_parent[name] = unit.kind
    ambiguous = {n: k for n, k in by_name.items() if len(k) > 1}
    return ({n: next(iter(k)) for n, k in by_name.items() if n not in ambiguous}, by_parent, ambiguous)


def _is_plain_dict(annotation: Any) -> bool:
    """Dict[str, unit] (possibly Optional): the values are figures, the keys are data."""
    candidates = [annotation, *get_args(annotation)]
    for cand in candidates:
        if get_origin(cand) is dict:
            value = get_args(cand)[1]
            if _find_unit(value) is not None and not list(_models_in(value)):
                return True
    return False


# ---------------------------------------------------------------------------
# The unit check
# ---------------------------------------------------------------------------
def _walk(value: Any, unit: Optional[Unit], path: tuple) -> Iterator[Tuple[tuple, Unit, Any]]:
    if isinstance(value, BaseModel):
        yield from iter_figures(value, path)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _walk(item, unit, (*path, i))
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, unit, (*path, key))
    elif unit is not None and value is not None:
        yield path, unit, value


def iter_figures(model: BaseModel, path: tuple = ()) -> Iterator[Tuple[tuple, Unit, Any]]:
    """Every figure of a validated payload with its path (a tuple of field names, data keys and list positions) and unit."""
    for name, field in type(model).model_fields.items():
        yield from _walk(getattr(model, name), _field_unit(field), (*path, name))
    extra_unit = _extra_unit(type(model))
    for key, item in (model.__pydantic_extra__ or {}).items():
        yield from _walk(item, extra_unit, (*path, key))


@dataclass(frozen=True)
class Violation:
    path: tuple
    value: Any
    rule: str

    def human(self) -> str:
        return f"{'.'.join(str(p) for p in self.path)} = {self.value!r}: {self.rule}"

    def safe(self) -> str:
        """The path with every data key (a segment, a quarter) as `*` and list positions as `[]`: no value, no name."""
        return _safe(self.path) + ": unit"


def _safe(path: tuple) -> str:
    known = {name for cls in _all_models() for name in cls.model_fields}
    return ".".join(p if isinstance(p, str) and p in known else "[]" if isinstance(p, int) else "*" for p in path)


def unit_violations(payload: MetricsPayload) -> List[Violation]:
    """Every figure that breaks its unit: a Fraction outside its range (a whole-number percent such as 106.41 sits above
    10), a count or a number of days that is not an integer. Empty when the payload is sound."""
    problems = []
    for path, unit, value in iter_figures(payload):
        if unit.kind == PCT:
            if unit.lo is not None and not (unit.lo <= value <= unit.hi):
                problems.append(Violation(path, value, f"a percent is a fraction between {unit.lo:g} and {unit.hi:g} "
                                                       f"(1.0641 is 106.41%)"))
        elif unit.kind in INTEGER_KINDS and unit.whole:
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append(Violation(path, value, f"a {unit.kind.replace('_', ' ')} is an integer"))
    return problems


def error_paths(exc) -> List[str]:
    """Paths and error types of a ValidationError, never the input values and never a data key: a value or a key can be
    a segment name or a reason text that quotes the upload, and this goes to a log line."""
    return [f"{_safe(tuple(e['loc']))}: {e['type']}" for e in exc.errors(include_input=False, include_url=False)]


def safe_problems(results: Any) -> List[str]:
    """Why `results` is not a sound MetricsPayload, as log-safe strings; empty when it is. The schema first, then the unit
    check (a stored percent of 106.41 where a fraction belongs is refused here)."""
    try:
        payload = MetricsPayload.model_validate(results)
    except ValidationError as exc:
        return error_paths(exc)
    return [v.safe() for v in unit_violations(payload)]


class ContractError(ValueError):
    """Stored metrics that must not be read: `str(exc)` says what is wrong, `log_text` is safe for a log line (field
    names and counts only)."""

    def __init__(self, message: str, log_text: str):
        super().__init__(message)
        self.log_text = log_text


def validate_for_export(results: Any) -> MetricsPayload:
    """The export's gate (docs/specs/interface-contracts.md section 5): `results` must validate against MetricsPayload and
    pass the unit check, or nothing is written."""
    try:
        payload = MetricsPayload.model_validate(results)
    except ValidationError as exc:
        paths = error_paths(exc)
        raise ContractError("the stored metrics do not match the engine contract (" + "; ".join(paths[:8]) + ")",
                            f"{len(paths)} schema problem(s): " + "; ".join(paths[:8]))
    problems = unit_violations(payload)
    if problems:
        raise ContractError("a figure breaks its unit: " + "; ".join(v.human() for v in problems[:8]),
                            f"{len(problems)} unit problem(s): " + "; ".join(sorted({v.safe() for v in problems})[:8]))
    return payload
