"""Forecast diagnostics (docs/specs/forecast-and-payback.md section 3; docs/design/claim-review-simplified-design.md section 3).

Pure Python: no database, no model, no network, no import from the register. For a forecast claim of a metric the engine holds by month, the
required annual growth, the historical comparator, the gap in percentage points, the pace indicator, the remaining amount and the calculation
behind them, all as figures and closed words (no deck text). The calculation describes an assumption: it never labels a claim, so nothing here
says verified, contradicted, beat, pass or fail.
"""
from typing import Callable, Dict, List, Optional, Tuple

FLOWS = ("Revenue",)                                    # summed over a period; the others are balances read at a month
BALANCES = ("ARR", "MRR", "Customer count")
FORMULA = "required annual growth = (forecast ÷ base) ^ (12 ÷ elapsed months) − 1"
LIMITED_UNDER = 12                                      # elapsed months below which a history is limited
PERIOD_LENGTHS = {12: "year", 3: "quarter", 1: "month"}

# The reasons a calculation is unavailable (spec section 3.8); the data-boundary test lists them.
R_PERIOD = "period is not a year, a quarter or a month"
R_NO_YEAR = "no complete 12 months of actual revenue"
R_NO_WINDOW = "no actual revenue for the same {unit} of an earlier year (missing comparator: {window})"
R_NO_OBSERVATION = "no actual observation of {metric}"
R_BASE = "base not positive"
R_FORECAST = "forecast not positive"
R_ELAPSED = "elapsed months not positive"
R_COMPARATOR_BASE = "comparator base not positive"
R_NO_YEAR_BEFORE = "insufficient history: no complete 12 months before {window}"
R_NO_UNIT_BEFORE = "insufficient history: no complete {unit} a year before {window}"
R_COMPARATOR_HOLES = "insufficient history: months missing in the comparator window {window}: {months}"
R_NO_OBSERVATION_BEFORE = "insufficient history: no observation of {metric} at {month}"
REASONS = (R_PERIOD, R_NO_YEAR, R_NO_WINDOW, R_NO_OBSERVATION, R_BASE, R_FORECAST, R_ELAPSED, R_COMPARATOR_BASE, R_NO_YEAR_BEFORE,
           R_NO_UNIT_BEFORE, R_COMPARATOR_HOLES, R_NO_OBSERVATION_BEFORE)


def mi(text) -> int:
    """The month index of "YYYY-MM" (or a longer date)."""
    year, month = (int(p) for p in str(text)[:7].split("-"))
    return year * 12 + month - 1


def ms(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _range_name(start: int, end: int) -> str:
    return ms(start) if start == end else f"{ms(start)} to {ms(end)}"


def window_name(start: int, end: int, fye: int) -> str:
    """"FY2024" for a twelve-month window that ends in the fiscal year-end month (named by the year it ends in), else its months."""
    if end - start == 11 and end % 12 + 1 == fye:
        return f"FY{end // 12}"
    return _range_name(start, end)


def _pct(fraction: float) -> str:
    return f"{round(fraction * 100, 1) + 0.0:.1f}%"


def _points(value: float) -> str:
    return f"{round(value, 1) + 0.0:+.1f}"


def _complete(series: Dict[int, float], start: int, end: int, last: Optional[int]) -> bool:
    return last is not None and end <= last and all(series.get(i) is not None for i in range(start, end + 1))


def _holes(series: Dict[int, float], start: int, end: int) -> List[int]:
    return [i for i in range(start, end + 1) if series.get(i) is None]


def _total(series: Dict[int, float], start: int, end: int) -> float:
    return sum(series[i] for i in range(start, end + 1))


def _growth(now: float, then: float, months: int = 12) -> Optional[float]:
    if now <= 0 or then <= 0 or months <= 0:
        return None
    return (now / then) ** (12 / months) - 1


def _comparator(series, metric, flow, start, end, last, fye, unit) -> Tuple[Optional[dict], Optional[str]]:
    """Growth between comparable annual windows: the base window over the window twelve months before it. (comparator, reason it has none)."""
    name = window_name(start, end, fye)
    if flow:
        p0, p1 = start - 12, end - 12
        if _complete(series, p0, p1, last):
            then, now = _total(series, p0, p1), _total(series, start, end)
            if then <= 0 or now <= 0:
                return None, R_COMPARATOR_BASE
            return {"kind": "annual", "value": now / then - 1, "windows": [window_name(p0, p1, fye), name], "then": then, "now": now}, None
        missing = _holes(series, p0, p1)
        if len(missing) == p1 - p0 + 1:
            return None, (R_NO_YEAR_BEFORE if end - start == 11 else R_NO_UNIT_BEFORE).format(window=name, unit=unit)
        return None, R_COMPARATOR_HOLES.format(window=window_name(p0, p1, fye), months=", ".join(ms(i) for i in missing))
    then, now = series.get(end - 12), series.get(end)
    if then is None:
        return None, R_NO_OBSERVATION_BEFORE.format(metric=metric, month=ms(end - 12))
    if then <= 0 or now is None or now <= 0:
        return None, R_COMPARATOR_BASE
    return {"kind": "annual", "value": now / then - 1, "windows": [ms(end - 12), ms(end)], "then": then, "now": now}, None


def _pace(series: Dict[int, float], last: Optional[int]) -> Optional[dict]:
    """The monthly endpoint growth of the series, annualised: first to last month in the data, with the elapsed months and the number of
    observations apart. Not annual growth, so no difference in points is taken against it."""
    months = sorted(i for i, v in series.items() if v is not None and (last is None or i <= last))
    if len(months) < 2:
        return None
    first, final = months[0], months[-1]
    elapsed = final - first
    value = _growth(series[final], series[first], elapsed)
    if value is None:
        return None
    return {"value": value, "start": ms(first), "end": ms(final), "elapsed": elapsed, "observations": len(months),
            "limited": elapsed < LIMITED_UNDER}


def _base(series, flow, start, end, last, fye) -> Tuple[Optional[dict], Optional[str]]:
    """The comparable base of section 3.2: ({value, window, start, end, elapsed}, reason it has none)."""
    if flow:
        length = end - start + 1
        if length == 12:
            k = 1
            while end - 12 * k - 11 >= min(series, default=end):
                b0, b1 = end - 12 * k - 11, end - 12 * k
                if _complete(series, b0, b1, last):
                    return {"value": _total(series, b0, b1), "window": window_name(b0, b1, fye), "start": ms(b0), "end": ms(b1),
                            "elapsed": 12 * k, "bounds": (b0, b1)}, None
                k += 1
            if last is not None and _complete(series, last - 11, last, last):
                b0, b1 = last - 11, last
                return {"value": _total(series, b0, b1), "window": window_name(b0, b1, fye), "start": ms(b0), "end": ms(b1),
                        "elapsed": end - last, "bounds": (b0, b1)}, None
            return None, R_NO_YEAR
        unit = PERIOD_LENGTHS[length]
        k = 1
        while start - 12 * k >= min(series, default=start):
            b0, b1 = start - 12 * k, end - 12 * k
            if _complete(series, b0, b1, last):
                return {"value": _total(series, b0, b1), "window": _range_name(b0, b1), "start": ms(b0), "end": ms(b1),
                        "elapsed": 12 * k, "bounds": (b0, b1)}, None
            k += 1
        return None, R_NO_WINDOW.format(unit=unit, window=_range_name(start - 12, end - 12))
    seen = [i for i in series if series[i] is not None and last is not None and i <= last]
    return ({"value": series[max(seen)], "window": ms(max(seen)), "start": ms(max(seen)), "end": ms(max(seen)),
             "elapsed": end - max(seen), "bounds": (max(seen), max(seen))}, None) if seen else (None, None)


def diagnose(*, metric: str, series: Dict[int, float], last: Optional[int], start: int, end: int, low: float, high: Optional[float] = None,
             fye: int = 12, money: Callable[[float], str] = lambda v: f"{v:,.0f}") -> dict:
    """The forecast diagnostics of one claim.

    `series` is {month index: value} of the months the data can be read at (complete, in the data), `last` the last month a figure can be
    read at; `start` and `end` the claim's period; `low` and `high` the claimed figure or range, in the metric's unit; `fye` the audit's
    fiscal year-end month; `money` formats an amount. Returns {"lines", "details", "reason", "required", "base", "historical",
    "historical_reason", "pace", "difference", "remaining"} (see the spec): `reason` is why no required growth is calculated.
    """
    flow = metric in FLOWS
    lo, hi = (low, None) if high is None else tuple(sorted((low, high)))
    pname = window_name(start, end, fye) if flow else _range_name(start, end)
    shown = money(lo) if hi is None else f"{money(lo)}–{money(hi)}"
    out = {"lines": [], "details": [], "reason": None, "text": "", "required": None, "base": None, "historical": None, "historical_reason": None,
           "pace": None, "difference": None, "remaining": None}
    unit = PERIOD_LENGTHS.get(end - start + 1)
    base, why = None, None
    if flow and unit is None:
        why = R_PERIOD
    else:
        base, why = _base(series, flow, start, end, last, fye)
        if base is None and why is None:
            why = R_NO_OBSERVATION.format(metric=metric)
    if base is not None:
        if base["value"] <= 0:
            why = R_BASE
        elif lo <= 0 or (hi is not None and hi <= 0):
            why = R_FORECAST
        elif base["elapsed"] <= 0:
            why = R_ELAPSED
    out["reason"] = why
    if base is not None:
        out["base"] = {k: v for k, v in base.items() if k != "bounds"}
    if why is None:
        elapsed = base["elapsed"]
        out["required"] = {"low": round(_growth(lo, base["value"], elapsed), 9), "high": None if hi is None else round(_growth(hi, base["value"], elapsed), 9)}
        rate = _pct(out["required"]["low"]) if hi is None else f"{_pct(out['required']['low'])} to {_pct(out['required']['high'])}"
        out["lines"].append(f"Required growth: {rate} a year ({shown} for {pname} against {money(base['value'])} for {base['window']}, "
                            f"{elapsed} months)")
    else:
        out["lines"].append(f"Required growth: not calculated – {why}")
        out["lines"].append(f"Target: {shown} for {pname}")

    historical, hreason = None, None
    if base is not None:
        b0, b1 = base["bounds"]
        historical, hreason = _comparator(series, metric, flow, b0, b1, last, fye, unit or "")
    out["historical"] = None if historical is None else {k: (round(v, 9) if k == "value" else v) for k, v in historical.items()
                                                         if k in ("kind", "value", "windows")}
    out["historical_reason"] = hreason
    if historical is not None:
        w0, w1 = historical["windows"]
        out["lines"].append(f"Historical growth: {_pct(historical['value'])} ({w0} → {w1})")
        if out["required"] is not None:
            diff = {"low": round((out["required"]["low"] - historical["value"]) * 100, 9),
                    "high": None if hi is None else round((out["required"]["high"] - historical["value"]) * 100, 9)}
            out["difference"] = diff
            gap = _points(diff["low"]) if hi is None else f"{_points(diff['low'])} to {_points(diff['high'])}"
            out["lines"].append(f"Difference: {gap} percentage points (required less historical)")
    else:
        out["lines"].append(f"Historical growth: not available – {hreason or why}")
        pace = _pace(series, last)
        if pace is not None:
            out["pace"] = {**pace, "value": round(pace["value"], 9)}
            limited = ", history limited: under 12 months" if pace["limited"] else ""
            out["lines"].append(f"Pace indicator (monthly endpoint growth, not annual growth): {_pct(pace['value'])} annualised, "
                                f"{pace['start']} to {pace['end']}, {pace['elapsed']} months elapsed, {pace['observations']} observations{limited}")

    out["remaining"], line = _remaining(series, flow, start, end, last, lo, hi, base, money)
    if line:
        out["lines"].append(line)
    out["details"] = _details(out, pname, start, end, shown, base, historical, money)
    out["text"] = _row_text(out)
    return out


def _row_text(found: dict) -> str:
    """The words after "Forecast: " on the register row: the required growth against the historical, or why there is none."""
    if found["required"] is None:
        return found["reason"]
    low, high = found["required"]["low"], found["required"]["high"]
    text = f"required growth {_pct(low) if high is None else f'{_pct(low)} to {_pct(high)}'} a year"
    return text + (f" against {_pct(found['historical']['value'])} historical" if found["historical"] else "")


def unavailable(reason: str, shown: str, start: int, end: int, fye: int = 12) -> dict:
    """The diagnostics of a claim whose amounts are not comparable (a population that differs): the target and the reason, no growth."""
    pname = window_name(start, end, fye) if end - start + 1 in PERIOD_LENGTHS else _range_name(start, end)
    return {"lines": [f"Required growth: not calculated – {reason}", f"Target: {shown} for {pname}"], "details": [FORMULA], "reason": reason,
            "text": reason, "required": None, "base": None, "historical": None, "historical_reason": None, "pace": None, "difference": None,
            "remaining": None}


def _remaining(series, flow, start, end, last, lo, hi, base, money) -> Tuple[Optional[dict], Optional[str]]:
    """The amount still needed to reach the target (section 3.6), a calculation and not a gap."""
    if flow:
        length = end - start + 1
        done = [i for i in range(start, end + 1) if series.get(i) is not None and (last is None or i <= last)]
        if not done or len(done) == length or done != list(range(start, start + len(done))):
            return None, None
        actual = _total(series, start, start + len(done) - 1)
        rest = {"value": max(lo - actual, 0), "actual": actual, "months": len(done)}
        amount = money(rest["value"]) if hi is None else f"{money(rest['value'])} to {money(max(hi - actual, 0))}"
        return rest, (f"Remaining to reach the target: {amount} (calculation: {len(done)} of {length} months actual, "
                      f"{money(actual)} to date)")
    if base is None or base["value"] is None:
        return None, None
    rest = {"value": max(lo - base["value"], 0), "actual": base["value"], "months": 1}
    amount = money(rest["value"]) if hi is None else f"{money(rest['value'])} to {money(max(hi - base['value'], 0))}"
    return rest, f"Remaining to reach the target: {amount} (calculation: target less the latest observation, {base['window']})"


def _details(out, pname, start, end, shown, base, historical, money) -> List[str]:
    """The formula and every input with its window (section 5.1, Details)."""
    lines = [FORMULA]
    period = _range_name(start, end)
    lines.append(f"forecast {shown} for {pname}" + (f" ({period})" if pname != period else ""))
    if base is not None:
        window = _range_name(*base["bounds"])
        lines.append(f"base {money(base['value'])} for {base['window']}" + (f" ({window})" if base["window"] != window else "")
                     + f", elapsed {base['elapsed']} months")
    if historical is not None:
        w0, w1 = historical["windows"]
        lines.append(f"comparator {w0} {money(historical['then'])} → {w1} {money(historical['now'])}")
    return lines

