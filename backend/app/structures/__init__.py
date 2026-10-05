"""Model reading of deck structures and spreadsheet headers (docs/specs/llm-structure-reading.md).

The orchestration around gateway.read_structure. The deck parser finds the structures and has no
link to the gateway (CLAUDE.md rule 16); this package builds the text the model reads from them,
redacted, and checks every value the model returns against its source cell (rule 18). The gateway
never reads parsed deck text: it is handed the redacted structure text and nothing else.

What may reach the model (rule 16): redacted deck structures as extracted text with cell positions,
and spreadsheet header rows (at most 3, the 3 nearest the data) with up to 3 sample values per
numeric or date column and a profile (distinct count, typical length, shape pattern) per text
column. Only with the audit's consent. Never raw files, full pages, prose slides or a text cell
value from a spreadsheet.
"""
import hashlib
import re
import statistics
from collections import Counter
from typing import Dict, List, Optional, Tuple

from . import redact

# Confirmed column mappings, per audit and header set: reused when a file with the same headers is
# uploaded again, so the model is not asked twice. Removed by Delete audit.
COLUMN_MAPPINGS_COLLECTION = "column_mappings"

# ---------------------------------------------------------------------------
# Column mapping (spec section 1): header stack, samples or profiles
# ---------------------------------------------------------------------------
_UNNAMED = re.compile(r"^Unnamed: \d+$")      # pandas' name for a column with no header cell
_ISO_DATETIME = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ]00:00:00(?:\.0+)?)?$")
_YEAR = re.compile(r"^(?:19|20)\d{2}(?:\.0)?$")
_SHAPE_KEEP = set(" -_./@:,#()+&'")
SAMPLE_SHARE = 0.8             # a column is numeric or date when this share of its values are


def _header_text(value) -> str:
    text = "" if value is None else str(value).strip()
    return "" if _UNNAMED.match(text) else text


def _sample(value) -> Optional[str]:
    """A value as a sample: a number or an ISO date. None for a text value, which is never sent."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return str(int(value)) if value.is_integer() else ("%.6f" % value).rstrip("0").rstrip(".")
    text = str(value).strip()
    m = _ISO_DATETIME.match(text)
    if m:
        return m.group(1)
    return text if text and redact.SAMPLE_VALUE.match(text) else None


def shape(value) -> str:
    """The shape pattern of a text value: a run of upper case letters is A, of lower case a, every
    digit 0; spaces and common punctuation stay; at most 20 characters ("Acme Corp" -> "Aa Aa")."""
    out = []
    for ch in str(value):
        kind = "A" if ch.isupper() else "a" if ch.isalpha() else "0" if ch.isdigit() else ch if ch in _SHAPE_KEEP else ""
        if not kind or (kind in "Aa" and out and out[-1] == kind) or (kind == " " and out and out[-1] == " "):
            continue
        out.append(kind)
    return "".join(out).strip()[:20] or "a"


def _profile(values: List) -> Dict:
    texts = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if not texts:
        return {"distinct": 0, "length": 0, "shape": "a"}
    shapes = Counter(shape(t) for t in texts)
    return {"distinct": len(set(texts)), "length": int(statistics.median(len(t) for t in texts)),
            "shape": shapes.most_common(1)[0][0]}


def _header_like(row: List) -> bool:
    """A sheet row of labels: no number other than a year (dates and text are header cells too)."""
    for value in row:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)) and not _YEAR.match(str(value)):
            return False
        if isinstance(value, str) and value.strip() and _sample(value) and not _ISO_DATETIME.match(value.strip()) \
                and not _YEAR.match(value.strip()):
            return False
    return True


def header_key(dtype: str, columns: List[str]) -> str:
    """The header set a stored mapping correction is kept under: the type and its column names."""
    names = sorted(_header_text(c).lower() for c in columns)
    return hashlib.sha256(("\x00".join([dtype] + names)).encode("utf-8")).hexdigest()


def column_mapping_input(columns: List[str], rows: List[Dict], customer_columns: Tuple[str, ...] = ()
                         ) -> Tuple[List[Dict], Dict[int, List[str]], Dict[int, Dict]]:
    """(header cells, samples, profiles) for a sheet stored as `columns` and `rows`.

    The header stack is the column names and the rows below them that hold no number other than a
    year, capped at the 3 rows nearest the data. A column whose values are numbers or dates
    (SAMPLE_SHARE of them) sends up to 3 samples; any other column, and a customer column whatever
    its values, sends a profile only. No text cell value is ever returned.
    """
    stack = [[_header_text(c) for c in columns]]
    body = list(rows)
    while body and _header_like([body[0].get(c) for c in columns]) and len(stack) < len(rows):
        stack.append([_header_text(body[0].get(c)) for c in columns])
        body = body[1:]
    stack = stack[-redact.MAX_HEADER_ROWS:]
    headers = [{"row": r, "col": c, "text": text} for r, row in enumerate(stack, 1)
               for c, text in enumerate(row, 1) if text]
    samples, profiles = {}, {}
    for c, name in enumerate(columns, 1):
        values = [row.get(name) for row in body if row.get(name) is not None and str(row.get(name)).strip()]
        if not values and not _header_text(name):
            continue                       # an empty column with no header says nothing
        as_samples = [_sample(v) for v in values]
        numeric = values and sum(1 for s in as_samples if s) >= SAMPLE_SHARE * len(values)
        if numeric and name not in customer_columns:
            samples[c] = [s for s in as_samples if s][:redact.MAX_SAMPLES]
        else:
            profiles[c] = _profile(values)
    return headers, samples, profiles


def column_mapping_text(columns: List[str], rows: List[Dict], company_name: Optional[str], mapping: Dict[str, str],
                        customer_columns: Tuple[str, ...] = ()) -> str:
    """The redacted column-mapping text the model reads."""
    headers, samples, profiles = column_mapping_input(columns, rows, customer_columns)
    headers, _ = redact.redact_structure(headers, company_name, mapping)
    return redact.column_text(headers, samples, profiles)


def proposed_mapping(items: List[Dict], columns: List[str], fields: List[str]) -> Dict[str, str]:
    """{field: column} from a column-mapping reply: each item names a field and cites the header cell
    of a column. Fields of another file type, unknown cells and a column proposed twice are left out."""
    out, used = {}, set()
    for item in items:
        m = re.fullmatch(r"r\d+c(\d+)", item.get("value_cell") or "")
        if not m or item.get("metric") not in fields or item["metric"] in out:
            continue
        col = int(m.group(1))
        if 1 <= col <= len(columns) and columns[col - 1] not in used:
            out[item["metric"]] = columns[col - 1]
            used.add(columns[col - 1])
    return out
