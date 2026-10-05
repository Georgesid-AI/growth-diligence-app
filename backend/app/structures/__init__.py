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
                        customer_columns: Tuple[str, ...] = (), withheld: Tuple[str, ...] = ()) -> str:
    """The redacted column-mapping text the model reads (`withheld`: the client name and engagement
    reference, see redact.withheld_values)."""
    headers, samples, profiles = column_mapping_input(columns, rows, customer_columns)
    headers, _ = redact.redact_structure(headers, company_name, mapping, withheld)
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


# ---------------------------------------------------------------------------
# Decks: queue, read, verify, and results in the existing approval list (spec sections 2-4, 9)
# ---------------------------------------------------------------------------
from datetime import datetime, timezone  # noqa: E402
import logging  # noqa: E402
import uuid  # noqa: E402

from ..decks import TEXT_COLLECTION, CANDIDATES_COLLECTION  # noqa: E402
from ..decks import claims  # noqa: E402
from ..llm import gateway  # noqa: E402
from ..llm import redaction as llm_redaction  # noqa: E402
from . import verify  # noqa: E402

# A deck's AI reading status, as the deck panel shows it.
WAITING = "waiting"                 # "waiting for revenue file"
READ, NOT_READ, STOPPED, PYTHON_ONLY = "read", "not_read", "stopped", "python_only"
WAITING_TEXT = "waiting for revenue file"
logger = logging.getLogger("growth.structures")
_UNITS = {"%", "x", "days", "months", "years"}


def revenue_mapped(dataset: Optional[Dict]) -> bool:
    """True once the revenue file is uploaded and the analyst confirmed its columns, customer included."""
    return bool(dataset and dataset.get("mapped_at") and (dataset.get("mapping") or {}).get("customer_id"))


async def process_deck(db, audit_id: str, deck_id: str, adapter=None, sleep=None) -> str:
    """Read one deck's structures with the model, or queue them; returns the deck's AI status.

    Unticked consent: the Python-only path, no call. Ticked but the revenue file not yet mapped: the
    deck waits ("waiting for revenue file"), so no customer name goes out unmapped. Otherwise each
    structure is redacted, sent through gateway.read_structure, verified against its source cells,
    and every item becomes a row of the approval list labelled Verified or "AI suggestion, not
    verified". A deck already read is not sent again (a re-read is served from the cache).
    """
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0, "id": 1, "company_name": 1, "fiscal_year_end": 1,
                                                       "structure_reading_consent": 1, "client_name": 1,
                                                       "engagement_reference": 1})
    deck = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id},
                                              {"_id": 0, "structures": 1, "file": 1, "page_unit": 1})
    if not audit or not deck:
        return NOT_READ
    found = deck.get("structures") or []
    if audit.get("structure_reading_consent") is not True:
        return await _deck_status(db, audit_id, deck_id, PYTHON_ONLY)
    if not revenue_mapped(await db.datasets.find_one({"audit_id": audit_id, "dtype": "revenue"},
                                                     {"_id": 0, "mapping": 1, "mapped_at": 1})):
        return await _deck_status(db, audit_id, deck_id, WAITING, WAITING_TEXT)
    mapping = await llm_redaction.get_map(db, audit_id)
    year_end = int(audit.get("fiscal_year_end") or 12)
    mode = verify.unmatched_mode()
    reviewed = await db[CANDIDATES_COLLECTION].find({"audit_id": audit_id, "file": deck["file"]}, {"_id": 0}).to_list(100000)
    known = _python_cells(reviewed)
    order = len(reviewed)
    stopped_message, statuses, sent = None, [], []
    for i, structure in enumerate(found):
        page = structure.get("slide") or structure.get("page")
        if stopped_message:
            statuses.append({"status": STOPPED, "reason": stopped_message})
            continue
        cells, _ = redact.redact_structure(structure["cells"], audit.get("company_name"), mapping,
                                           redact.withheld_values(audit))
        result = await gateway.read_structure(db, audit_id, redact.structure_text(cells), structure["type"],
                                              deck_id=deck_id, page=page, adapter=adapter, sleep=sleep)
        entry = {"status": result.status, "reason": result.reason, "key": result.key, "model_type": result.model_type,
                 "cache_hit": result.cache_hit}
        if result.status == "stopped":
            stopped_message = result.reason
        if result.status == "read":
            if not result.cache_hit:
                sent.append({"page": page, "type": structure["type"], "at": datetime.now(timezone.utc).isoformat()})
            checked = verify.verify(structure, result.items, year_end, mode)
            await gateway.record_verification(db, audit_id, result.key, [x["status"] for x in checked["items"]],
                                              checked["dropped"])
            entry["dropped"] = checked["dropped"]
            for item in checked["items"]:
                candidate = candidate_from_item(item, structure, deck, result.model_type, year_end)
                if _cell_key(candidate) in known:
                    continue                    # Python already found this value in this cell
                order += 1
                await db[CANDIDATES_COLLECTION].insert_one(
                    {**candidate, "audit_id": audit_id, "deck_id": deck_id, "file": deck["file"],
                     "id": str(uuid.uuid4()), "order": order, "status": "pending", "structure_key": result.key})
        statuses.append(entry)
    overall = STOPPED if stopped_message else READ if any(s["status"] == "read" for s in statuses) else NOT_READ
    previous = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id}, {"_id": 0, "sent": 1})
    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {
        "structures": [{**structure, "ai": status} for structure, status in zip(found, statuses)],
        "sent": list((previous or {}).get("sent") or []) + sent}})
    return await _deck_status(db, audit_id, deck_id, overall, stopped_message)


async def process_deck_safely(db, audit_id: str, deck_id: str) -> str:
    """process_deck as a background task: a failure marks the deck not read and logs the error type,
    run id and deck only (an exception message can quote a cell). The upload already returned."""
    try:
        return await process_deck(db, audit_id, deck_id)
    except Exception as exc:
        logger.error("structure reading failed: run_id=%s deck_id=%s error=%s", audit_id, deck_id, type(exc).__name__)
        try:
            return await _deck_status(db, audit_id, deck_id, NOT_READ)
        except Exception:
            return NOT_READ


async def process_waiting_decks_safely(db, audit_id: str) -> List[str]:
    """process_waiting_decks as a background task, with the same failure handling."""
    try:
        return await process_waiting_decks(db, audit_id)
    except Exception as exc:
        logger.error("structure reading failed: run_id=%s error=%s", audit_id, type(exc).__name__)
        return []


async def _deck_status(db, audit_id: str, deck_id: str, status: str, message: Optional[str] = None) -> str:
    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id},
                                         {"$set": {"ai_status": status, "ai_message": message}})
    return status


async def process_waiting_decks(db, audit_id: str, adapter=None, sleep=None) -> List[str]:
    """Read every deck that waited for the revenue file, once it is mapped. Returns their deck ids."""
    waiting = await db[TEXT_COLLECTION].find({"audit_id": audit_id, "ai_status": WAITING},
                                             {"_id": 0, "deck_id": 1}).to_list(1000)
    for d in waiting:
        await process_deck(db, audit_id, d["deck_id"], adapter=adapter, sleep=sleep)
    return [d["deck_id"] for d in waiting]


def _where(structure: Dict) -> Dict:
    return {k: structure[k] for k in ("slide", "page") if k in structure}


def _source_key(source: Dict, value):
    """A value and the cell it sits in: a table cell for Python and for a table structure, else the
    structure cell an earlier AI reading cited."""
    page = source.get("slide") or source.get("page")
    if source.get("table") is not None:
        return (page, "table", source["table"], source.get("row"), source.get("col"), value)
    if source.get("cell"):
        return (page, "structure", source.get("structure"), source["cell"], value)
    return None


def _cell_key(candidate: Dict):
    return _source_key(candidate["sources"][0], candidate.get("value"))


def _python_cells(candidates: List[Dict]) -> set:
    """The cell of every value already listed for the deck: Python's, and reviewed AI rows kept from an
    earlier upload of the same file, so a re-read adds no row twice."""
    out = set()
    for c in candidates:
        for v in claims.claim_values(c):
            for s in v.get("sources") or ():
                key = _source_key(s, v.get("value"))
                if key:
                    out.add(key)
    return out


def candidate_from_item(item: Dict, structure: Dict, deck: Dict, model_type: Optional[str], fiscal_year_end: int) -> Dict:
    """One approval-list row for a verified or suggested item, citing its source cell. The snippet is
    the value cell's own text (as the deck states it); the period keeps the text of its period cell."""
    by_id = {f"r{c['row']}c{c['col']}": c for c in structure["cells"]}
    cell = by_id.get(item["value_cell"]) or {}
    period_cells = [by_id[c]["text"] for c in item.get("period_cells") or () if c in by_id]
    label = next((h["text"] for h in verify.header_cells(structure, cell) if h["row"] == cell.get("row")), None) \
        if cell else None
    unit = item.get("unit")
    target, stated = _target_date(item.get("period")), (" ".join(period_cells) or item.get("period"))
    source = {"file": deck["file"], **_where(structure), "kind": "structure", "structure": model_type or structure["type"],
              "cell": item["value_cell"]}
    if structure.get("table") is not None:
        source.update(table=structure["table"], row=cell.get("row"), col=cell.get("col"))
    candidate = {
        "claim_type": item["metric"], "value": item.get("value"), "value_high": None,
        "unit": unit if unit in _UNITS else None, "currency": unit if unit and len(unit) == 3 and unit.isupper() else None,
        "target_date": target, "period_text": stated if target else None,
        "snippet": (cell.get("text") or "")[:claims.SNIPPET_MAX], "label_from": label if label != cell.get("text") else None,
        "date_from": stated if target and stated != cell.get("text") else None, "sources": [source],
        "inconsistent_dates": [], "origin": "ai", "cell": item["value_cell"], "ai_status": item["status"],
        "ai_label": verify.label(item["status"]),
        "ai_checks": item.get("checks"), "period_cells": list(item.get("period_cells") or []),
        "actual_or_forecast": item.get("actual_or_forecast"),
        "proposed_flags": list(item.get("proposed_flags") or []) if item["status"] == verify.VERIFIED else [],
    }
    found = claims.period_range(item.get("period"), fiscal_year_end) if item.get("period") else None
    candidate["period_start"], candidate["period_end"] = found or (None, None)
    return candidate


def _target_date(period: Optional[str]) -> Optional[str]:
    """The approval list's date for a model period: a fiscal year by the year it ends in."""
    if not period:
        return None
    m = re.fullmatch(r"FY(?:(\d{2})\d{2}/)?(\d{2}|\d{4})", period)
    if m:
        year = m.group(2)
        return (m.group(1) or "20") + year if len(year) == 2 else year
    return period


async def reverify_audit(db, audit_id: str, fiscal_year_end: int) -> int:
    """A new fiscal year-end re-runs period mapping on the model's readings too: every stored item is
    verified again under it and the open approval rows take the new label. Returns the rows changed."""
    changed = 0
    decks = await db[TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "deck_id": 1, "structures": 1}).to_list(1000)
    mode = verify.unmatched_mode()
    for deck in decks:
        for structure in deck.get("structures") or []:
            key = (structure.get("ai") or {}).get("key")
            stored = await gateway.stored_structure(db, audit_id, key) if key else None
            if not stored:
                continue
            checked = verify.verify(structure, stored["output"]["items"], fiscal_year_end, mode)
            await gateway.record_verification(db, audit_id, key, [x["status"] for x in checked["items"]],
                                              checked["dropped"])
            for item in checked["items"]:
                result = await db[CANDIDATES_COLLECTION].update_one(
                    {"audit_id": audit_id, "deck_id": deck["deck_id"], "structure_key": key, "status": "pending",
                     "cell": item["value_cell"], "claim_type": item["metric"], "value": item.get("value")},
                    {"$set": {"ai_status": item["status"], "ai_label": verify.label(item["status"]),
                              "ai_checks": item.get("checks")}})
                changed += getattr(result, "modified_count", 0)
    return changed
