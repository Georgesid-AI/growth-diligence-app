"""corrections: what the checks can fix on a claim by themselves, and the two claims that are no claim (George, 2026-10-26).

Pure: no I/O, no model, no database. checker.check calls this after its flags are set and records the result on each item:

- `corrections`: one entry per flag that names a correction, {"flag", "field" ("period" or "label"), "original", "options": [...]}. The
  options are the candidates the page offers: one option is applied before the register (pages.corrected_row), more than one go to
  "Needs your attention" with a button each. The page-read checker never changes the item itself.
  * PERIOD_FROM_OTHER_CELL: the period Python rebuilt from a cell outside the figure's block differs from the model's; the one candidate is
    the rebuilt period.
  * BAR_YEAR: the year label under the bar is the one candidate.
  * PERIOD_NOT_ON_PAGE: the model's period stands on no cell; the candidates are the periods the page's heading cells (title cell, top 20%)
    state, one option each.
  * LABEL_MISMATCH (a reason, no flag): the label cell the model cited is not next to the figure and the page offers exactly one cell where a
    label may stand (page_check.label_cells) that holds words and no figure. With several candidates nothing changes, as before: the
    label is left out and the confidence reads "no heading" (a card per such claim would swamp the page, George to decide).
- `drop`: DERIVED_FIGURE (the value is on no cell but can be computed from figures of the same page) or LAUNCH_NO_PRODUCT (a launch date
  whose text names no product). Such a claim never enters the register; the pipeline writes a Diagnostics line.

Every string here is a closed word or a model value; no line carries deck text except `original` / option `value` of a label, which
pages.corrected_row keeps on the row (the row holds the snippet already) and never writes to a log (rule 17: the log gets cell ids).
"""
import itertools
import math
import re
from typing import Dict, List, Optional

from ..decks import claims
from . import page_check, verify

DERIVED_FIGURE = "derived figure, not a claim"
LAUNCH_NO_PRODUCT = "launch date without product name"
COMPARABLE_SHARE = 0.05            # the smallest part of a sum, against the largest
DERIVED_TOLERANCE = 5e-3            # a displayed figure is rounded: "1.2M" + "0.8M" against "2M"
MAX_DERIVED_FIGURES = 30            # triples of more figures than this are not tried
_PAGE_FIELDS = {"period": ("target_date", "period_text", "date_from", "period_start", "period_end", "period_cells", "period_read_note"),
                "label": ("label_from", "type_from")}
FIELDS = tuple(_PAGE_FIELDS)
_WORDS = re.compile(r"[^\W\d_]{3,}")
# The words of a launch line that name no product: the launch itself, a date, a filler.
_LAUNCH_FILLER = frozenset("""launch launches launched launching release released releases go live golive rollout roll out available availability
    expected planned planning new product products platform version app application service solution feature features market general beta
    pilot early mid late end beginning start first second third fourth quarter half year the and our for from with will into
    january february march april may june july august september october november december jan feb mar apr jun jul aug sep sept oct nov dec""".split())


# ---------------------------------------------------------------------------
# Derived figures
# ---------------------------------------------------------------------------
def page_figures(listed: Dict, furniture: frozenset = frozenset()) -> List[float]:
    """The distinct figures of the page in full units (each item's default reading), outside the page's furniture."""
    seen: List[float] = []
    for structure in listed.values():
        for item in structure["items"]:
            if item["cell"] in furniture or not item["values"]:
                continue
            value = item["values"][0]["value"]
            if value is not None and not any(page_check._close(value, v) for v in seen):
                seen.append(float(value))
    return seen


def _near(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=DERIVED_TOLERANCE, abs_tol=1e-9)


def _comparable(*parts: float) -> bool:
    """Whether every part of a sum or difference is at least COMPARABLE_SHARE of the largest: a figure next to a rounding-sized one
    ("150,000" and "800") is no sum, the claim just sits near a figure of the page."""
    big = max(abs(p) for p in parts)
    return big > 0 and all(abs(p) >= COMPARABLE_SHARE * big for p in parts)


def computable(value: Optional[float], figures: List[float]) -> bool:
    """Whether `value` is a sum of two or three, a difference, a product, a ratio, a percentage or a growth percentage of figures of
    the page. A zero value is never derived; the parts of a sum or difference are comparable in size (_comparable)."""
    if value is None or value == 0 or len(figures) < 2:
        return False
    for a, b in itertools.permutations(figures, 2):
        if _comparable(a, b) and (_near(a + b, value) or _near(a - b, value)):
            return True
        if _near(a * b, value) and abs(a) != 1 and abs(b) != 1:
            return True
        if b and (any(_near(a / b * scale, value) for scale in (1, 100)) or _near((a / b - 1) * 100, value)):
            return True
    if len(figures) <= MAX_DERIVED_FIGURES:
        return any(_comparable(*trio) and _near(sum(trio), value) for trio in itertools.combinations(figures, 3))
    return False


# ---------------------------------------------------------------------------
# A launch date with no product name
# ---------------------------------------------------------------------------
def names_a_product(*texts: Optional[str]) -> bool:
    """Whether the text of a launch line holds a word that is not a launch word, a date or a filler."""
    joined = " ".join(t for t in texts if t)
    joined = re.sub(r"(?i)\b(?:q[1-4]|h[12]|fy\s*\d*|\d{4})\b", " ", joined)
    return any(w.lower() not in _LAUNCH_FILLER for w in _WORDS.findall(joined))


def launch_without_product(claim: Dict, cell_text: str, label_text: Optional[str]) -> bool:
    """A claim of metric product with a date and no figure (a launch) whose cell and label name no product."""
    return claim.get("metric") == "product" and claim.get("value") is None and bool(claim.get("period")) \
        and not names_a_product(cell_text, label_text)


# ---------------------------------------------------------------------------
# The corrections
# ---------------------------------------------------------------------------
def _heading_periods(grid: Dict, grid_views: Dict, fiscal_year_end: int) -> List[Dict]:
    """The distinct periods the page's heading cells (title cell or top 20%) state, in reading order."""
    out, spans = [], []
    for cell in grid["cells"]:
        if not (cell.get("title") or cell.get("top_band")) or verify.figures(cell["text"]) and not claims.period_cell(cell["text"]):
            continue
        found = page_check._from_source(page_check.view_of(grid_views, cell), cell, fiscal_year_end)
        if found and found[1] not in spans:
            spans.append(found[1])
            out.append({"period": found[0], "period_cells": found[2], "value": found[0], "ref": found[0]})
    return out


def label_candidates(structure: Dict, cell: Dict) -> List[Dict]:
    """The cells where the label of `cell` may stand that hold words and no figure, distinct by text, the value cell itself excluded."""
    out, texts = [], set()
    for c in page_check.label_cells(structure, cell):
        text = (c["text"] or "").strip()
        if c is cell or not _WORDS.search(text) or verify.figures(text) or page_check._is_date_source(text) or text in texts:
            continue
        texts.add(text)
        out.append({"label_cell": page_check._id(c), "value": text, "ref": page_check._id(c)})
    return out


def plan(grid: Dict, grid_views: Dict, claim: Dict, item: Dict, cell: Dict, flags: List[str], label_mismatch: str,
         fiscal_year_end: int) -> List[Dict]:
    """The corrections the checks name for one checked claim (see the module docstring). `label_mismatch` is checker.LABEL_MISMATCH."""
    from . import checker
    out = []
    checks = item["checks"]
    if checker.PERIOD_FROM_OTHER_CELL in flags and checks.get("period_corrected") and item.get("period"):
        out.append({"flag": checker.PERIOD_FROM_OTHER_CELL, "field": "period", "original": item.get("model_period"), "original_text": item.get("model_period"),
                    "options": [{"period": item["period"], "period_cells": list(item.get("period_cells") or []), "value": item["period"], "ref": item["period"]}]})
    if checker.BAR_YEAR in flags:
        bar = (claims.period_cell(str(cell["bar_year"])) or {}).get("label")
        if bar:
            out.append({"flag": checker.BAR_YEAR, "field": "period", "original": claim.get("period"), "original_text": claim.get("period"),
                        "options": [{"period": bar, "period_cells": [], "value": bar, "ref": bar}]})
    if checker.PERIOD_NOT_ON_PAGE in flags:
        options = _heading_periods(grid, grid_views, fiscal_year_end)
        if options:
            out.append({"flag": checker.PERIOD_NOT_ON_PAGE, "field": "period", "original": claim.get("period"), "original_text": claim.get("period"), "options": options})
    if claim.get("label_cell") and item.get("label_cell") is None:
        options = label_candidates(page_check.view_of(grid_views, cell), cell)
        if len(options) == 1:
            cited = next((c["text"] for c in grid["cells"] if page_check._id(c) == claim["label_cell"]), None)
            out.append({"flag": label_mismatch, "field": "label", "original": claim["label_cell"], "original_text": cited, "options": options})
    return out


def apply_option(item: Dict, field: str, option: Dict) -> Dict:
    """The item with one option applied (a copy)."""
    if field == "period":
        return {**item, "period": option["period"], "period_cells": list(option.get("period_cells") or [])}
    return {**item, "label_cell": option["label_cell"]}


def restore_original(item: Dict, plan_: Dict) -> Dict:
    """The item as the model read it, for the field of one plan entry (a copy)."""
    if plan_["field"] == "period":
        return {**item, "period": plan_["original"], "period_cells": []}
    return {**item, "label_cell": None}


def row_fields(field: str, row: Dict) -> Dict:
    """The fields of an approval-list row a correction of `field` sets."""
    return {k: row.get(k) for k in _PAGE_FIELDS[field]}
