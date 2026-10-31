"""The lines of a file block (docs/design/read-check-review.md section 11.2; PR 3 step c): one line per mapped row, in file order, as the screen's
"Show all lines" table lists them: Line, Read as, Basis, Actual / plan, Cells.

    - rows keep the order they have in the file;
    - a part row (its map entry names a `parent_row`) is indented under its total, after it;
    - PLACEMENT ONLY: a rate row (growth, churn, margin: basis "rate") whose label holds the words of one other line's label is shown directly
      under that line, indented, and marked `moved` when it stood elsewhere in the file ("shown under its line"). The label match decides where
      a row is drawn and nothing else: it is no reading of what the row means, nothing is written into "Read as", and no check or figure uses it.
      A rate whose line cannot be told uniquely stays where it is.

Pure: the map and the label text of each row go in, plain dicts come out. Labels are read from the cells the reader was sent (masked space);
the caller restores the names before storing (sheet_reader).
"""
import re
from typing import Dict, List, Optional

ROLE_WORDS = {"arr": "ARR", "mrr": "MRR", "rnd": "R&D", "ga": "G&A", "ebitda": "EBITDA", "sales_marketing": "sales & marketing",
              "contract_value": "contract value", "cost_of_revenue": "cost of revenue", "churn_rate": "churn rate", "growth_rate": "growth rate",
              "margin_rate": "margin rate"}
RATE_ROLES = ("churn_rate", "growth_rate", "margin_rate")
# PLACEMENT ONLY. Words that make a label a rate; what is left of a rate's label names the line to draw it under.
_PLACEMENT_RATE_WORDS = frozenset("rate growth churn churned margin percent pct as of the in yoy mom qoq".split())
_WORD = re.compile(r"[a-z0-9&]+")


def words(text: Optional[str]) -> List[str]:
    return _WORD.findall((text or "").lower())


def role_name(role: Optional[str]) -> str:
    return ROLE_WORDS.get(role or "", (role or "other").replace("_", " "))


def basis_name(basis: Optional[str]) -> str:
    return (basis or "").replace("_", " ") or "—"


def actual_plan_name(row: Dict) -> str:
    mark = row.get("actual_plan")
    if mark == "mixed":
        return f"mixed, boundary {row['boundary_col']}" if row.get("boundary_col") else "mixed"
    return mark or "—"


def is_rate(row: Dict) -> bool:
    return row.get("basis") == "rate" or row.get("role") in RATE_ROLES


def placement_line_of(rate: Dict, label: str, rows: List[Dict], labels: Dict[int, str]) -> Optional[Dict]:
    """PLACEMENT ONLY (where to draw a rate row, not what it is): the one non-rate row whose label holds every word that is left of the rate's label once the rate words are taken out, the one with the
    fewest other words. None when no row does, or when two do equally (the line cannot be told)."""
    wanted = [w for w in words(label) if w not in _PLACEMENT_RATE_WORDS]
    if not wanted:
        return None
    fits = []
    for row in rows:
        if row is rate or is_rate(row) or row.get("parent_row"):
            continue
        have = words(labels.get(row["row"]))
        if all(w in have for w in wanted):
            fits.append((len(have) - len(wanted), row))
    if not fits:
        return None
    fits.sort(key=lambda f: f[0])
    return fits[0][1] if len(fits) == 1 or fits[0][0] < fits[1][0] else None


def line_of(row: Dict, label: str, **extra) -> Dict:
    return {"row": row["row"], "label": label, "read_as": role_name(row.get("role")), "basis": basis_name(row.get("basis")),
            "actual_plan": actual_plan_name(row), "cells": row.get("cells") or row.get("label_cell"), "indent": 0, "moved": False,
            "role": row.get("role"), "parent_row": row.get("parent_row"), **extra}


def build(sheet_map: Dict, labels: Dict[int, str]) -> List[Dict]:
    """The lines of one sheet. `labels` is {row number: the text of its label cell}."""
    rows = sorted(sheet_map.get("rows") or [], key=lambda r: r["row"])
    present = {r["row"] for r in rows}
    rate_of: Dict[int, Dict] = {}
    for row in rows:
        if is_rate(row) and not row.get("parent_row"):
            base = placement_line_of(row, labels.get(row["row"], ""), rows, labels)
            if base is not None:
                rate_of[row["row"]] = base
    under: Dict[int, List[Dict]] = {}
    for row in rows:
        if row["row"] in rate_of:
            under.setdefault(rate_of[row["row"]]["row"], []).append(row)
    parts: Dict[int, List[Dict]] = {}
    for row in rows:
        if row.get("parent_row") in present and row["row"] not in rate_of:
            parts.setdefault(row["parent_row"], []).append(row)
    out: List[Dict] = []
    seen: set = set()

    def emit_parts(parent: Dict, indent: int) -> None:
        """The parts of a row, each directly under it and one level in; a part of a part goes one level further."""
        for part in parts.get(parent["row"], []):
            if part["row"] in seen:
                continue
            seen.add(part["row"])
            line = line_of(part, labels.get(part["row"], ""), indent=indent, part_of=parent["row"])
            line["read_as"] = f"{line['read_as']}, part of row {parent['row']}"
            out.append(line)
            emit_parts(part, indent + 1)

    for row in rows:
        if row["row"] in rate_of or (row.get("parent_row") in present):
            continue
        seen.add(row["row"])
        out.append(line_of(row, labels.get(row["row"], "")))
        for rate in under.get(row["row"], []):
            previous = rows[rows.index(rate) - 1] if rows.index(rate) else None
            adjacent = previous is not None and previous["row"] == row["row"]
            out.append(line_of(rate, labels.get(rate["row"], ""), indent=1, moved=not adjacent, rate_of=row["row"]))
        emit_parts(row, 1)
    for row in rows:        # a ring of parents (a is part of b, b of a) has no top row: its rows are still lines, in file order
        if row["row"] not in seen and row["row"] not in rate_of:
            seen.add(row["row"])
            out.append(line_of(row, labels.get(row["row"], ""), indent=1))
    return out
