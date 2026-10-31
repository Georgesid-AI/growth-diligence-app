"""P&L lines: what each mapped line feeds (docs/design/pnl-lines.md). Pure Python: no database, no model, no network.

Every mapped line of a statement has a use: a value series, a sum check, a recompute check or an exclusion. The use comes from the
line's mapped role (role, meaning, parent, basis), never from its label. The checks use the app's tolerances: `sheet.TOLERANCE` for a
total against its parts and `claim_matching.RATE_TOLERANCE_PP` for a rate. Plan cells of the yearly columns after the as-of month are
read here as plan claims (implied against observed rate); the register (claim_matching) turns them into rows.
"""
import re
from typing import Dict, List, Optional

from openpyxl.utils import get_column_letter

from . import sheet as sh
from .. import formatting as fmt

SERIES, SUM_CHECK, RECOMPUTE_CHECK, EXCLUDED = "series", "sum check", "recompute check", "excluded"
USES = (SERIES, SUM_CHECK, RECOMPUTE_CHECK, EXCLUDED)
PERIODS_PER_YEAR = {"year": 1, "half": 2, "quarter": 4, "month": 12}
GRAIN_WORDS = {"year": "yearly", "half": "half-yearly", "quarter": "quarterly", "month": "monthly"}
ANNUALISED = "annualised"
# The recompute of a % row: the money rows it is computed from (pick() by meaning), by the meaning of the % row.
MARGIN_MEANINGS = ("gross_margin", "ebitda", "opex")
_GROWTH_WORDS = re.compile(r"\b(?:growth|yoy|mom|qoq|change|changes|delta|chg)\b")      # a row with one of these is a rate of change
PLAN_MONEY = ("revenue", "cost_of_revenue", "sm_expense", "opex")       # a plan cell tested as growth
PLAN_MARGIN = ("gross_margin", "ebitda")                                 # a plan cell tested as a share of revenue
SUM_RULE = "Sum check: a total against the sum of its sub-lines, within 0.5%"
RECOMPUTE_RULE = "Recompute check: a % row within 1 point of the money rows, a money line within 0.5%"
PLAN_NAMES = {"revenue": "Revenue", "cost_of_revenue": "Cost of revenue", "sm_expense": "S&M expense", "opex": "Operating expenses",
              "gross_margin": "Gross margin", "ebitda": "EBITDA"}


def rate_tolerance_points() -> float:
    from .. import claim_matching
    return claim_matching.RATE_TOLERANCE_PP


def _present(line: Dict) -> bool:
    return any(v is not None for v in line["values"])


def _money_line(line: Dict) -> bool:
    return line["role"] not in ("rate",) + sh.NOT_LINES and _present(line)


# ---------------------------------------------------------------------------
# Periods (section 2)
# ---------------------------------------------------------------------------
def is_growth_row(line: Dict) -> bool:
    """A % row read as a growth or change rate: its meaning is growth_rate or its label holds growth, YoY, MoM, change or delta. "OPEX %"
    and "Gross margin %" are shares and are not."""
    return line["role"] == "rate" and (line["meaning"] == "growth_rate" or bool(_GROWTH_WORDS.search(sh._norm(line["label"]))))


def growth_base(line: Dict, lines: List[Dict]) -> Optional[tuple]:
    """(base lines, meaning) a growth row is the growth of: the row's own meaning when it names a line ("OPEX growth %" → opex), else the
    words left of its label once the growth words and the % are taken out ("Customer growth %" → customers, "Revenue growth rate" →
    revenue). None when it names no line of the file: the row is then not recomputed, and never against revenue by default."""
    meanings = [line["meaning"]] if line["meaning"] not in ("growth_rate", "other") else []
    stem = re.sub(r"\s+", " ", _GROWTH_WORDS.sub(" ", re.sub(r"[%()]|\brate\b|\bpct\b", " ", sh._norm(line["label"])))).strip()
    if stem:
        meanings += [m for m in (sh.meaning_of(stem)[0], sh.meaning_of(stem + "s")[0]) if m not in ("other", "growth_rate")]
    for meaning in meanings:
        chosen = [x for x in sh.pick(lines, meaning) if x is not line]
        if chosen:
            return chosen, meaning
    return None


def rate_period(line: Dict, periods: List[Dict]) -> Optional[str]:
    """The period a rate row speaks for: a growth rate inherits the grain of the columns it has figures in ("yearly" for a yearly file,
    never "monthly"); a margin % row is a ratio and has none (None), as has a line that is no rate."""
    if not is_growth_row(line):
        return None
    grains = {p["grain"] for k, p in enumerate(periods) if line["values"][k] is not None}
    return GRAIN_WORDS.get(next(iter(grains))) if len(grains) == 1 else None


def annualise(rate: float, grain: str) -> Optional[Dict]:
    """A growth rate of one period converted to a year, with the formula shown: {"value", "formula", "label"} labelled "annualised".
    The only place a rate changes period. None for a yearly rate (nothing to convert) or a grain that is no period."""
    n = PERIODS_PER_YEAR.get(grain)
    if not n or n == 1:
        return None
    value = (1 + rate) ** n - 1
    return {"value": value, "formula": f"(1 + {fmt.fmt_pct(rate)})^{n} − 1 = {fmt.fmt_pct(value)}", "label": ANNUALISED}


def _previous(periods: List[Dict], k: int) -> Optional[int]:
    """The index of the column right before column k, of the same grain, with no month between (a yearly column to the yearly column
    of the year before), else None."""
    p = periods[k]
    if not p.get("start") or not p.get("end"):
        return None
    for j, q in enumerate(periods):
        if j != k and q["grain"] == p["grain"] and q.get("end") and sh._ym(sh._add_months(int(q["end"][:4]), int(q["end"][5:]), 1)) == p["start"]:
            return j
    return None


# ---------------------------------------------------------------------------
# Uses (sections 1 and 5)
# ---------------------------------------------------------------------------
def _results(lines: List[Dict]) -> Dict[int, Dict]:
    """The bridge lines of a statement: the result lines below EBITDA (EBT, net income), found by the numbers and the structure. A line
    with no parent, mapped to no meaning, below the EBITDA line, that equals the previous anchor plus the unmapped money lines between
    them in at least half of its periods. {row: {"anchor": row, "between": [rows]}}. Never read from a label."""
    ebitda = [x for x in sh.pick(lines, "ebitda")]
    if not ebitda:
        return {}
    anchor, between, found = ebitda[-1], [], {}
    for line in lines:
        if line["row"] <= anchor["row"] or line.get("parent_row") or line["meaning"] != "other" or not _money_line(line):
            continue
        hits, tested = 0, 0
        for k in range(len(line["values"])):
            v, a = line["values"][k], anchor["values"][k]
            parts = [x["values"][k] for x in between]
            if v is None or a is None or any(p is None for p in parts):
                continue
            tested += 1
            hits += abs(a + sum(parts) - v) <= sh.TOLERANCE * abs(v) + 1e-9
        if tested and hits * 2 >= tested:
            found[line["row"]] = {"anchor": anchor["row"], "between": [x["row"] for x in between]}
            anchor, between = line, []
        else:
            between.append(line)
    return found


def uses(lines: List[Dict], periods: List[Dict]) -> Dict[int, str]:
    """{row: use} for every line that holds a figure or is a rate (a heading or a note has none). By role only:
    - a % row, a money gross margin, a result line below EBITDA and a ytd or ltm line beside the monthly one: recompute check;
    - a line the engine reads as a value (revenue, cost of revenue, S&M) or a line with no parts: series, and a total of parts that
      the engine does not read: sum check (a series total is also checked against its parts);
    - a line outside operations (mapped to no meaning, no parent), or measured another way than by the period: excluded."""
    results = _results(lines)
    read = {x["row"] for f in sh.YEARLY_FIELDS + sh.PNL_FIELDS for x in sh.pick(lines, f)}
    out: Dict[int, str] = {}
    for line in lines:
        if line["role"] in sh.NOT_LINES or not (_present(line) or line["role"] == "rate"):
            continue
        parts = sh.sublines(line, lines) if line["role"] == "total" else []
        if line["role"] == "rate":
            out[line["row"]] = RECOMPUTE_CHECK
        elif sh.line_tag(line) != "actual":
            out[line["row"]] = SERIES                              # a plan row: a series of plan figures
        elif line.get("basis") in ("ytd", "ltm"):
            out[line["row"]] = RECOMPUTE_CHECK                     # checked against the monthly line (sheet.basis_checks)
        elif sh.basis_unused(line):
            out[line["row"]] = EXCLUDED
        elif line["meaning"] == "gross_margin" or line["row"] in results:
            out[line["row"]] = RECOMPUTE_CHECK
        elif line["meaning"] == "other" and not line.get("parent_row"):
            out[line["row"]] = EXCLUDED
        elif parts and line["row"] not in read:
            out[line["row"]] = SUM_CHECK
        else:
            out[line["row"]] = SERIES
    return out


# ---------------------------------------------------------------------------
# Checks (section 3)
# ---------------------------------------------------------------------------
def _sum_of(chosen: List[Dict], k: int, meaning: str, lines: List[Dict]) -> Optional[float]:
    return sh._field_values(chosen, k, 1, meaning, lines)


def recompute_checks(lines: List[Dict], periods: List[Dict]) -> List[Dict]:
    """The % rows and the money gross margin and result lines recomputed from the money rows, as written: [{"row", "code", "period",
    "expected", "actual", "gap", "unit"}] for each period where the gap is beyond the tolerance. A rate gap is in points (tolerance
    ±1 point), a money gap in the file's own units (tolerance 0.5% of the figure). A period whose inputs are blank is not checked."""
    tolerance = rate_tolerance_points()
    revenue = sh.pick(lines, "revenue")
    out: List[Dict] = []

    def rev(k):
        return _sum_of(revenue, k, "revenue", lines) if revenue else None

    def rate(line, code, k, expected, absolute=False):
        actual = line["values"][k]
        if expected is None or actual is None:
            return
        if absolute:                                    # a cost % row is read by size: OPEX and OPEX % both negative raise nothing
            actual, expected = abs(actual), abs(expected)
        gap = (actual - expected) * 100
        if round(abs(gap), 9) > tolerance:
            out.append({"row": line["row"], "code": code, "period": periods[k]["header"], "expected": expected, "actual": actual,
                        "gap": gap, "unit": "points"})

    for line in lines:
        if line["role"] != "rate" or not _present(line):
            continue
        for k in range(len(periods)):
            if is_growth_row(line):
                base = growth_base(line, lines)         # the growth of its own base line, at the columns' period (section 2)
                j = _previous(periods, k)
                if base is None or j is None:
                    continue
                a, b = _sum_of(base[0], k, base[1], lines), _sum_of(base[0], j, base[1], lines)
                rate(line, "growth_mismatch", k, a / b - 1 if a is not None and b is not None and b > 0 else None)
            elif line["meaning"] in MARGIN_MEANINGS:
                r = rev(k)
                if not r:
                    continue
                if line["meaning"] == "gross_margin":
                    cost = sh.pick(lines, "cost_of_revenue")
                    c = _sum_of(cost, k, "cost_of_revenue", lines) if cost else None
                    value = None if c is None else (r - c) / r
                else:
                    chosen = sh.pick(lines, line["meaning"])
                    v = _sum_of(chosen, k, line["meaning"], lines) if chosen else None
                    value = None if v is None else v / r
                rate(line, "margin_mismatch", k, value, absolute=line["meaning"] == "opex")

    def money(line, code, k, expected):
        actual = line["values"][k]
        if expected is None or actual is None or abs(actual - expected) <= sh.TOLERANCE * abs(actual) + 1e-9:
            return
        out.append({"row": line["row"], "code": code, "period": periods[k]["header"], "expected": expected, "actual": actual,
                    "gap": actual - expected, "unit": "currency"})

    for line in sh.pick(lines, "gross_margin"):
        cost = sh.pick(lines, "cost_of_revenue")
        for k in range(len(periods)):
            r, c = rev(k), _sum_of(cost, k, "cost_of_revenue", lines) if cost else None
            money(line, "gross_margin_mismatch", k, None if r is None or c is None else r - c)
    by_row = {x["row"]: x for x in lines}
    for row, bridge in _results(lines).items():
        line, anchor = by_row[row], by_row[bridge["anchor"]]
        for k in range(len(periods)):
            parts = [by_row[r]["values"][k] for r in bridge["between"]]
            if anchor["values"][k] is None or any(p is None for p in parts):
                continue
            money(line, "result_mismatch", k, anchor["values"][k] + sum(parts))
    return out


def sum_gaps(lines: List[Dict], periods: List[Dict]) -> List[Dict]:
    """[{"row", "code" ("total_mismatch" or "sign_differs"), "period", "total", "parts", "gap"}]: each total against the sum of its
    sub-lines, as written, in the file's units; the gap is the total less the sum."""
    out = []
    for total in lines:
        codes = total.get("checks") or {}
        for code in ("total_mismatch", "sign_differs"):
            for header in codes.get(code, []):
                k = next(i for i, p in enumerate(periods) if p["header"] == header)
                parts = sum(x["values"][k] for x in sh.sublines(total, lines) if x["values"][k] is not None)
                out.append({"row": total["row"], "code": code, "period": header, "total": total["values"][k], "parts": parts,
                            "gap": total["values"][k] - parts})
    return out


# ---------------------------------------------------------------------------
# The statement block the engine stores (section 3, 4)
# ---------------------------------------------------------------------------
def _amount(value: float) -> str:
    return fmt.fmt_number(abs(value))


def _cells(periods: List[Dict], line: Dict, headers: List[str]) -> List[str]:
    return [f"{get_column_letter(p['col'])}{line['row']}" for p in periods if p["header"] in headers]


def findings(lines: List[Dict], periods: List[Dict], scale: float) -> List[Dict]:
    """The integrity findings of a statement, one per line and period: a total that differs from its sub-lines, one whose sign
    differs from them, a % row, gross margin or result line that does not recompute. Each carries the cell it cites."""
    by_row = {x["row"]: x for x in lines}
    out = []

    for g in sum_gaps(lines, periods):
        line = by_row[g["row"]]
        sign = g["code"] == "sign_differs"
        if sign:
            text = (f"{line['label']}: sign differs from its lines in {g['period']} "
                    f"(total {fmt.fmt_number(g['total'] * scale)}, lines {fmt.fmt_number(g['parts'] * scale)})")
        else:
            text = f"{line['label']} differs from the sum of its lines by {_amount(g['gap'] * scale)} in {g['period']}"
        out.append({"kind": "sign" if sign else "sum", "line": line["label"], "row": line["row"], "period": g["period"],
                    "gap": None if sign else g["gap"] * scale, "unit": "currency", "text": text,
                    "cell": _cells(periods, line, [g["period"]])[0], "rule": SUM_RULE})
    for g in recompute_checks(lines, periods):
        line = by_row[g["row"]]
        if g["unit"] == "points":
            text = (f"{line['label']} differs from the money rows by {fmt.fmt_number(abs(g['gap']))} points in {g['period']} "
                    f"(file {fmt.fmt_pct(g['actual'])}, recomputed {fmt.fmt_pct(g['expected'])})")
            gap = g["gap"]
        else:
            text = (f"{line['label']} differs from its recomputed value by {_amount((g['actual'] - g['expected']) * scale)} in "
                    f"{g['period']}")
            gap = g["gap"] * scale
        out.append({"kind": "recompute", "line": line["label"], "row": line["row"], "period": g["period"], "gap": gap,
                    "unit": g["unit"], "text": text,
                    "cell": _cells(periods, line, [g["period"]])[0], "rule": RECOMPUTE_RULE})
    return sorted(out, key=lambda f: (f["row"], f["period"]))


def plan_claims(yearly: Optional[Dict], meta: Dict) -> List[Dict]:
    """The plan cells of the yearly columns after the as-of month, one per line read as a series and period: its value, the cell, and
    the implied rate against the observed one. A money line is tested as growth (plan ÷ the year before − 1, the year before being the
    last actual or the plan before it, against the growth of the last two actual years); gross margin and EBITDA as a share of that
    year's revenue (against the last actual year's). A plan claim is never Verified or Contradicted; the gap is in points."""
    if not yearly or not yearly.get("planned"):
        return []
    actual = sorted(yearly.get("actual") or [], key=lambda y: y.get("year") or 0)
    sheet = meta.get("sheet") or ""
    known = {y["year"]: y for y in actual if y.get("year") is not None}
    for item in sorted(yearly["planned"], key=lambda y: y.get("year") or 0):
        known.setdefault(item["year"], item)
    last, before = (actual[-1] if actual else None), (actual[-2] if len(actual) > 1 else None)

    def value(item, field):
        return ((item or {}).get("fields") or {}).get(field, {}).get("value")

    def growth(a, b):
        return a / b - 1 if a is not None and b else None

    def share(item, field):
        r = value(item, "revenue")
        v = value(item, field)
        return v / r if v is not None and r else None
    out = []
    for item in sorted(yearly["planned"], key=lambda y: y.get("year") or 0):
        if not item.get("start") or not item.get("end"):
            continue
        for field, fv in item["fields"].items():
            if field not in PLAN_MONEY + PLAN_MARGIN:
                continue
            base = known.get(item["year"] - 1)
            if field in PLAN_MARGIN:
                implied, observed = share(item, field), share(last, field)
                measure, tail = "share of revenue", f"{item['period']} against {(last or {}).get('period')}"
            else:
                implied = growth(fv["value"], value(base, field))
                observed = growth(value(last, field), value(before, field))
                measure = "growth"
                tail = f"{(base or {}).get('period')} → {item['period']} against {(before or {}).get('period')} → {(last or {}).get('period')}"
            cell = fv["cells"][0] if len(fv["cells"]) == 1 else "+".join(fv["cells"])
            reason = None
            if implied is None:
                reason = "no figure for the year before" if measure == "growth" else "no revenue for the year"
            elif observed is None:
                reason = "fewer than two actual years" if measure == "growth" else "no actual year to compare with"
            out.append({
                "field": field, "metric": PLAN_NAMES[field], "period": item["period"], "period_start": item["start"],
                "period_end": item["end"], "value": fv["value"], "cell": cell,
                "source_text": f"File {sheet}!{cell} (plan)", "sheet": sheet, "measure": measure, "implied": implied,
                "observed": observed, "gap_points": (implied - observed) * 100 if implied is not None and observed is not None else None,
                "compared": tail, "reason": reason, "tag": item.get("tag") or "plan", "row": int(re.sub(r"^[A-Z]+", "", fv["cells"][0].split("+")[0]))})
    return out


def analyse(sheet_map: Dict, fiscal_year_end: int, scale: float, meta: Dict, as_of: Optional[str] = None) -> Dict:
    """The statement block the engine stores: {"basis", "findings", "plan"}. `plan` is read from the yearly columns only: a
    monthly statement's months after the as-of month are cut before the engine, and its forecast rows stay claims of the forecast file."""
    periods = sh.with_periods(sheet_map["periods"], fiscal_year_end)
    lines = [dict(x) for x in sheet_map["lines"]]
    sh.check(lines, periods)
    yearly = sh.yearly_input(lines, periods, scale, meta, as_of)
    return {"basis": "monthly" if any(p["grain"] == "month" for p in periods) else "yearly",
            "findings": findings(lines, periods, scale), "plan": plan_claims(yearly, meta)}
