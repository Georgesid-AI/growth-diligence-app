"""Model reading of deck structures and spreadsheet headers (docs/specs/llm-structure-reading.md).

The orchestration around gateway.read_structure. The deck parser finds the structures and has no
link to the gateway (CLAUDE.md rule 16); this package builds the text the model reads from them,
redacted, with the item list Python makes of every figure in it (items.py,
docs/specs/structure-labelling.md). The model labels the items; verify.py joins each label to its
item, so every value and cell is Python's, and rebuilds every period (rule 18). The gateway never
reads parsed deck text: it is handed the redacted structure text and its item list, nothing else.

What may reach the model (rule 16): redacted deck structures as extracted text with cell positions,
and spreadsheet header rows (at most 3, the 3 nearest the data) with up to 3 sample values per
numeric or date column and a profile (distinct count, typical length, shape pattern) per text
column. Only with the audit's consent. Never raw files, full pages, prose slides or a text cell
value from a spreadsheet.
"""
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




MAPPING_SAMPLE_ROWS = 20          # a column mapping is read from the first 20 data rows (chat-upload.md section 4.2)


def column_mapping_input(columns: List[str], rows: List[Dict], customer_columns: Tuple[str, ...] = (),
                         max_rows: int = MAPPING_SAMPLE_ROWS) -> Tuple[List[Dict], Dict[int, List[str]], Dict[int, Dict]]:
    """(header cells, samples, profiles) for a sheet stored as `columns` and `rows`.

    The header stack is the column names and the rows below them that hold no number other than a
    year, capped at the 3 rows nearest the data. A column whose values are numbers or dates
    (SAMPLE_SHARE of them) sends up to 3 samples; any other column, and a customer column whatever
    its values, sends a profile only. No text cell value is ever returned. Positions are the columns'
    sheet positions. Values come from the first `max_rows` data rows.
    """
    stack = [[_header_text(c) for c in columns]]
    body = list(rows)
    while body and _header_like([body[0].get(c) for c in columns]) and len(stack) < len(rows):
        stack.append([_header_text(body[0].get(c)) for c in columns])
        body = body[1:]
    body = body[:max_rows]
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


async def learn_company_names(db, audit_id: str, cells: List[Dict], company_name: Optional[str], mapping: Dict[str, str]
                              ) -> Dict[str, str]:
    """The audit's map with every company name under a company-name header in `cells` that it did not hold yet (the next Client-NN
    each, saved on the audit record). Called before a payload is masked, so no company name leaves the server under such a header."""
    swapped, _ = redact.pseudonymise_cells(cells, mapping, company_name)
    names = redact.new_company_names(swapped, company_name)
    return await llm_redaction.add_customers(db, audit_id, names) if names else mapping




FILE_TYPE_CELL_MAX = 200           # a longer title is prose: it is cut (the gateway refuses a cell over 200 characters)


def file_type_sheet(name: str, titles: List[Tuple[int, int, str]], header_row: int, headers: List[str], columns: List[str],
                    rows: List[Dict], customer_columns: Tuple[str, ...] = (), raw_headers: Optional[List[str]] = None) -> Dict:
    """One sheet as the file-type text reads it (chat-upload.md section 19): its name, the title rows nearest the header
    (at most 6 rows), the header row, and the masked sample of the column mapping (3 numbers or dates per numeric or date
    column, a profile per text column, from the first 20 rows). A wide sheet (periods across the columns) sends its header as
    written and the profile of its first column only: its other columns are the periods."""
    keep = sorted({r for r, _, _ in titles})[-redact.FILE_MAX_TITLE_ROWS:]
    cells = [{"row": r, "col": c, "text": t[:FILE_TYPE_CELL_MAX]} for r, c, t in titles if r in keep]
    shown = raw_headers if raw_headers is not None else headers
    head = [{"row": header_row, "col": c, "text": h[:FILE_TYPE_CELL_MAX]} for c, h in enumerate(shown[:redact.FILE_MAX_COLUMNS], 1) if h]
    _, samples, profiles = column_mapping_input(columns, rows, customer_columns)
    if raw_headers is not None:
        samples, profiles = {}, {1: profiles[1]} if 1 in profiles else {}
    cols = {c for c in range(1, redact.FILE_MAX_COLUMNS + 1)}
    return {"name": name[:FILE_TYPE_CELL_MAX], "titles": cells, "headers": head,
            "samples": {c: v for c, v in samples.items() if c in cols}, "profiles": {c: v for c, v in profiles.items() if c in cols}}


def file_type_text(sheets: List[Dict], company_name: Optional[str], mapping: Dict[str, str],
                   withheld: Tuple[str, ...] = (), max_sheets: int = redact.FILE_MAX_SHEETS) -> str:
    """The redacted text the model reads to tell a file's type: the sheets of file_type_sheet, each with the redaction of
    every text cell (sheet name, title rows, headers) that column mappings get. Built in memory, never stored."""
    out = []
    for sheet in sheets[:max_sheets]:
        cells, _ = redact.redact_structure(redact.file_type_cells(sheet), company_name, mapping, withheld)
        out.append({**sheet, "name": cells[0]["text"], "titles": cells[1:1 + len(sheet["titles"])],
                    "headers": cells[1 + len(sheet["titles"]):]})
    return redact.file_type_text(out)




# ---------------------------------------------------------------------------
# Decks: queue, read, verify, and results in the existing approval list (spec sections 2-4, 9)
# ---------------------------------------------------------------------------
from datetime import datetime, timezone  # noqa: E402
import logging  # noqa: E402
import uuid  # noqa: E402

from ..decks import TEXT_COLLECTION, CANDIDATES_COLLECTION  # noqa: E402
from ..decks import claims  # noqa: E402
from ..llm import gateway, prompt_store  # noqa: E402
from ..llm import redaction as llm_redaction  # noqa: E402
from . import items as structure_items  # noqa: E402
from . import verify  # noqa: E402

# A deck's AI reading status, as the deck panel shows it.
WAITING = "waiting"                 # "waiting for revenue file"
READ, NOT_READ, STOPPED, PYTHON_ONLY = "read", "not_read", "stopped", "python_only"
# Screen line S26 (George, 2026-10-22, chat-upload.md section 28): a deck uploaded with consent off lists no claim under the page read. Stored on the
# deck as its message by the page pipeline only, so the deck panel never says "no claims were extracted" under DECK_PIPELINE=rules (review of PR 164, L5).
CONSENT_OFF_LINE = ("Deck not read. AI-assisted reading is off for this audit, so no claims were extracted. "
                    "Tick consent on the Upload page to read it, or use Add claim.")
PROMPT_MISSING = "prompt_missing"       # the page reader found no deck_reading prompt in the store (review of PR 164, M6)
BLOCKED = "blocked"                     # the configured page-reader model is not on the allow-list (page-image.md section 2); nothing was sent
WAITING_TEXT = "waiting for revenue file"
logger = logging.getLogger("growth.structures")
_UNITS = {"%", "x", "days", "months", "years"}
ANALYST_ORIGINS = ("analyst", "deck_analyst")       # Add claim, Add from deck (claim-types-and-correction.md section 5)




def deck_pipeline() -> str:
    """The DECK_PIPELINE switch, owned by the gateway: "ai" (default) reads the pages (structures.pages), "rules" keeps the former
    path below (read at call time: the gateway imports this package)."""
    return gateway.deck_pipeline()


async def revenue_ready(db, audit_id: str) -> bool:
    """Whether the deck read may start: always. A deck never waits for a file to be mapped or confirmed, because there is no mapping to wait for
    (docs/design/read-check-review.md section 12, PR 4). The name stays for the callers that ask."""
    return True


CANDIDATE_KEY = ("audit_id", "deck_id", "structure_key", "order", "cell")       # what one candidate is: reading a deck again writes it once


async def store_candidate(db, row: Dict) -> None:
    """Write a candidate once: a second read of the same deck (the upload's task and Run audit's, or the settle step) that reaches the same
    page reply, order and cell finds the row there and leaves it alone (live bug, 2026-10-28: two stored copies, identical but for the id)."""
    key = {k: row.get(k) for k in CANDIDATE_KEY}
    await db[CANDIDATES_COLLECTION].update_one(key, {"$setOnInsert": {k: v for k, v in row.items() if k not in key}}, upsert=True)


async def process_deck(db, audit_id: str, deck_id: str, adapter=None, sleep=None) -> str:
    """Read one deck's structures with the model, or queue them; returns the deck's AI status.

    Unticked consent: the Python-only path, no call. Ticked but the revenue file not yet mapped: the
    deck waits ("waiting for revenue file"), so no customer name goes out unmapped. Otherwise each
    structure is redacted, sent through gateway.read_structure, verified against its source cells,
    and every item becomes a row of the approval list labelled Verified or "AI suggestion, not
    verified". A deck already read is not sent again (a re-read is served from the cache).
    """
    from . import pages as page_pipeline
    if deck_pipeline() == "ai":
        # The default since 2026-10-22 (docs/design/ai-reads-rules-check.md): the model reads the pages, Python checks each claim.
        return await page_pipeline.process_deck_pages(db, audit_id, deck_id, adapter=adapter, sleep=sleep)
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0, "id": 1, "company_name": 1, "fiscal_year_end": 1,
                                                       "structure_reading_consent": 1})
    deck = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id},
                                              {"_id": 0, "structures": 1, "file": 1, "page_unit": 1, "blocks": 1})
    if not audit or not deck:
        return NOT_READ
    found = deck.get("structures") or []
    if audit.get("structure_reading_consent") is not True:
        return await _deck_status(db, audit_id, deck_id, PYTHON_ONLY)
    if not await revenue_ready(db, audit_id):
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
        mapping = await learn_company_names(db, audit_id, structure["cells"], audit.get("company_name"), mapping)
        cells, _ = redact.redact_structure(structure["cells"], audit.get("company_name"), mapping, deck=True)
        redacted = {**structure, "cells": cells}
        listed = structure_items.list_items(redacted)
        result = await gateway.read_structure(db, audit_id, structure_items.text(redacted, listed), structure["type"],
                                              deck_id=deck_id, page=page, adapter=adapter, sleep=sleep)
        entry = {"status": result.status, "reason": result.reason, "key": result.key, "model_type": result.model_type,
                 "cache_hit": result.cache_hit}
        if result.status == "stopped":
            stopped_message = result.reason
        if result.status == "read":
            if not result.cache_hit:
                sent.append({"page": page, "type": structure["type"], "at": datetime.now(timezone.utc).isoformat()})
            checked = verify.verify(structure, listed, result.labels, result.pairs, year_end, mode)
            await gateway.record_verification(db, audit_id, result.key, [x["status"] for x in checked["items"]],
                                              checked["dropped"], checked["periods_corrected"],
                                              structure_items.stored(listed))
            entry.update({k: checked[k] for k in ("dropped", "periods_corrected", "not_a_metric")})
            for item in approval_items(checked["items"], mode):
                candidate = candidate_from_item(item, structure, deck, result.model_type, year_end)
                if value_match(candidate["value"], candidate["value_high"], known.get(_cell_key(candidate), ())):
                    continue                    # this cell already lists the value, or a range holding it
                twin = next((c for c in reviewed if claims.same_claim(c, candidate)), None)
                if twin is not None:
                    # Read twice, by the parser and by the model: one row listing both sources (deck-parser.md section 2).
                    if candidate["sources"][0] not in twin["sources"]:
                        twin["sources"] = list(twin["sources"]) + candidate["sources"]
                        await db[CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": twin["id"]},
                                                                   {"$set": {"sources": twin["sources"]}})
                    continue
                duplicate = rules_copy(reviewed, candidate)
                if duplicate is not None:
                    # The same figure read by the parser with another period (issue #154): one figure, one row. The row of the
                    # panel read keeps its period, takes the copy's place and cites its sources too.
                    candidate = {**candidate, "sources": candidate["sources"] + [s for s in duplicate["sources"] if s not in candidate["sources"]]}
                    await db[CANDIDATES_COLLECTION].delete_one({"audit_id": audit_id, "id": duplicate["id"]})
                    reviewed.remove(duplicate)
                    row_order = duplicate.get("order", order + 1)
                else:
                    row_order = order = order + 1
                row = {**candidate, "audit_id": audit_id, "deck_id": deck_id, "file": deck["file"],
                       "id": str(uuid.uuid4()), "order": row_order, "status": "pending", "structure_key": result.key}
                await store_candidate(db, row)
                reviewed.append(row)
        statuses.append(entry)
    overall = STOPPED if stopped_message else READ if any(s["status"] == "read" for s in statuses) else NOT_READ
    previous = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id}, {"_id": 0, "sent": 1})
    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {
        "structures": [{**structure, "ai": status} for structure, status in zip(found, statuses)],
        "periods_corrected": sum(s.get("periods_corrected", 0) for s in statuses),
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




async def _deck_status(db, audit_id: str, deck_id: str, status: str, message: Optional[str] = None) -> str:
    change = {"$set": {"ai_status": status, "ai_message": message}}
    if status == "reading":
        change["$unset"] = {"read_progress": ""}        # a new read starts at "queued", not at the page the last one reached
        change["$set"]["reading_since"] = datetime.now(timezone.utc).isoformat()
    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, change)
    return status


STALE_READING_SECONDS = 600     # a deck "reading" for longer is taken as not read: the process that read it died (George, 2026-10-23)
RESTARTED = "restarted"         # the deck's ai_message after such a restart; the panel shows "AI read: restarted" until the first page is read


STALE = "stale"          # a page read whose stored rows an earlier check wrote wrongly: Run audit reads it again (the cache serves the reply)




async def queue_stale_reading(db, audit_id: str, now: Optional[datetime] = None) -> List[str]:
    """Run audit reads again, with no new upload, every deck "reading" since more than STALE_READING_SECONDS (a read that never ended:
    the server restarted, the task died): marks it "reading" again with the message "restarted" and returns the ids, for the caller to
    read. The start is the deck's `reading_since`, else its upload time; a deck with neither is left alone. Pages read are kept."""
    now = now or datetime.now(timezone.utc)
    found = await db[TEXT_COLLECTION].find({"audit_id": audit_id, "ai_status": "reading"},
                                           {"_id": 0, "deck_id": 1, "reading_since": 1, "uploaded_at": 1}).to_list(1000)
    stale = []
    for d in found:
        try:
            since = datetime.fromisoformat(d.get("reading_since") or d.get("uploaded_at") or "")
        except ValueError:
            continue
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        if (now - since).total_seconds() > STALE_READING_SECONDS:
            stale.append(d["deck_id"])
    for deck_id in stale:
        await _deck_status(db, audit_id, deck_id, "reading", RESTARTED)
    return stale


async def queue_decks(db, audit_id: str) -> List[str]:
    """Mark every deck of the audit that is not being read as "reading" and return their ids, for the caller to read
    (consent ticked after the upload, chat-upload.md section 23). A deck already being read is not queued twice."""
    found = await db[TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "deck_id": 1, "ai_status": 1}).to_list(1000)
    queued = [d["deck_id"] for d in found if d.get("ai_status") != "reading"]
    for deck_id in queued:
        await _deck_status(db, audit_id, deck_id, "reading")
    return queued


async def queue_prompt_missing(db, audit_id: str) -> List[str]:
    """Run audit reads again, with no new upload, every deck the page reader could not read for want of the deck_reading prompt, once the
    store holds it (George, 2026-10-23, M6): marks them "reading" and returns their ids, for the caller to read. A deck already being
    read is not queued twice; while the prompt is missing nothing is queued."""
    found = await db[TEXT_COLLECTION].find({"audit_id": audit_id, "ai_status": PROMPT_MISSING}, {"_id": 0, "deck_id": 1}).to_list(1000)
    if not found:
        return []
    try:
        await prompt_store.load(db, gateway.PAGE_CLAIMS_PROMPT)
    except prompt_store.PromptMissing:
        return []
    for d in found:
        await _deck_status(db, audit_id, d["deck_id"], "reading")
    return [d["deck_id"] for d in found]


async def queue_blocked(db, audit_id: str) -> List[str]:
    """Run audit reads again every deck whose page read was blocked (the page-reader model was not permitted) once the configured model
    is on the allow-list. While it is not, nothing is queued."""
    found = await db[TEXT_COLLECTION].find({"audit_id": audit_id, "ai_status": BLOCKED}, {"_id": 0, "deck_id": 1}).to_list(1000)
    if not found or gateway.page_reader_problem():
        return []
    for d in found:
        await _deck_status(db, audit_id, d["deck_id"], "reading")
    return [d["deck_id"] for d in found]


async def queue_waiting(db, audit_id: str) -> List[str]:
    """Run audit reads again every deck still waiting for the revenue file once the audit has it (George, 2026-10-23, PR 164 follow-up,
    decision 2c): marks them "reading" and returns their ids, for the caller to read. While the revenue file is missing nothing is queued."""
    found = await db[TEXT_COLLECTION].find({"audit_id": audit_id, "ai_status": WAITING}, {"_id": 0, "deck_id": 1}).to_list(1000)
    if not found or not await revenue_ready(db, audit_id):
        return []
    for d in found:
        await _deck_status(db, audit_id, d["deck_id"], "reading")
    return [d["deck_id"] for d in found]


async def queue_unread_pages(db, audit_id: str) -> List[str]:
    """Run audit reads again, with no new upload, the pages of a deck a failure left unread (a timeout, an error; George, 2026-10-23,
    deck page reads): marks such decks "reading" and returns their ids, for the caller to read. process_deck_pages asks the model
    only for those pages. A deck being read, waiting for the revenue file or missing the prompt is not queued here."""
    found = [d for d in await db[TEXT_COLLECTION].find({"audit_id": audit_id, "ai_status": {"$in": [READ, NOT_READ, STOPPED]}},
                                                       {"_id": 0, "deck_id": 1, "retry_pages": 1}).to_list(1000) if d.get("retry_pages")]
    for d in found:
        await _deck_status(db, audit_id, d["deck_id"], "reading")
    return [d["deck_id"] for d in found]




def _where(structure: Dict) -> Dict:
    return {k: structure[k] for k in ("slide", "page") if k in structure}


def _source_key(source: Dict):
    """The cell a value sits in: a table cell for Python and for a table structure, else the structure cell an
    earlier AI reading cited."""
    page = source.get("slide") or source.get("page")
    if source.get("table") is not None:
        return (page, "table", source["table"], source.get("row"), source.get("col"))
    if source.get("cell"):
        return (page, "structure", source.get("structure"), source["cell"])
    return None


def _cell_key(candidate: Dict):
    return _source_key(candidate["sources"][0])


def _python_cells(candidates: List[Dict]) -> Dict:
    """{cell: [(value, value_high), ...]}: every value already listed for the deck, by its cell: Python's, and
    reviewed AI rows kept from an earlier upload of the same file, so a re-read adds no row twice."""
    out = {}
    for c in candidates:
        for v in claims.claim_values(c):
            for s in v.get("sources") or ():
                key = _source_key(s)
                if key:
                    out.setdefault(key, []).append((v.get("value"), v.get("value_high")))
    return out


def value_match(value, value_high, known) -> Optional[str]:
    """How a row's value meets the values its cell already lists (decision of 2026-10-06): "exact" for the same
    value or the same range, "in range" when one falls inside the other's range (12.5m in "12-13m", or the range
    holding a value the cell lists), else None. Either match means the row is already listed."""
    def inside(x, low, high):
        return x is not None and low is not None and high is not None and min(low, high) <= x <= max(low, high)
    found = None
    for low, high in known:
        if (low, high) == (value, value_high):
            return "exact"
        if value is not None and (inside(value, low, high) and (value_high is None or inside(value_high, low, high))
                                  or (value_high is not None and inside(low, value, value_high) and high is None)):
            found = "in range"
    return found


def approval_items(checked: List[Dict], mode: str = "suggest") -> List[Dict]:
    """The checked items as approval rows. A range's two items (items.list_items) make one row from its first
    labelled end, its value the low end and value_high the high end, Verified only when both ends are labelled
    with the same metric and Verified; the other end makes no row. With mode "drop" an unverified range row goes
    too."""
    by_id = {c["item"]: c for c in checked if c.get("range")}
    out, done = [], set()
    for c in checked:
        span = c.get("range")
        if not span:
            out.append(c)
            continue
        if c["item"] in done:
            continue
        done.update(span["items"])
        ends = [by_id[i] for i in span["items"] if i in by_id]
        ok = len(ends) == 2 and ends[0]["metric"] == ends[1]["metric"] and \
            all(e["status"] == verify.VERIFIED for e in ends)
        if ok or mode != "drop":
            out.append({**ends[0], "value": span["low"], "value_high": span["high"], "values": [],
                        "status": verify.VERIFIED if ok else verify.SUGGESTION})
    return out


def _same_figure(c: Dict, candidate: Dict) -> bool:
    """Whether row `c` states the figure of `candidate` on the same page: the same value, currency and kind of unit, the same type or one
    of them unknown. The period is not compared."""
    return bool(c.get("sources") and _page_of(c["sources"][0]) == _page_of(candidate["sources"][0])
                and (c["value"], c["value_high"]) == (candidate["value"], candidate["value_high"])
                and (c.get("currency") or None) == (candidate.get("currency") or None)
                and ((c.get("unit") in ("%", "x")) or (candidate.get("unit") in ("%", "x"))) <= (c.get("unit") == candidate.get("unit"))
                and (c["claim_type"] == candidate["claim_type"] or claims.UNKNOWN in (c["claim_type"], candidate["claim_type"])))


def rules_copy(reviewed: List[Dict], candidate: Dict) -> Optional[Dict]:
    """The row of the parser that reads again the figure of a panel-read `candidate` (issue #154): on the same page, the same value, currency
    and kind of unit, the same type or one of them unknown, and not yet touched by the analyst. Its period may differ (a year taken from
    elsewhere on the page); the panel read, which places the figure in its cell, decides it. None when there is no such row, or two.
    Only a parser row (no origin) is a copy: a claim the analyst added, by hand or from the deck, is never replaced (review of PR 164, M5)."""
    same = [c for c in reviewed if c.get("origin") is None and c.get("status") == "pending" and _same_figure(c, candidate)]
    return same[0] if len(same) == 1 else None


def analyst_copy(reviewed: List[Dict], candidate: Dict) -> Optional[Dict]:
    """The claim the analyst added (Add claim, Add from deck) that states the figure of a model-read `candidate` on the same page, whatever
    its period and status but rejected. The candidate is listed beside it with the flag "matches analyst claim", never in its place
    (George, 2026-10-23, review of PR 164, M5)."""
    return next((c for c in reviewed if c.get("origin") in ANALYST_ORIGINS and c.get("status") != "rejected" and _same_figure(c, candidate)), None)


def _page_of(source: Dict):
    return (source.get("slide"), source.get("page"))


def candidate_from_item(item: Dict, structure: Dict, deck: Dict, model_type: Optional[str], fiscal_year_end: int) -> Dict:
    """One approval-list row for a verified or suggested item, citing its source cell (the cell id, as before;
    the figure's position in it rides beside). The snippet is the cell's own text (as the deck states it); the
    period keeps the text of its period cells. An ambiguous figure carries both readings, Python's default first
    and the row's value (structure-labelling.md section 1): the analyst confirms it or uses Edit. The source
    names the type Python sent: a type the model corrected is only logged (`model_type` is not used). "Label
    from" is a header cell in the row's grid row; in a roadmap only one of its own text box, since the cells
    beside it belong to other boxes, such as the neighbouring paragraph (structure-labelling.md section 2)."""
    by_id = {f"r{c['row']}c{c['col']}": c for c in structure["cells"]}
    cell = by_id.get(item["value_cell"]) or {}
    period_cells = [by_id[c]["text"] for c in item.get("period_cells") or () if c in by_id]
    label = next((h["text"] for h in verify.header_cells(structure, cell) if h["row"] == cell.get("row")
                  and (structure.get("type") != "roadmap" or h.get("box") == cell.get("box"))), None) if cell else None
    unit = item.get("unit_other") if item.get("unit") == "other" else item.get("unit")   # "other": the ISO code
    target, stated = _target_date(item.get("period")), (" ".join(period_cells) or item.get("period"))
    source = {"file": deck["file"], **_where(structure), "kind": "structure", "structure": structure["type"],
              "cell": item["value_cell"]}
    if structure.get("table") is not None:
        source.update(table=structure["table"], row=cell.get("row"), col=cell.get("col"))
    candidate = {
        "claim_type": item["metric"], "value": item.get("value"), "value_high": item.get("value_high"),
        "unit": unit if unit in _UNITS else None, "currency": unit if unit and len(unit) == 3 and unit.isupper() else None,
        "target_date": target, "period_text": stated if target else None,
        "snippet": (cell.get("text") or "")[:claims.SNIPPET_MAX], "label_from": label if label != cell.get("text") else None,
        "date_from": stated if target and stated != cell.get("text") else None, "sources": [source],
        "inconsistent_dates": [], "origin": "ai", "cell": item["value_cell"], "position": item.get("position"),
        "item": item.get("item"), "readings": item["values"] if len(item.get("values") or ()) > 1 else [],
        "type_from": "heading" if label and label != cell.get("text") else
                     "line" if claims._keywords(cell.get("text") or "") else None,
        "reading": _reading(deck.get("blocks") or (), structure, cell),
        "ai_status": item["status"],
        "ai_label": verify.label(item["status"]),
        "ai_checks": item.get("checks"), "period_cells": list(item.get("period_cells") or []),
        "actual_or_forecast": item.get("actual_or_forecast"),
        "proposed_flags": list(item.get("proposed_flags") or []) if item["status"] == verify.VERIFIED else [],
    }
    claims.recurring_year_end(candidate)             # "MRR in 2021" is Dec 2021 (issue #151)
    found = claims.period_range(candidate["target_date"], fiscal_year_end) if candidate.get("period_read_note") else \
        claims.period_range(item.get("period"), fiscal_year_end) if item.get("period") else None
    candidate["period_start"], candidate["period_end"] = found or (None, None)
    if candidate["claim_type"] == "customers":
        # A qualified customers noun in the row's header or the figure's own cell is Users, as the parser reads it
        # (deck-parser.md section 2, George, 2026-10-13): "Registered Institutions" are not paying customers.
        qualifier = claims.qualifier_of(label or "") or claims.qualifier_of(cell.get("text") or "")
        if qualifier:
            candidate.update(claim_type="users", qualifier=qualifier)
    return candidate


def _reading(blocks, structure: Dict, cell: Dict) -> Optional[List[float]]:
    """[top, left] of a cell's text on its page, from the deck's parsed lines (the reading order of the approval list);
    None when the page has no layout or the line is not found."""
    page = {k: structure[k] for k in ("slide", "page") if structure.get(k) is not None}
    text = cell.get("text") or ""
    for b in blocks:
        if not b.get("bbox") or any(b.get(k) != v for k, v in page.items()):
            continue
        if structure.get("table") is not None:
            same = b.get("kind") == "table" and (b.get("table"), b.get("row"), b.get("col")) == \
                (structure["table"], cell.get("row"), cell.get("col"))
        else:
            same = b.get("kind") == "text" and bool(text) and text.startswith(b["text"])
        if same:
            return [round(b["bbox"][1], 3), round(b["bbox"][0], 3)]
    return None


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
    """A new fiscal year-end re-runs period mapping on the model's readings too: every stored reading is
    verified again under it, from its stored labels and item list, and the open approval rows take the new
    label. A reading stored under v2 holds no labels or item list: it is skipped and its rows keep their
    labels (structure-labelling.md section 5). Returns the rows changed."""
    changed = 0
    decks = await db[TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "deck_id": 1, "structures": 1}).to_list(1000)
    mode = verify.unmatched_mode()
    for deck in decks:
        # The model's periods are corrected again under the new year-end; the counts follow.
        found = deck.get("structures") or []
        for structure in found:
            key = (structure.get("ai") or {}).get("key")
            stored = await gateway.stored_structure(db, audit_id, key) if key else None
            if not stored or "labels" not in (stored.get("output") or {}) or not stored.get("items"):
                continue
            output = stored["output"]
            checked = verify.verify(structure, stored["items"], output["labels"], output.get("pairs") or [],
                                    fiscal_year_end, mode)
            await gateway.record_verification(db, audit_id, key, [x["status"] for x in checked["items"]],
                                              checked["dropped"], checked["periods_corrected"])
            structure["ai"] = {**structure["ai"], "periods_corrected": checked["periods_corrected"]}
            for item in approval_items(checked["items"], mode):
                result = await db[CANDIDATES_COLLECTION].update_one(
                    {"audit_id": audit_id, "deck_id": deck["deck_id"], "structure_key": key, "status": "pending",
                     "item": item["item"]},
                    {"$set": {"ai_status": item["status"], "ai_label": verify.label(item["status"]),
                              "ai_checks": item.get("checks")}})
                changed += getattr(result, "modified_count", 0)
        if found:
            await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck["deck_id"]}, {"$set": {
                "structures": found,
                "periods_corrected": sum((s.get("ai") or {}).get("periods_corrected", 0) for s in found)}})
    return changed
