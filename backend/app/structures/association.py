"""association: the one source-association rule for a printed value (docs/specs/source-association.md; section 4 of
docs/design/claim-review-simplified-design.md, 26 October 2026).

Pure: no I/O, no model, no database. page_check and checker call this; nothing here is ever sent to the model (CLAUDE.md rule 16: the
layout stays in Python, the page text goes as lines "p<n>r<row>c<col>: <text>" and nothing else).

A printed value is accepted with a supported association for its metric (the label), its period and its unit. The candidate sources, nearest
first: its own cell; an associated table header or chart axis; a containing segment label or legend; an applicable heading above the figure.
A valid explicit local association takes precedence over a broader heading, and a disagreement between them is a review flag.

What this module adds to the grid's text lines is the layout evidence the deck reader keeps (decks/parser.py): the filled rectangles of the
page and the places of the lines.

- Rotated text is read by the parser as one line in reading order, with `rot` (90 or 270) on its cell. A rotated line without a figure that
  stands beside a chart, level with its bars, is the chart's axis title: a source for the figure's label and unit in that chart.
- A chart has at least two bars, or is a group of shapes: a lone filled rectangle is a card or a tile, and no legend or axis title is read for it.
- A bar is a filled rectangle that is not a legend swatch; a legend swatch is a small, squarish rectangle with a line of words next to it on its
  row. A value printed on a bar (inside it, above it or beside it) takes the legend label of the swatch with the bar's colour, in the same
  chart: a chart is a group of shapes (pptx) or a cluster of bars (a rectangle within CLUSTER_GAP of another); a legend inside no chart serves
  the one chart that uses its colour. Two swatches of one colour in a chart, or one legend colour used by two charts, give several candidate
  labels: nothing is chosen and the claim goes to review ("source ambiguous").
- A date inside a chart's plot area that is not on its axis (above the bars' baseline) is a marker annotation. Its date belongs to the marker
  it is printed beside; it is not a source of the period of another figure.

Every word this module returns is a closed word (SOURCES, FLAGS); a cell is named by its id, never by its text (CLAUDE.md rule 17).
"""
import re
from typing import Dict, List, Optional, Tuple

from ..decks import claims
from . import redact, verify

# The closed words of a source: where the support for a field came from.
OWN, HEADER, AXIS, LEGEND, HEADING, OTHER, ANNOTATION = "own", "header", "axis", "legend", "heading", "other", "annotation"
SOURCES = (OWN, HEADER, AXIS, LEGEND, HEADING, OTHER, ANNOTATION)
# The review flags this module's findings become (checker.FLAGS holds them too).
SOURCES_DISAGREE = "sources disagree"
SOURCE_AMBIGUOUS = "source ambiguous"
SOURCE_NOT_ASSOCIATED = "source not associated"
FLAGS = (SOURCES_DISAGREE, SOURCE_AMBIGUOUS, SOURCE_NOT_ASSOCIATED)

# Geometry, as shares of the page. Measured on the 10 public test decks and the synthetic fixtures of tests/test_source_association.py.
SWATCH_MAX = 0.05             # a legend swatch is at most this wide and this tall
SWATCH_ASPECT = (0.5, 2.0)    # ... and about square (width over height)
LEGEND_REACH = 0.06           # the label of a swatch starts at most this far to its right (or ends this far to its left), on its row
BAR_REACH = 0.04              # a value stands on its bar: inside it, at most this far above it, or at most this far beside it
CLUSTER_GAP = 0.05            # bars at most this far apart are one chart when no group says so
CHART_MARGIN = 0.05           # the margin around a chart's bars that still belongs to the chart
AXIS_REACH = 0.12             # an axis title stands at most this far outside the chart's bars
LEGEND_ZONE = 0.25            # a legend item stands at most this far outside the box around the chart's bars
MAX_LEGEND_ITEMS = 8          # a card offers at most this many
LABEL_MAX = 59                # a legend label is at most this long (decks/parser.py LABEL_MAX): a longer line is a sentence, not a label
MIN_BARS = 2                  # bars that make a chart when no group says so
_WORDS = re.compile(r"[^\W\d_]{2,}")
_NOT_A_LEGEND = re.compile(r"(?i):|\.\s*$|^\s*(?:sources?|notes?|footnotes?)\b")        # a source line, a note or a sentence is no legend item
_YEAR = r"(?<![\w$€£.,'’])(?:(?:FY\s*)?(?:19|20)\d{2}|FY\s*\d{2})"
_FORECAST = re.compile(r"(?i)" + _YEAR + r"[FBPE]\b|\b(?:forecasts?|forecasted|projected|projection|plan|planned|budget|estimate[sd]?|target)\b")
_ACTUAL = re.compile(r"(?i)" + _YEAR + r"A\b|\b(?:actuals?|reported|historical)\b")


def period_marker(text: Optional[str]) -> Optional[str]:
    """The actual/forecast marker a period cell states beside its date: "actual" ("2024A", "Actual"), "forecast" ("2025E", "2025 Forecast",
    "Budget"), None for neither. Kept apart from the period token (George, 2026-10-26: the marker is preserved separately, never merged into
    the period)."""
    if not text:
        return None
    if _FORECAST.search(text):
        return "forecast"
    return "actual" if _ACTUAL.search(text) else None


# The metric a chart title or page heading names (George, 2026-10-26): one closed word, or none when it names no metric or more than one.
_HEADING_WORDS = (("revenue", re.compile(r"(?i)\brevenues?\b")), ("sales", re.compile(r"(?i)\bsales\b")), ("ARR", re.compile(r"\bARR\b")),
                  ("MRR", re.compile(r"\bMRR\b")))
GRAPHIC_GAPS = ("graphic", "chart")        # the reader saw a drawing it could not read: a pie or a chart whose slices are no rectangles


def heading_word(texts: List[str]) -> Optional[str]:
    """The one metric word the texts name (revenue, sales, ARR or MRR), else None. "Annual recurring revenue" is not a word here."""
    found = {word for text in texts for word, rx in _HEADING_WORDS if rx.search(text or "")}
    return next(iter(found)) if len(found) == 1 else None


def _box(at) -> Optional[Tuple[float, float, float, float]]:
    return tuple(at) if at and len(at) == 4 else None


def _centre(b) -> Tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _gap(a, b) -> float:
    """Distance between two boxes (0 when they touch or overlap)."""
    return max(0.0, b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])


def _overlap(a, b, lo: int) -> bool:
    """Whether two boxes overlap along x (lo 0) or y (lo 1)."""
    return min(a[lo + 2], b[lo + 2]) > max(a[lo], b[lo])


def _inside(point, b, slack: float = 0.0) -> bool:
    return b[0] - slack <= point[0] <= b[2] + slack and b[1] - slack <= point[1] <= b[3] + slack


def _is_label_text(text: str) -> bool:
    """Words and no figure: what a legend or an axis title says."""
    return bool(_WORDS.search(text or "")) and not verify.figures(text or "")


class Layout:
    """The layout evidence of one page grid. `measured` is False for a grid built without the deck's layout (nothing is known about
    rectangles or extraction)."""

    def __init__(self, grid: Dict):
        self.cells: List[Dict] = grid["cells"]
        self.measured = "layout" in grid
        info = grid.get("layout") or {}
        self.gaps: Tuple[str, ...] = tuple(info.get("gaps") or ())
        self.by_id = {redact.cell_id(c): c for c in self.cells}
        self.swatches: List[Dict] = []
        self.bars: List[Dict] = []
        for r in info.get("rects") or ():
            rect = {"at": _box(r.get("at")), "fill": r.get("fill"), "scope": int(r.get("scope") or 0)}
            if rect["at"] and rect["fill"]:
                legend = self._legend_label(rect)
                (self.swatches if legend else self.bars).append({**rect, "label": legend})
        self._scope_bars()

    # -- extraction ---------------------------------------------------------------------------------------------------------------
    @property
    def complete(self) -> Optional[bool]:
        """True when the page's extraction is measured and left nothing unread, False when it left something, None when it was not measured."""
        return None if not self.measured else not self.gaps

    # -- charts, bars, legends ----------------------------------------------------------------------------------------------------
    def _legend_label(self, rect: Dict) -> Optional[str]:
        """The id of the line of words next to a small squarish rectangle on its row, or None when the rectangle is no legend swatch."""
        x0, y0, x1, y1 = rect["at"]
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0 or w > SWATCH_MAX or h > SWATCH_MAX or not SWATCH_ASPECT[0] <= w / h <= SWATCH_ASPECT[1]:
            return None
        near = []
        for c in self.cells:
            box = _box(c.get("at"))
            if not box or c.get("rot") or c.get("table") is not None or not _is_label_text(c["text"]) or len(c["text"].strip()) > LABEL_MAX:
                continue
            level = _overlap(box, rect["at"], 1) and abs(_centre(box)[1] - (y0 + y1) / 2) <= max(h, box[3] - box[1]) / 2 + 1e-9
            if not level:
                continue
            side = box[0] - x1 if box[0] >= x1 - 1e-9 else x0 - box[2] if box[2] <= x0 + 1e-9 else None
            if side is not None and -1e-9 <= side <= LEGEND_REACH:
                near.append((side, redact.cell_id(c)))
        return min(near)[1] if near else None

    def _scope_bars(self) -> None:
        """Give every bar and swatch its chart: a group (pptx) keeps its number; ungrouped bars within CLUSTER_GAP of each other are one chart
        (a negative number); an ungrouped swatch belongs to the chart whose bars it stands inside the margin of, else to no chart (0)."""
        loose = [b for b in self.bars if b["scope"] == 0]
        clusters: List[List[Dict]] = []
        for bar in loose:
            joined = [c for c in clusters if any(_gap(bar["at"], other["at"]) <= CLUSTER_GAP for other in c)]
            merged = [bar] + [other for c in joined for other in c]
            clusters = [c for c in clusters if c not in joined] + [merged]
        for number, members in enumerate(clusters, 1):
            for bar in members:
                bar["scope"] = -number
        extents = self.extents()
        for swatch in self.swatches:
            if swatch["scope"] == 0:
                inside = [s for s, e in extents.items() if s < 0 and _inside(_centre(swatch["at"]), e, CHART_MARGIN)]
                swatch["scope"] = inside[0] if len(inside) == 1 else 0

    def extents(self) -> Dict[int, Tuple[float, float, float, float]]:
        """{chart: the box around its bars}."""
        out: Dict[int, List[float]] = {}
        for bar in self.bars:
            box = out.setdefault(bar["scope"], list(bar["at"]))
            box[0], box[1], box[2], box[3] = min(box[0], bar["at"][0]), min(box[1], bar["at"][1]), max(box[2], bar["at"][2]), max(box[3], bar["at"][3])
        return {s: tuple(b) for s, b in out.items()}

    def is_chart(self, scope: int) -> bool:
        """Whether the bars of a scope make a chart: a group of shapes, or at least MIN_BARS bars."""
        return scope > 0 or sum(1 for b in self.bars if b["scope"] == scope) >= MIN_BARS

    def bar_of(self, cell: Dict) -> Optional[Dict]:
        """The bar a printed value stands on: the smallest rectangle holding it, else the nearest one it sits on top of (a tall bar) or beside (a wide one)."""
        box = _box(cell.get("at"))
        if not box:
            return None
        centre = _centre(box)
        holding = [b for b in self.bars if _inside(centre, b["at"])]
        if holding:
            return min(holding, key=lambda b: (b["at"][2] - b["at"][0]) * (b["at"][3] - b["at"][1]))
        near = []
        for b in self.bars:
            x0, y0, x1, y1 = b["at"]
            upright = y1 - y0 >= x1 - x0            # a tall bar carries its value above it, a wide one beside it
            above = upright and x0 <= centre[0] <= x1 and 0 <= y0 - box[3] <= BAR_REACH
            beside = not upright and y0 <= centre[1] <= y1 and (0 <= box[0] - x1 <= BAR_REACH or 0 <= x0 - box[2] <= BAR_REACH)
            if above or beside:
                near.append((_gap(box, b["at"]), b["fill"], b))
        return min(near, key=lambda t: t[:2])[2] if near else None

    def segment_label(self, cell: Dict) -> Dict:
        """{"cells": [ids], "ambiguous": bool}: the legend label of the bar a value stands on. One cell is the explicit local association; several
        (two swatches of the bar's colour in its chart, or one colour in two charts with a legend of no chart) are ambiguous."""
        bar = self.bar_of(cell)
        if bar is None or not self.is_chart(bar["scope"]):
            return {"cells": [], "ambiguous": False}
        same = [s for s in self.swatches if s["fill"] == bar["fill"] and s["scope"] == bar["scope"]]
        if not same:
            charts = {b["scope"] for b in self.bars if b["fill"] == bar["fill"]}
            free = [s for s in self.swatches if s["fill"] == bar["fill"] and s["scope"] == 0]
            if len(charts) > 1 and free:
                return {"cells": sorted({s["label"] for s in free}), "ambiguous": True}
            same = free
        labels = sorted({s["label"] for s in same})
        return {"cells": labels, "ambiguous": len(labels) > 1}

    def axis_titles(self, cell: Dict) -> Dict:
        """{"cells": [ids], "ambiguous": bool}: the rotated lines of words beside the chart a value is printed in, level with its bars."""
        box = _box(cell.get("at"))
        if not box:
            return {"cells": [], "ambiguous": False}
        bar = self.bar_of(cell)
        extents = self.extents()
        scope = bar["scope"] if bar else next((s for s, e in extents.items() if _inside(_centre(box), e, CHART_MARGIN)), None)
        if scope is None or scope not in extents or not self.is_chart(scope):
            return {"cells": [], "ambiguous": False}
        ext = extents[scope]
        found = []
        for c in self.cells:
            at = _box(c.get("at"))
            if not at or not c.get("rot") or not _is_label_text(c["text"]) or not _overlap(at, ext, 1):
                continue
            centre = _centre(at)[0]
            outside = ext[0] - centre if centre < ext[0] else centre - ext[2] if centre > ext[2] else None
            if outside is not None and outside <= AXIS_REACH:
                found.append(redact.cell_id(c))
        texts = {self.by_id[i]["text"].strip().lower() for i in found}
        return {"cells": sorted(found), "ambiguous": len(texts) > 1}

    def _chart_extent(self, cell: Dict) -> Optional[Tuple[float, float, float, float]]:
        """The box around the bars of the chart a figure is printed in, else None."""
        box = _box(cell.get("at"))
        if not self.measured or not box:
            return None
        bar = self.bar_of(cell)
        extents = self.extents()
        scope = bar["scope"] if bar else next((s for s, e in extents.items() if self.is_chart(s) and _inside(_centre(box), e, CHART_MARGIN)), None)
        return extents[scope] if scope is not None and scope in extents and self.is_chart(scope) else None

    @staticmethod
    def _over(at, ext) -> bool:
        """Whether a line stands over the box of a chart's bars, centred on them: the chart's own title."""
        return at[3] <= ext[1] + 1e-9 and ext[1] - at[3] <= AXIS_REACH and abs(_centre(at)[0] - _centre(ext)[0]) <= (ext[2] - ext[0]) / 4

    def heading_metric(self, cell: Dict) -> Optional[str]:
        """The metric word (revenue, sales, ARR, MRR) of the chart title over the figure's chart when it names exactly one, else of the page's heading
        cells (title or top band) when they name exactly one, else None. Only Python reads the text; the word is closed."""
        ext = self._chart_extent(cell)
        if ext is not None:
            word = heading_word([c["text"] for c in self.cells if _box(c.get("at")) and not c.get("rot") and c.get("table") is None and self._over(_box(c["at"]), ext)])
            if word:
                return word
        return heading_word([c["text"] for c in self.cells if c.get("title") or c.get("top_band")])

    def legend_items(self, cell: Dict) -> List[str]:
        """The ids of the short lines of words a figure printed in a chart may be named by, for a card that asks the analyst which one it is
        (never paired automatically): lines of words with no figure, at most LABEL_MAX long, standing within LEGEND_ZONE of the chart's bars,
        that are not a source line or a sentence, not the page heading, a heading of the top band, the chart's own title (the line over the bars, centred on them), an axis tick,
        a date or period header, a rotated axis title, a table cell or page furniture. Empty when the figure is in no chart or the page was not measured."""
        box = _box(cell.get("at"))
        if not self.measured or not box:
            return []
        ext = self._chart_extent(cell)
        pie = ext is None and any(g in GRAPHIC_GAPS for g in self.gaps)         # a drawing the reader cannot read: the whole page is its zone
        if ext is None and not pie:
            return []
        ext = ext or (0.0, 0.0, 1.0, 1.0)
        zone = (ext[0] - LEGEND_ZONE, ext[1] - LEGEND_ZONE, ext[2] + LEGEND_ZONE, ext[3] + LEGEND_ZONE)
        found = []
        for c in self.cells:
            at = _box(c.get("at"))
            if c is cell or not at or c.get("rot") or c.get("table") is not None or c.get("title") or c.get("top_band") or c.get("tick") \
                    or c.get("furniture") or not _is_label_text(c["text"]) or len(c["text"].strip()) > LABEL_MAX:
                continue
            if verify.is_date_line(c["text"]) or verify.period_header(c["text"]) or not _inside(_centre(at), zone) or _NOT_A_LEGEND.search(c["text"]):
                continue
            if not pie and self._over(at, ext):
                continue            # the chart's own title
            found.append((_gap(at, ext), redact.cell_id(c)))
        return [i for _, i in sorted(found)[:MAX_LEGEND_ITEMS]]

    # -- marker annotations -------------------------------------------------------------------------------------------------------
    def is_annotation(self, cell: Dict) -> bool:
        """A date printed inside a chart's plot area (between the top of its bars and their baseline) that is no tick of its axis."""
        box = _box(cell.get("at"))
        if not box or cell.get("table") is not None or cell.get("tick") or cell.get("rot") or not claims.find_dates(cell["text"]):
            return False
        centre = _centre(box)
        for scope, ext in self.extents().items():
            if self.is_chart(scope) and ext[0] <= centre[0] <= ext[2] and ext[1] - CHART_MARGIN <= centre[1] < ext[3] - 1e-9:
                return True
        return False

    def annotation_for(self, cited: Dict, cell: Dict) -> bool:
        """Whether `cited` is a marker annotation that is no source for `cell`: an annotation outside the figure's own cell and text box."""
        if not self.measured or cited is cell or not self.is_annotation(cited):
            return False
        return cited.get("box") is None or cited.get("box") != cell.get("box")

    # -- what a value's chart says about its label and unit ------------------------------------------------------------------------
    def local_label(self, cell: Dict) -> Dict:
        """{"source": "legend" | "axis" | None, "cells": [ids], "ambiguous": bool}: the explicit local association of a value's label, the
        legend label of its bar first, the chart's axis title when there is no legend entry."""
        if not self.measured:
            return {"source": None, "cells": [], "ambiguous": False}
        legend = self.segment_label(cell)
        if legend["cells"]:
            return {"source": LEGEND, **legend}
        axis = self.axis_titles(cell)
        return {"source": AXIS if axis["cells"] else None, **axis}

    def unit_marks(self, cell: Dict) -> List[str]:
        """The texts beside the chart that may state the unit of a value printed in it: its axis titles and its legend label."""
        if not self.measured:
            return []
        ids = self.segment_label(cell)["cells"] + self.axis_titles(cell)["cells"]
        return [self.by_id[i]["text"] for i in ids if i in self.by_id]
