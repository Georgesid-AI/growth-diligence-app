"""Redaction of deck structure cells, and the structure text the model reads (pure, no I/O).

Spec: docs/specs/llm-structure-reading.md section 3; CLAUDE.md rule 16. Nothing here reads a
database or a file, and nothing here calls a model: the gateway runs these same functions again
on the text it is given and refuses the call if anything changes.

The text is one line per cell, `r<row>c<col>: <cell text>`, with no file name, slide number or
prose. A merged cell carries its span after its text, `r1c3: FY2025 (r1c3:r1c14)`, so the model
receives the full header stack (deck-parser.md section 2).
"""
import re
from typing import Dict, List, Optional, Tuple

_LINE = re.compile(r"^r(?P<row>\d+)c(?P<col>\d+): (?P<text>.*?)(?: \(r(?P=row)c(?P=col):r(?P<row2>\d+)c(?P<col2>\d+)\))?$")


def cell_id(cell: Dict) -> str:
    return f"r{cell['row']}c{cell['col']}"


def structure_text(cells: List[Dict]) -> str:
    """The structure as the model reads it: one `r<row>c<col>: <text>` line per cell, in reading order."""
    lines = []
    for c in sorted(cells, key=lambda c: (c["row"], c["col"])):
        text = re.sub(r"\s+", " ", str(c["text"])).strip()
        if not text:
            continue
        rows, cols = c.get("row_span", 1), c.get("col_span", 1)
        span = f" ({cell_id(c)}:r{c['row'] + rows - 1}c{c['col'] + cols - 1})" if rows > 1 or cols > 1 else ""
        lines.append(f"{cell_id(c)}: {text}{span}")
    return "\n".join(lines)


def parse_structure_text(text: str) -> Optional[List[Dict]]:
    """The cells of a structure text, or None when a line is not a cell line."""
    cells = []
    for line in (text or "").split("\n"):
        m = _LINE.match(line)
        if not m:
            return None
        cell = {"row": int(m.group("row")), "col": int(m.group("col")), "text": m.group("text")}
        if m.group("row2"):
            rows, cols = int(m.group("row2")) - cell["row"] + 1, int(m.group("col2")) - cell["col"] + 1
            if rows > 1:
                cell["row_span"] = rows
            if cols > 1:
                cell["col_span"] = cols
        cells.append(cell)
    return cells
