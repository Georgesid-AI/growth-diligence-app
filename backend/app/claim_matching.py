"""Claim matching: every approved claim tested against the engine's computed metrics.

Spec: docs/specs/claim-matching.md. A pure module: it reads the register's candidate rows and the stored
`audits.results`, and returns one register row per claim with its metric, observed figure, gap, evidence
label and proposed gate. It imports nothing from `app.llm` and nothing reaches a model (CLAUDE.md rules
14, 17, 18); the deck text a row was found in (snippet, borrowed label) is read here to propose a metric
and a segment and is never copied into a row. Only Python sets Verified or Contradicted.
"""
from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

# The register's fields, in the order of the spec's section 6 (and the CSV header of section 7).
FIELDS = (
    "claim_id", "deck_file", "page_ref", "claim_type", "status", "deck_reading", "claimed_value", "claimed_high",
    "unit", "currency", "period", "period_start", "period_end", "period_note", "segment", "segment_set_by", "metric",
    "metric_set_by", "direction", "observed_value", "observed_at", "observed_source", "gap", "gap_normalised",
    "gap_kind", "gloss", "evidence_label", "reason", "tolerance", "rank", "value_at_stake_arr", "gate_sentence",
    "gate_threshold", "gate_budget_decision", "gate_date", "gate_saved", "as_of_month", "as_of_defaulted",
)

WHOLE, NOT_IN_DATA = "Whole company", "Not in the data"
NO_PERIOD = "no period stated"
SUGGESTION = "AI suggestion, not verified"
DAYS_PER_WEEK, DAYS_PER_MONTH = 7.0, 30.44
RATE_TOLERANCE_PP, AMOUNT_TOLERANCE = 1.0, 0.05
BUDGET_DECISION_MAX = 200

# Table 2a. kind: how the claim's period reads the metric (table 2b): "sum" over the period's months, the value in the
# period's end "month", one calendar "quarter", or the "asof" figure. `seg`: the engine splits it by segment.
# `missing`: words of the engine's Missing Data entry that stand for the metric.
METRICS: Dict[str, dict] = {
    "Revenue": dict(kind="sum", unit="currency", direction="higher", seg=True, missing=("arr / mrr",)),
    "ARR": dict(kind="month", unit="currency", direction="higher", seg=True, missing=("arr / mrr",)),
    "MRR": dict(kind="month", unit="currency", direction="higher", seg=True, missing=("arr / mrr",)),
    "Customer count": dict(kind="month", unit="count", direction="higher", seg=True, missing=("arr / mrr",)),
    "New MRR": dict(kind="quarter", unit="currency", direction="higher", seg=False, missing=("arr / mrr",)),
    "NRR (12-month)": dict(kind="month", unit="%", direction="higher", seg=True, missing=("nrr",)),
    "Gross revenue churn": dict(kind="month", unit="%", direction="lower", seg=False, missing=("gross revenue churn",)),
    "ACV": dict(kind="asof", unit="currency", direction="higher", seg=True, missing=("arr / mrr",)),
    "Median sales cycle": dict(kind="asof", unit="days", direction="lower", seg=True, missing=("sales cycle",)),
    "Win rate": dict(kind="asof", unit="%", direction="higher", seg=False, missing=("win rate",)),
    "Gross margin": dict(kind="quarter", unit="%", direction="higher", seg=False, missing=("cac payback",)),
    "CAC payback": dict(kind="quarter", unit="months", direction="lower", seg=False, missing=("cac payback",)),
}
NO_METRIC = "none"                      # what the analyst picks to say "no metric fits"

_DURATIONS = ("days", "weeks", "months", "years")
_CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}

_NEW_MRR = re.compile(r"(?i)\bnew mrr\b")
_MRR = re.compile(r"\bMRR\b|(?i:\bmonthly recurring revenue\b)")
_ARR = re.compile(r"\bARR\b|(?i:\bannual recurring revenue\b)")
_REVENUE = re.compile(r"(?i)\b(?:revenue|turnover)\b")
_RECURRING = re.compile(r"(?i)\b(?:annual|monthly) recurring revenue\b")
_NRR = re.compile(r"\bNRR\b|(?i:\bnet (?:revenue )?retention\b)")
_CHURN = re.compile(r"(?i)\b(?:revenue|gross) churn\b")
_ACV = re.compile(r"\bACVs?\b")
_SALES_CYCLE = re.compile(r"(?i)\bsales cycles?\b")
_WIN_RATE = re.compile(r"(?i)\bwin rates?\b")
_PAYBACK = re.compile(r"(?i)\bpayback\b")


# --- months and periods ----------------------------------------------------------------------------------------------

def _mi(month: str) -> int:
    """'2024-02' -> months since year 0."""
    y, m = month.split("-")
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


def gate_date(as_of: str, fiscal_year_end: int) -> str:
    """The last day of the first fiscal quarter that ends after the as-of month (spec section 5)."""
    i = _mi(as_of) + 1
    while (i % 12 + 1 - fiscal_year_end) % 3:
        i += 1
    return date(i // 12, i % 12 + 1, calendar.monthrange(i // 12, i % 12 + 1)[1]).isoformat()


# --- units, tolerance, gloss -------------------------------------------------------------------------------------------

def _claim_unit(c: dict) -> Optional[str]:
    """currency, %, days, weeks, months or count: what the claimed figure is measured in."""
    if c.get("currency"):
        return "currency"
    unit = (c.get("unit") or "").strip().lower()
    if unit == "%":
        return "%"
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


def _money(amount: float, currency: Optional[str], whole_millions: bool = False) -> str:
    symbol = _CURRENCY_SYMBOLS.get(currency or "", f"{currency} " if currency else "")
    amount = abs(amount)
    if whole_millions and amount >= 1_000_000:
        return f"{symbol}{amount / 1_000_000:.1f}M"
    return f"{symbol}{amount:,.0f}"


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
        amount = f"{size:.1f} {unit}"
    elif unit == "%":
        amount = f"{size:.1f} points"
    elif unit == "count":
        n = f"{size:,.0f}"
        amount = f"{n} customer{'' if n == '1' else 's'}"
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
        return f"{value:.1f}%"
    if unit in ("days", "months"):
        return f"{value:.1f} {unit}"
    return f"{value:,.0f}"


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
        if m in ("NRR (12-month)", "Gross revenue churn"):
            block = r.get("nrr" if m == "NRR (12-month)" else "gross_churn")
            if not block:
                return None
            field = "nrr_pct" if m == "NRR (12-month)" else "churn_pct"
            return {d["month"]: _points(d.get(field)) for d in block.get("series") or ()}, _source(block), block.get("reason")
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


def propose_metric(claim_type: str, claim_unit: Optional[str], text: str) -> Optional[str]:
    """The metric a claim names by its type, a keyword in its snippet or borrowed label, and its unit (table 2a)."""
    metric = None
    if claim_type == "revenue":
        plain = _RECURRING.sub(" ", text)
        if _NEW_MRR.search(text):
            metric = "New MRR"
        elif _MRR.search(text):
            metric = "MRR"
        elif _ARR.search(text):
            metric = "ARR"
        elif _REVENUE.search(plain) and not re.search(r"(?i)\brecurring revenue\b", plain):
            metric = "Revenue"
    elif claim_type == "customers":
        metric = "Customer count"
    elif claim_type == "retention":
        metric = "NRR (12-month)" if _NRR.search(text) else "Gross revenue churn" if _CHURN.search(text) else None
    elif claim_type == "sales":
        metric = ("ACV" if _ACV.search(text) else "Median sales cycle" if _SALES_CYCLE.search(text)
                  else "Win rate" if _WIN_RATE.search(text) else "CAC payback" if _PAYBACK.search(text) else None)
    elif claim_type == "gross_margin":
        metric = "Gross margin"
    return metric if metric and _fits(METRICS[metric]["unit"], claim_unit) else None


def _page_ref(sources: list) -> str:
    refs = []
    for s in sources or ():
        ref = f"slide {s['slide']}" if s.get("slide") is not None else f"p{s['page']}" if s.get("page") is not None else None
        if ref and ref not in refs:
            refs.append(ref)
    return ", ".join(refs)


def _deck_reading(c: dict) -> str:
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
            out.append(claim)
    return out


def _row(c: dict, results: dict, settings: dict) -> dict:
    inputs = (c.get("claim_inputs") or {}).get(c["claim_id"]) or {}
    as_of = results.get("as_of_month")
    as_of_i = _mi(as_of) if as_of else None
    currency = (c.get("currency") or None)
    claim_unit = _claim_unit(c)
    text = f"{c.get('snippet') or ''} {c.get('label_from') or ''}"
    revenue_segments, data_segments = _segments(results)

    # metric and segment: Python proposes, the analyst may set either
    if inputs.get("metric") is not None:
        metric, metric_by = (None if inputs["metric"] == NO_METRIC else inputs["metric"]), "analyst"
    else:
        metric, metric_by = propose_metric(c.get("claim_type"), claim_unit, text), "python"
    if inputs.get("segment"):
        segment, segment_by = inputs["segment"], "analyst"
    else:
        named = [s for s in revenue_segments if re.search(rf"(?i)(?<!\w){re.escape(s)}(?!\w)", text)]
        segment, segment_by = (named[0] if len(named) == 1 else WHOLE), "python"
    spec = METRICS.get(metric) if metric else None

    start, end = _month_of(c.get("period_start")), _month_of(c.get("period_end"))
    period = c.get("period_text") or c.get("target_date") or None
    low, high = c.get("value"), c.get("value_high")
    out = dict.fromkeys(FIELDS)
    out.update(
        claim_id=c["claim_id"], deck_file=c.get("file"), page_ref=_page_ref(c.get("sources")),
        claim_type=c.get("claim_type"), status=c.get("status"), deck_reading=_deck_reading(c), claimed_value=low,
        claimed_high=high, unit=c.get("unit"), currency=currency, period=period,
        period_start=str(c["period_start"]) if c.get("period_start") else None,
        period_end=str(c["period_end"]) if c.get("period_end") else None,
        period_note=None if c.get("target_date") else NO_PERIOD, segment=segment, segment_set_by=segment_by,
        metric=metric, metric_set_by=metric_by, direction=spec["direction"] if spec else None,
        tolerance=tolerance_text(metric) if spec else None, as_of_month=as_of,
        as_of_defaulted=not settings.get("as_of_month"), gate_date=inputs.get("gate_date"),
        gate_threshold=inputs.get("gate_threshold"), gate_budget_decision=inputs.get("gate_budget_decision"),
        gate_saved=inputs.get("gate_threshold") is not None and bool(inputs.get("gate_budget_decision")))

    def finish(label: str, reason: str) -> dict:
        out.update(evidence_label=label, reason=reason)
        return out

    if not spec:
        return finish("Unsupported", "no metric")
    if not _fits(spec["unit"], claim_unit):
        return finish("Unsupported", "metric does not fit the claim's unit")
    if segment == NOT_IN_DATA or (segment != WHOLE and segment not in data_segments):
        return finish("Unsupported", "segment not in the data")
    if segment != WHOLE and not spec["seg"]:
        return finish("Unsupported", "not computed by segment")
    if c.get("target_date") and (start is None or end is None):
        return finish("Unsupported", "period not readable")

    figures = _Figures(results, metric, segment)
    observed, observed_at, source, why = _observe(figures, spec, metric, start, end, as_of_i)
    if isinstance(observed, str):                       # a verdict instead of a figure
        return finish(*observed.split("|", 1))
    forecast = end is not None and as_of_i is not None and end > as_of_i
    if observed is None:
        if observed_at == "missing":
            unlock = _missing(results, metric)
            return finish(*(("Unverified", f"Missing: {unlock}") if unlock else ("Unsupported", "not computed")))
        if forecast:
            return finish("Unverified", f"forecast: the period ends after the as-of month ({as_of})")
        return finish("Unsupported", why or "not computed")

    # currency claims are converted at the audit's FX rate
    rate = 1.0
    if claim_unit == "currency" and currency != settings.get("reporting_currency"):
        rate = (settings.get("fx") or {}).get(currency)
        if rate is None:
            return finish("Unverified", f"no FX rate for {currency}")
    claimed_low = _to_metric_unit(low, claim_unit, spec["unit"])
    claimed_high = _to_metric_unit(high, claim_unit, spec["unit"])
    if spec["unit"] == "currency":
        claimed_low = claimed_low * rate if claimed_low is not None else None
        claimed_high = claimed_high * rate if claimed_high is not None else None

    out.update(observed_value=observed, observed_at=observed_at, observed_source=source)
    if claimed_low is None:
        return finish("Unsupported", "no claimed value")
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
    out["gloss"] = gloss(spec["unit"], kind, gap, results.get("reporting_currency"), spec["direction"],
                         _label_of(end) if forecast else None)

    # the gate: no proposal and no default threshold; the sentence exists once the analyst has filled the threshold and
    # the budget decision (claimed and observed sit beside the empty field on the screen)
    gate_on = inputs.get("gate_date") or gate_date(as_of, settings.get("fiscal_year_end") or 12)
    out["gate_date"] = gate_on
    if out["gate_saved"]:
        shown = metric if segment == WHOLE else f"{metric} ({segment})"
        unit_currency = results.get("reporting_currency")
        out["gate_sentence"] = (
            f"Before {inputs['gate_budget_decision']}, {shown} must be at {'least' if sign > 0 else 'most'} "
            f"{_format(spec['unit'], inputs['gate_threshold'], unit_currency)} by {gate_on}. "
            f"Observed {_format(spec['unit'], observed, unit_currency)} ({observed_at}); "
            f"claimed {_format(spec['unit'], claimed, unit_currency)} ({period or NO_PERIOD}).")

    if forecast:
        return finish("Unverified", f"forecast: the period ends after the as-of month ({as_of})")
    verified = within_tolerance(metric, gap, claimed)
    if out["deck_reading"] == SUGGESTION:       # tested, but not Verified until the analyst edits the claim (decision D3)
        return finish("Unverified", "deck reading: AI suggestion, not verified until the analyst edits the claim")
    if verified:
        return finish("Verified", f"within {out['tolerance']} of the claim")
    return finish("Contradicted", f"outside {out['tolerance']}: a {'miss' if kind == 'miss' else 'beat'}")


def _observe(figures: "_Figures", spec: dict, metric: str, start: Optional[int], end: Optional[int], as_of_i: Optional[int]):
    """(observed, observed_at, source, reason) read as table 2b says. `observed` is a number, None, or a
    "Label|reason" verdict string when the claim cannot be tested; None with observed_at "missing" when the engine
    holds no figure for the metric at all."""
    results, kind = figures.results, spec["kind"]
    if as_of_i is None:
        return None, "missing", None, None
    forecast = end is not None and end > as_of_i

    if kind == "asof":
        got = figures.asof()
        if got is None:
            return None, "missing", None, None
        value, source, why = got
        if end is not None and not forecast and end != as_of_i:
            return "Unsupported|the figure is computed at the as-of month, not for this period", None, None, None
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
        target = as_of_i if end is None or forecast else end
        if first is not None and target < _mi(first):
            return f"Unverified|before {_short(metric)}'s first month, {first}", None, None, None
        value = values.get(_ms(target))
        return value, _ms(target), source, why or "not computed for that month"

    if kind == "sum":
        got = figures.monthly()
        if got is None:
            return None, "missing", None, None
        values, source, why = got
        if why == "segment not in the data":
            return "Unsupported|segment not in the data", None, None, None
        if start is None or end is None:
            return "Unverified|no period stated", None, None, None
        months = sorted(values, key=_mi)
        first = _mi(months[0]) if months else None
        if first is not None and end < first:
            return f"Unverified|before {_short(metric)}'s first month, {months[0]}", None, None, None
        if forecast:
            used = [m for m in range(max(start, first or start), as_of_i + 1) if _ms(m) in values]
            if not used:
                return None, _ms(as_of_i), source, None
        else:
            used = list(range(start, end + 1))
            absent = [m for m in used if values.get(_ms(m)) is None]
            if absent:
                return f"Unverified|months missing from the data: {_month_ranges(absent)}", None, None, None
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
            return f"Unverified|before {_short(metric)}'s first month, {_quarter_first_month(first)}", None, None, None
        if q not in quarters:
            return "Unsupported|not computed for that period", None, None, None
    item = quarters[q]
    return item["value"], q, source, item["reason"] or "not computed"


# --- the register -----------------------------------------------------------------------------------------------------

def _rank(rows: List[dict]) -> List[dict]:
    """Rows with a gap other than "to go" by normalised gap, largest first (a beat counts as 0); then the rest in register order."""
    def key(r):
        norm = r["gap_normalised"]
        if r["gap_kind"] == "beat" or norm is None and r["gap"] == 0:
            return 0.0
        return float("inf") if norm is None else max(norm, 0.0)
    ranked = [r for r in rows if r["gap"] is not None and r["gap_kind"] != "to go"]
    rest = [r for r in rows if r not in ranked]
    ordered = sorted(ranked, key=key, reverse=True) + rest
    for rank, row in enumerate(ordered, 1):
        row["rank"] = rank
    return ordered


def build_register(candidates: List[dict], results: Optional[dict], settings: dict) -> List[dict]:
    """The claim register: one row per claim, in rank order. `candidates` are the approved and edited rows in register
    order; `settings` carries fiscal_year_end, as_of_month (as set on the audit, None when defaulted),
    reporting_currency and fx. Nothing is read from a model and nothing is changed."""
    if not results:
        return []
    return _rank([_row(c, results, settings) for c in _expand(candidates)])


def label_counts(rows: List[dict]) -> Dict[str, int]:
    """Rows per evidence label: the only thing a log line may say about the register."""
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["evidence_label"]] = counts.get(r["evidence_label"], 0) + 1
    return counts
