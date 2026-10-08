from fastapi import BackgroundTasks, Body, FastAPI, APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, Response, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import csv
import re
import asyncio
import hashlib
import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

import growth_engine as ge
import demo_data
from schemas import metrics as contract
from app import formatting as fmt
from app import disclosure as disclosure_mod
from app import narrative_export
from app import claim_matching
from app import ic_memo
from app import verdict as verdict_mod
from app import decks
from app import structures
from app import column_rules as cr
from app import usage as usage_mod
from app.decks import claims as deck_claims
from app.decks import parser as deck_parser
from app.llm import gateway as llm_gateway
from app.llm import redaction as llm_redaction

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="Growth Diligence Engine")
api = APIRouter(prefix="/api")
from app.logsafety import install_secret_redaction

install_secret_redaction()      # no key can reach a log line, message or traceback
logger = logging.getLogger("growth")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Dataset field definitions (normalized names + fuzzy-match aliases): app/column_rules.py
# ---------------------------------------------------------------------------
FIELD_DEFS = cr.FIELD_DEFS
_score = cr._score


def suggest_mapping(dtype: str, columns: list) -> dict:
    return cr.suggest_mapping(dtype, columns)


def parse_file(content: bytes, filename: str):
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content))
        sheet = "CSV"
    elif filename.lower().endswith((".xlsx", ".xls")):
        xls = pd.ExcelFile(io.BytesIO(content))
        sheet = xls.sheet_names[0]
        df = xls.parse(sheet)
    else:
        raise HTTPException(400, "Only .xlsx and .csv files are supported")
    df.columns = [str(c) for c in df.columns]
    return df, sheet


def df_to_records(df: pd.DataFrame):
    d = df.astype(object).where(pd.notnull(df), None)
    recs = d.to_dict("records")
    for r in recs:
        for k, v in r.items():
            if isinstance(v, (pd.Timestamp, datetime)):
                r[k] = v.isoformat()
            elif isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
                r[k] = None
    return recs


def normalize(rows: list, dtype: str, mapping: dict, row_numbers: Optional[list] = None) -> pd.DataFrame:
    """The stored rows read through a mapping. `_row` is the row's number in the sheet it came from
    (`row_numbers`, kept at upload); without it the header is taken to be row 1 with no blank lines."""
    if not rows:
        return pd.DataFrame()
    raw = pd.DataFrame(rows)
    defs = FIELD_DEFS[dtype]
    out = pd.DataFrame()
    out["_row"] = list(row_numbers) if row_numbers is not None and len(row_numbers) == len(raw) else range(2, len(raw) + 2)
    for field, col in mapping.items():
        if col and col in raw.columns:
            out[field] = raw[col].values
    date_formats = {}
    for f in defs["dates"]:
        if f in out.columns:
            out[f], date_formats[f] = parse_date_column(out[f])
            if date_formats[f] and date_formats[f]["order"] is None:
                date_formats[f]["row_ids"] = out.loc[date_formats[f].pop("index"), "_row"].tolist()
    for f in defs["numeric"]:
        if f in out.columns:
            out[f] = pd.to_numeric(out[f], errors="coerce")
    out.attrs["date_formats"] = {f: v for f, v in date_formats.items() if v}
    return out


# 03/04/2024, 3.4.24, 03-04-2024 (+ optional time): day and month in either order.
_DM_DATE = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?:[ T].*)?$")


def parse_date_column(col: pd.Series):
    """(dates, finding) for one mapped date column.

    Never guesses day/month order. A value whose first part is above 12 proves
    day-first for the whole column; a second part above 12 proves month-first. With
    no such value the order is unknown: those rows stay unread (NaT) and the finding
    asks for the format. ISO and other unambiguous values parse as before.
    finding is None, {"order": "DD/MM/YYYY"|"MM/DD/YYYY", "rows": n} or
    {"order": None, "rows": n, "reason": ..., "index": [unread row index, ...]}.
    """
    parts = {i: m.groups() for i, v in col.items() if isinstance(v, str) and (m := _DM_DATE.match(v))}
    rest = col.drop(index=list(parts))
    out = pd.Series(pd.NaT, index=col.index, dtype="datetime64[ns]")
    if len(rest):
        out.loc[rest.index] = pd.to_datetime(rest, errors="coerce")
    if not parts:
        return out, None
    day_first = any(int(a) > 12 for a, _, _ in parts.values())
    month_first = any(int(b) > 12 for _, b, _ in parts.values())
    if day_first == month_first:
        why = "mixes day-first and month-first dates" if day_first else "has no day above 12"
        return out, {"order": None, "rows": len(parts), "reason": why, "index": list(parts)}
    for i, (a, b, y) in parts.items():
        d, m = (a, b) if day_first else (b, a)
        try:
            out.loc[i] = pd.Timestamp(int(y) + (2000 if len(y) == 2 else 0), int(m), int(d))
        except ValueError:
            pass  # e.g. 31/02/2024: unreadable, stays NaT
    return out, {"order": "DD/MM/YYYY" if day_first else "MM/DD/YYYY", "rows": len(parts)}


def candidate_views(datasets: dict) -> dict:
    """Every upload read as every dataset type, for the engine's can_compute.

    A file's own type is read through its current mapping; the other types through the
    column aliases in FIELD_DEFS. `datasets` maps dtype -> {file, sheet, columns, rows, mapping}.
    """
    files = {}
    for dtype, d in datasets.items():
        views = {}
        for as_type in FIELD_DEFS:
            mapping = (d.get("mapping") or {}) if as_type == dtype else suggest_mapping(as_type, d.get("columns") or [])
            mapping = {f: c for f, c in mapping.items() if c}
            views[as_type] = {"mapping": mapping, "frame": normalize(d.get("rows") or [], as_type, mapping, d.get("row_numbers"))}
        files[dtype] = {"file": d.get("file"), "sheet": d.get("sheet"), "views": views}
    return files


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
def _validate_target_date(v: Optional[str]) -> Optional[str]:
    """Year must be a plausible 2000–2100; catches "0027"-style typos before they
    ever reach the engine and produce an absurd Path-to-Plan calculation."""
    if not v:
        return v
    try:
        dt = datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        dt = None
    if dt is None or dt.strftime("%Y-%m-%d") != v:  # strptime alone takes 2027-1-5
        raise ValueError("target_date must be in YYYY-MM-DD format")
    if not (2000 <= dt.year <= 2100):
        raise ValueError(f"target_date year must be between 2000 and 2100, got {dt.year}")
    return v


def _validate_as_of_month(v: Optional[str]) -> Optional[str]:
    """ISO only: YYYY-MM-DD from the date picker, or YYYY-MM as older audits stored it.
    "30/06/2026" or "06/07/2026" is refused, never guessed: day/month order depends on locale."""
    if not v:
        return v
    for f in ("%Y-%m-%d", "%Y-%m"):
        try:
            dt = datetime.strptime(v, f)
        except ValueError:
            continue
        if dt.strftime(f) == v and 2000 <= dt.year <= 2100:
            return v
    raise ValueError("as_of_month must be an ISO date (YYYY-MM-DD) with a year between 2000 and 2100")


def _required_text(v: Optional[str]) -> Optional[str]:
    """A required name or reference: trimmed, and never blank."""
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError("must not be empty")
    return v


class AuditCreate(BaseModel):
    company_name: str                       # the target company
    reporting_currency: str = "EUR"
    target_arr: float = 0
    target_date: Optional[str] = None
    as_of_month: Optional[str] = None
    # The month the company's fiscal year ends in (deck-parser.md section 2). FY25 is the fiscal year
    # that ends in 2025; with December it is the calendar year.
    fiscal_year_end: int = Field(default=12, ge=1, le=12)
    # The investor commissioning the audit; the name never reaches the model.
    client_name: str
    structure_reading_consent: bool = True

    _check_target_date = field_validator("target_date")(_validate_target_date)
    _check_as_of_month = field_validator("as_of_month")(_validate_as_of_month)
    _check_required = field_validator("client_name")(_required_text)


class AuditUpdate(BaseModel):
    company_name: Optional[str] = None
    reporting_currency: Optional[str] = None
    target_arr: Optional[float] = None
    target_date: Optional[str] = None
    as_of_month: Optional[str] = None
    fiscal_year_end: Optional[int] = Field(default=None, ge=1, le=12)
    client_name: Optional[str] = None
    structure_reading_consent: Optional[bool] = None

    _check_target_date = field_validator("target_date")(_validate_target_date)
    _check_as_of_month = field_validator("as_of_month")(_validate_as_of_month)
    _check_required = field_validator("client_name")(_required_text)


def _consent_entry(value: bool) -> dict:
    """One change of the consent checkbox, with its time. The user is added when accounts exist."""
    return {"value": bool(value), "at": datetime.now(timezone.utc).isoformat()}


class MappingPayload(BaseModel):
    mapping: Optional[dict] = None          # omitted: the FX rates and billing terms only; the mapping is decided column by column
    fx: dict = Field(default_factory=dict)
    billing_terms: dict = Field(default_factory=dict)


def sanitize(obj):
    """Recursively replace non-finite floats (NaN/Inf) with None for valid JSON."""
    import math
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj


async def audit_public(a: dict) -> dict:
    a.pop("_id", None)
    a.pop("usage", None)          # the counters, notes included, are read only through the usage totals
    ds = await db.datasets.find({"audit_id": a["id"]}, {"rows": 0, "_id": 0}).to_list(10)
    a["datasets"] = {
        d["dtype"]: {k: d.get(k) for k in ("file", "sheet", "columns", "mapping", "fx", "billing_terms", "preview", "row_count",
                                           "mapping_source", "ai_reading")}
        for d in ds
    }
    return sanitize(a)


# ---------------------------------------------------------------------------
# Audit CRUD
# ---------------------------------------------------------------------------
@api.get("/")
async def root():
    return {"service": "growth-diligence", "status": "ok"}


@api.post("/audits")
async def create_audit(payload: AuditCreate):
    audit = {
        "id": str(uuid.uuid4()),
        "company_name": payload.company_name,
        "reporting_currency": payload.reporting_currency,
        "target_arr": payload.target_arr,
        "target_date": payload.target_date,
        "as_of_month": payload.as_of_month,
        "fiscal_year_end": payload.fiscal_year_end,
        "client_name": payload.client_name,
        "structure_reading_consent": payload.structure_reading_consent,
        "consent_log": [_consent_entry(payload.structure_reading_consent)],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "draft",
        "results": None,
        "metrics_stale": False,
    }
    await db.audits.insert_one({**audit, "usage": usage_mod.empty()})
    return audit


@api.get("/audits")
async def list_audits():
    return await db.audits.find({}, {"_id": 0, "results": 0, "usage": 0}).sort("created_at", -1).to_list(200)


@api.get("/audits/{audit_id}")
async def get_audit(audit_id: str):
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    return await audit_public(a)


@api.put("/audits/{audit_id}")
async def update_audit(audit_id: str, payload: AuditUpdate):
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    consent = updates.get("structure_reading_consent")
    if consent is not None and consent != (a.get("structure_reading_consent") is True):
        await db.audits.update_one({"id": audit_id},
                                   {"$set": {"consent_log": list(a.get("consent_log") or []) + [_consent_entry(consent)]}})
    if updates:
        await db.audits.update_one({"id": audit_id}, {"$set": updates})
        if RECOMPUTE_TRIGGER_FIELDS & updates.keys():
            await _mark_stale_and_maybe_recompute(audit_id)
        if "fiscal_year_end" in updates and updates["fiscal_year_end"] != _fiscal_year_end(a):
            await _remap_periods(audit_id, updates["fiscal_year_end"])
    return await audit_public(await db.audits.find_one({"id": audit_id}))


def _fiscal_year_end(audit: Optional[dict]) -> int:
    """The audit's fiscal year-end month; audits created before the field existed end in December."""
    return int((audit or {}).get("fiscal_year_end") or 12)


async def _remap_periods(audit_id: str, fiscal_year_end: int) -> None:
    """A new fiscal year-end re-runs period mapping: every stored claim's date range moves, its stated
    period and target date stay (deck-parser.md section 2)."""
    found = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id}, {"_id": 0}).to_list(10000)
    for c in deck_claims.remap_periods(found, fiscal_year_end):
        changes = {k: c.get(k) for k in ("period_start", "period_end", "by_period") if k in c}
        await db[decks.CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": c["id"]}, {"$set": changes})
    # The model's readings are verified again: a period counted from a stated start date ("Year 1"
    # from "Start: Jan 2025") matches a year label only under the year-end it falls in.
    await structures.reverify_audit(db, audit_id, fiscal_year_end)


class DeleteConfirm(BaseModel):
    confirm: str = ""


@api.delete("/audits/{audit_id}")
async def delete_audit(audit_id: str, payload: Optional[DeleteConfirm] = Body(default=None)):
    """Delete the audit and every document of it in every collection (CLAUDE.md rule 22). The company name
    goes in the body, never the URL, so no access log holds it; it is matched after trimming leading and trailing whitespace,
    exactly and case-sensitively, as the dialog does. A wrong or missing name deletes nothing."""
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    typed = ((payload.confirm if payload else "") or "").strip()
    if not typed or typed != str(a.get("company_name") or "").strip():
        raise HTTPException(400, "Type the company name to delete this audit")
    await db.audits.delete_one({"id": audit_id})
    await db.datasets.delete_many({"audit_id": audit_id})
    # Parsed deck text and claim candidates belong to the audit and go with it.
    deck_text = await db[decks.TEXT_COLLECTION].delete_many({"audit_id": audit_id})
    deck_candidates = await db[decks.CANDIDATES_COLLECTION].delete_many({"audit_id": audit_id})
    # Narratives, call log and pseudonym mapping are scoped to the run and must
    # not outlive it.
    purged = await llm_gateway.purge_run(db, audit_id)
    corrections = await db[structures.COLUMN_MAPPINGS_COLLECTION].delete_many({"audit_id": audit_id})
    purged["column_mappings"] = corrections.deleted_count
    return {"deleted": audit_id, "llm_purged": purged,
            "decks_purged": {"deck_text": deck_text.deleted_count, "deck_candidates": deck_candidates.deleted_count}}


# ---------------------------------------------------------------------------
# Usage counters (docs/specs/chat-upload.md section 7): counts and codes, no file name, value or company name
# ---------------------------------------------------------------------------
async def _usage_update(audit_id: str, change) -> None:
    """Read the audit's counters, apply `change(usage)`, write them back."""
    a = await db.audits.find_one({"id": audit_id}, {"id": 1, "usage": 1})
    if not a:
        return
    counters = usage_mod.get(a)
    change(counters)
    await db.audits.update_one({"id": audit_id}, {"$set": {"usage": counters}})


class UsageEvent(BaseModel):
    """What the browser reports: the screen it is on, or the extension of a file it refused."""
    model_config = {"extra": "forbid"}
    screen: Optional[Literal["mapping", "dashboard", "diagnostics"]] = None
    rejected_extension: Optional[str] = Field(default=None, max_length=12)


@api.post("/audits/{audit_id}/usage")
async def report_usage(audit_id: str, event: UsageEvent):
    if not await db.audits.find_one({"id": audit_id}, {"id": 1}):
        raise HTTPException(404, "Audit not found")

    def change(u):
        if event.screen:
            u["last_screen"] = event.screen
        if event.rejected_extension is not None:
            usage_mod.record_rejected(u, usage_mod.extension_of("x." + event.rejected_extension.lower().lstrip(".")))
    await _usage_update(audit_id, change)
    return {"ok": True}


@api.get("/usage/totals")
async def usage_totals():
    """Sums across audits, the median days from first upload to first export and the 50 newest "Other" notes. No
    per-audit rows, names or ids (chat-upload.md section 7). Tokens and cost come from the call log; evidence
    labels and analyst changes are computed on read from what the audits hold."""
    audits = await db.audits.find({}, {"_id": 0}).to_list(100000)
    calls = await db[llm_gateway.CALLS_COLLECTION].find({}, {"_id": 0}).to_list(1000000)
    steps: dict = {}
    for c in calls:
        step = steps.setdefault(str(c.get("step") or "other"), {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        step["calls"] += 0 if c.get("cache_hit") else 1
        step["input_tokens"] += int(c.get("input_tokens", 0))
        step["output_tokens"] += int(c.get("output_tokens", 0))
        step["cost_usd"] = round(step["cost_usd"] + float(c.get("estimated_cost_usd", 0.0)), 6)
    labels, missing, changes = {}, 0, 0
    for a in audits:
        _, rows = await _claim_rows(a["id"], a)
        for label, n in claim_matching.label_counts(rows).items():
            labels[label] = labels.get(label, 0) + n
        missing += len((a.get("results") or {}).get("missing_data") or [])
        claims = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": a["id"]}, {"_id": 0, "status": 1, "claim_inputs": 1}).to_list(10000)
        changes += sum(1 for c in claims if c.get("status") in ("edited", "rejected")) + \
            sum(len(c.get("claim_inputs") or {}) for c in claims)
        changes += usage_mod.get(a)["columns"]["corrected"]
    return sanitize(usage_mod.totals([usage_mod.get(a) for a in audits], {
        "tokens_and_cost_by_step": steps, "evidence_labels": labels, "metrics_missing": missing, "analyst_changes": changes}))


# ---------------------------------------------------------------------------
# Datasets: upload with type detection, the mapping rule, decisions, saved mappings
# (docs/specs/chat-upload.md sections 3-5)
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = ("xlsx", "xls", "csv")
MAPPING_AI_SECONDS = 20          # the model's budget for one column mapping (section 4.2)
NOTE_REFUSED = "Leave out file names, figures and cell values: this note is kept with the usage counts."
DTYPE_ORDER = ("revenue", "crm", "pnl")


async def _versions(audit_id: str, dtype: str) -> list:
    """The audit's saved mapping versions of one file type, oldest first (earlier versions are kept)."""
    found = await db[structures.COLUMN_MAPPINGS_COLLECTION].find({"audit_id": audit_id, "dtype": dtype}, {"_id": 0}).to_list(100000)
    return sorted(found, key=lambda v: v.get("version") or 0)


def _saved_columns(version: dict) -> list:
    """The columns of a saved version. One saved before versions existed holds only {field: column}."""
    return version.get("columns") or [{"column": c, "field": f} for f, c in (version.get("mapping") or {}).items() if c]


def _fingerprint(states: list) -> list:
    return sorted((s["column"], s.get("field")) for s in states)


async def _write_version(audit_id: str, dtype: str, ds: dict, states: list) -> Optional[int]:
    """Write a mapping version unless the latest one for this file already says the same thing."""
    versions = await _versions(audit_id, dtype)
    same = [v for v in versions if v.get("file_hash") == ds.get("file_hash")]
    if same and _fingerprint(_saved_columns(same[-1])) == _fingerprint(states):
        return same[-1].get("version")
    number = (versions[-1].get("version") or 0) + 1 if versions else 1
    mapping = cr.mapping_of(dtype, states)
    await db[structures.COLUMN_MAPPINGS_COLLECTION].insert_one({
        "audit_id": audit_id, "dtype": dtype, "file_hash": ds.get("file_hash"),
        "header_key": structures.header_key(dtype, ds.get("columns") or []), "version": number,
        "mapping": mapping, "saved_at": usage_mod.now(),
        "columns": [{k: s.get(k) for k in ("column", "field", "source", "confidence", "decision", "reason")} for s in states]})
    return number


def _source_map(states: list) -> dict:
    """{field: "rules" | "ai" | "stored"} for the columns that are mapped (the older shape of the screen's data)."""
    names = {"rules": "rules", "ai": "ai", "saved": "stored"}
    return {s["field"]: names[s["source"]] for s in states
            if s["state"] in cr.MAPPED and s.get("field") and s.get("source") in names}


def _legacy_states(ds: dict) -> list:
    """A dataset stored before the chat upload (or seeded) has a mapping and no column states: each mapped column
    counts as confirmed by the analyst."""
    held = {c: f for f, c in (ds.get("mapping") or {}).items() if c}
    return [cr.new_state(c, held.get(c), "decision" if held.get(c) else None, "confirmed" if held.get(c) else "unused")
            for c in ds.get("columns") or []]


def _dataset_view(ds: dict, version: Optional[int] = None, status: str = "ok") -> dict:
    """What the chat shows for one stored file: its bubble data and its mapping table. No rows (the preview
    is the first 8)."""
    dtype = ds["dtype"]
    states = ds.get("columns_state") or _legacy_states(ds)
    mapping = ds.get("mapping") or cr.mapping_of(dtype, states)
    rows = []
    for i, s in enumerate(states):
        rows.append({**s, "position": i + 1, "pending": s["state"] in cr.PENDING})
    return {
        "status": status, "dtype": dtype, "file": ds.get("file"), "size_bytes": ds.get("size_bytes"),
        "ext": usage_mod.extension_of(ds.get("file") or ""), "row_count": ds.get("row_count"),
        "header_row": ds.get("header_row"), "months": ds.get("months"), "columns": rows,
        "pending": cr.pending_count(states), "missing_required": cr.missing_required(dtype, states),
        "version": version, "ai_reading": ds.get("ai_reading"), "uploaded_at": ds.get("uploaded_at"),
        "fields": {"required": list(FIELD_DEFS[dtype]["required"]), "optional": list(FIELD_DEFS[dtype]["optional"])},
        "mapping": mapping, "suggested_mapping": mapping, "mapping_source": ds.get("mapping_source") or _source_map(states),
        "fx": ds.get("fx") or {}, "billing_terms": ds.get("billing_terms") or {}, "preview": ds.get("preview") or [],
        "saved": bool(ds.get("mapped_at")), "sheet": ds.get("sheet"),
    }


def _months_for(dtype: str, states: list, columns: list, rows: list) -> Optional[dict]:
    """The months of the date column, once that column is decided (S5: not before)."""
    field = {"revenue": "invoice_date", "crm": "close_date", "pnl": "month"}[dtype]
    state = next((s for s in states if s["field"] == field and s["state"] in ("auto", "confirmed", "corrected")), None)
    return cr.months_of([r.get(state["column"]) for r in rows]) if state else None


async def _ask_model(audit: dict, dtype: str, sheet: "cr.Sheet", rows: list, states: list, sent: list, proposals: list,
                     open_fields: list):
    """Step 2: the columns the rules could not decide go to the model, redacted, and nothing waits for it for
    longer than MAPPING_AI_SECONDS. Returns (states, ai_reading)."""
    if audit.get("structure_reading_consent") is not True:
        return states, {"status": "no_consent", "reason": "AI-assisted reading is off for this audit"}
    text = structures.column_mapping_text(
        sheet.columns, rows, audit.get("company_name"), await llm_redaction.get_map(db, audit["id"]),
        tuple(cr.customer_columns(sheet, proposals)), structures.redact.withheld_values(audit), only=tuple(sent))
    try:
        read = await asyncio.wait_for(llm_gateway.read_structure(db, audit["id"], text, "column_mapping"),
                                      MAPPING_AI_SECONDS)
    except asyncio.TimeoutError:
        return cr.apply_model_failure(states, sent), {"status": "timeout", "reason": "AI reading unavailable"}
    if read.status != "read":
        return cr.apply_model_failure(states, sent), {"status": read.status, "reason": read.reason}
    await llm_gateway.record_verification(db, audit["id"], read.key, ["suggestion"] * len(read.items))
    proposed = structures.proposed_mapping(read.items, sheet.columns, open_fields)
    proposed = {f: c for f, c in proposed.items() if c in sent}
    return cr.apply_model(states, sent, proposed), {"status": "read", "reason": read.reason}


async def _ingest(audit_id: str, upload: UploadFile, dtype: Optional[str], replace: bool, background: BackgroundTasks):
    if dtype is not None and dtype not in FIELD_DEFS:
        raise HTTPException(400, "Unknown dataset type")
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    filename = upload.filename or ""
    content = await upload.read()
    ext = usage_mod.extension_of(filename)
    if ext not in ALLOWED_EXTENSIONS:
        await _usage_update(audit_id, lambda u: usage_mod.record_rejected(u, ext))
        raise HTTPException(400, "Only .xlsx and .csv files are supported")
    try:
        sheet = await run_in_threadpool(cr.read_sheet, content, filename)
    except cr.SheetError:
        raise HTTPException(400, "This file could not be read as a sheet")
    detected, _ = cr.detect_type(sheet)
    chosen = dtype or detected
    if chosen is None:
        return {"status": "unknown_type", "file": filename, "size_bytes": len(content), "row_count": len(sheet.frame),
                "ext": ext, "types": list(DTYPE_ORDER)}
    digest = hashlib.sha256(content).hexdigest()
    existing = await db.datasets.find_one({"audit_id": audit_id, "dtype": chosen}, {"_id": 0, "rows": 0})
    versions = await _versions(audit_id, chosen)
    if existing and existing.get("file_hash") == digest:
        same = [v for v in versions if v.get("file_hash") == digest]
        if same:        # the latest saved version is applied again: no rules, no model, no clicks
            states = cr.states_from_saved(chosen, sheet, _saved_columns(same[-1]), scale=False)
            existing = {**existing, "columns_state": states, "mapping": cr.mapping_of(chosen, states),
                        "mapping_source": _source_map(states)}
            await db.datasets.update_one({"audit_id": audit_id, "dtype": chosen}, {"$set": {
                "columns_state": states, "mapping": existing["mapping"], "mapping_source": existing["mapping_source"]}})
        return _dataset_view(existing, same[-1]["version"] if same else None, "same_file")
    if existing and not replace:
        raise HTTPException(409, {"code": "type_loaded", "dtype": chosen, "file": existing.get("file")})
    rows = df_to_records(sheet.frame)
    key = structures.header_key(chosen, sheet.columns)
    same = [v for v in versions if v.get("file_hash") == digest]
    headers = [v for v in versions if v.get("header_key") == key]
    ai_reading = {"status": "rules", "reason": None}
    if same or headers:      # a saved mapping: no rules run for the columns, no model call (section 5)
        states = cr.states_from_saved(chosen, sheet, _saved_columns((same or headers)[-1]), scale=not same)
        ai_reading = {"status": "stored", "reason": None}
    else:
        proposals, open_fields = cr.analyse(chosen, sheet)
        states = cr.states_from_rules(proposals)
        sent = cr.to_send(states)
        if sent:
            states, ai_reading = await _ask_model(a, chosen, sheet, rows, states, sent, proposals, open_fields)
            await _usage_update(audit_id, lambda u: u["steps"]["mapping_ai"].__setitem__(
                ai_reading["status"], u["steps"]["mapping_ai"].get(ai_reading["status"], 0) + 1))
    mapping = cr.mapping_of(chosen, states)
    doc = {"audit_id": audit_id, "dtype": chosen, "file": filename, "sheet": sheet.sheet, "columns": sheet.columns,
           "headers": sheet.headers, "header_row": sheet.header_row, "rows": rows, "row_numbers": sheet.row_numbers,
           "row_count": len(rows), "mapping": mapping, "fx": {}, "billing_terms": {}, "preview": rows[:8],
           "mapping_source": _source_map(states), "ai_reading": ai_reading, "columns_state": states,
           "months": _months_for(chosen, states, sheet.columns, rows), "file_hash": digest, "size_bytes": len(content),
           "uploaded_at": usage_mod.now(), "mapped_at": None}
    await db.datasets.replace_one({"audit_id": audit_id, "dtype": chosen}, doc, upsert=True)

    def count(u):
        usage_mod.record_upload(u, chosen)
        for s in states:
            kind = {"rules": "rules", "saved": "saved", "ai": "ai"}.get(s.get("source"))
            if kind and s["state"] in cr.MAPPED:
                usage_mod.record_columns(u, kind)
    await _usage_update(audit_id, count)
    version = await _commit_mapping(audit_id, chosen, background)
    await _mark_stale_and_maybe_recompute(audit_id)
    logger.info("upload: run_id=%s type=%s detected=%s pending=%d ai=%s", audit_id, chosen, detected == chosen,
                cr.pending_count(states), ai_reading["status"])
    stored = await db.datasets.find_one({"audit_id": audit_id, "dtype": chosen}, {"_id": 0, "rows": 0})
    return _dataset_view(stored, version)


async def _commit_mapping(audit_id: str, dtype: str, background: Optional[BackgroundTasks]) -> Optional[int]:
    """When the file has nothing pending the mapping saves: a version is written, the file is marked mapped, its
    customers join the pseudonym map and decks that waited for the revenue file are read. Returns the version."""
    ds = await db.datasets.find_one({"audit_id": audit_id, "dtype": dtype})
    if not ds:
        return None
    states = ds.get("columns_state")
    if states is None or cr.pending_count(states):
        return None
    version = await _write_version(audit_id, dtype, ds, states)
    await db.datasets.update_one({"audit_id": audit_id, "dtype": dtype},
                                 {"$set": {"mapped_at": usage_mod.now(), "mapping": cr.mapping_of(dtype, states)}})
    await _add_customers(audit_id, {**ds, "mapping": cr.mapping_of(dtype, states)})
    if dtype == "revenue" and background is not None:
        background.add_task(structures.process_waiting_decks_safely, db, audit_id)
    return version


@api.post("/audits/{audit_id}/datasets/upload")
async def upload_chat_file(audit_id: str, background: BackgroundTasks, file: UploadFile = File(...),
                           dtype: Optional[str] = None, replace: bool = False):
    """One file of the chat: its type is detected unless `dtype` is given. Unknown: nothing is stored. A type
    already loaded with other bytes: 409 unless `replace` (docs/specs/chat-upload.md section 3)."""
    return await _ingest(audit_id, file, dtype, replace, background)


@api.post("/audits/{audit_id}/datasets/{dtype}/upload")
async def upload_dataset(audit_id: str, dtype: str, background: BackgroundTasks, file: UploadFile = File(...)):
    """The typed upload, for the demo seed and the tests: the same path, a loaded file of the type is replaced."""
    view = await _ingest(audit_id, file, dtype, True, background)
    return view


@api.get("/audits/{audit_id}/datasets")
async def list_datasets(audit_id: str):
    """One view per stored file, for rebuilding the chat on reload."""
    if not await db.audits.find_one({"id": audit_id}, {"id": 1}):
        raise HTTPException(404, "Audit not found")
    found = await db.datasets.find({"audit_id": audit_id}, {"_id": 0, "rows": 0}).to_list(10)
    found.sort(key=lambda d: DTYPE_ORDER.index(d["dtype"]) if d["dtype"] in DTYPE_ORDER else 9)
    views = []
    for d in found:
        same = [v for v in await _versions(audit_id, d["dtype"]) if v.get("file_hash") == d.get("file_hash")]
        views.append(_dataset_view(d, same[-1]["version"] if same else None))
    return sanitize({"datasets": views})


@api.get("/fields")
async def get_fields():
    return {dt: {"required": list(v["required"]), "optional": list(v["optional"])} for dt, v in FIELD_DEFS.items()}


@api.get("/audits/{audit_id}/datasets/revenue/customers")
async def revenue_customers(audit_id: str, customer_col: Optional[str] = None):
    ds = await db.datasets.find_one({"audit_id": audit_id, "dtype": "revenue"})
    if not ds:
        raise HTTPException(404, "Revenue dataset not uploaded")
    col = customer_col or ds["mapping"].get("customer_id")
    custs = set()
    if col:
        for row in ds["rows"]:
            v = row.get(col)
            if v is not None and str(v).strip():
                custs.add(str(v).strip())
    has_service = bool(ds["mapping"].get("service_start")) and bool(ds["mapping"].get("service_end"))
    return {"customers": sorted(custs), "has_service_dates": has_service, "billing_terms": ds.get("billing_terms", {})}


class Decision(BaseModel):
    """One analyst decision on one column (section 4.3). `note` rides only with the reason "other"."""
    model_config = {"extra": "forbid"}
    column: str
    action: Literal["confirm", "correct"]
    field: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=2000)


async def _check_notes(audit_id: str, audit: dict, notes: list) -> list:
    """The notes that may be kept, cleaned; HTTP 400 with S21 for the first that may not (nothing is saved)."""
    cleaned = [usage_mod.clean_note(n) for n in notes]
    cleaned = [n for n in cleaned if n]
    if not cleaned:
        return []
    files = await db.datasets.find({"audit_id": audit_id}, {"_id": 0}).to_list(10)
    deck_files = await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "file": 1}).to_list(1000)
    headers, cells = [], []
    for d in files:
        headers += [str(h) for h in d.get("headers") or []] + [str(c) for c in d.get("columns") or []]
        headers += [c["text"] for c in structures.column_mapping_input(d.get("columns") or [], d.get("rows") or [], (), None, 0)[0]]
        cells += [v for r in d.get("rows") or [] for v in r.values() if isinstance(v, str)]
    try:
        for n in cleaned:
            usage_mod.check_note(n, headers=headers, file_names=[d.get("file") for d in files] + [d.get("file") for d in deck_files],
                                 cell_texts=cells, names=[audit.get("company_name"), audit.get("client_name")])
    except usage_mod.NoteRefused:
        raise HTTPException(400, NOTE_REFUSED)
    return cleaned


@api.post("/audits/{audit_id}/datasets/{dtype}/decisions")
async def decide_columns(audit_id: str, dtype: str, decisions: List[Decision], background: BackgroundTasks):
    """Apply the analyst's decisions to one file's mapping table. The server works out what is still pending and
    saves a mapping version when nothing is, and again on every later change."""
    audit = await db.audits.find_one({"id": audit_id})
    ds = await db.datasets.find_one({"audit_id": audit_id, "dtype": dtype})
    if not audit or not ds:
        raise HTTPException(404, "Dataset not uploaded")
    raw = [d.model_dump() for d in decisions]
    for d in raw:
        if d["action"] == "correct" and d.get("reason") not in cr.REASONS:
            raise HTTPException(400, "Choose one of the listed reasons")
    kept_notes = await _check_notes(audit_id, audit, [d.get("note") for d in raw
                                                      if d["action"] == "correct" and d.get("reason") == "other"])
    return await _apply_decisions(audit_id, dtype, ds, raw, kept_notes, background)


async def _apply_decisions(audit_id: str, dtype: str, ds: dict, raw: list, kept_notes: list, background):
    before = ds.get("columns_state") or _legacy_states(ds)
    try:
        states = cr.apply_decisions(dtype, before, raw)
    except cr.DecisionError as exc:
        status = 409 if exc.code == "field_held" else 400
        raise HTTPException(status, {"code": exc.code, "column": exc.column})
    mapping = cr.mapping_of(dtype, states)
    await db.datasets.update_one({"audit_id": audit_id, "dtype": dtype}, {"$set": {
        "columns_state": states, "mapping": mapping, "mapping_source": _source_map(states),
        "months": _months_for(dtype, states, ds.get("columns") or [], ds.get("rows") or [])}})
    changed = [s for s, b in zip(states, before) if (s["state"], s["field"]) != (b["state"], b["field"]) or s["decision"] != b["decision"]]

    def count(u):
        for s in changed:
            if s["decision"] in ("confirm", "correct"):
                usage_mod.record_columns(u, "confirmed" if s["decision"] == "confirm" else "corrected")
            if s["decision"] == "correct" and s.get("reason") in cr.REASONS:
                usage_mod.record_reason(u, s["reason"])
        for n in kept_notes:
            usage_mod.keep_note(u, n)
    await _usage_update(audit_id, count)
    version = await _commit_mapping(audit_id, dtype, background)
    await _mark_stale_and_maybe_recompute(audit_id)
    logger.info("decisions: run_id=%s type=%s columns=%d pending=%d", audit_id, dtype, len(changed), cr.pending_count(states))
    stored = await db.datasets.find_one({"audit_id": audit_id, "dtype": dtype}, {"_id": 0, "rows": 0})
    return sanitize(_dataset_view(stored, version))


def _decisions_from_mapping(states: list, mapping: dict) -> list:
    """The older whole-mapping save as decisions: what the mapping keeps is confirmed or corrected, a mapped or
    pending column it leaves out is not used. Not-used first, so a field changes hands without a clash."""
    want = {c: f for f, c in mapping.items() if c}
    drop, keep = [], []
    for s in states:
        field = want.get(s["column"])
        if field is None and (s["state"] in cr.MAPPED or s["state"] == "needs"):
            drop.append({"column": s["column"], "action": "confirm" if s["state"] == "needs" else "correct",
                         "field": None, "reason": "not_needed"})
        elif field is not None and s["field"] == field and s["state"] in cr.PENDING:
            keep.append({"column": s["column"], "action": "confirm", "field": field})
        elif field is not None and s["field"] != field:
            keep.append({"column": s["column"], "action": "confirm" if s["state"] == "needs" else "correct",
                         "field": field, "reason": "other_column_right"})
    return drop + keep


@api.put("/audits/{audit_id}/datasets/{dtype}/mapping")
async def save_mapping(audit_id: str, dtype: str, payload: MappingPayload, background: BackgroundTasks):
    """Save the FX rates and billing terms, and (the older whole-mapping save) the mapping as decisions."""
    ds = await db.datasets.find_one({"audit_id": audit_id, "dtype": dtype})
    if not ds:
        raise HTTPException(404, "Dataset not uploaded")
    await db.datasets.update_one({"audit_id": audit_id, "dtype": dtype},
                                 {"$set": {"fx": payload.fx, "billing_terms": payload.billing_terms}})
    if payload.mapping is None:
        await _mark_stale_and_maybe_recompute(audit_id)
        return {"ok": True}
    if ds.get("columns_state") is None:       # stored before the chat upload: the mapping is the analyst's, as before
        await db.datasets.update_one({"audit_id": audit_id, "dtype": dtype}, {"$set": {
            "mapping": payload.mapping, "mapped_at": usage_mod.now(), "mapping_source": {}}})
        await db[structures.COLUMN_MAPPINGS_COLLECTION].insert_one({
            "audit_id": audit_id, "dtype": dtype, "file_hash": ds.get("file_hash"),
            "header_key": structures.header_key(dtype, ds.get("columns") or []),
            "version": len(await _versions(audit_id, dtype)) + 1, "mapping": payload.mapping, "saved_at": usage_mod.now(),
            "columns": [{"column": c, "field": f, "source": "decision", "confidence": None, "decision": "confirm", "reason": None}
                        for f, c in payload.mapping.items() if c]})
        await _add_customers(audit_id, {**ds, "mapping": payload.mapping})
        await _mark_stale_and_maybe_recompute(audit_id)
        if dtype == "revenue":
            background.add_task(structures.process_waiting_decks_safely, db, audit_id)
        return {"ok": True}
    decisions = _decisions_from_mapping(ds["columns_state"], payload.mapping)
    await _apply_decisions(audit_id, dtype, ds, decisions, [], background)
    return {"ok": True}


def customer_column(dataset: dict) -> Optional[str]:
    """The column whose cells are customer names: the revenue file's mapped customer column; for the
    CRM file, which has no customer field of its own, the column the FIELD_DEFS customer aliases find."""
    if dataset.get("dtype") == "revenue":
        return (dataset.get("mapping") or {}).get("customer_id")
    return suggest_mapping("revenue", dataset.get("columns") or []).get("customer_id")


async def _add_customers(audit_id: str, dataset: dict) -> None:
    """Every customer name of a mapped revenue or CRM file joins the audit's pseudonym mapping, shared
    by the narrative and structure paths (llm-structure-reading.md section 3)."""
    if dataset.get("dtype") not in ("revenue", "crm"):
        return
    col = customer_column(dataset)
    if not col:
        return
    rows = dataset.get("rows")
    if rows is None:
        full = await db.datasets.find_one({"audit_id": audit_id, "dtype": dataset["dtype"]}, {"rows": 1})
        rows = (full or {}).get("rows") or []
    await llm_redaction.add_customers(db, audit_id, (r.get(col) for r in rows))


# ---------------------------------------------------------------------------
# Board decks and growth plans: parsed text and candidate claims (docs/specs/deck-parser.md)
# ---------------------------------------------------------------------------
# "FY2025-04": the April inside year 2025, a month under a year header (deck-parser.md section 2).
_TARGET_DATE = re.compile(r"^(\d{4}(-(0[1-9]|1[0-2])|-Q[1-4]|-H[12])?|FY\d{4}-(0[1-9]|1[0-2]))$")


class PeriodValue(BaseModel):
    """One value of a table row candidate, as the analyst corrects it; its period and its cell stay."""
    value: Optional[float] = None
    value_high: Optional[float] = None
    target_date: Optional[str] = Field(default=None, pattern=_TARGET_DATE.pattern)


class CandidateUpdate(BaseModel):
    """Approve or reject a candidate, or edit its structured fields. An edit approves the claim
    with the analyst's corrections: status "edited", the parser's values kept under "parsed".
    The snippet, the borrowed label and the source references are evidence and cannot be edited."""
    status: Optional[Literal["pending", "approved", "rejected"]] = None
    claim_type: Optional[Literal[deck_claims.CLAIM_TYPES]] = None
    value: Optional[float] = None
    value_high: Optional[float] = None          # the high end of a range
    unit: Optional[str] = Field(default=None, min_length=1, max_length=40)   # "%", "months", "paying users"
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    target_date: Optional[str] = Field(default=None, pattern=_TARGET_DATE.pattern)
    by_period: Optional[List[PeriodValue]] = None   # a table row: every value, in the row's order


_EDITABLE = ("claim_type", "value", "value_high", "unit", "currency", "target_date", "by_period")
_ROW_FIELDS = ("value", "value_high", "target_date")     # held per period on a table row candidate
# Approved and edited claims make up the claim register; rejected ones stay on record, unused.
REGISTER_STATUSES = ("approved", "edited")


def _claim_key(c: dict) -> tuple:
    """What the parser found, so a re-upload can tell an already reviewed claim."""
    found = c.get("parsed") or c
    return tuple(tuple(tuple(i.get(f) for f in _ROW_FIELDS) for i in found.get(k) or ()) if k == "by_period"
                 else found.get(k) for k in _EDITABLE)


@api.post("/audits/{audit_id}/decks/upload")
async def upload_deck(audit_id: str, background: BackgroundTasks, file: UploadFile = File(...)):
    audit = await db.audits.find_one({"id": audit_id}, {"id": 1, "fiscal_year_end": 1})
    if not audit:
        raise HTTPException(404, "Audit not found")
    content = await file.read(deck_parser.MAX_BYTES + 1)
    try:
        deck = await run_in_threadpool(deck_parser.parse_deck, content, file.filename or "")
    except deck_parser.DeckError as exc:
        raise HTTPException(400, exc.message)
    candidates = deck_claims.detect_candidates(deck["blocks"], deck["file"], _fiscal_year_end(audit))
    deck_id = str(uuid.uuid4())
    # A file uploaded again replaces its earlier parse and its unreviewed candidates. Approved,
    # edited and rejected candidates stay on record; the same claim found again is not re-added.
    where = {"audit_id": audit_id, "file": deck["file"]}
    await db[decks.TEXT_COLLECTION].delete_many(where)
    await db[decks.CANDIDATES_COLLECTION].delete_many({**where, "status": "pending"})
    reviewed = await db[decks.CANDIDATES_COLLECTION].find(where, {"_id": 0}).to_list(10000)
    for c in reviewed:
        await db[decks.CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": c["id"]},
                                                       {"$set": {"deck_id": deck_id}})
    known = {_claim_key(c) for c in reviewed}
    candidates = [c for c in candidates if _claim_key(c) not in known]
    await db[decks.TEXT_COLLECTION].insert_one({
        "audit_id": audit_id, "deck_id": deck_id, "file": deck["file"], "format": deck["format"],
        "page_unit": deck["page_unit"], "pages": deck["pages"], "blocks": deck["blocks"],
        "structures": deck["structures"], "ai_status": "reading", "uploaded_at": datetime.now(timezone.utc).isoformat()})
    for order, c in enumerate(candidates):
        await db[decks.CANDIDATES_COLLECTION].insert_one(
            {**c, "audit_id": audit_id, "deck_id": deck_id, "file": deck["file"], "id": str(uuid.uuid4()),
             "order": len(reviewed) + order, "status": "pending"})
    # Its structures are read by the model after the response, or wait for the revenue file
    # (llm-structure-reading.md section 3); with consent unticked, Python's candidates stand alone.
    background.add_task(structures.process_deck_safely, db, audit_id, deck_id)
    return {"deck_id": deck_id, "file": deck["file"], "format": deck["format"], "page_unit": deck["page_unit"],
            "pages": deck["pages"], "candidates": len(candidates), "kept_reviewed": len(reviewed),
            "structures": len(deck["structures"])}


@api.get("/audits/{audit_id}/decks")
async def list_deck_candidates(audit_id: str):
    """The audit's decks (no parsed text), most recently uploaded first, and their candidates:
    grouped by deck in that order; within a deck the ones to review first, then by slide or page."""
    audit = await db.audits.find_one({"id": audit_id}, {"id": 1, "structure_reading_consent": 1, "reporting_currency": 1,
                                                         "as_of_month": 1, "results.as_of_month": 1})
    if not audit:
        raise HTTPException(404, "Audit not found")
    deck_fields = {"_id": 0, "deck_id": 1, "file": 1, "format": 1, "page_unit": 1, "pages": 1, "uploaded_at": 1,
                   "ai_status": 1, "ai_message": 1, "sent": 1, "periods_corrected": 1}
    found = await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, deck_fields).to_list(100)
    found.sort(key=lambda d: d.get("uploaded_at") or "", reverse=True)
    by_deck = (await llm_gateway.usage_for_run(db, audit_id)).by_deck
    for d in found:
        # The deck panel's run log: status, the pages sent to the model (no text) and the cost.
        d["sent_pages"] = sorted({s["page"] for s in d.pop("sent", None) or [] if s.get("page") is not None})
        usage = by_deck.get(d["deck_id"])
        d["ai_cost_usd"] = usage.estimated_cost_usd if usage else 0.0
        # Uploaded while AI reading was off (or before it existed) and not read since: re-upload to read.
        d["uploaded_before_consent"] = audit.get("structure_reading_consent") is True and \
            d.get("ai_status") in (None, structures.PYTHON_ONLY)
    rank = {d["deck_id"]: i for i, d in enumerate(found)}
    candidates = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id}, {"_id": 0}).to_list(10000)
    # By the group of the claim type (revenue, P&L, customers and sales, market size, Unknown, Other), then ascending by
    # slide or page across all decks (a tie goes to the more recent deck), then reading order on the page: top to bottom
    # in bands of 2% of the height, then left to right, then the order the parser found them in.
    for c in candidates:
        c["group"] = deck_claims.type_group(c.get("claim_type"))
    candidates.sort(key=lambda c: (c["group"], _first_page(c), rank.get(c.get("deck_id"), len(rank)), *_reading(c),
                                   c.get("order", 0)))
    # A claim in another currency than the audit's, with the rate it is converted at (None: "FX rate needed").
    fx = await _fx(audit_id, audit)
    settings = _register_settings(audit, fx)
    as_of = audit.get("as_of_month") or (audit.get("results") or {}).get("as_of_month")
    for c in candidates:
        c["fx"] = claim_matching.fx_view(c, settings, as_of)
    peers = {}
    for c in candidates:
        peers.setdefault(c.get("deck_id"), []).append(c)
    for c in candidates:
        c["confidence"] = deck_claims.confidence(c, peers[c.get("deck_id")])
    return sanitize({"decks": found, "candidates": candidates})


def _edited_period(value: dict, before: dict, fiscal_year_end: int) -> dict:
    """A value after an edit, its date range re-run. A date the analyst typed follows the same rules as
    a stated one: a year, quarter or half follows the audit's year-end, a month is a calendar month.
    The deck's stated text goes once the date changes."""
    if value.get("target_date") != before.get("target_date"):
        value["period_text"] = None
    else:
        value["period_text"] = before.get("period_text")
    return deck_claims.resolve_period(value, fiscal_year_end)


def _period_fields(value: dict) -> dict:
    return {k: value.get(k) for k in ("period_text", "period_start", "period_end")}


def _reading(candidate: dict) -> tuple:
    """(band, left) of a candidate's first line on its page; (inf, inf) when the page has no layout, so those keep the
    order the parser found them in."""
    top, left = candidate.get("reading") or (None, None)
    return (float("inf"), float("inf")) if top is None else (round(top / 0.02), left)


def _first_page(candidate: dict) -> int:
    pages = [s.get("slide", s.get("page")) for s in candidate.get("sources") or []]
    return min((p for p in pages if isinstance(p, int)), default=0)


@api.delete("/audits/{audit_id}/decks/{deck_id}")
async def remove_deck(audit_id: str, deck_id: str):
    """Remove one deck: its parsed text and all its candidates, reviewed ones included."""
    deck = await db[decks.TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id}, {"_id": 0, "file": 1})
    if not deck:
        raise HTTPException(404, "Deck not found")
    text = await db[decks.TEXT_COLLECTION].delete_many({"audit_id": audit_id, "deck_id": deck_id})
    candidates = await db[decks.CANDIDATES_COLLECTION].delete_many(
        {"audit_id": audit_id, "$or": [{"deck_id": deck_id}, {"file": deck["file"]}]})
    return {"removed": deck_id, "deck_text": text.deleted_count, "deck_candidates": candidates.deleted_count}


@api.put("/audits/{audit_id}/decks/candidates/{candidate_id}")
async def update_candidate(audit_id: str, candidate_id: str, payload: CandidateUpdate):
    where = {"audit_id": audit_id, "id": candidate_id}
    current = await db[decks.CANDIDATES_COLLECTION].find_one(where, {"_id": 0})
    if not current:
        raise HTTPException(404, "Candidate not found")
    sent = payload.model_fields_set
    edits = {k: getattr(payload, k) for k in _EDITABLE if k in sent}
    if not edits and "status" not in sent:
        raise HTTPException(400, "Nothing to change")
    if edits and "status" in sent:
        raise HTTPException(400, "Edit the fields or change the status, not both at once")
    rows = current.get("by_period") or []
    year_end = _fiscal_year_end(await db.audits.find_one({"id": audit_id}, {"fiscal_year_end": 1}))
    if "by_period" in edits:
        # One value of a row can be corrected; the row keeps its periods and cells.
        if not rows or edits["by_period"] is None or len(edits["by_period"]) != len(rows):
            raise HTTPException(400, "Send one value per period of the row")
        edits["by_period"] = [_edited_period({**old, **new.model_dump()}, old, year_end)
                              for old, new in zip(rows, edits["by_period"])]
    if rows and set(edits) & set(_ROW_FIELDS):
        raise HTTPException(400, "Edit the row's values by period")
    if "target_date" in edits:
        edits.update(_period_fields(_edited_period({"target_date": edits["target_date"]}, current, year_end)))
    if current.get("claim_type") in (structures.verify.OTHER, deck_claims.UNKNOWN) and "parsed" not in current and \
            (payload.status == "approved" or (edits and "claim_type" not in edits)):
        # An item the model labelled "other" is listed as type Other, a figure no heading names a type for as type
        # Unknown; either is approved only once its type is edited to a claim type (structure-labelling.md section 4,
        # deck-parser.md section 2). An edit approves, so it needs the type too.
        raise HTTPException(400, "Choose a claim type for this item before approving it")
    if edits:
        changes = {**edits, "status": "edited"}
        if current.get("claim_direction") and (edits.get("value") is not None or edits.get("by_period")):
            changes["claim_direction"] = None       # a figure typed in: no longer a direction with no figure
        if "parsed" not in current:       # what the parser found stays next to the analyst's edit
            changes["parsed"] = {k: current.get(k) for k in _EDITABLE if k != "by_period" or rows}
            if current.get("origin") == "ai":
                # The Verified or suggestion label described the model's reading, now kept under "parsed";
                # it never stands next to a value the analyst typed.
                changes["parsed"].update(ai_status=current.get("ai_status"), ai_label=current.get("ai_label"))
                changes.update(ai_status=None, ai_label=None)
    else:
        if payload.status is None:
            raise HTTPException(400, "status cannot be empty")
        # Approving an edited claim keeps it "edited": it is approved with the analyst's corrections.
        status = "edited" if payload.status == "approved" and "parsed" in current else payload.status
        changes = {"status": status}
    await db[decks.CANDIDATES_COLLECTION].update_one(where, {"$set": changes})
    return sanitize(await db[decks.CANDIDATES_COLLECTION].find_one(where, {"_id": 0}))


async def _fx(audit_id: str, audit: dict) -> dict:
    """The audit's FX rates, upper-cased, with the reporting currency at 1."""
    revenue = await db.datasets.find_one({"audit_id": audit_id, "dtype": "revenue"}, {"fx": 1}) or {}
    fx = {k.upper(): float(v) for k, v in (revenue.get("fx") or {}).items()}
    fx[(audit.get("reporting_currency") or "EUR").upper()] = 1.0
    return fx


def _register_settings(audit: dict, fx: dict) -> dict:
    return {"fiscal_year_end": _fiscal_year_end(audit), "as_of_month": audit.get("as_of_month"),
            "reporting_currency": audit.get("reporting_currency") or "EUR", "fx": fx}


async def _claim_rows(audit_id: str, audit: dict) -> tuple:
    """(register candidates, register rows in rank order). The rows are computed on read from the stored results and
    the analyst's inputs on the candidates (docs/specs/claim-matching.md section 6); nothing is sent to a model."""
    audit = await _current_audit(audit_id, audit, strict=False)
    claims = await db[decks.CANDIDATES_COLLECTION].find(
        {"audit_id": audit_id, "status": {"$in": list(REGISTER_STATUSES)}}, {"_id": 0}).to_list(10000)
    claims.sort(key=lambda c: (c.get("file") or "", c.get("order", 0)))
    rows = claim_matching.build_register(claims, audit.get("results"), _register_settings(audit, await _fx(audit_id, audit)))
    # Counts per label only: a value, a gate sentence or a deck file name never reaches a log line.
    counts = claim_matching.label_counts(rows)
    logger.info("claim register: run_id=%s rows=%d labels=%s", audit_id, len(rows), counts)
    return claims, rows


@api.get("/audits/{audit_id}/claims")
async def claim_register(audit_id: str):
    """The claim register: approved and edited claims, with what the parser found next to each edit, and `register`:
    one row per claim tested against the computed metrics, in rank order (docs/specs/claim-matching.md). Rejected and
    unreviewed candidates are not in it (they stay on record in the deck list)."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    claims, rows = await _claim_rows(audit_id, audit)
    return sanitize({"claims": claims, "register": rows})


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, dict):
        return f"{value.get('file')} · {value.get('sheet')} · {value.get('rows')}"
    return str(value)


async def _ic_context(audit_id: str, audit: dict, validate: bool = True) -> dict:
    """The register, the top 5 in force, the gaps and the analyst's inputs of an audit: what the verdict and the memo read.
    Pure reads; nothing is sent to a model (docs/specs/verdict-and-memo.md). With `validate`, the stored results are checked
    against MetricsPayload and the unit check first (section 9): on a failure there are no rows, and `contract` names the
    fields (paths only, never a value)."""
    results = (await _current_audit(audit_id, audit, strict=False)).get("results")
    ic = audit.get("ic_inputs") or {}
    if validate and results:
        try:
            contract.validate_for_export(results)
        except contract.ContractError as exc:
            return {"rows": [], "results": results, "ic": ic, "state": verdict_mod.top5_state([], None), "gaps": [],
                    "contract": exc.log_text}
    _, rows = await _claim_rows(audit_id, audit)
    state = verdict_mod.top5_state(rows, ic.get("top5"))
    gaps = verdict_mod.data_gaps(results, rows, state["in_force"], ic.get("gap_target_dates"))
    return {"rows": rows, "results": results, "ic": ic, "state": state, "gaps": gaps, "contract": None}


@api.get("/audits/{audit_id}/claims.csv")
async def claim_register_csv(audit_id: str):
    """The monitoring baseline (docs/specs/verdict-and-memo.md section 5): the register's rows in rank order, then the data
    gaps, as one CSV. Numbers unformatted, dates ISO, `observed_source` as "file · sheet · rows · rule", lists joined by "; "."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    ctx = await _ic_context(audit_id, audit, validate=False)
    text = verdict_mod.baseline_csv(ctx["rows"], ctx["gaps"], ctx["state"]["in_force"], ctx["ic"].get("first_quarterly_review"))
    return Response(content=text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="claim-register-{audit_id}.csv"'})


_GATE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ClaimInputs(BaseModel):
    """What the analyst sets on a claim of the register (section 8): its segment, its metric and its gate. A field sent
    as null clears it; a field not sent stays."""
    model_config = {"extra": "forbid"}
    segment: Optional[str] = Field(default=None, max_length=100)
    metric: Optional[str] = Field(default=None, max_length=60)
    gate_threshold: Optional[float] = Field(default=None, allow_inf_nan=False)
    gate_budget_decision: Optional[str] = Field(default=None, max_length=claim_matching.BUDGET_DECISION_MAX)
    gate_date: Optional[str] = None
    gate_metric_name: Optional[str] = Field(default=None, max_length=claim_matching.GATE_METRIC_MAX)
    gate_direction: Optional[Literal["at least", "at most"]] = None
    key_gate: Optional[bool] = None

    @field_validator("gate_date")
    @classmethod
    def _iso_date(cls, v):
        if v is not None:
            if not _GATE_DATE.match(v):
                raise ValueError("a date as YYYY-MM-DD")
            year = datetime.strptime(v, "%Y-%m-%d").year
            if not 2000 <= year <= 2100:
                raise ValueError(f"gate_date year must be between 2000 and 2100, got {year}")
        return v


@api.put("/audits/{audit_id}/claims/{claim_id}")
async def update_claim_inputs(audit_id: str, claim_id: str, payload: ClaimInputs):
    """Store the analyst's segment, metric or gate for one claim of the register, on the candidate's row, and give the
    register back. The claim's text, value and period are edited in the approval list, not here."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    sent = payload.model_fields_set
    if not sent:
        raise HTTPException(400, "Nothing to change")
    if not audit.get("results"):
        raise HTTPException(409, "Audit not computed yet")
    claims, rows = await _claim_rows(audit_id, audit)
    row = next((r for r in rows if r["claim_id"] == claim_id), None)
    if row is None:
        raise HTTPException(404, "Claim not in the register")
    values = {k: getattr(payload, k) for k in sent}
    for text_field in ("gate_budget_decision", "gate_metric_name"):
        if isinstance(values.get(text_field), str):
            values[text_field] = values[text_field].strip() or None
    if values.get("key_gate") is False:
        values["key_gate"] = None                    # an unmarked gate is the default: the mark is cleared, not stored as false
    metric, segment = values.get("metric"), values.get("segment")
    if metric is not None and metric != claim_matching.NO_METRIC and \
            not claim_matching.fits_metric(metric, row["unit"], row["currency"]):
        raise HTTPException(400, "Choose a metric in the claim's unit, or none")
    if segment is not None and segment not in (claim_matching.WHOLE, claim_matching.NOT_IN_DATA,
                                               *claim_matching.data_segments(audit["results"])):
        raise HTTPException(400, "Choose a segment of the data, Whole company or Not in the data")
    candidate = next(c for c in claims if c["id"] == claim_id.split("#")[0])
    inputs = {**(candidate.get("claim_inputs") or {})}
    kept = {**inputs.get(claim_id, {}), **{k: v for k, v in values.items() if v is not None}}
    for k, v in values.items():
        if v is None:
            kept.pop(k, None)
    if kept:
        inputs[claim_id] = kept
    else:
        inputs.pop(claim_id, None)
    if values.get("key_gate"):
        # A key gate is a saved gate, and at most 5 are marked (verdict-and-memo.md section 3): tested on the row as it
        # would read after this change, before anything is written.
        trial = [{**c, "claim_inputs": inputs} if c["id"] == candidate["id"] else c for c in claims]
        current = await _current_audit(audit_id, audit, strict=False)
        after = claim_matching.build_register(trial, current.get("results"), _register_settings(audit, await _fx(audit_id, audit)))
        after_row = next(r for r in after if r["claim_id"] == claim_id)
        if not after_row["gate_saved"]:
            raise HTTPException(400, "A key gate needs a saved gate")
        if sum(1 for r in after if r["key_gate"]) > verdict_mod.MAX_KEY_GATES:
            raise HTTPException(400, verdict_mod.W5_SIXTH)
    await db[decks.CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": candidate["id"]},
                                                    {"$set": {"claim_inputs": inputs}})
    _, rows = await _claim_rows(audit_id, audit)
    return sanitize({"register": rows})


# ---------------------------------------------------------------------------
# Blockers: three kinds, and nothing else, at the top of every audit view (CLAUDE.md rule 21)
# ---------------------------------------------------------------------------
BLOCKER_KINDS = ("revenue_file_missing", "claim_contradicted", "revenue_reconciliation")
TOP_CLAIMS = 5


def _figure(value, unit, currency) -> str:
    """A claimed or observed figure for the banner: 1,200,000 EUR, 35%, 12 months."""
    if value is None:
        return "—"
    text = f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
    if unit == "%":
        return f"{text}%"
    return f"{text} {currency or unit}".strip() if (currency or unit) else text


@api.get("/audits/{audit_id}/blockers")
async def audit_blockers(audit_id: str):
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    return sanitize({"blockers": await _blocker_list(audit_id, audit)})


async def _blocker_list(audit_id: str, audit: dict) -> list:
    """The banner's hard blockers. The claim blocker reads rows 1-5 of the pre-sort, so the analyst's top 5 never hides one
    (docs/specs/verdict-and-memo.md section 6.1)."""
    audit = await _current_audit(audit_id, audit, strict=False)
    out = []
    revenue = await db.datasets.find_one({"audit_id": audit_id, "dtype": "revenue"}, {"_id": 0, "mapped_at": 1})
    if not revenue:
        out.append({"kind": "revenue_file_missing", "text": "Revenue file missing: upload and map it to compute metrics."})
    elif not revenue.get("mapped_at"):
        # The file is there; its mapping waits for the analyst. Still the same hard blocker, worded as what is left to do.
        out.append({"kind": "revenue_file_missing", "text": "Revenue file uploaded – confirm the mapping to compute metrics."})
    if audit.get("results"):
        _, rows = await _claim_rows(audit_id, audit)
        for r in rows:
            if r["rank"] is not None and r["rank"] <= TOP_CLAIMS and r["evidence_label"] == "Contradicted":
                claimed = _figure(r["claimed_value"], r["unit"], r["currency"])
                if r.get("claimed_high") is not None:
                    claimed = f"{claimed}–{_figure(r['claimed_high'], r['unit'], r['currency'])}"
                reporting = audit.get("reporting_currency")
                claimed += claim_matching.converted_note(r, lambda v: _figure(v, None, reporting))
                # An amount is observed in the audit's currency, whatever currency the deck states the claim in.
                observed_currency = reporting if (claim_matching.METRICS.get(r.get("metric") or "") or {}).get("unit") == "currency" \
                    else r["currency"]
                out.append({"kind": "claim_contradicted", "citation": r["observed_source"], "claim_id": r["claim_id"],
                            "text": f"Top-5 claim contradicted: {r['claim_type']} {claimed} vs "
                                    f"{_figure(r['observed_value'], r['unit'], observed_currency)} observed "
                                    f"({r['deck_file']}, {r['page_ref']})."})
    rec = (audit.get("results") or {}).get("revenue_reconciliation")
    if rec and rec.get("available") and rec.get("blocker"):
        pct = "—" if rec["gap_pct"] is None else f"{abs(rec['gap_pct']) * 100:g}"    # a fraction, shown as a percent
        ccy = audit.get("reporting_currency") or ""
        out.append({"kind": "revenue_reconciliation", "citation": rec["source"], "link": f"/audit/{audit_id}/diagnostics",
                    "text": f"Revenue file and P&L differ by {pct}% over {rec['first']}–{rec['last']} "
                            f"({rec['file_total']:,.0f} {ccy} vs {rec['pnl_total']:,.0f} {ccy})."})
    return out


# ---------------------------------------------------------------------------
# Verdict and IC memo (docs/specs/verdict-and-memo.md): computed on read from the register, the results and the analyst's
# inputs on the audit (`ic_inputs`). No model call, nothing stored but the inputs.
# ---------------------------------------------------------------------------
@api.get("/audits/{audit_id}/verdict")
async def get_verdict(audit_id: str):
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    ctx = await _ic_context(audit_id, audit)
    rows, ic = ctx["rows"], ctx["ic"]
    ver = verdict_mod.verdict(rows, ctx["results"], ic.get("top5"))
    if ctx["contract"]:
        ver = {**ver, "status": "no_verdict", "message": ic_memo.CONTRACT_NO_VERDICT.format(fields=ctx["contract"])}
    key = verdict_mod.key_gates(rows)
    # Codes and counts only: no value, gate, thesis, metric name, company or file name reaches the log.
    top5 = claim_matching.label_counts([r for r in rows if r["claim_id"] in set(ver["top5"]["claim_ids"])])
    confirmed = ver["top5"]["confirmed"]
    blocked = ver["status"] == "blocked"
    logger.info("verdict: run_id=%s outcome=%s blocked=%s top5=%s confirmed=%s", audit_id, ver["outcome_code"], blocked, top5, confirmed)
    return sanitize({
        "verdict": ver, "data_gaps": ctx["gaps"], "top_gaps": verdict_mod.top_gaps(ctx["gaps"]),
        "key_gates": {"note": key["note"], "ok": key["ok"], "all_key": key["all_key"], "saved": key["saved"],
                      "sentences": [{"claim_id": g["claim_id"], "rank": g["rank"], "sentence": g["gate_sentence"]} for g in key["gates"]]},
        "gates_still_needed": verdict_mod.gates_still_needed(rows, ver["top5"]["in_force"]),
        "deal_terms": verdict_mod.W13_DEAL_TERMS, "top5_statement": verdict_mod.W24_STATEMENT,
        "candidates": [{"claim_id": r["claim_id"], "rank": r["rank"], "claim": verdict_mod.claim_name(r),
                        "evidence_label": r["evidence_label"], "reason": r["reason"]} for r in rows],
        "ic_inputs": {k: ic.get(k) for k in ("first_quarterly_review", "ratings", "thesis")},
        "ratings": list(verdict_mod.RATINGS), "ratings_for": {k: ic_memo.RATING_LABELS[k] for k in verdict_mod.RATED_ROWS},
        "thesis_labels": ic_memo.THESIS_LABELS, "thesis_max": verdict_mod.THESIS_MAX,
    })


class IcInputs(BaseModel):
    """The analyst's inputs to the verdict and the memo. A key sent as null clears it; a key not sent stays."""
    model_config = {"extra": "forbid"}
    top5: Optional[List[str]] = None
    first_quarterly_review: Optional[str] = None
    gap_target_dates: Optional[dict] = None
    ratings: Optional[dict] = None
    thesis: Optional[dict] = None

    @field_validator("first_quarterly_review")
    @classmethod
    def _iso_review(cls, v):
        if v is not None and not verdict_mod.valid_date(v):
            raise ValueError("a date as YYYY-MM-DD")
        return v

    @field_validator("gap_target_dates")
    @classmethod
    def _iso_gaps(cls, v):
        for item, day in (v or {}).items():
            if day is not None and not verdict_mod.valid_date(day):
                raise ValueError("a date as YYYY-MM-DD")
        return v

    @field_validator("ratings")
    @classmethod
    def _known_ratings(cls, v):
        for row, rating in (v or {}).items():
            if row not in verdict_mod.RATED_ROWS or (rating is not None and rating not in verdict_mod.RATINGS):
                raise ValueError("a rating is Strong, Adequate or Weak, on the two assessed rows")
        return v

    @field_validator("thesis")
    @classmethod
    def _known_thesis(cls, v):
        for part, text in (v or {}).items():
            if part not in verdict_mod.THESIS_PARTS or (text is not None and (not isinstance(text, str) or len(text) > verdict_mod.THESIS_MAX)):
                raise ValueError(f"the thesis is Plan, Evidence and Condition, each at most {verdict_mod.THESIS_MAX} characters")
        return v


@api.put("/audits/{audit_id}/ic-inputs")
async def put_ic_inputs(audit_id: str, payload: IcInputs):
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    sent = payload.model_fields_set
    if not sent:
        raise HTTPException(400, "Nothing to change")
    ctx = await _ic_context(audit_id, audit, validate=False)       # storing an input reads no figure; the verdict and the memo validate
    if "top5" in sent and not ctx["rows"]:
        raise HTTPException(409, "The register has no claims")
    try:
        ic = verdict_mod.apply_ic_inputs(ctx["ic"], {k: getattr(payload, k) for k in sent}, ctx["rows"], ctx["gaps"],
                                         datetime.now(timezone.utc).isoformat())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await db.audits.update_one({"id": audit_id}, {"$set": {"ic_inputs": ic}})
    return await get_verdict(audit_id)


def _memo_filename(company: str) -> str:
    safe = "".join(c for c in (company or "audit") if c.isalnum() or c in " -_").strip().replace(" ", "_")
    return f"{safe or 'audit'}_ic_memo.md"


@api.get("/audits/{audit_id}/memo.md")
async def export_memo(audit_id: str):
    """The IC memo as Markdown, built now from the stored data and never stored (verdict-and-memo.md section 7). Refused, with
    the reason named and nothing written, when it cannot be built."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    ctx = await _ic_context(audit_id, audit)
    rows, results = ctx["rows"], ctx["results"]
    refusal = None
    text = ""
    try:
        if ctx["contract"]:
            raise ic_memo.MemoRefused("contract", ic_memo.W19_CONTRACT.format(fields=ctx["contract"]))
        if not results:
            raise ic_memo.MemoRefused("no_verdict", ic_memo.WORDING_NOT_IN_W["no_verdict"].format(message="compute the audit first."))
        try:
            narratives = [n.model_dump() for n in await llm_gateway.narratives_for_run(db, audit_id)]
        except Exception:                                 # the memo never depends on the narrative service
            narratives = []
        usage = (await llm_gateway.usage_for_run(db, audit_id)).model_dump()
        datasets = await db.datasets.find({"audit_id": audit_id}, {"dtype": 1, "file": 1, "sheet": 1, "_id": 0}).to_list(10)
        deck_docs = await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, {"file": 1, "_id": 0}).to_list(100)
        meta = {**audit, "results": results}
        try:
            tables = ic_memo.workbook_tables(build_export_workbook(meta, results))
        except (contract.ContractError, fmt.UnitError):
            tables = []                                   # the memo itself refuses on the contract before it reads a figure
        text = ic_memo.build_memo(
            audit=audit, results=results, rows=rows, ver=verdict_mod.verdict(rows, results, ctx["ic"].get("top5")),
            key=verdict_mod.key_gates(rows), gaps=ctx["gaps"], ic=ctx["ic"],
            blockers=await _blocker_list(audit_id, audit), narratives=narratives, usage=usage,
            files=[{"dtype": d["dtype"], "file": d.get("file"), "sheet": d.get("sheet")} for d in datasets],
            decks=[{"file": d.get("file")} for d in deck_docs], tables=tables, today=datetime.now(timezone.utc).date().isoformat())
    except ic_memo.MemoRefused as exc:
        refusal = exc
    words = ic_memo.word_count_of(text) if text else (refusal.words or 0)
    logger.info("memo export: run_id=%s status=%s reason=%s words=%d unmatched=%d", audit_id, "refused" if refusal else "ok",
                refusal.code if refusal else "none", words, len(refusal.unmatched) if refusal else 0)
    if refusal:
        raise HTTPException(409, refusal.message)
    return Response(content=text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{_memo_filename(audit.get("company_name"))}"'})


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------
# Setup inputs that change what a computed audit's metrics should be. A change
# to any of these on an already-computed audit means the stored results are
# stale until recomputed (see _mark_stale_and_maybe_recompute).
RECOMPUTE_TRIGGER_FIELDS = {"reporting_currency", "target_arr", "target_date", "as_of_month"}


async def _run_compute(audit_id: str) -> dict:
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    ds = {d["dtype"]: d for d in await db.datasets.find({"audit_id": audit_id}).to_list(10)}
    if "revenue" not in ds:
        raise HTTPException(409, "Revenue lines are required before compute")
    for d in ds.values():          # a file read by the chat upload waits for the analyst (chat-upload.md section 4.3)
        states = d.get("columns_state")
        if states is not None and cr.pending_count(states):
            raise HTTPException(409, "Columns wait for your decision before compute")
        if states is not None and cr.missing_required(d["dtype"], states):
            raise HTTPException(409, "A required field is not mapped")

    rev = normalize(ds["revenue"]["rows"], "revenue", ds["revenue"]["mapping"], ds["revenue"].get("row_numbers"))
    crm = normalize(ds["crm"]["rows"], "crm", ds["crm"]["mapping"], ds["crm"].get("row_numbers")) if "crm" in ds else pd.DataFrame()
    pnl = normalize(ds["pnl"]["rows"], "pnl", ds["pnl"]["mapping"], ds["pnl"].get("row_numbers")) if "pnl" in ds else pd.DataFrame()

    fx = {k.upper(): float(v) for k, v in ds["revenue"].get("fx", {}).items()}
    fx[a["reporting_currency"].upper()] = 1.0
    config = {
        "reporting_currency": a["reporting_currency"], "target_arr": a["target_arr"],
        "target_date": a["target_date"], "fx": fx,
        "billing_terms": ds["revenue"].get("billing_terms", {}), "default_l": 1,
        "as_of_month": a.get("as_of_month"),
    }
    sources = {t: {"file": ds[t]["file"], "sheet": ds[t]["sheet"]} for t in ds}
    failures = []

    def on_error(exc):
        failures.append(type(exc).__name__)
        _log_metric_error(exc, audit_id)
    try:
        results = sanitize(ge.compute_all(rev, crm, pnl, config, sources, files=candidate_views(ds), on_error=on_error))
    except Exception as exc:
        await _usage_update(audit_id, lambda u: usage_mod.record_compute(u, failures + [type(exc).__name__]))
        raise
    await _usage_update(audit_id, lambda u: usage_mod.record_compute(u, failures))
    await db.audits.update_one(
        {"id": audit_id},
        {"$set": {"results": results, "status": "computed", "computed_at": datetime.now(timezone.utc).isoformat(),
                  "metrics_stale": False}},
    )
    return results


async def _current_audit(audit_id: str, audit: dict, strict: bool = True) -> dict:
    """The audit with results of the current engine contract (schemas/metrics.py). Results stored before it hold
    whole-number percents, which every reader would show 100 times too large; they are recomputed from the stored files
    on first read (deterministic Python, no model, no cost). If that is not possible the read fails (409), or with
    strict=False the audit is returned without results: they are never shown, and a caller that must keep working (the
    banner, the usage totals) reads "not computed" instead of a figure 100 times too large."""
    results = audit.get("results")
    if not results or results.get("contract_version") == contract.CONTRACT_VERSION:
        return audit
    try:
        results = await _run_compute(audit_id)
    except HTTPException:
        if strict:
            raise HTTPException(409, "Results predate the current engine contract; recompute needed")
        return {**audit, "results": None}
    return {**audit, "results": results, "metrics_stale": False}


async def _recompute_if_old(audit_id: str) -> None:
    """Results stored before the engine contract are recomputed before the gateway reads them, so a narrative is never
    refused for a payload the dashboard is about to replace. A recompute that is not possible is left to the gateway,
    which refuses the old payload."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0, "id": 1, "results": 1})
    if audit and audit.get("results"):
        await _current_audit(audit_id, audit, strict=False)


@api.post("/audits/{audit_id}/compute")
async def compute_audit(audit_id: str):
    return await _run_compute(audit_id)


async def _mark_stale_and_maybe_recompute(audit_id: str):
    """A setup input (mapping, FX rate, billing terms, target, as-of month, ...)
    changed. If the audit was already computed, recompute it automatically so it
    never silently shows stale results. If recompute isn't possible right now
    (e.g. a required mapping was cleared), leave metrics_stale set so the UI can
    show a warning instead of outdated numbers."""
    a = await db.audits.find_one({"id": audit_id})
    if not a or a.get("status") != "computed":
        return
    await db.audits.update_one({"id": audit_id}, {"$set": {"metrics_stale": True}})
    try:
        await _run_compute(audit_id)
    except HTTPException:
        pass
    except Exception as exc:
        # An engine error must not fail the upload or setup change that triggered
        # the recompute. metrics_stale stays set, so the UI warns instead. The log
        # carries the error type, run id and engine step only: the exception message
        # and traceback can quote uploaded cell values.
        logger.error("auto-recompute failed: error=%s run_id=%s step=%s; results left marked stale",
                     type(exc).__name__, audit_id, _engine_step(exc))


def _log_metric_error(exc: BaseException, run_id: str) -> None:
    """One metric failed and is reported as Missing; the rest of the run went on. Error type,
    run id and engine step only: the message and traceback can quote uploaded cell values."""
    logger.error("metric failed: error=%s run_id=%s step=%s; reported as Missing",
                 type(exc).__name__, run_id, _engine_step(exc))


def _engine_step(exc: BaseException) -> str:
    """The deepest growth_engine function the error passed through (a code name, never data)."""
    step = "_run_compute"
    tb = exc.__traceback__
    while tb is not None:
        code = tb.tb_frame.f_code
        if Path(code.co_filename).name == "growth_engine.py" and not code.co_name.startswith("<"):  # not <dictcomp>
            step = code.co_name
        tb = tb.tb_next
    return step


@api.get("/audits/{audit_id}/results")
async def get_results(audit_id: str):
    a = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Audit not found")
    if not a.get("results"):
        raise HTTPException(409, "Audit not computed yet")
    a = await _current_audit(audit_id, a)
    keys = ("id", "company_name", "reporting_currency", "target_arr", "target_date", "as_of_month", "status", "computed_at",
            "metrics_stale")
    return sanitize({"audit": {k: a.get(k) for k in keys}, "results": a["results"]})


def build_export_workbook(meta: dict, r: dict, disclosure_text: Optional[str] = None,
                          narratives: Optional[list] = None) -> io.BytesIO:
    """Numeric cells with Excel number formats (see app/formatting.py), so the
    display follows the formatting rules while analysts can still sum and sort."""
    contract.validate_for_export(r)    # schema, then the unit check; ContractError before any cell is written
    ccy = r.get("reporting_currency", "")
    cur = ccy or None                  # the currency code is a unit: last in the label's one bracket
    lab = fmt.label_with               # the shared label builder - one bracket, fixed order
    qual = fmt.qualifier_for           # qualifiers come from the shared map, so tile, table and export agree

    def kv_sheet(xw, sheet, rows):
        """rows: (label, kind, value); kind None means the value is text."""
        df = pd.DataFrame(
            [(label, v if kind is None else fmt.xlsx_value(kind, v)) for label, kind, v in rows],
            columns=["Metric", "Value"],
        )
        df.to_excel(xw, sheet_name=sheet, index=False)
        ws = xw.sheets[sheet]
        for i, (_, kind, _) in enumerate(rows, start=2):
            if kind is not None:
                ws.cell(row=i, column=2).number_format = fmt.XLSX_NUMBER_FORMAT[kind]

    def table_sheet(xw, sheet, df, kinds, startrow=0):
        """kinds: {column: kind}; the rest of the columns are written as-is."""
        df = df.copy()
        for col, kind in kinds.items():
            if col in df.columns:
                df[col] = df[col].map(lambda v, k=kind: fmt.xlsx_value(k, v))
        df.to_excel(xw, sheet_name=sheet, index=False, startrow=startrow)
        ws = xw.sheets[sheet]
        for col, kind in kinds.items():
            if col in df.columns:
                c = list(df.columns).index(col) + 1
                for row in range(startrow + 2, startrow + 2 + len(df)):
                    ws.cell(row=row, column=c).number_format = fmt.XLSX_NUMBER_FORMAT[kind]

    def write_narrative_sheet(xw, resp, meta, results):
        """One sheet for one generated narrative: what it was written against, then six sections."""
        from openpyxl.styles import Alignment, Font

        narrative = resp.narrative
        name = narrative_export.sheet_name(resp.step)
        ws = xw.book.create_sheet(name)
        bold, wrap = Font(bold=True), Alignment(wrap_text=True, vertical="top")
        for col, width in zip("ABCD", (34, 90, 46, 24)):
            ws.column_dimensions[col].width = width
        row = [1]

        def put(col, text, font=None):
            cell = ws.cell(row=row[0], column=col)
            cell.value = text
            if isinstance(text, str) and text[:1] in ("=", "+", "-", "@"):
                cell.data_type = "s"          # narrative text is never a formula
            cell.alignment = wrap
            if font:
                cell.font = font
            return cell

        def line(label=None, text=None):
            if label is not None:
                put(1, label, bold)
            if text is not None:
                put(2, text)
            row[0] += 1

        put(1, f"{disclosure_mod.STEP_LABELS.get(resp.step, resp.step)} narrative", Font(bold=True, size=13))
        row[0] += 1
        for label, text in narrative_export.written_against(meta, results):
            line(label, text)
        row[0] += 1
        if resp.narrative_status == "flagged" and resp.unmatched_numbers:
            line("Unverified figures",
                 f"Unverified figures in this text: {', '.join(resp.unmatched_numbers)}. Numbers in the headline and "
                 "evidence table are verified against the calculation engine; these are not.")
            row[0] += 1
        line("Headline", narrative.headline)
        line("What this means", narrative.what_this_means)
        row[0] += 1
        line("Evidence table")
        for col, head in enumerate(("Metric", "Value", "Source key", "Where to find the number"), start=1):
            put(col, head, bold)
        row[0] += 1
        for tr in narrative.table_rows:
            put(1, (resp.row_labels or {}).get(tr.source_key) or fmt.display_name(tr.source_key, tr.label))
            put(2, tr.value)
            put(3, tr.source_key)
            sheet = narrative_export.data_sheet_for(tr.source_key, results)
            put(4, sheet)
            row[0] += 1
        if not narrative.table_rows:
            line(None, "No evidence rows.")
        row[0] += 1
        for title, items in (("Worth flagging", narrative.worth_flagging),
                             ("Next actions", narrative.next_actions),
                             ("Source keys", narrative.source_keys)):
            if not items:
                line(title, "None")
            for i, item in enumerate(items):
                put(1, title if i == 0 else None, bold)
                put(2, item if title == "Source keys" else f"{i + 1}. {item}")
                row[0] += 1
            row[0] += 1

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        # Headline
        arr = r.get("arr") or {}
        nrr = r.get("nrr") or {}
        churn = r.get("gross_churn") or {}
        sc = r.get("sales_cycle") or {}
        wr = r.get("win_rate") or {}
        cac = r.get("cac_payback") or {}
        # Headline is the latest COMPLETE quarter (a partial quarter overstates payback and is
        # never a headline); the quarter is named so an older figure is not read as current.
        cac_label, cac_value = lab("CAC payback", "no complete quarter", unit="months"), None
        if cac:
            L = f"L{cac.get('default_l', 1)}"
            hq = cac.get("headline_quarter")
            if hq is None and "headline_quarter" not in cac:  # results computed before partial quarters were flagged
                done = [q for q in sorted(cac.get("quarters", {}))
                        if not cac["quarters"][q].get("partial") and cac["quarters"][q][L]["months"] is not None]
                hq = done[-1] if done else None
            if hq:
                cac_value = cac["quarters"][hq][L]["months"]
                cac_label = lab("CAC payback", hq, qual("months"), unit="months")
        kv_sheet(xw, "Headline", [
            ("Company", None, meta.get("company_name")),
            ("As-of month", None, meta.get("as_of_month") or r.get("as_of_month")),
            ("Reporting currency", None, ccy),
            (lab("Ending ARR", unit=cur), fmt.CURRENCY, arr.get("value")),
            (lab("Current MRR", unit=cur), fmt.CURRENCY, arr.get("mrr")),
            ("ARR month", None, arr.get("month")),
            ("NRR overall", fmt.PCT, nrr.get("overall_pct")),
            ("Gross revenue churn", fmt.PCT, churn.get("overall_pct")),
            (cac_label, fmt.MONTHS, cac_value),
            (lab("S&M spend lag used for CAC payback", unit="quarters"), fmt.PLAIN, cac.get("default_l") if cac else None),
            (lab("Median sales cycle", unit="days"), fmt.DAYS, sc.get("median_days")),
            ("Win rate", fmt.PCT, wr.get("win_rate_pct")),
            ("Deals excluded (close<created)", fmt.COUNT, wr.get("excluded_invalid")),
        ])
        for n in narratives or []:
            write_narrative_sheet(xw, n, meta, r)
        if disclosure_text:
            # Foot of the summary sheet: the same block the dashboard shows (app/disclosure.py).
            ws = xw.sheets["Headline"]
            ws.cell(row=ws.max_row + 2, column=1).value = "AI disclosure"
            ws.cell(row=ws.max_row, column=2).value = disclosure_text

        # By segment
        seg_rows = {}
        for seg, v in (nrr.get("by_segment") or {}).items():
            seg_rows.setdefault(seg, {})["NRR"] = v.get("nrr_pct")
            seg_rows[seg]["NRR base n"] = v.get("nrr_base_customers", v.get("n"))
        for seg, v in (sc.get("by_segment") or {}).items():
            seg_rows.setdefault(seg, {})[lab("Sales cycle median", unit="days")] = v.get("median_days")
            seg_rows[seg]["Sales cycle n"] = v.get("n")
        for seg, v in ((r.get("acv_path") or {}).get("by_segment") or {}).items():
            seg_rows.setdefault(seg, {})["Customers"] = v.get("customers")
            seg_rows[seg][lab("ACV", qual("acv"), unit=cur)] = v.get("acv")
            seg_rows[seg][lab("ARR", unit=cur)] = v.get("arr")
        if seg_rows:
            table_sheet(xw, "By Segment", pd.DataFrame([{"Segment": s, **vals} for s, vals in seg_rows.items()]), {
                "NRR": fmt.PCT, "NRR base n": fmt.COUNT, lab("Sales cycle median", unit="days"): fmt.DAYS,
                "Sales cycle n": fmt.COUNT, "Customers": fmt.COUNT,
                lab("ACV", qual("acv"), unit=cur): fmt.CURRENCY, lab("ARR", unit=cur): fmt.CURRENCY,
            })
        else:
            pd.DataFrame([{"Segment": "(no segment column mapped)"}]).to_excel(xw, sheet_name="By Segment", index=False)

        # NRR by cohort
        if nrr.get("by_cohort"):
            table_sheet(xw, "NRR by Cohort", pd.DataFrame(
                [{"Cohort": k, "NRR": v.get("nrr_pct"), "NRR base customers": v.get("nrr_base_customers", v.get("n")), "Note": v.get("reason")}
                 for k, v in nrr["by_cohort"].items()]
            ), {"NRR": fmt.PCT, "NRR base customers": fmt.COUNT})
        else:
            pd.DataFrame([{"Cohort": "(not computable)"}]).to_excel(xw, sheet_name="NRR by Cohort", index=False)

        # NRR series
        series_df = pd.DataFrame(nrr.get("series") or [], columns=["month", "nrr_pct"])
        if series_df.empty:
            pd.DataFrame([{"month": "(not computable)"}]).to_excel(xw, sheet_name="NRR Series", index=False)
        else:
            table_sheet(xw, "NRR Series", series_df, {"nrr_pct": fmt.PCT})

        # CAC by quarter
        cac_rows = []
        for q, v in (cac.get("quarters") or {}).items():
            row = {"Quarter": q,
                   "Quarter status": (f"partial ({v.get('months_in_quarter')} of 3 months)" if v.get("partial") else "complete"),
                   lab("New MRR", unit=cur): v.get("new_mrr"), "Gross margin": v.get("gross_margin_pct")}
            for L in ("L0", "L1", "L2"):
                row[f"{L} months"] = v[L].get("months")
                row[lab(f"{L} S&M used", unit=cur)] = v[L].get("sm_expense")
                row[f"{L} reason"] = v[L].get("reason")
            cac_rows.append(row)
        if cac_rows:
            kinds = {lab("New MRR", unit=cur): fmt.CURRENCY, "Gross margin": fmt.PCT}
            for L in ("L0", "L1", "L2"):
                kinds[f"{L} months"] = fmt.MONTHS
                kinds[lab(f"{L} S&M used", unit=cur)] = fmt.CURRENCY
            table_sheet(xw, "CAC by Quarter", pd.DataFrame(cac_rows), kinds)
        else:
            pd.DataFrame([{"Quarter": "(P&L not provided)"}]).to_excel(xw, sheet_name="CAC by Quarter", index=False)

        # Path to plan
        ap = r.get("acv_path") or {}
        kv_sheet(xw, "Path to Plan", [
            ("Current customers", fmt.COUNT, ap.get("current_customers")),
            (lab("Current ARR", unit=cur), fmt.CURRENCY, ap.get("current_arr")),
            (lab("ACV", qual("acv"), unit=cur), fmt.CURRENCY, ap.get("acv")),
            (lab("Target ARR", unit=cur), fmt.CURRENCY, ap.get("target_arr")),
            ("Target date", None, ap.get("target_date")),
            (fmt.display_name("total_customers_at_target"), fmt.COUNT_UP,
             ap.get("total_customers_at_target", ap.get("customers_needed"))),
            (fmt.display_name("additional_customers_needed"), fmt.COUNT_UP, ap.get("additional_customers_needed")),
            ("Required net-new / year", fmt.COUNT_UP, ap.get("required_net_new_per_year")),
            (lab("Observed net-new / year", "12m"), fmt.COUNT, ap.get("observed_net_new_per_year_12m")),
            (lab("Observed net-new / year", "24m"), fmt.COUNT, ap.get("observed_net_new_per_year_24m")),
            (lab("Required ÷ observed", "12m"), fmt.RATIO, ap.get("required_vs_observed_12m")),
            (lab("Required ÷ observed", "24m"), fmt.RATIO, ap.get("required_vs_observed_24m")),
        ])

        # ACV bands (hide empty bands, keep fixed low-to-high display order)
        as_of = meta.get("as_of_month") or r.get("as_of_month") or ""
        band_rows = [
            {"Band": b["label"], "ACV range": fmt.band_range_label(b.get("low"), b.get("high"), ccy), "Customers": b["count"]}
            for b in (ap.get("bands") or []) if b.get("count")
        ]
        if band_rows:
            table_sheet(xw, "ACV Bands", pd.DataFrame(band_rows), {"Customers": fmt.COUNT}, startrow=1)
        else:
            pd.DataFrame([{"Band": "(no active customers)"}]).to_excel(xw, sheet_name="ACV Bands", index=False, startrow=1)
        xw.sheets["ACV Bands"]["A1"] = f"ACV Bands — active customers (as of {as_of})"

        # Segment mix paths to target ARR (segments only; ACV bands are a separate cut).
        sp = r.get("segment_paths") or {}
        if sp.get("stage_one"):
            so = sp["stage_one"]
            rows_ = [{"Segment": seg, lab("Starting ARR", unit=cur): v["start_arr"], "Customers": v["customers"],
                      fmt.display_name("nrr.overall_pct"): v["nrr_pct"], "NRR base customers": v["nrr_base_customers"],
                      lab("Projected ARR", qual("projected_arr"), unit=cur): v["projected_arr"],
                      lab("Change in ARR", qual("change_arr"), unit=cur): v["change_arr"],
                      lab("ARR change per NRR point", qual("arr_change_per_nrr_point"), unit=cur): v["arr_change_per_nrr_point"],
                      "Small base": "yes (fewer than 10)" if v["small_base"] else "no"}
                     for seg, v in so["segments"].items()]
            rows_.append({"Segment": "All segments", lab("Starting ARR", unit=cur): so["start_arr_total"],
                          lab("Projected ARR", qual("projected_arr"), unit=cur): so.get("projected_base_arr"),
                          lab("Change in ARR", qual("change_arr"), unit=cur): (
                              so["projected_base_arr"] - so["start_arr_total"] if so.get("projected_base_arr") is not None else None)})
            table_sheet(xw, "Segment Base", pd.DataFrame(rows_), {
                lab("Starting ARR", unit=cur): fmt.CURRENCY, "Customers": fmt.COUNT, fmt.display_name("nrr.overall_pct"): fmt.PCT,
                "NRR base customers": fmt.COUNT, lab("Projected ARR", qual("projected_arr"), unit=cur): fmt.CURRENCY,
                lab("Change in ARR", qual("change_arr"), unit=cur): fmt.CURRENCY, lab("ARR change per NRR point", qual("arr_change_per_nrr_point"), unit=cur): fmt.CURRENCY,
            }, startrow=1)
            xw.sheets["Segment Base"]["A1"] = sp["assumption"]
            mix_rows = [
                ("Months to target date", fmt.MONTHS, sp.get("horizon_months")),
                (lab("Target ARR", unit=cur), fmt.CURRENCY, sp.get("target_arr")),
                (lab("Gap to target ARR", qual("gap_arr"), unit=cur), fmt.CURRENCY, sp.get("gap_arr")),
                (lab("ARR with no segment (excluded)", unit=cur), fmt.CURRENCY, sp.get("unsegmented_arr")),
                ("Customers with no segment (excluded)", fmt.COUNT, sp.get("unsegmented_customers")),
            ]
            detail = []
            for w, rs in (sp.get("reverse_solve") or {}).items():
                tag = f"{w}-month window"
                if not rs.get("computable") or rs.get("target_met_by_base"):
                    mix_rows.append((lab("Reverse-solve", tag), None, rs.get("reason") or "not computable"))
                    continue
                verdict = {True: "yes", False: "no"}.get(rs.get("reachable"), f"undetermined: {rs.get('reason')}")
                mix_rows += [
                    (lab("Gross new customers per year", tag), fmt.COUNT, rs.get("gross_new_per_year")),
                    (lab("Gross new customers by target date", tag), fmt.COUNT_UP, rs.get("new_customers_by_target")),
                    (lab("Required blended landed ACV", tag, unit=cur), fmt.CURRENCY, rs.get("required_blended_landed_acv")),
                    (lab("Best segment landed ACV", tag, unit=cur), fmt.CURRENCY, rs.get("best_segment_landed_acv")),
                    (lab("Any segment mix reaches it", tag), None, verdict),
                    (lab("Landed ACV at current mix", tag, unit=cur), fmt.CURRENCY, rs.get("current_mix_landed_acv")),
                    (lab("Total mix moved", tag, unit="percentage points"), fmt.PCT, rs.get("moved_mix_pct")),
                    (lab("Gross new customers per year needed at current mix", tag), fmt.COUNT_UP, rs.get("required_new_per_year_at_current_mix")),
                    (lab("Needed vs observed gross new customers", tag), fmt.RATIO, rs.get("required_vs_observed_gross")),
                ]
                for seg, v in (rs.get("by_segment") or {}).items():
                    landed = ((sp.get("landed") or {}).get(w) or {}).get("segments", {}).get(seg, {})
                    detail.append({lab("Window", unit="months"): int(w), "Segment": seg,
                                   "Gross new customers": landed.get("new_customers"), lab("Landed ACV", unit=cur): v.get("landed_acv"),
                                   "Current mix": v.get("current_mix_pct"), "Required mix": v.get("required_mix_pct"),
                                   lab("Shift vs current mix", unit="percentage points"): v.get("shift_pct_points")})
            for w, rc in (sp.get("reconciliation") or {}).items():
                if not rc.get("available"):
                    mix_rows.append((lab("Reconciliation of the simple and segment views", f"{w}-month window"), None,
                                     rc.get("reason") or "not available"))
                    continue
                for leaf in ("path_to_plan_ratio", "factor_compounded_base", "factor_landed_acv",
                             "factor_gross_rate", "segment_ratio"):
                    mix_rows.append((fmt.display_name(f"segment_paths.reconciliation.{w}.{leaf}"), fmt.RATIO, rc[leaf]))
            kv_sheet(xw, "Segment Mix", mix_rows)
            if detail:
                table_sheet(xw, "Segment Mix Detail", pd.DataFrame(detail), {
                    "Gross new customers": fmt.COUNT, lab("Landed ACV", unit=cur): fmt.CURRENCY, "Current mix": fmt.PCT,
                    "Required mix": fmt.PCT, lab("Shift vs current mix", unit="percentage points"): fmt.PCT,
                })
        elif sp:
            pd.DataFrame([{"Segment paths": "not available", "Missing": m["input"], "What would resolve it": m["resolve"]}
                          for m in sp.get("missing_inputs", [])]).to_excel(xw, sheet_name="Segment Base", index=False)

        # Anomalies
        an = r.get("anomalies")
        an_rows = [("Anomaly flags", "calculation error", "Not computed; see Missing Data")] if an is None else [
            ("Months with negative MRR", len(an.get("negative_mrr_months", [])), ", ".join(an.get("negative_mrr_months", []))),
            ("Customers with gaps > 2 months then resume", len(an.get("revenue_gap_then_resume", [])), ", ".join(an.get("revenue_gap_then_resume", [])[:50])),
            ("Revenue lines missing customer ID", an.get("revenue_missing_customer_id", {}).get("count"), ""),
            ("Deals close-before-created (excluded)", an.get("deals_close_before_created", {}).get("excluded_count"), ""),
            ("Date columns with day/month order set from the data", len(an.get("date_order_from_data", [])),
             "; ".join(f"{n['field']} ({n['dataset']}): {n['order']}, {n['rows']} rows" for n in an.get("date_order_from_data", []))),
        ]
        pd.DataFrame(an_rows, columns=["Flag", "Count", "Detail"]).to_excel(xw, sheet_name="Anomalies", index=False)

        # Missing data
        md = [{k: ("; ".join(f"{t}: {', '.join(f) or 'no usable rows'}" for t, f in v.items())
                   if k == "absent_fields" else v) for k, v in m.items()} for m in (r.get("missing_data") or [])]
        (pd.DataFrame(md) if md else pd.DataFrame([{"metric": "(none — all computed)"}])).to_excel(
            xw, sheet_name="Missing Data", index=False)
        pd.DataFrame(sorted(fmt.GLOSSARY.items()), columns=["Term", "Definition"]).to_excel(
            xw, sheet_name="Glossary", index=False)
    buf.seek(0)
    return buf


@api.get("/audits/{audit_id}/export")
async def export_audit(audit_id: str):
    a = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Audit not found")
    if not a.get("results"):
        raise HTTPException(409, "Audit not computed yet")
    a = await _current_audit(audit_id, a)
    try:
        narratives = await llm_gateway.narratives_for_run(db, audit_id)
    except Exception:  # the export never depends on the narrative service
        narratives = []
    block = llm_gateway.disclosure_from(narratives)
    try:
        buf = build_export_workbook(a, a["results"], block["text"] if block else None, narratives)
    except contract.ContractError as exc:
        safe = exc.log_text                  # field names and counts only (schemas/metrics.py), never a value
        logger.error("export blocked: run_id=%s: %s", audit_id, safe)
        raise HTTPException(500, f"Export blocked, no file written: {exc}")
    except fmt.UnitError:
        logger.error("export blocked: run_id=%s: a cell does not fit its unit", audit_id)
        raise HTTPException(500, "Export blocked, no file written: a cell does not fit its unit")
    await _usage_update(audit_id, lambda u: u.__setitem__("first_export_at", u["first_export_at"] or usage_mod.now()))
    safe = "".join(c for c in (a.get("company_name") or "audit") if c.isalnum() or c in " -_").strip().replace(" ", "_")
    fname = f"{safe or 'audit'}_growth_diligence.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------------------------------------------------------------------------
# LLM narrative gateway (the only component that calls a model provider)
# ---------------------------------------------------------------------------
@api.post("/runs/{run_id}/narrative/{step}")
async def generate_narrative(run_id: str, step: str):
    """Generate or return a cached narrative.

    Returns 200 with narrative_status="unavailable" on any LLM-side failure -
    the computed metrics still come back, so the dashboard is never blocked.
    """
    await _recompute_if_old(run_id)
    try:
        result = await llm_gateway.generate_narrative(db, run_id, step)
    except llm_gateway.GatewayError as exc:
        if exc.reason == "run_not_found":
            raise HTTPException(404, "Run not found")
        if exc.reason == "not_computed":
            raise HTTPException(409, "Run not computed yet")
        raise HTTPException(500, exc.reason)
    return sanitize(result.model_dump())


@api.get("/runs/{run_id}/narrative/{step}")
async def read_narrative(run_id: str, step: str):
    """Read-only: returns an existing narrative, or narrative_status="not_generated".

    Never calls a provider, so a dashboard load can never spend. Generation is
    the POST below, which is the only path that can.
    """
    await _recompute_if_old(run_id)
    try:
        result = await llm_gateway.read_cached_narrative(db, run_id, step)
    except llm_gateway.GatewayError as exc:
        if exc.reason == "run_not_found":
            raise HTTPException(404, "Run not found")
        if exc.reason == "not_computed":
            raise HTTPException(409, "Run not computed yet")
        raise HTTPException(500, exc.reason)
    return sanitize(result.model_dump())


@api.get("/runs/{run_id}/disclosure")
async def narrative_disclosure(run_id: str):
    """The AI-provenance block for this run (model and generation time), or null.

    Read-only; shared by the dashboard, the xlsx export and any memo export.
    """
    try:
        block = await llm_gateway.disclosure_for_run(db, run_id)
    except llm_gateway.GatewayError as exc:
        if exc.reason == "run_not_found":
            raise HTTPException(404, "Run not found")
        if exc.reason == "not_computed":
            return {"disclosure": None}
        raise HTTPException(500, exc.reason)
    return {"disclosure": block}


@api.get("/runs/{run_id}/llm-usage")
async def llm_usage(run_id: str):
    usage = await llm_gateway.usage_for_run(db, run_id)
    return sanitize(usage.model_dump())


app.include_router(api)


@app.middleware("http")
async def log_unexpected_errors(request, call_next):
    """Log any exception an endpoint does not handle, and answer with a readable 500.

    Without this an unhandled exception is answered by the server's outermost error layer,
    which sits outside CORS: the browser then sees a bare network failure with no status and
    no text. Registered before the CORS middleware, so this response carries CORS headers and
    the page can show the real status. Only the exception's class name is sent to the client
    and to the log: the message and traceback can quote uploaded cell values.
    """
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error("unexpected error handling %s %s: error=%s", request.method, request.url.path,
                     type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Unexpected server error ({type(exc).__name__}); the details are in the server log"},
        )


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# 4: demo audits carry a client name, consent and a fiscal year-end.
# 5: demo P&L revenue reconciles with the revenue file (one demo audit keeps a deliberate 5% gap).
# 6: results carry contract_version 1 (percents as fractions, whole counts and days).
# 7: results carry contract_version 2 (a citation on every result block).
# 8: demo audits carry no engagement reference (the field is gone).
SEED_VERSION = 8


@app.on_event("startup")
async def seed_demo():
    # The engagement reference is gone from the audit record (2026-10-08): audits created before keep no copy of it.
    await db.audits.update_many({"engagement_reference": {"$exists": True}}, {"$unset": {"engagement_reference": ""}})
    if await db.audits.count_documents({"seed_version": SEED_VERSION}) > 0:
        return
    demo_ids = {"audit_id": {"$in": [a["id"] for a in await db.audits.find({"demo": True}, {"id": 1}).to_list(50)]}}
    for name in ("datasets", decks.TEXT_COLLECTION, decks.CANDIDATES_COLLECTION, structures.COLUMN_MAPPINGS_COLLECTION):
        await db[name].delete_many(demo_ids)
    for audit in demo_ids["audit_id"]["$in"]:
        await llm_gateway.purge_run(db, audit)
    await db.audits.delete_many({"demo": True})
    for spec in demo_data.DEMO_AUDITS:
        datasets, meta = demo_data.build(spec)
        audit_id = str(uuid.uuid4())
        norm, uploads = {}, {}
        for dtype, (df, mapping) in datasets.items():
            recs = df_to_records(df)
            await db.datasets.replace_one(
                {"audit_id": audit_id, "dtype": dtype},
                {"audit_id": audit_id, "dtype": dtype, "file": meta[dtype]["file"], "sheet": meta[dtype]["sheet"],
                 "columns": list(df.columns), "rows": recs, "row_count": len(recs),
                 "mapping": mapping, "fx": meta.get("fx", {}), "billing_terms": {}, "preview": recs[:8],
                 "mapped_at": datetime.now(timezone.utc).isoformat()},
                upsert=True,
            )
            await _add_customers(audit_id, {"dtype": dtype, "columns": list(df.columns), "rows": recs, "mapping": mapping})
            norm[dtype] = normalize(recs, dtype, mapping)
            uploads[dtype] = {"file": meta[dtype]["file"], "sheet": meta[dtype]["sheet"], "columns": list(df.columns),
                              "rows": recs, "mapping": mapping}
        fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
        fx[spec["reporting_currency"].upper()] = 1.0
        config = {"reporting_currency": spec["reporting_currency"], "target_arr": spec["target_arr"],
                  "target_date": spec["target_date"], "fx": fx, "billing_terms": {}, "default_l": 1,
                  "as_of_month": None}
        sources = {t: {"file": meta[t]["file"], "sheet": meta[t]["sheet"]} for t in datasets}
        results = ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], config, sources,
                                 files=candidate_views(uploads),
                                 on_error=lambda exc: _log_metric_error(exc, audit_id))
        await db.audits.insert_one({
            "id": audit_id, "company_name": spec["company_name"], "reporting_currency": spec["reporting_currency"],
            "target_arr": spec["target_arr"], "target_date": spec["target_date"],
            "fiscal_year_end": spec["fiscal_year_end"], "client_name": spec["client_name"],
            "structure_reading_consent": True,
            "consent_log": [_consent_entry(True)],
            "created_at": datetime.now(timezone.utc).isoformat(), "status": "computed",
            "computed_at": datetime.now(timezone.utc).isoformat(), "results": sanitize(results), "demo": True,
            "seed_version": SEED_VERSION, "usage": usage_mod.empty(),
        })
    logger.info("Seeded demo audits")


@app.on_event("startup")
async def ensure_llm_indexes():
    await llm_gateway.guards.ensure_indexes(db)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
