"""The item list: Python lists every figure, the model only labels it (docs/specs/structure-labelling.md).

Pure: no I/O, no model, no database. For every deck type Python lists every figure in every redacted cell
(section 1); dates are periods and are left out. Each item has

- "id": i1, i2, ... in reading order (row, column, position), so the same structure always gives the same
  list;
- "cell" and "position": a cell with several figures gives one item each, the position counting from 1;
- "raw": the figure's text, cut from the redacted cell. It is sent in the item line and never stored;
- "values": [{"value", "dot_reading", "bracket_reading"}], the value in full units under today's
  normalisation (verify.figures, verify.scale_factor), Python's default first. A "2.500" reads as thousands
  unless it carries a suffix ("1.250M" is 1.25m); a bracketed number after text reads as negative when the
  text before it in its cell holds loss, deficit, negative or decline (any case), else positive. The model
  does not choose between them: the approval row shows both;
- "headers": the ids of its header cells (verify.header_cells).

A roadmap also lists its date cells (d1, ...: date labels as in deck-parser.md section 7) and its text lines
(t1, ...: the other non-empty cells), which the model pairs (section 2).
"""
import re
from typing import Dict, List

from ..decks import claims
from . import redact, verify

_LOSS_WORD = re.compile(r"(?i)loss|deficit|negative|decline")


def _full_units(number: float, factor: float) -> float:
    value = round(number * factor, 6)
    return int(value) if float(value).is_integer() else value


def _first(choices: List, default) -> List:
    """The choices with the default first, the rest in their order."""
    return sorted(choices, key=lambda c: c != default)


def list_items(structure: Dict) -> Dict:
    """{"items": [...], "dates": [...], "lines": [...]} for a structure's (redacted) cells; dates and lines are
    empty unless it is a roadmap."""
    cells = sorted(structure["cells"], key=lambda c: (c["row"], c["col"]))
    comma = verify.decimal_comma(cells)
    out = []
    for cell in cells:
        text = redact.cell_text(cell)                 # as its cell line writes it, so raw text stays inside it
        found = claims.period_cell(text)
        if found and ("part" in found or "relative" in found):
            continue                                  # "Q3", "Mar", "M3", "Year 1": a period header, never a value
        figures = verify.figures(text, comma)
        if not figures:
            continue
        headers = [redact.cell_id(h) for h in verify.header_cells(structure, cell)]
        factor = None
        for n, figure in enumerate(figures, 1):
            if not figure["own_scale"] and factor is None:
                factor = verify.scale_factor(structure, cell)
            scale = 1.0 if figure["own_scale"] else factor
            readings = figure["readings"]
            dot = ("decimal" if figure["suffix"] else "thousands") if readings[0][1] else None
            bracket = ("negative" if _LOSS_WORD.search(text[:figure["start"]]) else "positive") \
                if readings[0][2] else None
            dots = _first(list(dict.fromkeys(r[1] for r in readings)), dot)
            signs = _first(list(dict.fromkeys(r[2] for r in readings)), bracket)
            ordered = [next(r for r in readings if r[1] == d and r[2] == b) for d in dots for b in signs]
            out.append({"id": f"i{len(out) + 1}", "cell": redact.cell_id(cell), "position": n,
                        "raw": text[figure["start"]:figure["end"]],
                        "values": [{"value": _full_units(number, scale), "dot_reading": d, "bracket_reading": b}
                                   for number, d, b in ordered],
                        "headers": headers})
    dates, lines = roadmap_cells(structure) if structure.get("type") == "roadmap" else ([], [])
    return {"items": out, "dates": dates, "lines": lines}


def roadmap_cells(structure: Dict):
    """([{"id": "d1", "cell"}...], [{"id": "t1", "cell"}...]): a roadmap's date cells (date labels, deck-parser.md
    section 7) and its text lines (every other non-empty cell), each in reading order."""
    dates, lines = [], []
    for cell in sorted(structure["cells"], key=lambda c: (c["row"], c["col"])):
        if not str(cell["text"]).strip():
            continue
        kept = dates if verify.is_date_line(cell["text"]) else lines
        kept.append({"id": f"{'d' if kept is dates else 't'}{len(kept) + 1}", "cell": redact.cell_id(cell)})
    return dates, lines


def text(structure: Dict, listed: Dict) -> str:
    """The text the model reads: the structure text (redact.structure_text), the line "items:", then one line per
    item, date cell and text line (redact.item_lines)."""
    return "\n".join([redact.structure_text(structure["cells"]), redact.ITEMS_HEADER] + redact.item_lines(listed))


def stored(listed: Dict) -> Dict:
    """The item list as llm_structures keeps it (CLAUDE.md rule 17): ids, cells, positions, values and header
    ids. Never the raw text."""
    return {"items": [{k: v for k, v in item.items() if k != "raw"} for item in listed.get("items") or ()],
            "dates": [dict(d) for d in listed.get("dates") or ()], "lines": [dict(t) for t in listed.get("lines") or ()]}
