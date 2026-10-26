"""The page grid: every text line and table cell of a deck page as a cell with an id (docs/design/ai-reads-rules-check.md).

Python only, no model: this module is part of the deck parser and has no link to the gateway (CLAUDE.md rule 16). Where the
structures of deck-parser.md section 7 give cell ids to the lines of a KPI panel, a roadmap or a table only, a page grid gives one
to every line of the page, so a claim the model reads from the page can cite the cell it stands in and Python can check it there
(app/structures/page_check.py). It is built with the same code: text boxes as bands of rows (parser._band_cells), each cell with
its box, its "next_to" (the ids of the cells of other boxes directly next to its line), the title mark, a bar's year label by place
("bar_year", issue #148) and an axis-tick mark; then each table of the page as rows below, its cells keeping their table, row and
column. Layout fields (next_to, bar_year, tick, top_band, box, table) are kept with the grid and never sent.

Layout evidence for the source association (docs/specs/source-association.md): with the deck's layout (parser.parse_deck), every cell also
keeps "at", its place on the page as fractions [left, top, right, bottom], and "rot" when its text is turned a quarter; the grid keeps
"layout" {"rects": [{"at", "fill", "scope"}], "gaps": [closed words]}. A grid built without the layout (a deck stored before this field,
a hand-built test grid) has no "layout" key: its extraction is not measured, and nothing is dropped for it (structures/association.py).

    {"type": "page", "slide": 5, "header_rows": 0, "figure": True,
     "cells": [{"row": 1, "col": 1, "text": "Traction", "box": 1, "title": True, "next_to": ["r2c1"]}, ...],
     "tables": [{"table": 1, "header_rows": 1}]}

"figure" says whether the page carries a figure written in digits (claims.figures: a number that is not a date; a number
written in words, "three million", is none; a line that is only the page's own number, "3", "Slide 3", "3/25", is none either:
claims.page_number_line, George, 2026-10-22, review of PR #159; nor is a digit in the page's furniture, a header or footer line, a phone
number, a URL or an email: claims.page_figures, George, 2026-10-23). Decision 1b (George, 2026-10-22, PR #158): only such a page may
go to the model.
Pages whose figures section 2 drops as background or cited research (claims.excluded_pages) are marked "excluded" and are not
sent either.
"""
from typing import Dict, List, Optional

from . import claims, parser


def page_grids(blocks: List[Dict], layout: Optional[List[Dict]] = None) -> List[Dict]:
    """One grid per page of the parsed deck that holds any text, in page order. `layout` is the deck's layout (parser.parse_deck): one
    entry per slide or page; a grid whose page has an entry keeps it."""
    excluded = claims.excluded_pages(blocks)
    placed = {(e.get("slide"), e.get("page")): e for e in layout or ()}
    ticks = claims.tick_lines(blocks)
    pages: Dict = {}
    for b in blocks:
        pages.setdefault(parser._page_key(b), []).append(b)
    out = []
    for key in sorted(pages, key=lambda k: (k[0] or 0, k[1] or 0)):
        grid = page_grid(pages[key], ticks, placed.get(key))
        if grid is None:
            continue
        if key in excluded:
            grid["excluded"] = True
        out.append(grid)
    return out


def page_grid(blocks: List[Dict], ticks: set = frozenset(), layout: Optional[Dict] = None) -> Optional[Dict]:
    """The grid of one page's blocks (all of one slide or page), or None when the page holds no text. `layout` is the page's entry of the
    deck's layout, kept on the grid with the cells' places."""
    # An axis tick is marked on the line itself (claims.tick_lines gives the ids of the page's blocks), so the grid cell keeps it.
    texts = [dict(b, tick=True) if id(b) in ticks else b for b in blocks if b["kind"] != "table" and b["text"].strip()]
    # Page furniture (a header or footer band line, the page's own number) is marked on the cell: the checker never looks for a value there.
    page = int((parser._where(blocks[0]).get("slide") or parser._where(blocks[0]).get("page") or 0)) if blocks else 0
    texts = [dict(b, furniture=True) if claims.page_furniture_line(b) or claims.page_number_line(b["text"], page) else b for b in texts]
    ticks = {id(b) for b in texts if b.get("tick")}
    tables: Dict = {}
    for b in blocks:
        if b["kind"] == "table" and b["text"].strip():
            tables.setdefault(b["table"], []).append(b)
    if not texts and not tables:
        return None
    first = texts[0] if texts else next(iter(tables.values()))[0]
    boxes: Dict = {}
    titles = []
    for b in texts:
        if b.get("title"):
            titles.append(b)
            continue
        key = b.get("box") if b.get("box") is not None else ("line", len(boxes))
        boxes.setdefault(key, []).append(b)
    page_boxes = list(boxes.values()) + ([titles] if titles else [])
    others = [e for e in map(parser._extent, page_boxes) if e]
    years = claims.bar_years(texts, ticks)
    cells = parser._band_cells(page_boxes, others, None, years, top_band=True, place=layout is not None) if page_boxes else []
    offset = max((c["row"] for c in cells), default=0)
    listed = []
    for t in sorted(tables):
        table_cells = [parser._cell(b) for b in tables[t]]
        header_rows = parser._header_rows(table_cells, claims)
        for c, b in zip(table_cells, tables[t]):
            cells.append({**c, "row": offset + c["row"], "table": t, "trow": c["row"], "tcol": c["col"],
                          **({"at": b["bbox"]} if layout is not None and b.get("bbox") else {})})
        listed.append({"table": t, "header_rows": header_rows})
        offset = max(c["row"] for c in cells)
    where = parser._where(first)
    number = int(where.get("slide") or where.get("page") or 0)
    # A figure counts when it stands outside the page's furniture: the page number, a header or footer line, a phone number, a URL, an email.
    lines = [b["text"] for b in texts if not claims.page_furniture_line(b)] + [t["text"] for ts in tables.values() for t in ts]
    grid = {"type": "page", **where, "header_rows": 0, "cells": cells, "tables": listed,
            "figure": any(claims.page_figures(text, number) for text in lines)}
    if layout is not None:
        grid["layout"] = {"rects": [dict(r) for r in layout.get("rects") or ()], "gaps": list(layout.get("gaps") or ())}
    return grid


def has_digit_figure(grid: Dict) -> bool:
    """Whether the page carries a figure written in digits (decision 1b): a number that is not a date, by the parser's own
    reader. Number-words and the page's own printed number do not count."""
    return bool(grid.get("figure"))


def sendable(grids: List[Dict]) -> List[Dict]:
    """The grids that may go to the model: a page with a figure as digits that section 2 does not drop whole."""
    return [g for g in grids if has_digit_figure(g) and not g.get("excluded")]


def page_number(grid: Dict) -> int:
    return int(grid.get("slide") or grid.get("page") or 0)
