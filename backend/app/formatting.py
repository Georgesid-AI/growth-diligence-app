"""The single place numbers become display strings.

Every figure a reader sees - narrative, dashboard, workbook export - and every
figure the LLM gateway is handed goes through this module, so one number can
never appear in two formats. The calc engine and MongoDB keep full precision;
rounding happens here, at display time, from the raw computed value.

Rules (kind -> behaviour):

    currency   whole number, comma thousands, currency code   3129104.4 -> "3,129,104 EUR"
    count      observed count, rounds to nearest              100.0     -> "100"
    count_up   required / implied count, rounds UP            128.3     -> "129"
    days       rounds UP to the next whole day, unit suffix   42.1      -> "43 days"
    months     one decimal, nearest, "months" suffix          12.24     -> "12.2 months"
    pct        whole number, nearest, half away from zero     106.41    -> "106%"
    ratio      always two decimals, "x" suffix                1.28      -> "1.28x"
    plain      integer identifier / setting, no grouping      1         -> "1"

The frontend mirrors this file in `frontend/src/lib/format.js`; both are pinned
to `format_vectors.json` by a test on each side.
"""
import math
import re
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Optional

CURRENCY, COUNT, COUNT_UP, DAYS, MONTHS, PCT, RATIO, PLAIN = (
    "currency", "count", "count_up", "days", "months", "pct", "ratio", "plain",
)

# A binary float that is "really" 43.0 can arrive as 43.00000000000001, and
# ceil would then say 44. Absorb noise far below any real figure's precision.
_EPSILON = Decimal("1e-9")

PLACEHOLDER = "—"


class FormattingError(ValueError):
    """A numeric value had no registered display kind."""


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    # str() of a float is its shortest round-trip repr, so 0.1 stays 0.1
    # rather than 0.1000000000000000055...
    return Decimal(str(value))


def _nearest(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _up(d: Decimal) -> int:
    return int((d - _EPSILON).to_integral_value(rounding=ROUND_CEILING))


def _grouped(n: int) -> str:
    return f"{n:,}"


def fmt_currency(value: Any, ccy: Optional[str] = None) -> str:
    d = _dec(value)
    if d is None:
        return PLACEHOLDER
    text = _grouped(_nearest(d))
    return f"{text} {ccy}" if ccy else text


def fmt_count(value: Any) -> str:
    d = _dec(value)
    return PLACEHOLDER if d is None else _grouped(_nearest(d))


def fmt_count_up(value: Any) -> str:
    d = _dec(value)
    return PLACEHOLDER if d is None else _grouped(_up(d))


def fmt_days_number(value: Any) -> str:
    """The rounded-up day count on its own, for composing ranges ("17–59 days")."""
    d = _dec(value)
    return PLACEHOLDER if d is None else _grouped(_up(d))


def fmt_days(value: Any) -> str:
    """Whole days, rounded up, with the unit as a suffix: 42.1 -> "43 days".

    The rounding rule governs the number only; the unit does not change it.
    """
    d = _dec(value)
    if d is None:
        return PLACEHOLDER
    n = _up(d)
    return f"{_grouped(n)} {'day' if n == 1 else 'days'}"


def fmt_months(value: Any) -> str:
    """CAC payback is a duration in months: one decimal, not rounded up."""
    d = _dec(value)
    if d is None:
        return PLACEHOLDER
    return f"{d.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)} months"


def fmt_pct(value: Any) -> str:
    d = _dec(value)
    return PLACEHOLDER if d is None else f"{_nearest(d)}%"


def fmt_ratio(value: Any) -> str:
    d = _dec(value)
    if d is None:
        return PLACEHOLDER
    return f"{d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}x"


def fmt_plain(value: Any) -> str:
    d = _dec(value)
    return PLACEHOLDER if d is None else str(_nearest(d))


def fmt(kind: str, value: Any, ccy: Optional[str] = None) -> str:
    """Format `value` as `kind`. The one entry point callers should use."""
    if kind == CURRENCY:
        return fmt_currency(value, ccy)
    if kind == COUNT:
        return fmt_count(value)
    if kind == COUNT_UP:
        return fmt_count_up(value)
    if kind == DAYS:
        return fmt_days(value)
    if kind == MONTHS:
        return fmt_months(value)
    if kind == PCT:
        return fmt_pct(value)
    if kind == RATIO:
        return fmt_ratio(value)
    if kind == PLAIN:
        return fmt_plain(value)
    raise FormattingError(f"unknown display kind {kind!r}")


# ---------------------------------------------------------------------------
# Spreadsheet cells: numeric, with an Excel number format
# ---------------------------------------------------------------------------
# Analysts must be able to sum and sort, so the export keeps cells numeric and
# lets the number format do the display. Excel formats can round but not round
# UP, and "0%" scales by 100, so `xlsx_value` prepares the stored number so the
# format then shows exactly what `fmt` would.
XLSX_NUMBER_FORMAT = {
    CURRENCY: "#,##0", COUNT: "#,##0", COUNT_UP: "#,##0", DAYS: "#,##0",
    MONTHS: "0.0", PCT: "0%", RATIO: '0.00"x"', PLAIN: "0",
}


def xlsx_value(kind: str, value: Any) -> Optional[float]:
    """The number to store in a cell that will carry XLSX_NUMBER_FORMAT[kind]."""
    d = _dec(value)
    if d is None:
        return None
    if kind in (COUNT_UP, DAYS):
        return _up(d)              # the format cannot round up, so the cell holds the rounded-up value
    if kind == PCT:
        return float(d / 100)      # 106.41 -> 1.0641, shown by "0%" as 106%
    return float(d)


# ---------------------------------------------------------------------------
# Which engine field is which kind
# ---------------------------------------------------------------------------
# Keyed by the field's own name; the same name means the same thing wherever it
# appears in the engine's output (by_segment, quarters, series, ...).
KIND_BY_KEY = {
    # money
    "value": CURRENCY, "mrr": CURRENCY, "current_arr": CURRENCY, "acv": CURRENCY,
    "target_arr": CURRENCY, "arr": CURRENCY, "new_mrr": CURRENCY,
    "sm_expense": CURRENCY, "start_mrr": CURRENCY, "total": CURRENCY,
    "low": CURRENCY, "high": CURRENCY,
    # counts of things that were observed
    "n": COUNT, "n_customers": COUNT, "customers": COUNT, "current_customers": COUNT,
    "count": COUNT, "won": COUNT, "lost": COUNT, "excluded_invalid": COUNT, "excluded_after_as_of": COUNT,
    "months_available": COUNT,
    "observed_net_new_per_year_12m": COUNT, "observed_net_new_per_year_24m": COUNT,
    # counts the plan requires or implies - never round down
    "customers_needed": COUNT_UP, "required_net_new_per_year": COUNT_UP,
    # durations
    "median_days": DAYS, "iqr": DAYS,
    "months": MONTHS,
    # percentages
    "overall_pct": PCT, "nrr_pct": PCT, "churn_pct": PCT, "win_rate_pct": PCT,
    "gross_margin_pct": PCT,
    # ratios
    "required_vs_observed_12m": RATIO, "required_vs_observed_24m": RATIO,
    # settings that are numbers but not measurements
    "default_l": PLAIN, "max_offset": PLAIN,
    # source-row references (provenance): identifiers, not measurements
    "row_numbers": PLAIN, "rows": PLAIN,
}

# Numeric fields inside a container whose own key decides the kind: cohort
# retention stores {"values": {"0": 100.0, "3": 96.2}} - every value a pct.
KIND_BY_PARENT = {"values": PCT}

# Engine-built display strings ("€45.2K", "€25K–50K"). They format the same
# figures in a different style. `range_label` is rebuilt here from the band's
# raw thresholds; `value_label` repeats `acv`, so it is dropped.
_ENGINE_LABEL_KEYS = {"range_label", "value_label"}


def band_range_label(low: Any, high: Any, ccy: Optional[str]) -> str:
    """"25,000–50,000 EUR" from the band's raw thresholds."""
    if high is None:
        return f"{fmt_currency(low, ccy)}+"
    if not low:
        return f"<{fmt_currency(high, ccy)}"
    return f"{fmt_currency(low)}–{fmt_currency(high, ccy)}"


def format_payload(node: Any, ccy: Optional[str] = None, _key: Optional[str] = None,
                   _parent: Optional[str] = None) -> Any:
    """Deep-copy computed results with every number turned into its display string.

    This is what the LLM gateway sends: the model is given strings it can only
    copy, never a float it could reformat. A numeric field with no registered
    kind raises rather than leaking a raw float, so a new engine field cannot
    silently bypass the rules.
    """
    if isinstance(node, dict):
        ccy = node.get("reporting_currency") or ccy
        out = {}
        for k, v in node.items():
            if k in _ENGINE_LABEL_KEYS:
                continue
            out[k] = format_payload(v, ccy, _key=k, _parent=_key)
        if "range_label" in node and "low" in node:
            out["range_label"] = band_range_label(node.get("low"), node.get("high"), ccy)
        return out
    if isinstance(node, list):
        return [format_payload(i, ccy, _key=_key, _parent=_parent) for i in node]
    if isinstance(node, bool) or node is None or isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        kind = KIND_BY_KEY.get(_key) or KIND_BY_PARENT.get(_parent)
        if kind is None:
            raise FormattingError(f"no display kind registered for numeric field {_key!r}")
        return fmt(kind, node, ccy)
    return node


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------
GLOSSARY = {
    "ACV": "average contract value",
    "ARR": "annual recurring revenue",
    "MRR": "monthly recurring revenue",
    "NRR": "net revenue retention",
    "CAC": "customer acquisition cost",
}
ACV_DEFINITION = f"ACV ({GLOSSARY['ACV']})"

_ACV = re.compile(r"\bACV\b")
_DEFINED = f" ({GLOSSARY['ACV']})"


def define_acv_on_first_use(fields: list) -> list:
    """Expand the first "ACV" across `fields`, taken in reading order.

    Idempotent, and a no-op if the term is already defined at its first use or
    never used. Later mentions stay short. Returns a new list.
    """
    out = list(fields)
    for i, text in enumerate(out):
        if not isinstance(text, str):
            continue
        m = _ACV.search(text)
        if not m:
            continue
        if not text.startswith(_DEFINED, m.end()):
            out[i] = text[: m.end()] + _DEFINED + text[m.end():]
        return out
    return out


# ---------------------------------------------------------------------------
# Readable names for cited engine fields
# ---------------------------------------------------------------------------
# The narrative table cites each figure by its dotted engine path
# ("metrics.nrr.overall_pct"). That path is the audit trail and stays available,
# but the primary text of a row is a plain-English name from this module. It is a
# display concern only: the model is never sent these names and citations are
# still matched on the path.
#
# A name is a base label plus, where the number cannot be read correctly without
# it, a qualifier - always rendered in brackets with no comma before them:
# "NRR (latest month)". Dashboard tiles and table rows use the same base label and
# the same qualifier wording, taken from here; the tile shows the qualifier as
# small text beneath its value. `frontend/src/lib/metric_names.json` is generated
# from these two maps and a test fails if it is out of date.
#
# Keyed by the last two path segments where the leaf alone is ambiguous
# ("nrr.overall_pct" vs "gross_churn.overall_pct"), otherwise by the last one.
# The longest match wins. Segment names, quarters and cohort ages that vary per
# run ("by_segment.SMB", "quarters.2026-Q1") never need an entry of their own.
LABEL_BY_PATH = {
    # containers
    "arr": "ARR", "nrr": "Net revenue retention", "gross_churn": "Gross revenue churn",
    "cac_payback": "CAC payback", "sales_cycle": "Sales cycle", "win_rate": "Win rate",
    "acv_path": "Path to plan", "cohort_retention": "Cohort retention",
    "overall_band": "Overall ACV band", "bands": "ACV bands", "by_segment": "By segment",
    "by_cohort": "By cohort", "by_founder": "By founder involvement",
    "target_arr": "Target ARR", "target_date": "Target date", "as_of_month": "As-of month",
    "month": "Month",
    # ARR - the same figure under two paths, so one name
    "arr.value": "Ending ARR", "current_arr": "Ending ARR", "arr.mrr": "MRR", "arr.arr": "ARR",
    # retention
    "nrr.overall_pct": "NRR", "nrr.n": "NRR base customers", "nrr_pct": "NRR",
    "gross_churn.overall_pct": "Gross churn", "churn_pct": "Gross churn",
    "months_available": "Months of history available",
    # CAC payback
    "months": "CAC payback", "default_l": "S&M spend lag (quarters)",
    "new_mrr": "New MRR", "sm_expense": "S&M spend", "gross_margin_pct": "Gross margin",
    # sales
    "median_days": "Median sales cycle", "iqr": "Sales cycle interquartile range",
    "sales_cycle.n": "Deals in sales-cycle sample", "win_rate_pct": "Win rate",
    "won": "Deals won", "lost": "Deals lost",
    "excluded_invalid": "Deals excluded (close before created)",
    "excluded_after_as_of": "Deals excluded (after as-of month)",
    "founder_involved_excluded.count": "Deals with an unrecognised founder flag",
    # path to plan
    "current_customers": "Customers", "acv": "ACV (average contract value)",
    "customers_needed": "Customers needed",
    "required_net_new_per_year": "Required net-new customers per year",
    "observed_net_new_per_year_12m": "Observed net-new customers per year",
    "observed_net_new_per_year_24m": "Observed net-new customers per year",
    "required_vs_observed_12m": "Required vs observed net-new customers",
    "required_vs_observed_24m": "Required vs observed net-new customers",
    "low": "ACV band lower bound", "high": "ACV band upper bound",
    "customers": "Customers", "count": "Customers in band",
    # cohort retention
    "max_offset": "Longest cohort age (months)", "start_mrr": "Cohort starting MRR",
    "values": "Cohort MRR retained",
    # generic
    "n": "Sample size", "total": "Total MRR",
}

# What a reader needs to know to read the number correctly, from the engine's own
# rules (see the `source` rule strings in growth_engine.py). Only metrics whose
# scope is not obvious from the name carry one.
QUALIFIER_BY_PATH = {
    "arr.value": "latest month MRR × 12", "current_arr": "latest month MRR × 12",
    "arr.mrr": "latest month",
    "nrr.overall_pct": "trailing 12 months", "nrr_pct": "trailing 12 months",
    "gross_churn.overall_pct": "trailing 12 months", "churn_pct": "trailing 12 months",
    "months": "latest computable quarter",
    "median_days": "all won deals", "iqr": "all won deals",
    "win_rate_pct": "closed deals",
    "current_customers": "active, latest month",
    "acv": "ARR ÷ active customers",
    "customers_needed": "at current ACV",
    "required_net_new_per_year": "to reach target ARR",
    "observed_net_new_per_year_12m": "last 12 months",
    "observed_net_new_per_year_24m": "last 24 months",
    "required_vs_observed_12m": "last 12 months",
    "required_vs_observed_24m": "last 24 months",
}

_QUARTER = re.compile(r"^\d{4}-Q[1-4]$")


def _label_segments(source_key: str) -> list:
    segs = [s for s in str(source_key).split(".") if s]
    if segs and segs[0] == "metrics":
        segs = segs[1:]
    # {"values": {"0": .., "3": ..}}: the age is data, the field is "values"
    if len(segs) > 1 and segs[-1].isdigit() and segs[-2] == "values":
        segs = segs[:-1]
    return segs


def _lookup(table: dict, segs: list) -> Optional[str]:
    for width in (2, 1):
        if len(segs) >= width:
            hit = table.get(".".join(segs[-width:]))
            if hit:
                return hit
    return None


def explicit_label(source_key: str) -> Optional[str]:
    """The mapped base label for a cited path, or None if the path has no entry."""
    return _lookup(LABEL_BY_PATH, _label_segments(source_key))


def label_for(source_key: str, fallback: Optional[str] = None) -> str:
    """Plain-English base label for a cited engine path (no qualifier).

    An unmapped path gets a humanised leaf ("overall_band" -> "Overall band")
    rather than the raw dotted path, so a new field degrades to something
    readable until it is given a proper entry.
    """
    label = explicit_label(source_key)
    if label:
        return label
    segs = _label_segments(source_key)
    if segs:
        return segs[-1].replace("_", " ").capitalize()
    return fallback or str(source_key)


def qualifier_for(source_key: str) -> Optional[str]:
    """The qualifier text (without brackets) for a cited path, if it needs one."""
    segs = _label_segments(source_key)
    qualifier = _lookup(QUALIFIER_BY_PATH, segs)
    # A row citing one specific quarter says which, instead of "latest quarter".
    quarter = next((s for s in segs if _QUARTER.match(s)), None)
    if quarter and qualifier == "latest computable quarter":
        return quarter
    return qualifier


def with_qualifier(label: str, qualifier: Optional[str]) -> str:
    """"NRR" + "latest month" -> "NRR (latest month)". One format, everywhere."""
    return f"{label} ({qualifier})" if qualifier else label


def display_name(source_key: str, fallback: Optional[str] = None) -> str:
    """The full name shown for a cited path: base label plus qualifier."""
    return with_qualifier(label_for(source_key, fallback), qualifier_for(source_key))


def metric_names_export() -> dict:
    """What `frontend/src/lib/metric_names.json` must contain."""
    return {"labels": dict(LABEL_BY_PATH), "qualifiers": dict(QUALIFIER_BY_PATH)}
