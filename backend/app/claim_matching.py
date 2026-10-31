"""Claim matching: every approved claim tested against the engine's computed metrics.

Spec: docs/specs/claim-matching.md. A pure module: it reads the register's candidate rows and the stored
`audits.results`, and returns one register row per claim with its metric, observed figure, gap, evidence
label and proposed gate. It imports nothing from `app.llm` and nothing reaches a model (CLAUDE.md rules
14, 17, 18); the deck text a row was found in (snippet, borrowed label) is read here to propose a metric
and a segment and is never copied into a row, except the name a cited label gives the segment (docs/design/segment-partitions.md). Only Python sets Verified or Contradicted.
"""
from __future__ import annotations

import calendar
import hashlib
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from . import deck_actuals, forecast_calc, payback_definition
from . import formatting as fmt
from .decks.claims import BASIS_CONFLICT, CASES as SCENARIO_CASES, review_flags

# The register's fields, in the order of the spec's section 6 (and the CSV header of section 7).
FIELDS = (
    "claim_id", "deck_file", "page_ref", "claim_type", "status", "deck_reading", "extraction_confidence", "claimed_value", "claimed_high",
    "claim_direction", "unit", "currency", "claimed_converted", "claimed_converted_high", "fx_rate", "fx_date", "period", "period_start", "period_end", "period_note", "segment", "segment_set_by", "metric",
    "metric_set_by", "direction", "observed_value", "observed_at", "observed_source", "observed_citation", "gap", "gap_normalised",
    "gap_kind", "gloss", "evidence_label", "reason", "tolerance", "rank", "value_at_stake_arr", "vas_reason", "shortfall",
    "overlaps_with", "evidence_analysis", "evidence_source_key", "gate_sentence", "gate_threshold",
    "gate_budget_decision", "gate_date", "gate_saved", "gate_metric_name", "gate_direction", "key_gate", "gate_needed", "gate_status",
    "as_of_month", "as_of_defaulted", "turnover_state", "turnover_note", "turnover_set_by", "turnover_reason",
    "implied_take_rate", "implied_take_rate_source", "turnover_suggested", "deck_revenue_note", "definition_check",
    "definition_question", "period_coverage", "months_missing", "growth_basis", "population", "figure_type", "required_unknown",
    "auto_approval", "basis", "scenario", "period_sort", "deck_status", "deck_only", "source", "details", "data_request",
    "group_id", "group_role", "relationship", "calc_lines", "calc_details",
)
# How the baseline CSV reads each field back (verdict-and-memo.md section 5); a field not listed is text.
FLOAT_FIELDS = frozenset({"implied_take_rate", "claimed_value", "claimed_high", "claimed_converted", "claimed_converted_high", "fx_rate",
                          "observed_value", "gap", "gap_normalised", "value_at_stake_arr",
                          "shortfall", "gate_threshold"})
INT_FIELDS = frozenset({"rank"})
BOOL_FIELDS = frozenset({"gate_saved", "key_gate", "gate_needed", "as_of_defaulted", "deck_only"})
JSON_FIELDS = frozenset({"details"})        # the details block of docs/design/deck-actuals.md section 3: JSON text in the baseline CSV
LIST_FIELDS = frozenset({"overlaps_with", "months_missing", "required_unknown", "calc_lines", "calc_details"})
SOURCE_FIELDS = frozenset({"observed_source"})

WHOLE, NOT_IN_DATA = "Whole company", "Not in the data"
NO_PERIOD = "no period stated"
# The one Unsupported left (evidence-labels.md section 2, simplified-flow.md): the plan implies a figure and no slide states it.
NO_CLAIMED_VALUE = "no claimed value"
# George, 2026-10-19 (issue #136, decision 3): a claim whose period cannot be read is Unverified with this text and is never read at
# the as-of month or the evidence end; the 7 Oct fallback to the whole company applies to the segment only.
PERIOD_NOT_READ = "Period not read – set it in the claim row"
# George, 2026-10-20 (finding A): the figures of one table cell whose header holds a different number of periods have none, and read this.
PERIOD_UNCLEAR = "Period unclear – confirm"
# George, 2026-10-23 (engine contract 8, decision on PR 171): the engine holds gross revenue churn as a trailing-12-month rate and as a monthly one.
# A churn claim worded monthly is tested against the month's rate, any other with a period against the trailing-12-month rate at the period
# end; a churn claim with neither wording nor period could be either, and is not tested.
CHURN_RATE_UNCLEAR_REASON = ("churn rate unclear: the trailing-12-month rate (Gross revenue churn) or the monthly rate (Monthly gross revenue churn)"
                             " – word it monthly or set the period")
# George, 2026-10-19 (issue #136, decision 2): a contract value (annual or total contract value, contracted revenue, contracted or
# committed ARR or MRR, CARR) is typed but not computed: never matched to engine revenue, Unsupported with this reason.
CONTRACT_VALUE = "Contract value"
CONTRACT_REASON = "Contract value – not computed by the app"
NO_REVENUE_SERIES = "Not computed – revenue series not available"     # no revenue_series: no observed figure, no question
# George, 2026-10-20: revenue per account, client, customer or user (ARPA, ARPU) is typed but not computed: never matched to engine revenue.
UNIT_ECONOMICS_REASON = "Unit economics – not computed by the app"
UNIT_ECONOMICS = {"arpa": "ARPA", "arpu": "ARPU"}      # claim type -> metric
FX_NEEDED = "FX rate needed"
USE_OF_FUNDS = "use_of_funds"
USE_OF_FUNDS_NOTE = "use of funds: an allocation share of the raise, no engine metric to test it against"
ACQUISITION_CHANNELS = "acquisition_channels"
ACQUISITION_NOTE = "acquisition channels: a count per platform, no engine metric to test it against"
# Claim types that are never matched, ranked, gated or put in the top 5, with the closed sentence each register row carries.
PRICING_NOTE = "pricing: a price the deck states, no engine metric to test it against"
UNTESTED_TYPES = {USE_OF_FUNDS: USE_OF_FUNDS_NOTE, ACQUISITION_CHANNELS: ACQUISITION_NOTE, "pricing": PRICING_NOTE}
# A claim read from a forecast table (chat-upload.md section 20): Unverified, never matched, ranked, gated or put in the top 5, with no
# value at stake and no overlaps (null), whatever its type. Its deck reading stays "forecast-file" after an edit.
FORECAST_FILE = "forecast_file"
FORECAST_READING = "forecast-file"
# A plan cell of a P&L read as a statement (docs/design/pnl-lines.md section 4): a claim with source "File <sheet>!<cell> (plan)", never Verified or
# Contradicted, tested as implied against observed rate, ranked by value at stake like a deck forecast and compared with the deck's forecast of the
# same metric and period. It is built from the engine's `pnl_lines.plan`, not stored.
PLAN_FILE = "plan_file"
PLAN_READING = "plan-file"
PLAN_NOTE = "plan in the file: never Verified or Contradicted; its implied rate is tested against the observed rate"
PLAN_DIFFERS = "plan in file differs from plan in deck"
PLAN_CLAIM_TYPES = {"Revenue": "revenue", "Cost of revenue": "cost_of_revenue", "S&M expense": "s_and_m", "Operating expenses": "opex",
                    "Gross margin": "gross_profit", "EBITDA": "ebitda"}      # one claim type per line: lines are never rivals for one year
PLAN_PERCENT_TYPES = {"share of revenue": {"gross_profit": "gross_profit", "gross_margin": "gross_profit", "ebitda": "ebitda"},      # plan measure → {deck type: plan type}
                      "growth": {"revenue": "revenue", "revenue_growth": "revenue"}}
PLAN_PERCENT_DECK = ("gross_margin", "revenue_growth")        # the percentage claim types that are not also money types
PLAN_DECK_TYPES = ("revenue", "gross_profit", "ebitda")        # the claim types whose deck forecast names one plan line (a cost claim does not)
FORECAST_NOTE = "Read from the forecast file, not yet tested against data"      # George, 2026-10-16
DIRECTION_ONLY = "direction only: the claim states no figure to test"
# George, 2026-10-23 (review of PR 164, H2): a best-case or worst-case figure of a deck page is stored and listed under Scenarios, never matched,
# ranked, gated or put in the top 5, with no value at stake and no overlaps (null), whatever its type. Only realistic / none are plan targets.
SCENARIO_NOTE = "{case} case: a scenario, not the plan target; not tested against data"
BEAT_PREFIX = "beat: observed beats the claim by "       # the reason of a Verified beat outside tolerance, its gloss follows
# Section 4.1 (George, 2026-10-14): a tested gap beyond this share of the claim, either way, asks the analyst "Same metric and
# period?" before the row gets a label. Adjustable; exactly at it the normal rule applies.
BIG_GAP_THRESHOLD = 0.5
# A rate is read in points, not as a share of the claim (George, 2026-10-14): its gap opens the check only beyond this many
# percentage points. Adjustable; exactly at it the normal rule applies.
BIG_GAP_RATE_POINTS = 10.0
DEFINITION_ASK, DEFINITION_ANSWERS = "ask", ("yes", "no")     # "ask": the row is a Definition check, a status with no label
DEFINITION_QUESTION = "Observed {observed}, claimed {claimed}. Same metric and period?"
DEFINITION_OPEN_REASON = "definition check: the gap is beyond {share} of the claim"
DEFINITION_OPEN_REASON_RATE = "definition check: the gap is beyond {points} percentage points"
DEFINITION_MISMATCH = "definition mismatch"
# A Users claim the parser typed from a qualified customers noun (deck-parser.md section 2, George, 2026-10-13); the label is
# two words of closed lists: the qualifier and the customers keyword. It is read against the paying customers and is Inconclusive
# (docs/specs/evidence-labels.md section 3): the figure is shown, it cannot confirm or contradict a count of other people.
QUALIFIED_REASON = "population differs: deck label '{label}' is not paying customers; the figure shown is paying customers"
QUALIFIED_NO_FIGURE = "population differs: deck label '{label}' is not paying customers"     # Unsupported: no figure to show
POPULATION_PREFIX = "population differs: "
# docs/specs/evidence-labels.md: the five evidence statuses in screen order, the memo's grouping of them, and the two explainers.
# frontend/src/lib/evidence_labels.json holds the same, pinned by tests/test_interface_contracts.py.
EVIDENCE_STATUSES = ("Verified", "Contradicted", "Inconclusive", "Unverified", "Unsupported")
INCONCLUSIVE = "Inconclusive"
MEMO_GROUPS = {"Unverified": ["Unverified", "Inconclusive"]}
EXTRACTION_EXPLAINER = "How confidently the app extracted and linked the figure to its source. This does not verify the company’s claim."
EVIDENCE_EXPLAINER = "How this claim compares with the company data supplied for this audit. Agreement is not independent verification."
NOT_VERIFIED = ("Unverified", "Inconclusive", "Unsupported", "Contradicted")      # the labels whose row needs a gate
# docs/specs/dates-and-periods.md section 4: claim-period coverage, measured on the months the observed figure reads.
COVERED, PARTLY_COVERED, NOT_COVERED = "Covered", "Partly covered", "Not covered"
NOT_COVERED_REASON = "claim period not in supplied data: {detail}"
PARTLY_REASON = "claim period partly covered (months missing: {months})"
AFTER_SOURCE_DETAIL = "after the latest valid source period, {month}"
# docs/specs/claim-types-and-correction.md section 2: the fields a claim must know before it is matched.
FIGURE_TYPES = ("actual", "target", "unknown")
REQUIRED_REASON = "required field unknown: {fields}; set it with Edit in the claims list"
TARGET_REASON = "target figure: the deck states a plan for this period, not a result"
POPULATION_REASON = "population differs: the claim counts {population}; the figure shown counts {measured}"
POPULATION_WORDS = {"paying": "paying customers", "registered": "registered users", "active": "active users",
                    "free": "free users", "trial": "trial users", "all": "all customers",
                    "deals won": "deals won", "all closed": "all closed deals", "open": "open deals"}
METRIC_POPULATION = {"Customer count": "paying", "Customer growth": "paying", "Median sales cycle": "deals won",
                     "Win rate": "all closed"}
POPULATION_TYPES = ("customers", "users", "user_growth")
# The types whose figure is an amount: with no currency and no unit, the currency is the field still unknown.
MONEY_TYPES = ("revenue", "arr", "mrr", "costs", "cost_of_revenue", "s_and_m", "opex", "burn", "cash", "gross_profit", "ebitda", "net_profit", "ltv", "cac", "arpa", "arpu", "pipeline", "pricing")
# The types whose period may stay unknown (the plan's table: optional or "–").
PERIOD_OPTIONAL_TYPES = ("market", "use_of_funds", "acquisition_channels", "product", "pricing")
PERIOD_MISSING = "period missing; set it with Edit"
# Design note section 3 (docs/specs/forecast-and-payback.md): a forecast reads its calculation, not a repeated disclaimer.
FORECAST_REASON = "Forecast: {text}"
FORECAST_NO_CALC = "no comparison is calculated for this metric"
FORECAST_METRICS = ("Revenue", "ARR", "MRR", "Customer count")        # the metrics forecast_calc reads
FORECAST_BASES = ("projection", "scenario")
ANNUAL_ANALYSIS = "Yearly basis (P&L summary)"          # forecast-and-payback.md section 4: the annual CAC payback of a P&L read as a statement
ANNUAL_KEYS = {payback_definition.REVENUE_GROWTH: "yearly_basis.years.cac_payback_months",
               payback_definition.NET_NEW_ARR: "yearly_basis.years.cac_payback_net_new_arr_months"}
ANNUAL_NOT_CALCULATED = "annual payback not calculated for {year}: {reason}"
YEARLY_REVENUE_BASED = "yearly, revenue-based"      # the label of a payback read from yearly columns (docs/design/pnl-lines.md section 6)
ANNUAL_NO_YEAR = "no actual year in the yearly P&L"
# dates-and-periods.md section 3 (2026-10-28): a deck year matches a yearly column only when both end in the same month.
PERIOD_NOT_COVERED = "period not covered: the claim's period ends {claim}, the file's {name} ends {file}"
POPULATION_REASON_FC = "population differs: the claim counts {claimed}, the series counts {measured}"
# Section 5: growth claims. The basis is the analyst's, else the parser's, else read from the claim's own words on read.
GROWTH_BASES = ("mom", "yoy", "annualised", "cumulative")
GROWTH_TYPES = ("revenue_growth", "growth", "user_growth")
GROWTH_UNKNOWN_REASON = "growth basis unknown: set the growth basis"
GROWTH_WINDOW_REASON = "growth window not stated"
GROWTH_BASE_REASON = "growth base is not positive"
GROWTH_RULES = {"mom": "MoM growth = v(e) ÷ v(e−1) − 1", "yoy": "YoY growth = v(e) ÷ v(e−12) − 1",
                "yoy_sum": "YoY growth = revenue of the period ÷ revenue of the same months a year earlier − 1",
                "cumulative": "Cumulative growth = v(e) ÷ v(s) − 1",
                "annualised": "Annualised growth = (v(e) ÷ v(s))^(12 ÷ (e − s)) − 1"}
SUGGESTION = "AI suggestion, not verified"
ANALYST_ENTERED = "analyst-entered"
ADDED_FROM_DECK = "added-from-deck"     # a line the analyst picked on the stored deck page (claim-types-and-correction.md section 5)
DAYS_PER_WEEK, DAYS_PER_MONTH = 7.0, 30.44
RATE_TOLERANCE_PP, AMOUNT_TOLERANCE = 1.0, 0.05
BUDGET_DECISION_MAX = 200
GATE_METRIC_MAX = 100
GATE_DIRECTIONS = ("at least", "at most")
NO_APP_METRIC = ("no metric", "metric does not fit the claim's unit")      # the rows that need the analyst's metric name

# Table 2a. kind: how the claim's period reads the metric (table 2b): "sum" over the period's months, the value in the
# period's end "month", one calendar "quarter", or the "asof" figure. `seg`: the engine splits it by segment.
# `missing`: words of the engine's Missing Data entry that stand for the metric.
MONTHLY_CHURN = "Monthly gross revenue churn"      # the monthly rate of gross_churn.monthly_series; "Gross revenue churn" is the trailing-12-month one
METRICS: Dict[str, dict] = {
    "Revenue": dict(kind="sum", unit="currency", direction="higher", seg=True, missing=("arr / mrr",)),
    "ARR": dict(kind="month", unit="currency", direction="higher", seg=True, missing=("arr / mrr",)),
    "MRR": dict(kind="month", unit="currency", direction="higher", seg=True, missing=("arr / mrr",)),
    "Customer count": dict(kind="month", unit="count", direction="higher", seg=True, missing=("arr / mrr",)),
    "New MRR": dict(kind="quarter", unit="currency", direction="higher", seg=False, missing=("arr / mrr",)),
    "NRR (12-month)": dict(kind="month", unit="%", direction="higher", seg=True, missing=("nrr",)),
    "Gross revenue churn": dict(kind="month", unit="%", direction="lower", seg=False, missing=("gross revenue churn",)),
    MONTHLY_CHURN: dict(kind="month", unit="%", direction="lower", seg=False, missing=("gross revenue churn",)),
    "ACV": dict(kind="asof", unit="currency", direction="higher", seg=True, missing=("arr / mrr",)),
    "Median sales cycle": dict(kind="asof", unit="days", direction="lower", seg=True, missing=("sales cycle",)),
    "Win rate": dict(kind="asof", unit="%", direction="higher", seg=False, missing=("win rate",)),
    "Gross margin": dict(kind="quarter", unit="%", direction="higher", seg=False, missing=("cac payback",)),
    "CAC payback": dict(kind="quarter", unit="months", direction="lower", seg=False, missing=("cac payback",)),
    # Section 11: no engine source exists, so a claim measured here is always Unsupported.
    "Transaction volume": dict(kind="sum", unit="currency", direction="higher", seg=False, missing=()),
    # Issue #136 (George, 2026-10-19): typed, never computed; always Unsupported, "Contract value – not computed by the app".
    "Contract value": dict(kind="sum", unit="currency", direction="higher", seg=False, missing=()),
    # George, 2026-10-20: unit economics, typed and never computed; always Unsupported, "Unit economics – not computed by the app".
    "ARPA": dict(kind="sum", unit="currency", direction="higher", seg=False, missing=()),
    "ARPU": dict(kind="sum", unit="currency", direction="higher", seg=False, missing=()),
    # dates-and-periods.md section 5: growth of a monthly series on the claim's basis, in percentage points
    "Revenue growth": dict(kind="growth", unit="%", direction="higher", seg=False, missing=("arr / mrr",), base="Revenue"),
    "ARR growth": dict(kind="growth", unit="%", direction="higher", seg=False, missing=("arr / mrr",), base="ARR"),
    "MRR growth": dict(kind="growth", unit="%", direction="higher", seg=False, missing=("arr / mrr",), base="MRR"),
    "Customer growth": dict(kind="growth", unit="%", direction="higher", seg=False, missing=("arr / mrr",), base="Customer count"),
    # docs/design/deck-actuals.md: a deck's "3.3 x" is the revenue of a year over the revenue of the year before, recomputed from the files, tested at ±5%
    "Revenue growth multiple": dict(kind="multiple", unit="x", direction="higher", seg=False, missing=("arr / mrr",), base="Revenue"),
}
GROWTH_MULTIPLE = "Revenue growth multiple"
MULTIPLE_RULE = "Growth multiple = revenue of the year ÷ revenue of the year before"
YEARLY_REVENUE_KEY = "yearly_basis.years.revenue"
# The metric_periods block each metric's figures are read from (dates-and-periods.md section 3); the revenue-file ones end at the
# latest valid source period.
PERIOD_BLOCK = {"Revenue": "revenue_series", "ARR": "mrr_series", "MRR": "mrr_series", "Customer count": "customers_series",
                "New MRR": "new_mrr_by_quarter", "NRR (12-month)": "nrr", "Gross revenue churn": "gross_churn",
                MONTHLY_CHURN: "gross_churn_monthly",
                "Gross margin": "cac_payback", "CAC payback": "cac_payback"}
REVENUE_FILE_METRICS = ("Revenue", "ARR", "MRR", "Customer count", "New MRR")
VOLUME = "Transaction volume"
VOLUME_REASON = "no engine volume source for transaction volume"
TURNOVER_REASONS = ("deck_says_gross_revenue", "deck_says_processed_volume", "file_confirms", "other")
TURNOVER_CHOICES = ("revenue", "volume")
VOLUME_CHOICE = "volume"
CONTRADICTORY_ANSWERS = (("volume", "deck_says_gross_revenue"), ("revenue", "deck_says_processed_volume"))
GROSS_REVENUE_NOTE = "Gross revenue (turnover)"
ASK_NOTE = "Revenue or volume? Confirm below"
ASK_REASON = "turnover or volume: confirm Revenue or Volume"
SALES_CHOICES = ("revenue", "bookings")          # the answer to "Is 'Sales' in this deck revenue or bookings?", kept per deck on the audit
SALES_ASK_REASON = "sales: confirm revenue or bookings"
BOOKINGS_REASON = "bookings not in the data"
# A money claim labelled Sales: the label is "Sales" alone or "Sales by <something>" (product, quarter ...), optionally with a unit in brackets or a
# word in front ("Total sales"). "Sales cycle" and "Sales & Marketing" are not it; neither is any label that names revenue, ARR or bookings.
_SALES_LABEL = re.compile(r"(?i)^\s*(?:(?:total|net|gross)\s+)?sales(?:\s+by\s+[a-z][\w /&-]*?)?\s*(?:\([^)]*\))?\s*$")
NO_METRIC = "none"                      # what the analyst picks to say "no metric fits"

_DURATIONS = ("days", "weeks", "months", "years")
_CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}

_NEW_MRR = re.compile(r"(?i)\bnew mrr\b")
_MRR = re.compile(r"\bMRR\b|(?i:\bmonthly recurring revenue\b)")
_ARR = re.compile(r"\bARR\b|(?i:\bannual recurring revenue\b)")
_REVENUE = re.compile(r"(?i)\brevenue\b")
_TURNOVER = re.compile(r"(?i)\b(?:turnover|GMV|TPV|gross merchandise (?:value|volume)|(?:total )?(?:trading|payment|transaction) volume)\b")
_TAKE_RATE = re.compile(r"(?i)\btake[- ]rates?\b")
_RECURRING = re.compile(r"(?i)\b(?:annual|monthly) recurring revenue\b")
_NRR = re.compile(r"\bNRR\b|(?i:\bnet (?:revenue )?retention\b)")
_CHURN = re.compile(r"(?i)\b(?:revenue|gross) churn\b")
_ACV = re.compile(r"\bACVs?\b")
_SALES_CYCLE = re.compile(r"(?i)\bsales cycles?\b")
_WIN_RATE = re.compile(r"(?i)\bwin rates?\b")
_PAYBACK = re.compile(r"(?i)\bpayback\b")
_MONTHLY = re.compile(r"(?i)\bmonthly\b|\bper month\b|\ba month\b|(?:\bper\s|/\s?)mo\b|\bMoM\b")
_CUSTOMERS = re.compile(r"(?i)\b(?:customers?|clients?|subscribers?|accounts?)\b")


# --- months and periods ----------------------------------------------------------------------------------------------

def _mi(month: str) -> int:
    """'2024-02' -> months since year 0."""
    y, m = month[:7].split("-")
    return int(y) * 12 + int(m) - 1


def _ms(index: int) -> str:
    return f"{index // 12}-{index % 12 + 1:02d}"


def _month_of(day: Optional[str]) -> Optional[int]:
    return _mi(str(day)[:7]) if day else None


def _label_of(index: int) -> str:
    return f"{calendar.month_abbr[index % 12 + 1]} {index // 12}"


def _quarter(start: int, end: int) -> Optional[str]:
    """'2023-Q4' when the months start..end are one calendar quarter."""
    if end - start == 2 and start % 3 == 0:
        return f"{start // 12}-Q{start % 12 // 3 + 1}"
    return None


def _short(metric: str) -> str:
    """'NRR (12-month)' -> 'NRR': how a reason names its metric."""
    return re.sub(r"\s*\(.*\)", "", metric)


def _month_ranges(indexes: List[int]) -> str:
    """'2022-04 to 2022-12, 2023-03': the months, joined into runs."""
    runs, first = [], indexes[0]
    for prev, m in zip(indexes, indexes[1:] + [None]):
        if m is None or m != prev + 1:
            runs.append(_ms(first) if first == prev else f"{_ms(first)} to {_ms(prev)}")
            first = m
    return ", ".join(runs)


def _quarter_first_month(quarter: str) -> str:
    year, q = quarter.split("-Q")
    return f"{year}-{(int(q) - 1) * 3 + 1:02d}"


# --- units, tolerance, gloss -------------------------------------------------------------------------------------------

def _claim_unit(c: dict) -> Optional[str]:
    """currency, %, days, weeks, months or count: what the claimed figure is measured in."""
    if c.get("currency"):
        return "currency"
    unit = (c.get("unit") or "").strip().lower()
    if unit == "%":
        return "%"
    if unit in ("x", "×"):
        return "x"
    if re.fullmatch(r"(?:day|week|month|year)s?", unit):
        return unit.rstrip("s") + "s"
    if re.fullmatch(r"hours?", unit):
        return None                                 # not a duration the spec converts
    return "count"


def _fits(metric_unit: str, claim_unit: Optional[str]) -> bool:
    if metric_unit in ("days", "months"):
        return claim_unit in _DURATIONS
    return claim_unit == metric_unit


def _to_metric_unit(value: Optional[float], claim_unit: str, metric_unit: str) -> Optional[float]:
    """A duration in days (7 a week, 30.44 a month, 12 months a year) or months; other units unchanged."""
    if value is None or metric_unit not in ("days", "months"):
        return value
    days = {"days": 1.0, "weeks": DAYS_PER_WEEK, "months": DAYS_PER_MONTH, "years": 12 * DAYS_PER_MONTH}[claim_unit] * value
    return days if metric_unit == "days" else days / DAYS_PER_MONTH


def tolerance_text(metric: str) -> str:
    return "±1 pp" if METRICS[metric]["unit"] == "%" else "±5%"


def within_tolerance(metric: str, gap: float, claimed: float) -> bool:
    """±5% of the claimed value for amounts, counts and durations; ±1 percentage point for rates. The boundary is Verified."""
    tolerance = RATE_TOLERANCE_PP if METRICS[metric]["unit"] == "%" else AMOUNT_TOLERANCE * abs(claimed)
    return round(abs(gap), 9) <= round(tolerance, 9)


_NUMBER_WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " \
                "seventeen eighteen nineteen twenty".split()


def _shown(value: float) -> str:
    """A number by the one display rule (app/formatting.display_number, read-check-review.md section 11.5)."""
    return fmt.display_number(Decimal(str(value)))


def _money(amount: float, currency: Optional[str], whole_millions: bool = False) -> str:
    symbol = _CURRENCY_SYMBOLS.get(currency or "", f"{currency} " if currency else "")
    amount = abs(amount)
    if whole_millions and amount >= 1_000_000:
        return f"{symbol}{_shown(amount / 1_000_000)}M"
    return f"{symbol}{_shown(amount)}"


def gloss(unit: str, kind: str, gap: float, currency: Optional[str], direction: Optional[str], by: Optional[str]) -> str:
    """The gap in words, one rule for every metric (spec section 3): the observed figure against the claimed one in plain
    words, the kind in brackets. `gap` is signed: positive a miss, negative a beat; for "to go" it is claimed - observed."""
    if round(gap, 9) == 0:
        return "as claimed"
    size = abs(gap)
    # a miss is above the claim when lower is better, a beat when higher is better; a to-go is always claimed - observed
    above = gap < 0 if kind == "to go" or direction == "higher" else gap > 0
    higher, lower = {"days": ("longer", "shorter"), "months": ("longer", "shorter"), "count": ("more", "fewer")}.get(
        unit, ("higher", "lower"))
    if unit in ("days", "months"):
        amount = f"{_shown(size)} {unit}"
    elif unit == "%":
        amount = f"{_shown(size)} points"
    elif unit == "count":
        n = _shown(size)
        amount = f"{n} customer{'' if n == '1' else 's'}"
    elif unit == "x":
        amount = f"{_shown(size)}x"
    else:
        amount = _money(size, currency, whole_millions=kind == "to go")
    text = f"{amount} {higher if above else lower}"
    if unit == "days" and kind != "beat" and above:
        weeks = int(size / DAYS_PER_WEEK + 0.5)
        text += ", under a working week" if weeks == 0 else \
            f", {_NUMBER_WORDS[weeks] if weeks < len(_NUMBER_WORDS) else weeks} working week{'s' if weeks != 1 else ''}"
    return f"{text} ({f'to go by {by}' if kind == 'to go' else kind})"


def _format(unit: str, value: float, currency: Optional[str]) -> str:
    if unit == "currency":
        return _money(value, currency)
    if unit == "%":
        return f"{_shown(value)}%"
    if unit in ("days", "months"):
        return f"{_shown(value)} {unit}"
    if unit == "x":
        return f"{_shown(value)}x"
    return _shown(value)


def _one_place(value: float) -> str:
    """One decimal place, half up as the memo's number check reads it (a stored 120.55 is 120.6, not the binary float's 120.5)."""
    return str(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# --- what the engine holds ----------------------------------------------------------------------------------------------

def _points(fraction: Optional[float]) -> Optional[float]:
    """The engine holds a percent as its fraction (1.0641); a claim states percent points (106.41)."""
    return None if fraction is None else round(fraction * 100, 2)


def _source(block: Optional[dict], rule: Optional[str] = None) -> Optional[dict]:
    src = (block or {}).get("source") or {}
    if not src:
        return None
    return {"file": src.get("file"), "sheet": src.get("sheet"), "rows": src.get("rows"), "rule": rule or src.get("rule")}


class _Figures:
    """One metric read from the stored results: its months or quarters, its as-of figure, its source."""

    def __init__(self, results: dict, metric: str, segment: str):
        self.results, self.metric, self.segment = results, metric, segment
        self.whole = segment == WHOLE

    def monthly(self) -> Optional[Tuple[Dict[str, Optional[float]], dict, Optional[str]]]:
        """({month: value}, source, why a month has no value) for a metric read by month; None when the engine holds none."""
        r, m = self.results, self.metric
        if m in ("ARR", "MRR", "Customer count", "Revenue"):
            key = {"Revenue": "revenue_series", "Customer count": "customers_series"}.get(m, "mrr_series")
            series = r.get(key) or {}
            if not series.get("months"):
                return None
            if not self.whole and self.segment not in series.get("segments", ()):
                return {}, None, "segment not in the data"
            field = "total" if self.whole else self.segment
            factor = 12 if m == "ARR" else 1
            values = {d["month"]: (round(d[field] * factor, 2) if isinstance(d.get(field), (int, float)) and m in ("ARR", "Revenue")
                                   else d.get(field)) for d in series["data"]}
            if m == "ARR":
                source = _source(r.get("arr"), "ARR = current-month recurring MRR × 12")
            elif m == "MRR":
                source = _source(r.get("arr"), "MRR = current-month recurring MRR")
            else:
                source = _source(series)
            return values, source, None
        if m in ("NRR (12-month)", "Gross revenue churn", MONTHLY_CHURN):
            block = r.get("nrr" if m == "NRR (12-month)" else "gross_churn")
            if not block:
                return None
            field = "nrr_pct" if m == "NRR (12-month)" else "churn_pct"
            series = block.get("monthly_series" if m == MONTHLY_CHURN else "series") or ()
            return {d["month"]: _points(d.get(field)) for d in series}, _source(block), block.get("reason")
        return None

    def asof(self) -> Optional[Tuple[Optional[float], dict, Optional[str]]]:
        """(value, source, reason it has none) for a metric read at the as-of month; None when the engine holds none."""
        r, m = self.results, self.metric
        block = {"NRR (12-month)": r.get("nrr"), "ACV": r.get("acv_path"), "Median sales cycle": r.get("sales_cycle"),
                 "Win rate": r.get("win_rate")}.get(m)
        if not block:
            return None
        field = {"NRR (12-month)": "nrr_pct", "ACV": "acv", "Median sales cycle": "median_days", "Win rate": "win_rate_pct"}[m]
        convert = _points if m in ("NRR (12-month)", "Win rate") else (lambda v: v)
        if self.whole:
            value = block.get("overall_pct") if m == "NRR (12-month)" else block.get(field)
            return convert(value), _source(block), block.get("reason")
        entry = (block.get("by_segment") or {}).get(self.segment)
        if entry is None:
            return None, None, "segment not in the data"
        return convert(entry.get(field)), _source(block), entry.get("reason")

    def quarters(self) -> Optional[Tuple[Dict[str, dict], dict]]:
        """{quarter: {"value", "reason", "partial"}} and the source, for a metric read by calendar quarter."""
        r, m = self.results, self.metric
        if m == "New MRR":
            block = r.get("new_mrr_by_quarter")
            if not block:
                return None
            return ({q: {"value": v.get("new_mrr"), "reason": None, "partial": bool(v.get("partial"))} for q, v in block.items()},
                    _source(r.get("arr"), "New MRR = MRR in the quarter's last month of the customers who started in the quarter"))
        cac = r.get("cac_payback")
        if not cac or not cac.get("quarters"):
            return None
        lag = f"L{cac.get('default_l', 1)}"
        out = {}
        for q, v in cac["quarters"].items():
            if m == "Gross margin":
                out[q] = {"value": _points(v.get("gross_margin_pct")), "reason": f"no P&L for {q}", "partial": bool(v.get("partial"))}
            else:
                out[q] = {"value": (v.get(lag) or {}).get("months"), "reason": (v.get(lag) or {}).get("reason"),
                          "partial": bool(v.get("partial"))}
        rule = "Gross margin = (revenue - cost of revenue) ÷ revenue, from the P&L" if m == "Gross margin" else None
        return out, _source(cac, rule)

    def headline(self, quarters: Dict[str, dict]) -> Optional[str]:
        """The quarter a claim with no period, or a forecast, is read at: CAC payback's headline quarter, else the latest complete one."""
        if self.metric == "CAC payback":
            return (self.results.get("cac_payback") or {}).get("headline_quarter")
        complete = [q for q in sorted(quarters) if not quarters[q]["partial"] and quarters[q]["value"] is not None]
        return complete[-1] if complete else None


def _missing(results: dict, metric: str) -> Optional[str]:
    """The engine's own words for what would give the metric: its Missing Data entry's unlocked_by."""
    for item in results.get("missing_data") or ():
        name = str(item.get("metric") or "").lower()
        if any(word in name for word in METRICS[metric]["missing"]) and item.get("unlocked_by"):
            return str(item["unlocked_by"])
    return None


# Table 2.3 of verdict-and-memo.md: where a register figure sits in the stored results. `{seg}` is a segment, `{q}` the
# quarter the figure was read at, `{l}` the default lag of CAC payback. The contract test pins every key to a path
# MetricsPayload declares (`*` for a data key).
EVIDENCE: Dict[str, Tuple[str, str, Optional[str]]] = {
    "Revenue": ("Revenue by month", "revenue_series.data.total", "revenue_series.data.{seg}"),
    GROWTH_MULTIPLE: ("Revenue by month", "revenue_series.data.total", None),
    "ARR": ("Monthly MRR by Segment", "mrr_series.data.total", "mrr_series.data.{seg}"),
    "MRR": ("Monthly MRR by Segment", "mrr_series.data.total", "mrr_series.data.{seg}"),
    "Customer count": ("Customers", "customers_series.data.total", "customers_series.data.{seg}"),
    "New MRR": ("New MRR by quarter", "new_mrr_by_quarter.{q}.new_mrr", None),
    "NRR (12-month)": ("NRR", "nrr.series.nrr_pct", "nrr.by_segment.{seg}.nrr_pct"),
    "Gross revenue churn": ("Gross revenue churn", "gross_churn.series.churn_pct", None),
    MONTHLY_CHURN: ("Gross revenue churn", "gross_churn.monthly_series.churn_pct", None),
    "ACV": ("Path to Plan", "acv_path.acv", "acv_path.by_segment.{seg}.acv"),
    "Median sales cycle": ("Sales cycle", "sales_cycle.median_days", "sales_cycle.by_segment.{seg}.median_days"),
    "Win rate": ("Win rate", "win_rate.win_rate_pct", None),
    "Gross margin": ("CAC Payback by Quarter", "cac_payback.quarters.{q}.gross_margin_pct", None),
    "CAC payback": ("CAC Payback by Quarter", "cac_payback.quarters.{q}.L{l}.months", None),
    "Revenue growth": ("Revenue by month", "revenue_series.data.total", None),
    "ARR growth": ("Monthly MRR by Segment", "mrr_series.data.total", None),
    "MRR growth": ("Monthly MRR by Segment", "mrr_series.data.total", None),
    "Customer growth": ("Customers", "customers_series.data.total", None),
}
MISSING_KEY = "missing_data"


def evidence_key(metric: str, segment: str, observed_at: Optional[str], default_l: int = 1) -> Optional[Tuple[str, str]]:
    """(analysis, source key) of a figure the register read, or None when the metric has no row in table 2.3."""
    entry = EVIDENCE.get(metric)
    if not entry:
        return None
    analysis, whole, by_segment = entry
    key = whole if segment == WHOLE or by_segment is None else by_segment
    return analysis, key.format(seg=segment, q=observed_at or "", l=default_l)


def period_words(observed_at: Optional[str]) -> Optional[str]:
    """An observed period in month names (issue #136): "2024-02" -> "Feb 2024"; "2023-Q4" and "2023-10 to 2023-12" -> "Oct–Dec 2023";
    "2022-04 to 2023-03" -> "Apr 2022–Mar 2023"; a comparison keeps its "vs"; a note in brackets stays. Any other text stands."""
    if not observed_at:
        return observed_at

    def month(m: str) -> str:
        return _label_of(_mi(m))

    def span(first: str, last: str) -> str:
        if first == last:
            return month(first)
        if first[:4] == last[:4]:
            return f"{calendar.month_abbr[int(first[5:7])]}–{month(last)}"
        return f"{month(first)}–{month(last)}"

    def one(text: str) -> str:
        text = text.strip()
        if _QUARTER.match(text):
            first = _mi(_quarter_first_month(text))
            return span(_ms(first), _ms(first + 2))
        found = re.fullmatch(r"(\d{4}-\d{2}) to (\d{4}-\d{2})(?P<note> \(.*\))?", text)
        if found:
            return span(found.group(1), found.group(2)) + (found.group("note") or "")
        return month(text) if _MONTH.match(text) else text
    return " vs ".join(one(part) for part in observed_at.split(" vs "))


def citation(source_key: Optional[str], source: Optional[dict], observed_at: Optional[str]) -> Optional[str]:
    """The citation beside an observed figure (George, 2026-10-19, issue #136): "(source key, sheet, rows, period)", the period in
    month names; a part that is unknown is left out. None with no source key and no source."""
    src = source or {}
    parts = [source_key, src.get("sheet"), src.get("rows"), period_words(observed_at)]
    kept = [str(p) for p in parts if p]
    return f"({', '.join(kept)})" if kept else None


def _missing_item(results: dict, metric: str) -> Optional[dict]:
    """The engine's Missing Data item that stands for the metric (the one `_missing` reads `unlocked_by` from)."""
    for item in results.get("missing_data") or ():
        name = str(item.get("metric") or "").lower()
        if any(word in name for word in METRICS[metric]["missing"]) and item.get("unlocked_by"):
            return item
    return None


def format_figure(unit: Optional[str], value: float, currency: Optional[str], unit_text: Optional[str] = None) -> str:
    """A figure in the unit it is measured in (the metric's unit, or the claim's own): the register's one number format."""
    if unit in ("currency", "%", "days", "months", "count", "x"):
        return _format(unit, value, currency)
    return f"{_shown(value)} {unit}" if unit else f"{_shown(value)}{' ' + unit_text if unit_text else ''}"


def as_of_date(as_of: Optional[str]) -> Optional[str]:
    """The as-of month as a date: its last day ("2026-06" -> "2026-06-30"); a full date stands."""
    if not as_of:
        return None
    if len(str(as_of)) >= 10:
        return str(as_of)[:10]
    year, month = (int(p) for p in str(as_of)[:7].split("-"))
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def fx_view(c: dict, settings: dict, as_of: Optional[str]) -> Optional[dict]:
    """{"rate", "date", "currency"} for a claimed amount in a currency other than the audit's: the saved rate to the
    reporting currency (None when none is saved: "FX rate needed") and the date it applies at, the as-of month's last
    day. None for any other claim."""
    currency, reporting = c.get("currency") or None, settings.get("reporting_currency")
    if not currency or currency == reporting or _claim_unit(c) != "currency":
        return None
    rate = (settings.get("fx") or {}).get(currency)
    return {"rate": rate, "date": as_of_date(as_of), "currency": reporting}


def fx_date_text(day: Optional[str]) -> str:
    """'2026-06-30' -> '30 Jun 2026'; '' for a date that is missing or not an ISO date."""
    try:
        d = date.fromisoformat(str(day)[:10])
    except ValueError:
        return ""
    return f"{d.day} {calendar.month_abbr[d.month]} {d.year}"


def converted_note(row: dict, money) -> str:
    """' (171,000 EUR at 1.14, 30 Jun 2026)': a claim in another currency at the saved rate, both ends of a range, in the
    audit's currency as `money` writes an amount. '' for a claim in the audit's currency or with no saved rate."""
    low, high = row.get("claimed_converted"), row.get("claimed_converted_high")
    if low is None or row.get("fx_rate") is None:
        return ""
    text = money(low) if high is None else f"{money(low)}–{money(high)}"
    when = fx_date_text(row.get("fx_date"))
    return f" ({text} at {fmt.fmt_exact(row['fx_rate'])}{', ' + when if when else ''})"


def _claimed_text(c: dict) -> str:
    """The claim's figure in its own unit: what a gate sentence says was claimed."""
    unit, currency = _claim_unit(c), c.get("currency") or None
    low, high = c.get("value"), c.get("value_high")
    if low is None:
        return f"{c['claim_direction']} (no figure)" if c.get("claim_direction") else "—"
    text = format_figure(unit, low, currency) if unit != "currency" else _money(low, currency)
    if high is not None:
        end = format_figure(unit, high, currency) if unit != "currency" else _money(high, currency)
        text = f"{text}–{end}"
    return text


def needs_metric_name(row: dict) -> bool:
    """Whether a row's gate is saved only with the analyst's metric name and direction: the row has no app metric (none set, or
    one that does not fit the claim's unit), or the app's metric counts another population than the claim (evidence-labels.md
    section 3). The screen asks for the two fields by the same rule."""
    return row.get("metric") not in METRICS or row.get("reason") in NO_APP_METRIC \
        or str(row.get("reason") or "").startswith(POPULATION_PREFIX)


def _is_saved(inputs: dict, needs_name: bool) -> bool:
    """The analyst edited the gate: threshold and date are filled (the budget decision is optional, simplified-flow.md); a row with no app
    metric also needs the metric and the direction."""
    saved = inputs.get("gate_threshold") is not None and bool(inputs.get("gate_date"))
    if needs_name:
        saved = saved and bool(inputs.get("gate_metric_name")) and inputs.get("gate_direction") in GATE_DIRECTIONS
    return saved


# --- turnover and transaction volume (spec section 11) ------------------------------------------------------------

def mentions_take_rate(deck) -> bool:
    """Whether a parsed deck (any nesting of dicts, lists and strings) says "take rate" anywhere. Python reads the stored deck text; only this yes or no is used and nothing is stored or sent."""
    if isinstance(deck, str):
        return bool(_TAKE_RATE.search(deck))
    if isinstance(deck, dict):
        return any(mentions_take_rate(v) for v in deck.values())
    if isinstance(deck, (list, tuple)):
        return any(mentions_take_rate(v) for v in deck)
    return False


def turnover_key(c: dict) -> str:
    """What an audit answer to the turnover question is kept under: the turnover term and the period, hashed. No deck text."""
    import hashlib
    text = f"{c.get('snippet') or ''} {c.get('label_from') or ''}"
    found = _TURNOVER.search(text)
    term = re.sub(r"\s+", " ", found.group(0).lower()) if found else ""
    raw = f"{term}|{c.get('period_start') or ''}|{c.get('period_end') or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _is_turnover_claim(c: dict, text: str) -> bool:
    return c.get("claim_type") == "revenue" and bool(_TURNOVER.search(text)) and not (
        _NEW_MRR.search(text) or _MRR.search(text) or _ARR.search(text))


def _file_revenue(results: dict, segment: str, start: Optional[int], end: Optional[int],
                  as_of_i: Optional[int], forecast: bool) -> Tuple[Optional[float], Optional[dict]]:
    """(the revenue file's revenue for the claim period and segment, its source), or (None, None) when no file covers the
    period: no revenue file, months missing, no period, or a forecast (section 11 point 4). `forecast` is the claim's classification."""
    if as_of_i is None or start is None or end is None or forecast:
        return None, None
    got, _, src, _ = _observe(_Figures(results, "Revenue", segment), METRICS["Revenue"], "Revenue", start, end, as_of_i, forecast=False)
    return (float(got), src) if isinstance(got, (int, float)) else (None, None)


def _turnover(c: dict, inputs: dict, results: dict, settings: dict, rate: Optional[float], start: Optional[int],
              end: Optional[int], as_of_i: Optional[int], segment: str = WHOLE, forecast: bool = False) -> dict:
    """Section 11: whether a turnover claim is revenue, transaction volume or still a question. Only the analyst's answer
    makes it revenue or volume (amended 2026-10-09, George): until then it asks, whatever the revenue file or the deck
    says. Returns state, metric, note, set_by, reason, an optional verdict (label, reason), `fx_needed`, `suggested`
    ("volume" when no file covers the period and the deck says "take rate") and the file revenue for the period (of the
    claim's segment) when one covers it. `rate` is None when the claim's currency has no saved rate."""
    low = c.get("value")
    file_revenue, source = _file_revenue(results, segment, start, end, as_of_i, forecast)
    choice, reason, by = inputs.get("turnover_as"), inputs.get("turnover_reason"), "analyst"
    if choice not in TURNOVER_CHOICES:
        saved = (settings.get("turnover_choices") or {}).get(turnover_key(c)) or {}
        choice, reason = (saved.get("as"), saved.get("reason")) if saved.get("as") in TURNOVER_CHOICES else (None, None)
    out = dict(state=None, metric=None, note=None, set_by="python", reason=reason, verdict=None, fx_needed=False,
               suggested=None, file_revenue=file_revenue, source=source)
    if choice:
        out.update(set_by=by)
    elif file_revenue is not None and low is not None and rate is None:
        out.update(fx_needed=True)      # the file covers the period but the claim cannot be compared yet
    elif file_revenue is None and settings.get("deck_take_rate"):
        out.update(suggested=VOLUME_CHOICE)     # no file covers the period and the deck says "take rate": pre-selected only
    if choice == "revenue":
        out.update(state="revenue", metric="Revenue", note=GROSS_REVENUE_NOTE)
    elif choice == "volume":
        out.update(state="volume", metric=VOLUME, note=VOLUME)
    else:
        out.update(state="ask", note=ASK_NOTE, verdict=("Unverified", ASK_REASON))
    return out


# --- one claim ------------------------------------------------------------------------------------------------------------

def _segments(results: dict) -> Tuple[List[str], set]:
    """(segments of the revenue file, every segment any engine figure is split by)."""
    revenue = [s for s in (results.get("mrr_series") or {}).get("segments", ()) if s != "Unsegmented"]
    if not revenue:
        revenue = [s for s in (results.get("revenue_series") or {}).get("segments", ()) if s != "Unsegmented"]
    every = set(revenue)
    for block in ("sales_cycle", "acv_path", "nrr"):
        every |= set((results.get(block) or {}).get("by_segment") or {})
    return revenue, every


def fits_metric(metric: str, unit: Optional[str], currency: Optional[str]) -> bool:
    """Whether a metric is measured in the unit of a claim (the analyst may pick only such a metric, or none)."""
    return metric in METRICS and _fits(METRICS[metric]["unit"], _claim_unit({"unit": unit, "currency": currency}))


def data_segments(results: dict) -> List[str]:
    """Every segment the engine's figures are split by: what the analyst may pick besides the two markers."""
    return sorted(_segments(results)[1])


# docs/design/segment-partitions.md section 1: the segment a money figure's cited label names besides the metric. The label is read on read and
# the name is the row's segment only; it is never stored, never logged and never sent to a model (the register is outside the gateway).
_LABEL_NOISE = re.compile(
    r"(?i)\([^)]*\)|\bby\s+\w+|\b(?:FY|CY)?\d{2,4}(?:[-/]\d{2,4})?\b|\b[QH][1-4]?\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b|[€$£]|\b(?:eur|usd|gbp|chf)\b|\b(?:mm|bn|million|millions|thousand|billion)\b")
_LABEL_WORDS = frozenset((
    "total totals company group overall consolidated whole all annual annually yearly monthly quarterly recurring current net new existing "
    "forecast forecasts projected projection projections plan planned budget target targets actual actuals expected base case best worst "
    "realistic scenario run rate year years month months quarter quarters fy ytd ttm ending end of the and in per for vs to from at on with "
    "mix split breakdown share contribution overview summary key kpi kpis metric metrics financial financials figures numbers highlights "
    "performance average avg gross recognised recognized").split())
_LABEL_DIMENSIONS = frozenset((
    "product products segment segments customer customers client clients region regions channel channels line lines market markets tier tiers "
    "plan plans country countries geography use cohort cohorts vertical verticals type types category categories business unit units").split())
LABEL_SEGMENT_MAX_WORDS = 4


def page_segment(name: Optional[str], claim_type: Optional[str] = None) -> Optional[str]:
    """The segment the page reader printed for a figure (`page_segment` of the deck claim), as printed, or None when it names no segment: only
    period words (Q1, H2, a month, a year), only words for the whole company or the metric ("Total"), only a dimension word ("Product"), or, for
    a customer or user count, a population (paying, free, trial, all ...), which sets the population instead (George, 2026-10-27)."""
    text = " ".join((name or "").split())
    if not text:
        return None
    left = [t.strip(".,&'") for t in _LABEL_NOISE.sub(" ", text).split()]
    left = [t for t in left if t and t.lower() not in _LABEL_WORDS]
    if not left or all(t.lower() in _LABEL_DIMENSIONS for t in left):
        return None
    if claim_type in POPULATION_TYPES and population_in_label(text):
        return None
    return text


def label_segment(label: Optional[str]) -> Optional[str]:
    """The segment a cited label names, or None when it names the metric, the period, the company or a scenario only. The metric words, the
    period, currency and scale words and the closed words above are taken out; what is left must be one to four capitalised words (a product,
    a customer, a use case, a segment or a legend item as the deck writes it). A dimension word alone ("Product"), a sentence and a lower-case
    phrase name no segment, so the claim stays the whole company's."""
    if not label:
        return None
    from .decks import claims as deck_claims
    text = label
    for _, rx in deck_claims._KEYWORDS:
        text = rx.sub(" ", text)
    text = _LABEL_NOISE.sub(" ", text)
    text = re.sub(r"[|:;,/\\\u2013\u2014]|\s-\s|\s[-.]+\s", " ", text)
    tokens = [t.strip(".,&'") for t in text.split()]
    tokens = [t for t in tokens if t and t.lower() not in _LABEL_WORDS]
    while tokens and tokens[0].lower() in ("a", "an"):
        tokens = tokens[1:]
    if not tokens or len(tokens) > LABEL_SEGMENT_MAX_WORDS or all(t.lower() in _LABEL_DIMENSIONS for t in tokens):
        return None
    if tokens[0].isdigit() or not all(t[0].isupper() or t.isdigit() for t in tokens):
        return None
    return " ".join(tokens)


# The engine metric each recurring claim type is tested against (George, 2026-10-23; docs/specs/claim-matching.md table 2a).
RECURRING_METRIC = {"arr": "ARR", "mrr": "MRR", "churn": "Gross revenue churn", "nrr": "NRR (12-month)", "cac_payback": "CAC payback"}
# George, 2026-10-24: a claim of a type that names an engine metric, with no period, is Unverified for the period, not Unsupported for the metric.
METRIC_TYPES = (*RECURRING_METRIC, "customers", "users", "user_growth", "gross_margin", "revenue_growth")


# George, 2026-10-26: a revenue-typed figure whose own text names no metric takes it from the title over its chart or the page heading when that
# names exactly one (association.heading_word); "sales" follows the Sales answer of the deck.
HEADING_METRIC = {"revenue": "Revenue", "ARR": "ARR", "MRR": "MRR"}


def is_sales_claim(c: dict, results: Optional[dict]) -> bool:
    """A money claim labelled Sales with a past period (George, 2026-10-26): the deck's "Sales" may be revenue or bookings, so the analyst answers once
    per deck. Past means the claim's period ends in or before the as-of month; a plan or scenario figure is not asked."""
    as_of = (results or {}).get("as_of_month")
    end = _month_of(c.get("period_end"))
    return bool(as_of and end is not None and end <= _mi(as_of) and c.get("claim_type") in ("revenue", "sales") and c.get("currency")
                and c.get("value") is not None and c.get("scenario") in (None, "none") and c.get("basis") != "projection"
                and ((c.get("label_from") and _SALES_LABEL.match(c["label_from"])) or c.get("heading_metric") == "sales"))


def sales_questions(candidates: List[dict], results: Optional[dict], settings: dict) -> List[dict]:
    """The decks that still owe the Sales answer: [{deck_id, file, claims}], one per deck, in the order the decks first appear. A deck with an
    answer (settings["sales_choices"][deck_id]["as"]) is not asked again."""
    answered = settings.get("sales_choices") or {}
    out: Dict[Optional[str], dict] = {}
    for c in candidates:
        if c.get("status") == "rejected" or not is_sales_claim(c, results) or (answered.get(c.get("deck_id")) or {}).get("as") in SALES_CHOICES:
            continue
        entry = out.setdefault(c.get("deck_id"), {"deck_id": c.get("deck_id"), "file": c.get("file"), "claims": 0})
        entry["claims"] += 1
    return list(out.values())


def propose_metric(claim_type: str, claim_unit: Optional[str], text: str) -> Optional[str]:
    """The metric a claim names by its type, a keyword in its snippet or borrowed label, and its unit (table 2a)."""
    found = _keyword_metric(claim_type, claim_unit, text)
    if found == "Gross revenue churn" and _MONTHLY.search(text):       # engine contract 8: a rate worded monthly is the month's, not the year's
        found = MONTHLY_CHURN
    return found


def _keyword_metric(claim_type: str, claim_unit: Optional[str], text: str) -> Optional[str]:
    from .decks.claims import CONTRACT_TERM
    metric = None
    if claim_type in RECURRING_METRIC:         # engine contract 8: the type names the engine's figure, not a keyword in the snippet
        metric = RECURRING_METRIC[claim_type]
        if claim_type in ("arr", "mrr") and CONTRACT_TERM.search(text):     # a contracted or committed figure is a contract value, whatever the type
            metric = CONTRACT_VALUE
        elif claim_type == "mrr" and _NEW_MRR.search(text):
            metric = "New MRR"
    elif claim_type == "revenue":
        plain = _RECURRING.sub(" ", text)
        if CONTRACT_TERM.search(text):               # issue #136: a contracted or committed figure is a contract value, not revenue
            metric = CONTRACT_VALUE
        elif _NEW_MRR.search(text):
            metric = "New MRR"
        elif _MRR.search(text):
            metric = "MRR"
        elif _ARR.search(text):
            metric = "ARR"
        elif _REVENUE.search(plain) and not re.search(r"(?i)\brecurring revenue\b", plain):
            metric = "Revenue"
    elif claim_type in UNIT_ECONOMICS:
        metric = UNIT_ECONOMICS[claim_type]
    elif claim_type in ("customers", "users"):          # users: the population decides (claim-types-and-correction.md section 2)
        metric = "Customer count"
    elif claim_type == "user_growth":
        metric = "Customer growth"
    elif claim_type == "retention":
        metric = "NRR (12-month)" if _NRR.search(text) else "Gross revenue churn" if _CHURN.search(text) else None
    elif claim_type == "sales":
        metric = ("ACV" if _ACV.search(text) else "Median sales cycle" if _SALES_CYCLE.search(text)
                  else "Win rate" if _WIN_RATE.search(text) else "CAC payback" if _PAYBACK.search(text) else None)
    elif claim_type == "gross_margin":
        metric = "Gross margin"
    elif claim_type in ("revenue_growth", "growth") and claim_unit == "x":      # deck-actuals.md: "3.3 x" is a multiple of the year before
        metric = GROWTH_MULTIPLE if claim_type == "revenue_growth" or _REVENUE.search(text) else None
    elif claim_type in ("revenue_growth", "growth"):     # dates-and-periods.md section 5: growth of the series the claim names
        if _MRR.search(text) and not _NEW_MRR.search(text):
            metric = "MRR growth"
        elif _ARR.search(text):
            metric = "ARR growth"
        elif claim_type == "revenue_growth" or _REVENUE.search(text):
            metric = "Revenue growth"
        elif _CUSTOMERS.search(text):
            metric = "Customer growth"
    return metric if metric and _fits(METRICS[metric]["unit"], claim_unit) else None


def _page_ref(sources: list) -> str:
    refs = []
    for s in sources or ():
        ref = s["plan_ref"] if s.get("plan_ref") else f"slide {s['slide']}" if s.get("slide") is not None else f"p{s['page']}" if s.get("page") is not None else \
            f"{s['sheet']}!{s['cell']}" if s.get("cell") else None
        if ref and ref not in refs:
            refs.append(ref)
    return ", ".join(refs)


def _deck_reading(c: dict) -> str:
    if c.get("origin") == PLAN_FILE:
        return PLAN_READING
    if c.get("origin") == FORECAST_FILE:
        return FORECAST_READING                         # kept after a later edit: the claim came from a forecast table
    if c.get("origin") == "analyst":
        return ANALYST_ENTERED                          # kept after a later edit: the claim never came from the deck
    if c.get("origin") == "deck_analyst":
        return ADDED_FROM_DECK                          # kept after a later edit: the analyst picked the line
    if c.get("status") == "edited":
        return "edited"                                 # an edit clears the AI label (deck-parser.md section 6)
    if c.get("origin") == "ai":
        return "Verified" if c.get("ai_label") == "Verified" or c.get("ai_status") == "verified" else SUGGESTION
    return "parser"


def _expand(candidates: List[dict]) -> List[dict]:
    """One claim per candidate, or per value by period of a table row (id `<candidate id>#<n>`, n from 1)."""
    out = []
    for c in candidates:
        rows = c.get("by_period")
        if not rows:
            out.append({**c, "claim_id": c["id"]})
            continue
        for n, item in enumerate(rows, 1):
            claim = {**c, **{k: item.get(k) for k in ("value", "value_high", "target_date", "period_text", "period_start",
                                                      "period_end")}, "claim_id": f"{c['id']}#{n}"}
            if (item.get("source") or {}).get("file"):
                claim["sources"] = [item["source"]]
            claim["period_unclear"] = bool(item.get("period_unclear"))
            out.append(claim)
    return out


def deck_revenue_hint(c: dict, peers: List[dict]) -> Optional[dict]:
    """Section 11, deck hint: the deck's own revenue figure for the period of a turnover claim, when it is a single figure
    in the same currency and file, one value only, and below the turnover figure beyond tolerance. {"note", "take_rate"} or
    None. Derived from two deck figures, so never Verified."""
    from .decks.claims import deck_label
    low = c.get("value")
    if low is None or c.get("value_high") is not None or not c.get("period_start"):
        return None
    found = [p for p in peers if p.get("claim_id") != c.get("claim_id") and deck_label(p) == "Revenue" and p.get("value") is not None
             and p.get("value_high") is None and p.get("currency") == c.get("currency") and p.get("file") == c.get("file")
             and (p.get("period_start"), p.get("period_end")) == (c.get("period_start"), c.get("period_end"))]
    if len({p["value"] for p in found}) != 1:
        return None
    revenue = found[0]
    if revenue["value"] >= low or within_tolerance("Revenue", revenue["value"] - low, low):
        return None
    src = (revenue.get("sources") or [{}])[0]
    where = f"slide {src['slide']}" if src.get("slide") is not None else f"page {src['page']}" if src.get("page") is not None else ""
    rate = revenue["value"] / low
    currency = f" {revenue['currency']}" if revenue.get("currency") else ""
    return {"take_rate": rate, "note": f"Deck revenue for the same period: {_shown(revenue['value'])}{currency}"
                                       f"{f' ({where})' if where else ''}; implied take rate {fmt.fmt_pct(rate)}, derived, not verified"}


def _population(c: dict, metric: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(population, set by) of a claim (claim-types-and-correction.md section 2): the analyst's or the parser's, else what the type's
    keyword means (a customers keyword counts paying customers; a qualifier names registered users) or, for sales, the metric's own
    population. None when nothing says it (plain users)."""
    from .decks.claims import QUALIFIERS
    if c.get("population"):
        return c["population"], c.get("population_set_by") or "parser"
    kind = c.get("claim_type")
    if kind in POPULATION_TYPES and kind != "user_growth":      # a population the page reader's label or segment names sets it (George, 2026-10-27)
        named = population_in_label(f"{c.get('label_from') or ''} {c.get('page_segment') or ''}")
        if named:
            return named, "python"
    if kind == "customers":
        return "paying", "python"
    if kind == "users" and c.get("qualifier") in QUALIFIERS:
        return "registered", "python"
    if kind == "sales" and metric in METRIC_POPULATION:
        return METRIC_POPULATION[metric], "python"
    if kind in ("users", "user_growth"):
        inferred = population_in_label(f"{c.get('label_from') or ''} {c.get('snippet') or ''}")
        if inferred:
            return inferred, "python"
    return None, None


# The nouns of a label that say which people a user figure counts (George, 2026-10-26): only a label that holds exactly one of the
# three kinds answers; "paying and active users" stays a question.
_LABEL_POPULATION = (("paying", re.compile(r"(?i)\b(?:paying|paid|subscribers?)\b")),
                     ("registered", re.compile(r"(?i)\b(?:registered|sign-?ups?|signed[- ]up)\b")),
                     ("active", re.compile(r"(?i)\b(?:active|MAU|DAU|WAU)\b")),
                     ("free", re.compile(r"(?i)\bfree\b")),
                     ("trial", re.compile(r"(?i)\b(?:trials?|trialists?)\b")))
_ALL_POPULATION = re.compile(r"(?i)\ball\b")


def population_in_label(text: Optional[str]) -> Optional[str]:
    """paying, registered, active, free or trial when the label text holds the noun of exactly one of them, "all" when it holds none of them and
    says "all" ("All clients"); None when it holds none or several."""
    found = [population for population, rx in _LABEL_POPULATION if rx.search(text or "")]
    if not found and _ALL_POPULATION.search(text or ""):
        return "all"
    return found[0] if len(found) == 1 else None


def _figure_type(c: dict, text: str, end: Optional[int], as_of_i: Optional[int]) -> Optional[str]:
    """The analyst's or the parser's figure type, a target cue in the claim's words, else the source classification: a projection or
    scenario basis for a period after the as-of month is a target, any other claim with a period an actual (docs/specs/forecast-and-payback.md
    section 2). A period after the data alone makes no forecast: it is missing coverage. None while the period is unknown."""
    from .decks.claims import target_cue
    if c.get("figure_type") in FIGURE_TYPES:
        return c["figure_type"]
    if target_cue(text):
        return "target"
    if end is not None and as_of_i is not None:
        return "target" if end > as_of_i and c.get("basis") in FORECAST_BASES else "actual"
    return None


def basis_conflict(c: dict, as_of: Optional[str]) -> bool:
    """The model read a projection (`basis`) for a period that Python reads as an actual: on or before the as-of month, no analyst figure
    type, no target cue in the claim's words. The evidence label stays Python's; only a flag is raised (George, 2026-10-23, M2)."""
    if c.get("basis") != "projection" or not as_of:
        return False
    text = f"{c.get('snippet') or ''} {c.get('label_from') or ''}"
    return _figure_type(c, text, _month_of(c.get("period_end")), _mi(as_of)) == "actual"


def flags_of(c: dict, as_of: Optional[str]) -> List[str]:
    """The flags of a deck claim as the screens and the bulk approvals read them: those the checker stored, plus the ones that depend on the
    as-of month, known only after the engine ran ("basis conflicts with period")."""
    flags = list(c.get("flags") or [])
    return flags + [BASIS_CONFLICT] if BASIS_CONFLICT not in flags and basis_conflict(c, as_of) else flags


def candidate_fields(c: dict, results: Optional[dict]) -> dict:
    """The figure type, population and growth basis of a deck candidate as the register reads them, for the editor and for the
    previous value of an edit (claim-types-and-correction.md section 3). Nothing is stored."""
    text = f"{c.get('snippet') or ''} {c.get('label_from') or ''}"
    as_of = (results or {}).get("as_of_month")
    metric = propose_metric(c.get("claim_type"), _claim_unit(c), text)
    out = {"figure_type": _figure_type(c, text, _month_of(c.get("period_end")), _mi(as_of) if as_of else None),
           "population": _population(c, metric)[0], "growth_basis": None}
    if c.get("claim_type") in GROWTH_TYPES:
        from .decks.claims import growth_basis
        shown = ((c.get("claim_inputs") or {}).get(c.get("id")) or {}).get("growth_basis")     # the register row's one-click choice
        out["growth_basis"] = shown or (c.get("growth_basis") if c.get("growth_basis") in GROWTH_BASES else None) or growth_basis(text)
    return out


def _row(c: dict, results: dict, settings: dict, peers: Optional[List[dict]] = None) -> dict:
    inputs = (c.get("claim_inputs") or {}).get(c["claim_id"]) or {}
    as_of = results.get("as_of_month")
    as_of_i = _mi(as_of) if as_of else None
    currency = (c.get("currency") or None)
    # an amount with no currency and no unit: the currency is the field still unknown (claim-types-and-correction.md section 2)
    currency_unknown = c.get("claim_type") in MONEY_TYPES and not currency and not (c.get("unit") or "").strip() \
        and c.get("value") is not None
    claim_unit = "currency" if currency_unknown else _claim_unit(c)
    text = f"{c.get('snippet') or ''} {c.get('label_from') or ''}"
    revenue_segments, data_segments = _segments(results)

    # metric and segment: Python proposes, the analyst may set either
    if inputs.get("metric") is not None:
        metric, metric_by = (None if inputs["metric"] == NO_METRIC else inputs["metric"]), "analyst"
    else:
        metric, metric_by = propose_metric(c.get("claim_type"), claim_unit, text), "python"
    from .decks.claims import QUALIFIERS, qualified_label
    population, population_by = _population(c, metric)
    qualified = c.get("claim_type") == "users" and c.get("qualifier") in QUALIFIERS and population_by != "analyst"
    # evidence-labels.md section 3, claim-types-and-correction.md section 2: the figure counts other people than the claim
    population_differs = metric in METRIC_POPULATION and population is not None and population != METRIC_POPULATION[metric]
    if inputs.get("segment"):
        segment, segment_by = inputs["segment"], "analyst"
    else:
        named = [s for s in revenue_segments if re.search(rf"(?i)(?<!\w){re.escape(s)}(?!\w)", text)]
        # a name in the data wins; two named is the whole company; with none, the segment the page reader printed (George, 2026-10-27), else the
        # label of a money figure may name a product, customer or use case
        found = None if named else (c.get("split_segment") or page_segment(c.get("page_segment"), c.get("claim_type"))
                                    or (label_segment(c.get("label_from")) if c.get("claim_type") in MONEY_TYPES else None))
        segment, segment_by = (named[0] if len(named) == 1 else found or WHOLE), "python"
    start, end = _month_of(c.get("period_start")), _month_of(c.get("period_end"))
    figure_type = _figure_type(c, text, end, as_of_i)
    sort = deck_actuals.period_sort(c, as_of)           # deck-actuals.md section 1: the figure's own period against the as-of month, never the deck's date
    deck_actual = deck_actuals.is_deck_actual(c, sort, figure_type) and c.get("scenario") not in SCENARIO_CASES    # a best or worst case is listed, never matched (George, 2026-10-23): no reconcile
    forecast = figure_type == "target" and end is not None and as_of_i is not None and end > as_of_i     # the classification says so
    turn = None
    if metric_by == "python" and _is_turnover_claim(c, text) and c.get("origin") != FORECAST_FILE:   # section 11
        fx0 = fx_view(c, settings, as_of)
        turn = _turnover(c, inputs, results, settings, fx0["rate"] if fx0 else 1.0, start, end, as_of_i, segment, forecast)
        if turn["fx_needed"]:
            turn["verdict"] = ("Unverified", f"{FX_NEEDED}: {currency}→{fx0['currency']}")
        metric, metric_by = turn["metric"], turn["set_by"]
        hint = deck_revenue_hint(c, peers or []) if turn["state"] == "ask" else None
        suggested = VOLUME_CHOICE if hint or turn["suggested"] else None
    if metric is None and metric_by == "python" and c.get("claim_type") == "revenue" and HEADING_METRIC.get(c.get("heading_metric")) \
            and _fits(METRICS[HEADING_METRIC[c["heading_metric"]]]["unit"], claim_unit):
        metric = HEADING_METRIC[c["heading_metric"]]
    sales_reason = None
    if metric is None and metric_by == "python" and is_sales_claim(c, results):        # the deck-wide answer decides what "Sales" is
        choice = ((settings.get("sales_choices") or {}).get(c.get("deck_id")) or {}).get("as")
        if choice == "revenue":
            metric = "Revenue"
        else:
            sales_reason = BOOKINGS_REASON if choice == "bookings" else SALES_ASK_REASON
    spec = METRICS.get(metric) if metric else None

    period = c.get("period_text") or c.get("target_date") or None
    low, high = c.get("value"), c.get("value_high")
    out = dict.fromkeys(FIELDS)
    out.update(
        basis=c.get("basis"), scenario=c.get("scenario") or "none",
        claim_id=c["claim_id"], deck_file=c.get("file"), page_ref=_page_ref(c.get("sources")),
        claim_type=c.get("claim_type"), status=c.get("status"), deck_reading=_deck_reading(c), claimed_value=low,
        claimed_high=high, claim_direction=c.get("claim_direction") if low is None else None, unit=c.get("unit"),
        extraction_confidence=c.get("extraction_confidence"),
        currency=currency, period=period,
        period_start=str(c["period_start"]) if c.get("period_start") else None,
        period_end=str(c["period_end"]) if c.get("period_end") else None,
        period_note=c.get("period_read_note") if c.get("target_date") else NO_PERIOD, segment=segment, segment_set_by=segment_by,
        metric=metric, metric_set_by=metric_by, direction=spec["direction"] if spec else None,
        tolerance=tolerance_text(metric) if spec else None, as_of_month=as_of,
        as_of_defaulted=settings.get("as_of_by", "detected" if not settings.get("as_of_month") else "analyst") != "analyst", overlaps_with=[], months_missing=[], calc_lines=[], calc_details=[],
        gate_date=inputs.get("gate_date"),
        gate_threshold=inputs.get("gate_threshold"), gate_budget_decision=inputs.get("gate_budget_decision"),
        gate_metric_name=inputs.get("gate_metric_name"), gate_direction=inputs.get("gate_direction"))
    if c.get("claim_type") in GROWTH_TYPES:            # dates-and-periods.md section 5: the analyst's, the parser's, or the words'
        from .decks.claims import growth_basis
        stated = c.get("growth_basis") if c.get("growth_basis") in GROWTH_BASES else None
        out["growth_basis"] = inputs.get("growth_basis") or stated or growth_basis(text)
    if metric == GROWTH_MULTIPLE:                  # a multiple of the year before has no basis to choose
        out["growth_basis"] = None
    out.update(population=population, figure_type=figure_type, period_sort=sort, deck_only=False)
    # the required fields still Unknown, in the order of the plan's table (claim-types-and-correction.md section 1)
    required = []
    if currency_unknown:
        required.append("currency")
    if not c.get("target_date") and c.get("claim_type") not in PERIOD_OPTIONAL_TYPES:
        required.append("period")
    if population is None and (c.get("claim_type") in POPULATION_TYPES or metric in ("Median sales cycle", "Win rate")):
        required.append("population")
    if figure_type == "unknown":
        required.append("figure type")
    if out["growth_basis"] == "unknown":
        required.append("growth basis")
    out["required_unknown"] = required
    if turn:
        out.update(turnover_state=turn["state"], turnover_note=turn["note"], turnover_set_by=turn["set_by"],
                   turnover_reason=turn["reason"])
        # Volume is pre-selected in the question; the analyst's confirmation is still required
        out.update(turnover_suggested=suggested, deck_revenue_note=hint["note"] if hint else None)
    shown_claim: List[Optional[float]] = [None]         # the claimed figure the gate sentence names, once it is known

    def finish(label: Optional[str], reason: str) -> dict:
        if qualified and population_differs and label == "Unsupported":     # no paying-customer figure: the reason names the population
            reason = QUALIFIED_NO_FIGURE.format(label=qualified_label(text, c["qualifier"]))
        if label == "Unsupported" and reason != NO_CLAIMED_VALUE:       # evidence-labels.md section 2: a stated figure the app cannot test is Unverified
            label = "Unverified"
        if deck_actual and label == "Unverified" and deck_actuals.holds_nothing(reason):        # deck-actuals.md section 2b: used as it stands, tagged
            reason, out["deck_status"] = deck_actuals.DECK_ONLY_REASON, deck_actuals.TAG
        elif deck_actual and label == "Verified" and not reason.startswith(BEAT_PREFIX):        # section 2a: the deck is consistent with the files
            out["deck_status"] = deck_actuals.CONSISTENT
        out.update(evidence_label=label, reason=reason)
        out["deck_only"] = out["deck_status"] == deck_actuals.TAG
        out["source"] = deck_actuals.source_text(out)
        if deck_actual and not out["claim_direction"]:
            out["details"] = deck_actuals.deck_block(out, c.get("label_from"), note=deck_actuals.mark_note(c))
            out["data_request"] = deck_actuals.data_request(out)
        if out["evidence_analysis"] is None and reason.startswith("Missing:") and metric in METRICS:
            item = _missing_item(results, metric)
            if item:
                out.update(evidence_analysis=str(item.get("metric")), evidence_source_key=MISSING_KEY)
        _gate(out, c, inputs, spec, claim_unit, results, shown_claim[0], settings.get("first_quarterly_review"))
        return out

    fx = fx_view(c, settings, as_of)
    if fx and fx["rate"] is not None:           # converted at the saved rate before matching; both figures are shown
        out.update(fx_rate=fx["rate"], fx_date=fx["date"],
                   claimed_converted=low * fx["rate"] if low is not None else None,
                   claimed_converted_high=high * fx["rate"] if high is not None else None)
    if c.get("origin") == PLAN_FILE:           # docs/design/pnl-lines.md section 4: never Verified or Contradicted; implied against observed rate
        out.update(metric=None, metric_set_by=None, direction=None, tolerance=None)
        out.update(plan_measure=c["plan"]["measure"], plan_implied=c["plan"]["implied"],
                   calc_lines=_plan_lines(c["plan"], results.get("reporting_currency")),
                   calc_details=["implied growth = plan ÷ the year before − 1; implied share = plan ÷ that year's revenue; "
                                 "observed = the last two actual years (the last actual year for a share); gap in points"])
        finish("Unverified", PLAN_NOTE)
        out.update(gate_needed=False, overlaps_with=None)
        return out
    if c.get("origin") == FORECAST_FILE:       # chat-upload.md section 20: never matched, ranked or gated; no value at stake, no overlaps
        out.update(metric=None, metric_set_by=None, direction=None, tolerance=None)
        finish("Unverified", FORECAST_NOTE)
        out.update(gate_needed=False, value_at_stake_arr=None, overlaps_with=None)
        return out
    if c.get("scenario") in SCENARIO_CASES:     # George, 2026-10-23: a best or worst case is listed, never matched, ranked or gated
        out.update(metric=None, metric_set_by=None, direction=None, tolerance=None)
        finish("Unverified", SCENARIO_NOTE.format(case=c["scenario"]))
        out.update(gate_needed=False, value_at_stake_arr=None, overlaps_with=None)
        return out
    if out["claim_direction"]:                  # "Positive EBITDA": never Verified or Contradicted
        return finish("Unverified", DIRECTION_ONLY)
    if turn and turn["verdict"]:
        return finish(*turn["verdict"])
    if sales_reason:
        return finish("Unverified", sales_reason)
    if out["claim_type"] in UNTESTED_TYPES:     # never matched, never ranked, never gated: not a claim about the business
        finish("Unverified", UNTESTED_TYPES[out["claim_type"]])
        out["gate_needed"] = False
        return out
    if not spec:
        if qualified:                                   # a figure that is not a count: nothing to read
            return finish("Unsupported", QUALIFIED_NO_FIGURE.format(label=qualified_label(text, c["qualifier"])))
        if c.get("claim_type") in METRIC_TYPES and not c.get("target_date") and c.get("claim_type") not in PERIOD_OPTIONAL_TYPES:
            return finish("Unverified", PERIOD_MISSING)     # George, 2026-10-24: the metric follows the period, so the period is the gap
        if forecast:
            return finish("Unverified", FORECAST_REASON.format(text=FORECAST_NO_CALC))
        return finish("Unsupported", "no metric")
    if metric == VOLUME:                        # never matched to engine revenue; the take rate is derived, never Verified
        if turn and turn["file_revenue"] is not None and low and not c.get("value_high"):
            claimed_volume = low * (fx["rate"] if fx and fx["rate"] else 1.0)
            if fx is None or fx["rate"]:
                src = turn["source"] or {}
                out.update(implied_take_rate=round(turn["file_revenue"] / claimed_volume, 6),
                           implied_take_rate_source=(f"revenue: {src.get('file')} · {src.get('sheet')} · {src.get('rows')}; "
                                                     f"volume: {out['deck_file']} · {out['page_ref']}"))
        return finish("Unsupported", VOLUME_REASON)
    if metric == CONTRACT_VALUE:                # issue #136: typed, never computed, never matched to engine revenue
        return finish("Unsupported", CONTRACT_REASON)
    if metric in UNIT_ECONOMICS.values():       # 2026-10-20: ARPA and ARPU are never computed, never matched, never ranked
        finish("Unsupported", UNIT_ECONOMICS_REASON)
        out["gate_needed"] = False
        return out
    if [f for f in required if f != "growth basis"]:      # not matched until every required field is known (section 2)
        others = [f for f in required if f != "period"]
        if "period" in required and metric == "Gross revenue churn":       # a rate with no wording and no period: either, so neither is tested
            return finish("Unverified", CHURN_RATE_UNCLEAR_REASON + (f"; {REQUIRED_REASON.format(fields=', '.join(others))}" if others else ""))
        if "period" in required:                # decision 3 of 2026-10-19: its own text, never the as-of month
            words = PERIOD_UNCLEAR if c.get("period_unclear") else PERIOD_NOT_READ
            return finish("Unverified", words + (f"; {REQUIRED_REASON.format(fields=', '.join(others))}" if others else ""))
        return finish("Unverified", REQUIRED_REASON.format(fields=", ".join(required)))
    if not _fits(spec["unit"], claim_unit):
        return finish("Unsupported", "metric does not fit the claim's unit")
    if segment == NOT_IN_DATA or (segment != WHOLE and segment not in data_segments):
        return finish("Unsupported", "segment not in the data")
    if segment != WHOLE and not spec["seg"]:
        return finish("Unsupported", "not computed by segment")
    if c.get("target_date") and (start is None or end is None):
        return finish("Unverified", PERIOD_NOT_READ)       # a date the parser could not read: the analyst sets it

    if fx and fx["rate"] is None:
        return finish("Unverified", f"{FX_NEEDED}: {currency}→{fx['currency']}")       # names the pair (the rate to set)
    span, cov = _Span(results, metric), {}
    annual = metric == "CAC payback" and not forecast and start is not None and end is not None and end - start == 11 \
        and bool((results.get("yearly_basis") or {}).get("years"))
    if annual:                                          # forecast-and-payback.md section 4: a fiscal year reads the yearly-basis block
        observed, observed_at, source, why = _annual_payback(out, results, text, start, end)
        if not isinstance(observed, str):
            cov.update(coverage=COVERED, missing=[])
    elif spec["kind"] == "multiple":                    # deck-actuals.md: recomputed from the revenue of the two years
        observed, observed_at, source, why = _multiple(results, start, end, span, cov)
    elif spec["kind"] == "growth":                      # dates-and-periods.md section 5: tested on its basis only
        if out["growth_basis"] not in GROWTH_BASES:
            return finish("Unverified", GROWTH_UNKNOWN_REASON)
        figures = _Figures(results, spec["base"], segment)
        observed, observed_at, source, why = _growth(figures, spec, out["growth_basis"], start, end, as_of_i, span, cov, forecast)
    else:
        figures = _Figures(results, metric, segment)
        observed, observed_at, source, why = _observe(figures, spec, metric, start, end, as_of_i, span, cov, forecast)
    if cov:
        out.update(period_coverage=cov["coverage"], months_missing=cov["missing"])
    partly = cov.get("coverage") == PARTLY_COVERED
    partly_reason = PARTLY_REASON.format(months=_month_ranges([_mi(m) for m in cov.get("missing") or ()])) if partly else None
    if isinstance(observed, str):                       # a verdict instead of a figure
        return finish(*observed.split("|", 1))
    # currency claims are converted at the audit's FX rate (checked above: a claim with no saved rate is not tested)
    rate = fx["rate"] if fx else 1.0
    claimed_low = _to_metric_unit(low, claim_unit, spec["unit"])
    claimed_high = _to_metric_unit(high, claim_unit, spec["unit"])
    if spec["unit"] == "currency":
        claimed_low = claimed_low * rate if claimed_low is not None else None
        claimed_high = claimed_high * rate if claimed_high is not None else None

    def forecast_finish() -> dict:
        """A forecast is Unverified and says how demanding it is, not that it cannot be tested (forecast-and-payback.md section 3)."""
        mismatch = POPULATION_REASON_FC.format(claimed=POPULATION_WORDS.get(population, population), measured=POPULATION_WORDS[METRIC_POPULATION[metric]]) \
            if population_differs else None
        view = _forecast_view(results, metric, segment, start, end, as_of_i, claimed_low, claimed_high, settings.get("fiscal_year_end") or 12,
                              span, mismatch)
        out.update(calc_lines=view["lines"], calc_details=view["details"])
        return finish("Unverified", FORECAST_REASON.format(text=view["text"]))

    if observed is None:
        if observed_at == "missing":
            if (spec.get("base") or metric) == "Revenue":     # George, 2026-10-20: no revenue series, no figure read from anywhere else
                return finish("Unverified", NO_REVENUE_SERIES)
            if forecast:
                return forecast_finish()
            unlock = _missing(results, metric)
            return finish(*(("Unverified", f"Missing: {unlock}") if unlock else ("Unsupported", "not computed")))
        if forecast:
            return forecast_finish()
        return finish("Unsupported", why or "not computed")

    out.update(observed_value=observed, observed_at=observed_at, observed_source=source)
    found = None if annual else (ANNUAL_ANALYSIS, YEARLY_REVENUE_KEY) if (source or {}).get("cells") else \
        evidence_key(metric, segment, observed_at, (results.get("cac_payback") or {}).get("default_l", 1))
    if found:
        out.update(evidence_analysis=found[0], evidence_source_key=found[1])
        if observed is not None:
            out["observed_citation"] = citation(found[1], source, observed_at)
    if claimed_low is None:
        return finish("Unsupported", NO_CLAIMED_VALUE)
    if partly:                                          # section 4: the figure over the months present, no test
        return finish(INCONCLUSIVE, partly_reason)
    if figure_type == "target" and not forecast:        # a plan for a period that has passed: shown, never tested as a result
        return finish("Unverified", TARGET_REASON)
    if population_differs and not forecast:     # the figure is shown; it cannot confirm or contradict a count of other people
        if qualified:
            return finish(INCONCLUSIVE, QUALIFIED_REASON.format(label=qualified_label(text, c["qualifier"])))
        return finish(INCONCLUSIVE, POPULATION_REASON.format(population=POPULATION_WORDS.get(population, population),
                                                             measured=POPULATION_WORDS[METRIC_POPULATION[metric]]))
    claimed = claimed_low
    if claimed_high is not None:                        # a range is tested at the end nearest the observed value
        lo, hi = sorted((claimed_low, claimed_high))
        claimed = observed if lo <= observed <= hi else lo if observed < lo else hi
    sign = 1.0 if spec["direction"] == "higher" else -1.0
    if forecast:
        gap, kind = claimed - observed, "to go"
    else:
        gap = sign * (claimed - observed)
        kind = "miss" if gap > 0 else "beat" if gap < 0 else None
    if round(gap, 9) == 0:
        gap, kind = 0.0, None if not forecast else "to go"
    out.update(gap=round(gap, 6), gap_kind=kind, gap_normalised=round(gap / abs(claimed), 6) if claimed else None)
    out["shortfall"] = out["gap_normalised"] if kind == "miss" else None
    out["gloss"] = gloss(spec["unit"], kind, gap, results.get("reporting_currency"), spec["direction"],
                         _label_of(end) if forecast else None)

    shown_claim[0] = claimed

    if forecast:
        return forecast_finish()
    verified = within_tolerance(metric, gap, claimed)
    if verified:
        return finish("Verified", f"within {out['tolerance']} of the claim")
    if deck_actual:                             # deck-actuals.md section 2a, checked before the Definition check: data prepared by management, not a claim; it differs from the file, either way
        out["deck_status"] = deck_actuals.DIFFERS_STATUS
        return finish("Contradicted", deck_actuals.DIFFERS_REASON.format(deck=_format(spec["unit"], claimed, results.get("reporting_currency")),
                                                                     file=_format(spec["unit"], observed, results.get("reporting_currency"))))
    if is_big_gap(spec["unit"], out["gap"], out["gap_normalised"]):    # section 4.1: the analyst says whether claim and figure measure the same thing
        reporting = results.get("reporting_currency")
        # an answer holds only for the figures it was given against: if any differs now, it is asked again
        answer = inputs.get("definition_check") if inputs.get("definition_check") in DEFINITION_ANSWERS \
            and inputs.get("definition_basis") == definition_basis(out) else None
        out.update(definition_check=answer or DEFINITION_ASK, definition_question=DEFINITION_QUESTION.format(
            observed=_format(spec["unit"], observed, reporting), claimed=_format(spec["unit"], claimed, reporting)))
        if answer is None:                      # a status, not an evidence label: no label until the analyst answers
            return finish(None, DEFINITION_OPEN_REASON_RATE.format(points=_shown(BIG_GAP_RATE_POINTS)) if spec["unit"] == "%"
                          else DEFINITION_OPEN_REASON.format(share=fmt.fmt_pct(BIG_GAP_THRESHOLD)))
        if answer == "no":
            return finish("Unverified", DEFINITION_MISMATCH)
    if kind == "beat":                          # amended 2026-10-13 (George): a beat is Verified, marked (beat), not Contradicted
        return finish("Verified", f"{BEAT_PREFIX}{out['gloss']}")
    return finish("Contradicted", f"outside {out['tolerance']}: a miss")


def is_big_gap(unit: str, gap: Optional[float], gap_normalised: Optional[float]) -> bool:
    """Whether a tested gap opens the Definition check (section 4.1): a rate, beyond BIG_GAP_RATE_POINTS points; any other unit,
    beyond BIG_GAP_THRESHOLD of the claim, either way. A claim of 0 has no share, so it is never one."""
    if unit == "%":
        return gap is not None and round(abs(gap), 9) > BIG_GAP_RATE_POINTS
    return gap_normalised is not None and round(abs(gap_normalised), 9) > BIG_GAP_THRESHOLD


def definition_basis(row: dict) -> dict:
    """What a Definition check answer was given against (section 4.1): the claimed figures and the rate they are converted at,
    the observed figure, the claim's period, the as-of month and the FX rate date. Stored with the answer; the answer applies only
    while all of it is unchanged. Read from the register row's own fields, so it adds none."""
    figure = lambda v: None if v is None else round(float(v), 6)  # noqa: E731
    return {"claimed": [figure(row.get("claimed_value")), figure(row.get("claimed_high"))], "fx_rate": figure(row.get("fx_rate")),
            "fx_date": row.get("fx_date"), "observed": figure(row.get("observed_value")),
            "period": [row.get("period_start"), row.get("period_end")], "as_of_month": row.get("as_of_month")}


GATE_PROPOSED, GATE_SET = "proposed", "set by the analyst"
# The claim types whose gate reads "at most" when the row has no app metric (simplified-flow.md section 3): lower is better.
AT_MOST_TYPES = ("churn", "costs", "burn", "cac", "cac_payback", "months_to_profitability")
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def claim_name(row: dict) -> str:
    """How a register row is called in a sentence: its metric (or claim type), the segment when not the whole company, the period."""
    from .decks.claims import TYPE_NAMES
    name = row.get("metric") or TYPE_NAMES.get(row.get("claim_type")) or str(row.get("claim_type") or "claim").replace("_", " ").capitalize()
    if str(row.get("reason") or "").startswith(POPULATION_PREFIX):     # the app's metric counts other people: name the claim's own
        name = TYPE_NAMES.get(row.get("claim_type")) or str(row.get("claim_type") or "claim").replace("_", " ").capitalize()
    if row.get("segment") not in (None, WHOLE):
        name = f"{name} · {row['segment']}"
    if row.get("period"):
        name = f"{name}, {row['period']}"
    return name


def _template(out: dict, c: dict, spec: Optional[dict], claim_unit: Optional[str], app_metric: bool, review: Optional[str]) -> Optional[dict]:
    """The gate written from the claim (simplified-flow.md section 3): threshold = the claimed figure in the claim's unit (the converted
    one in another currency), direction from the metric (higher: at least, lower: at most; no metric: at most for churn, cost, burn, CAC,
    payback and sales-cycle claims), date = the end of the claim's period, never later than the first quarterly review, else the review
    date. None when the claim states no figure or no date can be given."""
    shown = out["claimed_converted"] if out.get("claimed_converted") is not None else out.get("claimed_value")
    if shown is None:
        return None
    period_end = out.get("period_end") if _ISO_DAY.match(str(out.get("period_end") or "")) else None
    valid_review = review if _ISO_DAY.match(str(review or "")) else None
    date = min(period_end, valid_review) if period_end and valid_review else (period_end or valid_review)
    if not date:
        return None
    if app_metric and spec:
        threshold = _to_metric_unit(shown, claim_unit, spec["unit"]) if _fits(spec["unit"], claim_unit) else shown
        direction = "at least" if spec["direction"] == "higher" else "at most"
        return {"threshold": threshold, "date": date, "direction": direction, "name": None}
    text = f"{c.get('snippet') or ''} {c.get('label_from') or ''}".lower()
    lower = out.get("claim_type") in AT_MOST_TYPES or "sales cycle" in text
    return {"threshold": shown, "date": date, "direction": "at most" if lower else "at least", "name": claim_name(out)[:GATE_METRIC_MAX]}


def _gate(out: dict, c: dict, inputs: dict, spec: Optional[dict], claim_unit: Optional[str], results: dict,
          claimed: Optional[float], review: Optional[str] = None) -> None:
    """The gate of a row (simplified-flow.md section 3): every row labelled Unverified, Inconclusive, Unsupported or Contradicted has one,
    except the rows that are never tested. The analyst's edit wins (threshold and date filled; a row with no app metric also the metric
    and the direction): status "set by the analyst". Otherwise the gate is written from the claim (`_template`): status "proposed".
    Sets gate_saved (the analyst's edit), gate_sentence, gate_status, gate_needed (always false) and key_gate (the verdict marks it)."""
    app_metric = not needs_metric_name(out)
    saved = _is_saved(inputs, needs_name=not app_metric)
    out["gate_saved"] = saved and out["evidence_label"] in NOT_VERIFIED
    out["key_gate"] = False
    out["gate_needed"] = False
    if out["evidence_label"] not in NOT_VERIFIED or is_untested(out):
        return
    if saved:
        threshold, date, decision = inputs["gate_threshold"], inputs["gate_date"], inputs.get("gate_budget_decision")
        name, direction, status = inputs.get("gate_metric_name"), inputs.get("gate_direction"), GATE_SET
    else:
        made = _template(out, c, spec, claim_unit, app_metric, review)
        if made is None:
            return
        threshold, date, decision, name, direction, status = made["threshold"], made["date"], None, made["name"], made["direction"], GATE_PROPOSED
        out.update(gate_threshold=threshold, gate_date=date, gate_direction=direction if not app_metric else None, gate_metric_name=name)
    out["gate_status"] = status
    before = f"Before {decision}, " if decision else ""
    if app_metric:
        metric, segment = out["metric"], out["segment"]
        shown = metric if segment == WHOLE else f"{metric} ({segment})"
        word = "least" if spec["direction"] == "higher" else "most"
        reporting = results.get("reporting_currency")
        shown_threshold = _format(spec["unit"], threshold, reporting)
    else:
        shown = name
        word = "least" if direction == "at least" else "most"
        shown_threshold = format_figure(claim_unit, threshold, out["currency"], c.get("unit"))
    start = f"{before}{shown} must be at {word} {shown_threshold} by {date}."
    if not before:
        start = start[0].upper() + start[1:]
    period = out["period"] or NO_PERIOD
    if out["observed_value"] is not None and claimed is not None and spec is not None and app_metric:
        reporting = results.get("reporting_currency")
        out["gate_sentence"] = (f"{start} Observed {_format(spec['unit'], out['observed_value'], reporting)} "
                                f"({out['observed_at']}); claimed {_format(spec['unit'], claimed, reporting)} ({period}).")
    else:
        out["gate_sentence"] = f"{start} Not yet observed: {out['reason']}; claimed {_claimed_text(c)} ({period})."


class _Span:
    """The months a metric's figures can be read for (dates-and-periods.md sections 3 and 4): first..last of its stored
    metric_periods block, without the missing months; the as-of month always counts as complete (section 2). With no
    stored periods (results computed before them) every month the series holds counts."""

    def __init__(self, results: dict, metric: str):
        spec = METRICS.get(metric) or {}
        self.metric = spec.get("base", metric)
        periods = (results.get("metric_periods") or {}).get(PERIOD_BLOCK.get(self.metric) or "")
        source = results.get("source_period") or {}
        self.known = periods is not None
        self.first = _mi(periods["first"]) if periods else None
        self.last = _mi(periods["last"]) if periods else None
        self.missing = {_mi(m) for m in periods["missing"]} if periods else set()
        self.evidence_to = source.get("evidence_to")

    def has(self, m: int, values: Optional[dict] = None) -> bool:
        if not self.known:
            return values is None or values.get(_ms(m)) is not None
        return self.first <= m <= self.last and m not in self.missing

    def last_month(self, fallback: int) -> int:
        """The last month a figure can be read at, never after `fallback` (the as-of month)."""
        if not self.known:
            return fallback
        return min(self.last, fallback)

    def detail(self, read: List[int]) -> str:
        """Why none of the months `read` is in the data (section 4, "Not covered")."""
        name = _short(self.metric)
        if self.known and all(m < self.first for m in read):
            return f"before {name}'s first month, {_ms(self.first)}"
        if self.known and all(m > self.last for m in read):
            if self.metric in REVENUE_FILE_METRICS and self.evidence_to:
                return AFTER_SOURCE_DETAIL.format(month=self.evidence_to)
            return f"after {name}'s last month, {_ms(self.last)}"
        return f"months missing: {_month_ranges(sorted(read))}"


def _forecast_view(results: dict, metric: Optional[str], segment: str, start: Optional[int], end: Optional[int], as_of_i: Optional[int],
                   low: Optional[float], high: Optional[float], fiscal_year_end: int, span: "_Span", mismatch: Optional[str] = None) -> dict:
    """{"lines", "details", "text"} of a forecast claim: the calculation of forecast_calc over the metric's months the data can be read at,
    and the words after "Forecast: " on the row. A metric forecast_calc does not read has no lines."""
    if metric not in FORECAST_METRICS or low is None or start is None or end is None or as_of_i is None:
        return {"lines": [], "details": [], "text": FORECAST_NO_CALC}
    currency = results.get("reporting_currency")
    money = (lambda v: _money(v, currency)) if metric != "Customer count" else (lambda v: _shown(v))
    shown = money(low) if high is None else f"{money(min(low, high))}–{money(max(low, high))}"
    if mismatch:
        view = forecast_calc.unavailable(mismatch, shown, start, end, fiscal_year_end, flow=metric in forecast_calc.FLOWS)
    else:
        got = _Figures(results, metric, segment).monthly()
        values = got[0] if got else {}
        series = {_mi(m): v for m, v in values.items() if v is not None and span.has(_mi(m), values)}
        view = forecast_calc.diagnose(metric=metric, series=series, last=span.last_month(as_of_i), start=start, end=end, low=low, high=high,
                                      fye=fiscal_year_end, money=money)
    return {"lines": view["lines"], "details": view["details"], "text": view["text"]}


def _year_column(columns: list, start: int, end: int):
    """(column, reason) of the yearly column whose first and last month are the claim's, else None with `period not covered` when a column of the
    same year number ends in another month, else None with no reason."""
    year = next((y for y in columns if y.get("period_start") == _ms(start) and y.get("period_end") == _ms(end)), None)
    if year is not None:
        return year, None
    other = next((y for y in columns if (y.get("period_end") or "")[:4] == _ms(end)[:4] and y.get("period_end") != _ms(end)), None)
    if other:
        return None, PERIOD_NOT_COVERED.format(claim=period_words(_ms(end)), name=other["period"], file=period_words(other["period_end"]))
    return None, None


def yearly_year(results: dict, start: int, end: int, plan: bool = False):
    """(year, reason) for a claim period [start, end] (month indexes) against the yearly columns of the P&L read as a statement
    (dates-and-periods.md section 3): the column whose first and last month are the claim's, else None with `period not covered` when a
    column of the same year number ends in another month (never a mismatch), else None with no reason. The one rule for every claim
    matched against a yearly column (docs/design/pnl-lines.md section 7): the actual years (`yearly_basis`) and, with `plan`, the plan years
    of the statement (`pnl_lines`)."""
    columns = (results.get("pnl_lines") or {}).get("plan") if plan else (results.get("yearly_basis") or {}).get("years")
    return _year_column(columns or [], start, end)


def _annual_payback(out: dict, results: dict, text: str, start: int, end: int):
    """(observed, observed_at, source, reason) of a CAC payback claim whose period is one fiscal year, read against the yearly-basis block
    (forecast-and-payback.md section 4): both proxies are listed in `calc_lines`, and the claim is compared with one of them only when its own
    words state a definition that matches the annual calculation. A claim the annual figure does not answer keeps the Missing Data link, so the
    request for a monthly P&L still names it; one it answers does not."""
    currency = results.get("reporting_currency")
    money = lambda v: _money(v, currency)      # noqa: E731
    label = out.get("period") or f"{_ms(start)} to {_ms(end)}"
    item = _missing_item(results, "CAC payback")

    def blocked(reason: str):
        if item:
            out.update(evidence_analysis=str(item.get("metric")), evidence_source_key=MISSING_KEY)
        return f"Unverified|{reason}", None, None, None

    year, why_not = yearly_year(results, start, end)
    if year is None:
        return blocked(ANNUAL_NOT_CALCULATED.format(year=label, reason=why_not or ANNUAL_NO_YEAR))
    name = year["period"]
    gm = year.get("gross_margin_pct")
    proxies = ((payback_definition.REVENUE_GROWTH, "revenue-growth proxy", year.get("cac_payback_months"), year.get("cac_payback_reason"),
                year.get("new_revenue")),
               (payback_definition.NET_NEW_ARR, "net-new-ARR proxy", year.get("cac_payback_net_new_arr_months"),
                year.get("cac_payback_net_new_arr_reason"), year.get("net_new_arr")))
    lines, details = [], ["annual payback = 12 × S&M ÷ (incremental annual recurring value × gross margin)"]
    for denominator, proxy, months, reason, amount in proxies:
        # docs/design/pnl-lines.md section 6: the revenue-growth proxy is the yearly, revenue-based payback; its unit stays, its label follows
        revenue = denominator == payback_definition.REVENUE_GROWTH
        label = f" ({YEARLY_REVENUE_BASED})" if revenue else ""
        head = f"CAC payback {name}" if revenue else f"Annual payback {name} ({proxy})"
        if months is not None:
            lines.append(f"{head}: {fmt.fmt_months(months)}{label} = 12 × S&M "
                         f"{money(year['sm_expense'])} ÷ ({denominator} {money(amount)} × gross margin {fmt.fmt_pct(gm)})")
        else:
            lines.append(f"{head}{label}: not calculated – {reason}")
    scope = year.get("sm_scope") or "unknown"
    claimed = payback_definition.claimed_definition(text)
    lines += [f"S&M scope: {scope}", "Claim definition: " + ", ".join(claimed[k] or "not stated" for k in ("denominator", "margin", "cost"))]
    details += [f"revenue growth = revenue {name} less the year before", "net new ARR = year-end ARR less the prior year-end ARR "
                f"({_money(year['arr_year_end'], currency) if year.get('arr_year_end') is not None else 'not in the data'} and "
                f"{_money(year['arr_prior_year_end'], currency) if year.get('arr_prior_year_end') is not None else 'not in the data'})"]
    out.update(calc_lines=lines, calc_details=details)
    reason = payback_definition.compare(claimed, {"denominators": tuple(ANNUAL_KEYS), "margin": payback_definition.GROSS_MARGIN, "cost": scope})
    if reason:
        return blocked(reason)
    months, why = next((m, r) for d, _, m, r, _ in proxies if d == claimed["denominator"])
    if months is None:
        return blocked(ANNUAL_NOT_CALCULATED.format(year=name, reason=why))
    key = ANNUAL_KEYS[claimed["denominator"]]
    source = _source({"source": year.get("source")})
    observed_at = f"{name} (annual)"
    out.update(evidence_analysis=ANNUAL_ANALYSIS, evidence_source_key=key, observed_citation=citation(key, source, observed_at))
    return months, observed_at, source, None


def _not_covered(span: "_Span", read: List[int], cov: dict) -> str:
    cov.update(coverage=NOT_COVERED, missing=[_ms(m) for m in sorted(read)])
    return f"Unverified|{NOT_COVERED_REASON.format(detail=span.detail(read))}"


def _after_data(span: "_Span", end: int, as_of_i: int, cov: dict) -> str:
    """Not covered: the claim's period ends after the as-of month (the engine has no block, or no figure, for it)."""
    cov.update(coverage=NOT_COVERED, missing=[_ms(end)])
    detail = span.detail([end]) if span.known and end > span.last else f"after {_short(span.metric)}'s last month, {_ms(as_of_i)}"
    return f"Unverified|{NOT_COVERED_REASON.format(detail=detail)}"


def _yearly_revenue(results: dict, start: Optional[int], end: Optional[int]) -> Optional[dict]:
    """The revenue of a fiscal year the yearly P&L holds (its column ends in the claim's month): {"value", "source"}, the source naming the file, the
    sheet and the cells of the revenue line; None when the P&L holds no such column or no revenue for it (docs/design/deck-actuals.md section 2)."""
    if start is None or end is None:
        return None
    year, _ = yearly_year(results, start, end)
    if not year or year.get("revenue") is None:
        return None
    src = year.get("source") or {}
    cells = list(year.get("revenue_cells") or [])
    return {"value": year["revenue"], "name": year["period"],
            "source": {"file": src.get("file"), "sheet": src.get("sheet"), "rows": src.get("rows"),
                       "rule": f"Revenue of {year['period']} from the yearly P&L", "cells": cells}}


def _revenue_over(results: dict, start: int, end: int, span: "_Span") -> Optional[dict]:
    """The company's revenue over the months start..end: the monthly series when it holds every month, else the yearly P&L's column for the year."""
    figures = _Figures(results, "Revenue", WHOLE)
    got = figures.monthly()
    if got is not None and got[0]:
        values, source, _ = got
        months = list(range(start, end + 1))
        if all(span.has(m, values) and values.get(_ms(m)) is not None for m in months):
            return {"value": round(sum(values[_ms(m)] for m in months), 2), "name": f"{_label_of(start)}–{_label_of(end)}", "source": source}
    return _yearly_revenue(results, start, end)


def _multiple(results: dict, start: Optional[int], end: Optional[int], span: "_Span", cov: dict):
    """(observed, observed_at, source, reason) of a growth multiple (docs/design/deck-actuals.md): the revenue of the claim's twelve months over the revenue
    of the twelve months before, from the files; the source names the cells of both years. Returns what `_observe` returns."""
    if start is None or end is None:
        return f"Unverified|{PERIOD_NOT_READ}", None, None, None
    if end - start != 11:
        return "Unsupported|a growth multiple is tested for a twelve-month period", None, None, None
    now, before = _revenue_over(results, start, end, span), _revenue_over(results, start - 12, end - 12, span)
    if now is None or before is None:
        return None, "missing", None, None
    if not before["value"] or before["value"] <= 0:
        return f"Unverified|{GROWTH_BASE_REASON}", None, None, None
    cov.update(coverage=COVERED, missing=[])
    src, prior = now["source"] or {}, before["source"] or {}
    cells = [*(prior.get("cells") or ()), *(src.get("cells") or ())]
    source = {"file": src.get("file"), "sheet": src.get("sheet"), "rows": src.get("rows"), "rule": MULTIPLE_RULE, **({"cells": cells} if cells else {}),
              "inputs": [{"name": f"{now['name']} revenue", "value": now["value"]}, {"name": f"{before['name']} revenue", "value": before["value"]}]}
    observed = round(now["value"] / before["value"], 4)
    return observed, f"{_ms(start)} to {_ms(end)} vs {_ms(start - 12)} to {_ms(end - 12)}", source, None


def _observe(figures: "_Figures", spec: dict, metric: str, start: Optional[int], end: Optional[int], as_of_i: Optional[int],
             span: Optional["_Span"] = None, cov: Optional[dict] = None, forecast: bool = False):
    """(observed, observed_at, source, reason) read as table 2b says, with the claim-period coverage of dates-and-periods.md
    section 4 written into `cov` (coverage, missing months). `observed` is a number, None, or a "Label|reason" verdict string
    when the claim cannot be tested; None with observed_at "missing" when the engine holds no figure for the metric at all.
    `forecast` is the claim's classification (docs/specs/forecast-and-payback.md section 2), never inferred from the period."""
    kind = spec["kind"]
    cov = {} if cov is None else cov
    span = span or _Span(figures.results, metric)
    if as_of_i is None:
        return None, "missing", None, None
    if end is None:                 # decision 3 of 2026-10-19: no as-of or latest figure stands in for a period that was not read
        return f"Unverified|{PERIOD_NOT_READ}", None, None, None
    if end > as_of_i and not forecast and kind in ("asof", "month"):      # an actual after the data is missing coverage, whatever the kind
        return _after_data(span, end, as_of_i, cov), None, None, None

    if kind == "asof":
        got = figures.asof()
        if got is None:
            return None, "missing", None, None
        value, source, why = got
        if end is not None and not forecast and end != as_of_i:
            return "Unsupported|the figure is computed at the as-of month, not for this period", None, None, None
        if value is not None:
            cov.update(coverage=COVERED, missing=[])
        return value, _ms(as_of_i), source, why or "not computed"

    if kind == "month":
        if metric == "NRR (12-month)" and figures.segment != WHOLE:
            got = figures.asof()
            if got is None:
                return None, "missing", None, None
            value, source, why = got
            if end is not None and not forecast and end != as_of_i:
                return "Unsupported|the figure by segment is computed at the as-of month, not for this period", None, None, None
            return value, _ms(as_of_i), source, why or "not computed"
        got = figures.monthly()
        if got is None:
            return None, "missing", None, None
        values, source, why = got
        if why == "segment not in the data":
            return "Unsupported|segment not in the data", None, None, None
        months = sorted(values, key=_mi)
        first = months[0] if months else None
        # no period, or a forecast: the latest figure, at the evidence end, never at an as-of month the data does not reach
        target = span.last_month(as_of_i) if end is None or forecast else end
        if first is not None and target < _mi(first) and not span.known:
            return f"Unverified|{NOT_COVERED_REASON.format(detail=span.detail([target]))}", None, None, None
        if not forecast and not span.has(target, values if not span.known else None):
            if span.known:
                return _not_covered(span, [target], cov), None, None, None
        value = values.get(_ms(target))
        if value is not None and not forecast:
            cov.update(coverage=COVERED, missing=[])
        return value, _ms(target), source, why or "not computed for that month"

    if kind == "sum":
        got = figures.monthly()
        yearly = _yearly_revenue(figures.results, start, end) if metric == "Revenue" and figures.whole and not forecast else None
        if got is None and yearly:                          # no monthly series: the yearly P&L's column for the year (deck-actuals.md section 2)
            cov.update(coverage=COVERED, missing=[])
            return yearly["value"], f"{_ms(start)} to {_ms(end)}", yearly["source"], None
        if got is None:
            return None, "missing", None, None
        values, source, why = got
        if why == "segment not in the data":
            return "Unsupported|segment not in the data", None, None, None
        if start is None:
            return f"Unverified|{PERIOD_NOT_READ}", None, None, None
        months = sorted(values, key=_mi)
        first = _mi(months[0]) if months else None
        if forecast:
            used = [m for m in range(max(start, first or start), as_of_i + 1) if _ms(m) in values and span.has(m, values)]
            if not used:
                return None, _ms(as_of_i), source, None
        else:
            period = list(range(start, end + 1))
            used = [m for m in period if span.has(m, values) and values.get(_ms(m)) is not None]
            absent = [m for m in period if m not in used]
            if not used and yearly:                         # the monthly series holds none of the year, the yearly P&L holds all of it
                cov.update(coverage=COVERED, missing=[])
                return yearly["value"], f"{_ms(start)} to {_ms(end)}", yearly["source"], None
            if not used:
                return _not_covered(span, period, cov), None, None, None
            if absent:                                     # some months of the period are in the data: the figure over them
                cov.update(coverage=PARTLY_COVERED, missing=[_ms(m) for m in absent])
                total = round(sum(values[_ms(m)] for m in used), 2)
                return total, f"{_ms(used[0])} to {_ms(used[-1])} ({len(used)} of {len(period)} months)", source, None
            cov.update(coverage=COVERED, missing=[])
        total = round(sum(values[_ms(m)] for m in used), 2)
        return total, f"{_ms(used[0])} to {_ms(used[-1])}", source, None

    # quarter
    got = figures.quarters()
    if got is None:
        return None, "missing", None, None
    quarters, source = got
    if end is None or forecast:
        q = figures.headline(quarters)
        if q is None:
            return None, "missing" if not quarters else _ms(as_of_i), source, "no quarter has a figure"
    else:
        q = _quarter(start, end)
        if q is None:
            return "Unsupported|the period is not one calendar quarter of the data", None, None, None
        first = min(quarters, key=lambda k: (int(k.split("-Q")[0]), int(k.split("-Q")[1])))
        if _mi(_quarter_first_month(q)) < _mi(_quarter_first_month(first)):
            cov.update(coverage=NOT_COVERED, missing=[_ms(m) for m in range(start, end + 1)])
            detail = f"before {_short(metric)}'s first month, {_quarter_first_month(first)}"
            return f"Unverified|{NOT_COVERED_REASON.format(detail=detail)}", None, None, None
        if q not in quarters:           # the engine holds no value for the quarter: Unverified, the reason names its months (2026-10-23)
            return _not_covered(span, list(range(start, end + 1)), cov), None, None, None
    item = quarters[q]
    if item["value"] is not None and not forecast:
        cov.update(coverage=COVERED, missing=[])
    return item["value"], q, source, item["reason"] or "not computed"


def _growth(figures: "_Figures", spec: dict, basis: str, start: Optional[int], end: Optional[int], as_of_i: Optional[int],
            span: "_Span", cov: dict, forecast: bool = True):
    """The growth of the metric's monthly series on `basis` for the claim's period [s, e] (dates-and-periods.md section 5), in
    percentage points, computed on read from the stored series as the revenue sum is. The four bases read different months; only
    the claim's basis is computed and tested. Returns what `_observe` returns."""
    got = figures.monthly()
    if got is None or as_of_i is None:
        return None, "missing", None, None
    values, source, why = got
    if why == "segment not in the data":
        return "Unsupported|segment not in the data", None, None, None
    if end is None:
        return f"Unverified|{PERIOD_NOT_READ}", None, None, None
    if end > as_of_i:
        if not forecast:                                # a period after the data is missing coverage unless the claim is a forecast
            return _not_covered(span, [end], cov), None, None, None
        return None, None, source, None                 # a forecast: the caller says so
    e = span.last_month(as_of_i) if end is None else end
    s = e if start is None or end is None else start
    if basis in ("cumulative", "annualised") and e <= s:
        return f"Unverified|{GROWTH_WINDOW_REASON}", None, None, None
    window = basis == "yoy" and spec["base"] == "Revenue" and e > s      # revenue of the period against the same months a year earlier
    if basis == "mom":
        now, then = [e], [e - 1]
    elif basis == "yoy":
        now = list(range(s, e + 1)) if window else [e]
        then = [m - 12 for m in now]
    else:
        now, then = [e], [s]
    read = sorted(set(now + then))
    present = [m for m in read if span.has(m, values) and values.get(_ms(m)) is not None]
    if not present:
        return _not_covered(span, read, cov), None, None, None
    if len(present) < len(read):
        return _not_covered(span, [m for m in read if m not in present], cov), None, None, None     # a compared month is outside the data
    current, base = sum(values[_ms(m)] for m in now), sum(values[_ms(m)] for m in then)
    if base <= 0 or current < 0:
        return f"Unsupported|{GROWTH_BASE_REASON}", None, None, None
    ratio = current / base
    growth = ratio ** (12 / (e - s)) - 1 if basis == "annualised" else ratio - 1
    if window:
        at = f"{_ms(s)} to {_ms(e)} vs {_ms(s - 12)} to {_ms(e - 12)}"
    elif basis in ("mom", "yoy"):
        at = f"{_ms(e)} vs {_ms(then[0])}"
    else:
        at = f"{_ms(s)} to {_ms(e)}"
    rule = GROWTH_RULES["yoy_sum" if window else basis]
    cov.update(coverage=COVERED, missing=[])
    return round(growth * 100, 2), at, ({**source, "rule": rule} if source else None), None


# --- overlaps (verdict-and-memo.md section 2.2) ----------------------------------------------------------------------

_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")


def observed_months(observed_at: Optional[str]) -> set:
    """The months an observed figure stands for: a month, a calendar quarter (its three months) or 'a to b'."""
    if not observed_at:
        return set()
    if " to " in observed_at:
        first, last = observed_at.split(" to ", 1)
        if _MONTH.match(first) and _MONTH.match(last):
            return set(range(_mi(first), _mi(last) + 1))
        return set()
    if _MONTH.match(observed_at):
        return {_mi(observed_at)}
    q = _QUARTER.match(observed_at)
    if q:
        start = _mi(_quarter_first_month(observed_at))
        return {start, start + 1, start + 2}
    return set()


def _same_measure(a: Optional[str], b: Optional[str]) -> bool:
    return a is not None and (a == b or {a, b} == {"ARR", "MRR"})


def _overlaps(rows: List[dict]) -> None:
    """Fill `overlaps_with` (claim ids in rank order). Two rows overlap when their metrics are the same (or ARR and MRR), they
    have the same segment or either is Whole company, and their observed periods share a month. A row with no observed
    figure overlaps with nothing. Symmetric. A row whose overlaps are null (a forecast-table claim) stays null."""
    months = {r["claim_id"]: observed_months(r["observed_at"]) if r["observed_value"] is not None else set() for r in rows}
    for r in rows:
        if r["overlaps_with"] is None:
            continue
        mine = months[r["claim_id"]]
        r["overlaps_with"] = [o["claim_id"] for o in rows if o is not r and mine and months[o["claim_id"]] & mine
                              and _same_measure(r["metric"], o["metric"])
                              and (r["segment"] == o["segment"] or WHOLE in (r["segment"], o["segment"]))]


# --- the register -----------------------------------------------------------------------------------------------------

# George, 2026-10-25: a row whose reason asks the analyst to set or confirm something is a card under "Needs your attention" and an open
# question; the control is the claim's editor in the claims list. Not Verified or Contradicted, whatever the reason says.
ASK_REASONS = (PERIOD_NOT_READ, PERIOD_UNCLEAR, PERIOD_MISSING, "required field unknown", GROWTH_UNKNOWN_REASON, "churn rate unclear")


def undated_by_page(rows: List[dict], kept: Iterable[str] = ()) -> Dict[str, dict]:
    """The claims the register reads as "Period not read", grouped by the page they stand on (George, 2026-10-27): {claim id: {"key", "page",
    "n"}} for each claim on a page where two or more of them stand, `n` being their number there. One card asks for the period of the page's
    undated figures; a claim the analyst chose to keep undated (`kept`) asks nothing."""
    pages: Dict[tuple, List[str]] = {}
    for row in rows:
        cid = str(row["claim_id"]).split("#")[0]
        if asks_analyst(row) and str(row.get("reason") or "").startswith(PERIOD_NOT_READ) and cid not in kept:
            ids = pages.setdefault((row.get("deck_file"), row.get("page_ref")), [])
            if cid not in ids:
                ids.append(cid)
    out = {}
    for (deck, page), ids in pages.items():
        if len(ids) > 1:
            key = hashlib.sha256(f"undated|{deck}|{page}".encode("utf-8")).hexdigest()[:16]
            out.update({cid: {"key": key, "page": page, "n": len(ids)} for cid in ids})
    return out


def asks_analyst(row: dict) -> bool:
    return row.get("evidence_label") in ("Unverified", "Unsupported", INCONCLUSIVE) and str(row.get("reason") or "").startswith(ASK_REASONS)


def is_untested(row: dict) -> bool:
    """A row that is never matched, ranked among the tested ones, gated or put in the top 5: use of funds, acquisition channels, a
    claim read from a forecast table (chat-upload.md section 20), unit economics (ARPA, ARPU), a pipeline column (George,
    2026-10-20) and a best-case or worst-case figure (George, 2026-10-23)."""
    return row.get("claim_type") in UNTESTED_TYPES or row.get("deck_reading") == FORECAST_READING \
        or row.get("claim_type") in UNIT_ECONOMICS or row.get("claim_type") == "pipeline" or row.get("metric") in UNIT_ECONOMICS.values() \
        or row.get("scenario") in SCENARIO_CASES


# George, 2026-10-24 (claim-matching.md section 6): value at stake is the ARR a claim stands for, in the reporting currency, once Target ARR
# and Target date are set. Revenue-like amounts are annualised from their period (ARR as stated, MRR times 12, a quarter times 4) and capped at
# Target ARR; a rate is its share of the current ARR; a customer count is the count times the ACV. Any other claim has no ARR link.
VAS_RATE_TYPES = ("churn", "nrr", "revenue_growth", "growth")
VAS_COUNT_TYPES = ("customers",)
VAS_AMOUNT_TYPES = ("arr", "mrr", "revenue", "sales")
VAS_EMPTY = "not yet computed: {fields} empty"
VAS_NO_LINK = "no ARR link: {why}"
VAS_RUN_RATE = "run-rate: {period} × {multiplier}"       # the amount of a short period annualised, with the period and the multiplier (design note section 1)


def _value_at_stake(row: dict, results: dict, settings: dict) -> dict:
    """Sets `value_at_stake_arr` and `vas_reason` on a register row: the figure, or the reason it is none (the empty set-up field, the
    missing input, or no ARR link). Reads nothing a model wrote."""
    row.update(value_at_stake_arr=None, vas_reason=None)
    if is_untested(row) or row.get("claim_type") in UNTESTED_TYPES:
        row["vas_reason"] = VAS_NO_LINK.format(why="untested claim")
        return row
    empty = [name for name, value in (("Target ARR", settings.get("target_arr")), ("Target date", settings.get("target_date"))) if not value]
    if empty:
        row["vas_reason"] = VAS_EMPTY.format(fields=" and ".join(empty))
        return row
    kind, low = row.get("claim_type"), row.get("claimed_value")
    if low is None:
        row["vas_reason"] = VAS_NO_LINK.format(why="no claimed figure")
        return row
    arr = (results.get("arr") or {}).get("value")
    if kind in VAS_RATE_TYPES and row.get("unit") == "%":
        if arr is None:
            row["vas_reason"] = VAS_NO_LINK.format(why="ARR not computed")
        else:
            row["value_at_stake_arr"] = abs(low) / 100 * arr
    elif kind in VAS_COUNT_TYPES:
        acv = (results.get("acv_path") or {}).get("acv")
        if acv is None:
            row["vas_reason"] = VAS_NO_LINK.format(why="ACV not computed")
        else:
            row["value_at_stake_arr"] = abs(low) * acv
    elif kind in VAS_AMOUNT_TYPES and (row.get("currency") or row.get("unit") in (None, "")):
        reporting = results.get("reporting_currency")
        amount = row["claimed_converted"] if row.get("claimed_converted") is not None else low
        if row.get("currency") and reporting and row["currency"] != reporting and row.get("claimed_converted") is None:
            row["vas_reason"] = VAS_NO_LINK.format(why=FX_NEEDED)
            return row
        months, level = 12, False
        if row.get("metric") == "MRR" or kind == "mrr":
            months, level = 1, True       # MRR times 12 is the metric's definition of ARR, not an annualised flow: no run-rate mark
        elif row.get("metric") != "ARR" and kind != "arr":
            start, end = _month_of(row.get("period_start")), _month_of(row.get("period_end"))
            if start is None or end is None:
                row["vas_reason"] = VAS_NO_LINK.format(why="period missing")
                return row
            months = max(end - start + 1, 1)
        row["value_at_stake_arr"] = min(abs(amount) * 12 / months, float(settings["target_arr"]))
        if months != 12 and not level:
            row["vas_reason"] = VAS_RUN_RATE.format(period=row.get("period") or f"{months} month{'s' if months != 1 else ''}",
                                                    multiplier=_shown(12 / months))
    else:
        row["vas_reason"] = VAS_NO_LINK.format(why=f"{kind} has no ARR conversion")
    return row


def _rank(rows: List[dict]) -> List[dict]:
    """Rows with a gap other than "to go" by normalised gap, largest first (a beat counts as 0); then the rest in register order,
    then the use-of-funds, acquisition-channel and forecast-table rows."""
    def key(r):
        norm = r["gap_normalised"]
        if r["gap_kind"] == "beat" or norm is None and r["gap"] == 0:
            return 0.0
        return float("inf") if norm is None else max(norm, 0.0)
    ranked = [r for r in rows if r["gap"] is not None and r["gap_kind"] != "to go"]
    funds = [r for r in rows if is_untested(r)]
    rest = [r for r in rows if r not in ranked and r not in funds]
    ordered = sorted(ranked, key=key, reverse=True) + rest + funds         # use of funds last: no claim's rank depends on it
    for rank, row in enumerate(ordered, 1):
        row["rank"] = rank
    return ordered


def plan_candidates(results: Optional[dict]) -> List[dict]:
    """The plan cells of the statement (`pnl_lines.plan`) as candidates of origin PLAN_FILE, each with its source "File <sheet>!<cell> (plan)".
    The id is the cell's own identity (sheet, line, period), so it holds when a column moves. A forecast-table claim of the same cell is
    folded into it by `_fold_forecast_table`."""
    block = (results or {}).get("pnl_lines") or {}
    file = (block.get("source") or {}).get("file")
    out = []
    for p in block.get("plan") or ():
        sheet = p["source"].get("sheet")
        if p["metric"] not in PLAN_CLAIM_TYPES:
            continue
        last = calendar.monthrange(int(p["period_end"][:4]), int(p["period_end"][5:7]))[1]
        out.append({"id": f"plan:{sheet}:{PLAN_CLAIM_TYPES[p['metric']]}:{p['period'].replace(' ', '')}", "claim_type": PLAN_CLAIM_TYPES[p["metric"]], "value": p["value"], "value_high": None, "unit": None,
                    "currency": results.get("reporting_currency"), "target_date": p["period_end"][:4], "period_text": p["period"],
                    "period_start": f"{p['period_start']}-01", "period_end": f"{p['period_end']}-{last:02d}", "snippet": p["metric"],
                    "label_from": None, "file": file, "sources": [{"file": file, "sheet": sheet, "cell": p["cell"], "kind": "plan",
                                                                   "plan_ref": p["source_text"]}],
                    "origin": PLAN_FILE, "status": "approved", "basis": "projection", "scenario": "none", "plan": p})
    return out


def _fold_forecast_table(claims: List[dict], plans: List[dict]) -> List[dict]:
    """A claim of the confirmed forecast table that reads a plan cell is the plan row itself (docs/design/pnl-lines.md section 4): one claim,
    two sources. The table row leaves the list and its cell joins the plan row's sources, so the plan row keeps its place in the ranking."""
    by_cell = {(p["sources"][0].get("sheet"), p["sources"][0].get("cell")): p for p in plans}
    kept = []
    for c in claims:
        srcs = c.get("sources") or ()
        plan = by_cell.get((srcs[0].get("sheet"), srcs[0].get("cell"))) if len(srcs) == 1 and c.get("origin") == FORECAST_FILE else None
        if plan is None:
            kept.append(c)
            continue
        plan["sources"].append({**srcs[0], "plan_ref": f"{srcs[0].get('sheet')}!{srcs[0].get('cell')} (forecast table)"})
    return kept


def _plan_lines(p: dict, currency: Optional[str]) -> List[str]:
    """The calculation lines of a plan row: the implied rate, the observed one and the gap in points, each with the columns it compares."""
    shown = lambda v: "not calculated" if v is None else fmt.fmt_pct(v)      # noqa: E731
    implied, observed, gap = p["implied"], p["observed"], p["gap_points"]
    first, second = (p["compared"].split(" against ") + [""])[:2]
    word = "growth" if p["measure"] == "growth" else "share of revenue"
    lines = [f"Plan {p['period']}: {_money(p['value'], currency)} at {p['source_text']}",
             f"Implied {word} {first}: {shown(implied)}" + (f" – {p['reason']}" if implied is None else "")]
    lines.append(f"Observed {word} {second}: {shown(observed)}" + (f" – {p['reason']}" if implied is not None and observed is None else ""))
    if gap is not None:
        lines.append(f"Gap: {fmt.fmt_signed(gap)} points")
    return lines


def _compare_plan(rows: List[dict], results: dict) -> List[dict]:
    """The plan rows against the deck forecasts of the same line and period (docs/design/pnl-lines.md section 4). The deck period is matched
    to the plan year through `yearly_year`. Within tolerance the two are one claim with two sources: the plan row goes and its source joins
    the deck row's. Beyond it the plan row reads "plan in file differs from plan in deck" (Worth flagging). A deck period the plan years do not
    cover reads "period not covered" on the deck row. Nothing here changes a label."""
    plans = [r for r in rows if r.get("deck_reading") == PLAN_READING and r["claim_type"] in PLAN_DECK_TYPES]
    if not plans:
        return rows
    currency, gone = results.get("reporting_currency"), set()
    for deck in rows:
        if deck.get("deck_reading") == PLAN_READING or deck.get("claim_type") not in PLAN_DECK_TYPES + PLAN_PERCENT_DECK or deck.get("figure_type") != "target" \
                or deck.get("claimed_value") is None or deck.get("segment") not in (None, WHOLE) or not deck.get("period_start") \
                or not deck.get("period_end"):
            continue
        year, why = yearly_year(results, _month_of(deck["period_start"]), _month_of(deck["period_end"]), plan=True)
        if year is None:
            if why:
                deck["calc_lines"] = list(deck.get("calc_lines") or []) + [f"Plan in file: {why}"]
            continue
        percent = deck.get("unit") == "%"
        for plan in plans:
            if plan["period"] != year["period"] or plan["claim_id"] in gone:
                continue
            if percent:         # like with like (PR 200 review, N1): a deck margin or growth against the plan's implied rate, in points
                shares = PLAN_PERCENT_TYPES[plan["plan_measure"]]
                implied = plan.get("plan_implied")
                if deck["claim_type"] not in shares or plan["claim_type"] != shares[deck["claim_type"]] or implied is None:
                    continue
                claimed, filed = deck["claimed_value"], implied * 100
                gap = filed - claimed
                within, shown = abs(gap) <= RATE_TOLERANCE_PP, lambda v: f"{_shown(v)}%"      # noqa: E731
                tol, size = RATE_TOLERANCE_TEXT, f"{fmt.fmt_signed(gap)} points"
                what = f"implied {'growth' if plan['plan_measure'] == 'growth' else 'share of revenue'} "
            else:
                if plan["claim_type"] != deck["claim_type"] or deck["claim_type"] not in PLAN_DECK_TYPES:
                    continue
                claimed = deck["claimed_converted"] if deck.get("claimed_converted") is not None else deck["claimed_value"]
                if deck.get("currency") not in (None, currency) and deck.get("claimed_converted") is None:
                    continue
                filed = plan["claimed_value"]
                gap = filed - claimed
                within, shown = within_tolerance("Revenue", gap, claimed), lambda v: _money(v, currency)      # noqa: E731
                tol, size = tolerance_text("Revenue"), fmt.fmt_signed_pct(gap / abs(claimed)) if claimed else ""
                what = ""
            if within:
                deck["page_ref"] = ", ".join(x for x in (deck.get("page_ref"), plan["page_ref"]) if x)
                deck["calc_lines"] = list(deck.get("calc_lines") or []) + [
                    f"Plan in file: {what}{shown(filed)} at {plan['page_ref']}, within {tol} of the deck"]
                gone.add(plan["claim_id"])
            else:
                text = f"{PLAN_DIFFERS}: file {what}{shown(filed)}, deck {shown(claimed)} ({size})" if size else f"{PLAN_DIFFERS}"
                plan.update(reason=text, gloss=text)
                deck["calc_lines"] = list(deck.get("calc_lines") or []) + [f"Plan in file: {what}{shown(filed)} at {plan['page_ref']} – {PLAN_DIFFERS}"]
    return [r for r in rows if r["claim_id"] not in gone]


def build_register(candidates: List[dict], results: Optional[dict], settings: dict,
                   peers: Optional[List[dict]] = None) -> List[dict]:
    """The claim register: one row per claim, in rank order. `candidates` are the approved and edited rows in register
    order; `settings` carries fiscal_year_end, as_of_month (as set on the audit, None when defaulted),
    reporting_currency and fx. `peers` are the candidates the deck hint of section 11 point 7 reads: every one not
    rejected, pending ones included (None: the register's own). Nothing is read from a model and nothing is changed."""
    if not results:
        return []
    from .decks.claims import OTHER_TYPES
    # Other figures are never matched, ranked or put in the top 5 (claim-types-and-correction.md section 4)
    candidates = with_confidence([c for c in candidates if c.get("claim_type") not in OTHER_TYPES],
                                 peers if peers is not None else candidates)
    claims = _expand(candidates)
    plans = _expand(plan_candidates(results))                   # the statement's plan cells (docs/design/pnl-lines.md section 4)
    claims = _fold_forecast_table(claims, plans)
    others = _expand(peers) if peers is not None else claims
    claims += plans
    rows = [_value_at_stake(_mark_auto(_row(c, results, settings, others), c), results, settings) for c in claims]
    rows = _rank(_compare_plan(rows, results))
    _overlaps(rows)
    from . import claim_groups      # the relationships of docs/specs/claim-groups.md; a part adds no exposure of its own
    claim_groups.annotate(rows, settings.get("group_choices"), settings.get("fiscal_year_end"))
    return rows


# Simplified flow (George, 2026-10-25): Python enters a claim it matched to its page when no check asks about it; the register row reads
# `auto_approval` "auto" for such a row and nothing for a row the analyst answered, edited or added (memo Appendix A: "auto" / "analyst").
AUTO_REVOKED = "Re-opened – a check now asks about it"      # the note of a claim sent back to "Needs your attention"
AUTO_LABEL = "auto"
ANALYST_LABEL = "analyst"          # the memo's Approval column for every other register row (George, PR 157)
RATE_TOLERANCE_TEXT = "±1 pp"


def entered_by_python(c: dict) -> bool:
    """A claim Python entered on its own and the analyst has not touched since: `auto_accepted` on an approved claim that carries no edit."""
    return bool(c.get("auto_accepted") and c.get("status") == "approved" and "parsed" not in c)


def _mark_auto(row: dict, c: dict) -> dict:
    """Sets `auto_approval` ("auto") on the row of a claim Python entered. Display and the memo's Approval column only: no label, gap,
    rank or gate reads it."""
    if entered_by_python(c):
        row["auto_approval"] = AUTO_LABEL
    return row


def auto_views(candidates: List[dict], results: Optional[dict], settings: dict) -> Dict[str, dict]:
    """For each candidate Python entered on its own: `auto_approval` "auto" and the figure's citation when the register tested it,
    keyed by candidate id."""
    if not results:
        return {}
    marked = [c for c in candidates if entered_by_python(c)]
    out: Dict[str, dict] = {}
    for cid in {c["id"] for c in marked}:
        mine = [r for r in build_register([c for c in marked if c["id"] == cid], results, settings) if r["claim_id"].split("#")[0] == cid]
        if mine:
            widest = max(mine, key=lambda r: abs(r["gap_normalised"] or 0) + abs(r["gap"] or 0))
            out[cid] = {"auto_approval": AUTO_LABEL, "auto_citation": widest["observed_citation"]}
    return out


def confidence_level(candidate: dict, peers: List[dict]) -> str:
    """The extraction confidence the deck list shows (deck-parser.md section 6): High, Medium or Low, "Analyst-entered" for a
    claim added with Add claim, "Analyst-edited" for a parsed claim the analyst edited. `peers` are the candidates of the audit; only those of the candidate's deck are read."""
    from .decks.claims import confidence
    deck = candidate.get("deck_id") or candidate.get("file")
    same = [p for p in peers if (p.get("deck_id") or p.get("file")) == deck] or [candidate]
    found = confidence(candidate, same)
    return found["level"] or found["text"]


def with_confidence(candidates: List[dict], peers: List[dict]) -> List[dict]:
    """The candidates with `extraction_confidence` (evidence-labels.md section 1), kept where the caller set it. Display only: no
    label, gap, rank or gate reads it."""
    return [c if c.get("extraction_confidence") else {**c, "extraction_confidence": confidence_level(c, peers)} for c in candidates]


# Section 11 point 8: what the deck list shows of a turnover claim, before it is approved.
NO_FILE_PERIOD = "Revenue file does not cover this period"
TURNOVER_VIEW_FIELDS = ("claim_id", "period", "turnover_state", "turnover_note", "turnover_set_by", "turnover_reason",
                        "turnover_suggested", "deck_revenue_note", "implied_take_rate", "implied_take_rate_source")


def turnover_views(candidates: List[dict], results: Optional[dict], settings: dict) -> Dict[str, List[dict]]:
    """For each candidate that holds a turnover claim: one view per claim (one per value of a table row), keyed by candidate
    id, with the register's turnover fields, computed by the register's own code, and `file_note`: "Revenue file does not
    cover this period" when no revenue file covers the claim's period. Every candidate not rejected is read, pending ones included,
    and before the first Calculate (no results: no file covers any period). Nothing is read from a model."""
    results = results or {}
    as_of = results.get("as_of_month")
    as_of_i = _mi(as_of) if as_of else None
    claims = _expand([c for c in candidates if c.get("status") != "rejected"])
    out: Dict[str, List[dict]] = {}
    for c in claims:
        row = _row(c, results, settings, claims)
        if row["turnover_state"] is None:
            continue
        end = _month_of(c.get("period_end"))
        covered, _ = _file_revenue(results, row["segment"], _month_of(c.get("period_start")), end, as_of_i,
                                   row["figure_type"] == "target" and end is not None and as_of_i is not None and end > as_of_i)
        out.setdefault(c["id"], []).append({**{k: row[k] for k in TURNOVER_VIEW_FIELDS},
                                            "file_note": None if covered is not None else NO_FILE_PERIOD})
    return out


DEFINITION_VIEW_FIELDS = ("claim_id", "period", "definition_check", "definition_question")


def definition_rows(candidates: List[dict], results: Optional[dict], settings: dict) -> Dict[str, List[dict]]:
    """Section 4.1: the register rows with a Definition check (asked or answered), keyed by candidate id, computed by the register's
    own code over every candidate not rejected, pending ones included, so the Audit page can ask the question as a card.
    Empty before the first Calculate: no figure, no gap. Nothing is read from a model."""
    if not results:
        return {}
    claims = _expand([c for c in candidates if c.get("status") != "rejected"])
    out: Dict[str, List[dict]] = {}
    for c in claims:
        row = _row(c, results, settings, claims)
        if row["definition_check"] is not None:
            out.setdefault(c["id"], []).append(row)
    return out


def definition_views(candidates: List[dict], results: Optional[dict], settings: dict) -> Dict[str, List[dict]]:
    """`definition_rows` cut to the fields the deck list shows."""
    return {cid: [{k: r[k] for k in DEFINITION_VIEW_FIELDS} for r in rows]
            for cid, rows in definition_rows(candidates, results, settings).items()}


def open_definition_ids(views: Dict[str, List[dict]]) -> set:
    """The candidates of `definition_views` with a question still open. Approve all approves them like any other claim and
    counts the approved ones as `open_definition` (section 4.1)."""
    return {cid for cid, found in views.items() if any(v["definition_check"] == DEFINITION_ASK for v in found)}


def without_definition_answer(inputs: Optional[dict], claim_ids: Optional[set] = None) -> dict:
    """A candidate's `claim_inputs` with the Definition check answer dropped (of `claim_ids`, or of every claim): a re-typed or
    re-matched claim is asked again (section 4.1). A claim left with no input loses its entry."""
    out = {}
    for cid, kept in (inputs or {}).items():
        if claim_ids is None or cid in claim_ids:
            kept = {k: v for k, v in kept.items() if k not in ("definition_check", "definition_basis")}
        if kept:
            out[cid] = kept
    return out


def is_beat(row: dict) -> bool:
    """A Verified row whose observed figure beat the claim beyond tolerance (section 4): listed under Worth flagging."""
    return row.get("evidence_label") == "Verified" and str(row.get("reason") or "").startswith(BEAT_PREFIX)


def label_counts(rows: List[dict]) -> Dict[str, int]:
    """Rows per evidence label: the only thing a log line may say about the register. An open Definition check has no label and is
    in no count (section 4.1)."""
    counts: Dict[str, int] = {}
    for r in rows:
        if r["evidence_label"] is not None:
            counts[r["evidence_label"]] = counts.get(r["evidence_label"], 0) + 1
    return counts


def definition_counts(rows: List[dict]) -> Dict[str, int]:
    """Definition checks by state (section 4.1): open (ask), answered yes, answered no."""
    return {state: sum(1 for r in rows if r.get("definition_check") == state) for state in (DEFINITION_ASK, *DEFINITION_ANSWERS)}


def review_flags_of(c: dict, as_of: Optional[str]) -> List[str]:
    """The flags that list a claim under Review and keep it out of the bulk approvals: flags_of without the informational ones."""
    return review_flags(flags_of(c, as_of))
