from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import re
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
from app import formatting as fmt
from app import disclosure as disclosure_mod
from app import narrative_export
from app import decks
from app import structures
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
# Dataset field definitions (normalized names + fuzzy-match aliases)
# ---------------------------------------------------------------------------
FIELD_DEFS = {
    "revenue": {
        "required": {
            "customer_id": ["customer", "customer id", "account", "client", "cust"],
            "invoice_date": ["invoice date", "date", "billing date", "posted"],
            "amount": ["amount", "value", "revenue", "total", "arr", "mrr"],
            "currency": ["currency", "ccy", "curr"],
        },
        "optional": {
            "service_start": ["service start", "start date", "period start", "term start"],
            "service_end": ["service end", "end date", "period end", "term end"],
            "segment": ["segment", "tier", "size", "band"],
            "revenue_type": ["revenue type", "type", "recurring", "rec/one-off"],
        },
        "dates": ["invoice_date", "service_start", "service_end"],
        "numeric": ["amount"],
    },
    "crm": {
        "required": {
            "deal_id": ["deal id", "opportunity id", "deal", "id"],
            "created_date": ["created", "create date", "created date", "open date"],
            "close_date": ["close date", "closed", "won date", "close"],
            "stage": ["stage", "status", "outcome"],
            "amount": ["amount", "value", "deal value", "acv"],
        },
        "optional": {
            "segment": ["segment", "tier", "size"],
            "founder_involved": ["founder", "founder involved", "founder-led", "exec involved"],
        },
        "dates": ["created_date", "close_date"],
        "numeric": ["amount"],
    },
    "pnl": {
        "required": {
            "month": ["month", "period", "date", "fiscal month"],
            "sm_expense": ["sales & marketing", "s&m", "sales and marketing", "marketing expense", "sm expense"],
            "revenue": ["revenue", "total revenue", "sales", "turnover"],
            "cost_of_revenue": ["cost of revenue", "cogs", "cost of sales", "cost"],
        },
        "optional": {},
        "dates": ["month"],
        "numeric": ["sm_expense", "revenue", "cost_of_revenue"],
    },
}


def _score(field, alias, lc):
    if lc == alias:
        return 100
    if lc.startswith(alias) or alias.startswith(lc):
        return 80 if min(len(lc), len(alias)) >= 4 else 30
    if alias in lc:  # alias is a substring of the column header
        return 60
    if lc in alias and len(lc) >= 4:  # column header is a substring of the alias
        return 40
    return 0


def suggest_mapping(dtype: str, columns: list) -> dict:
    defs = FIELD_DEFS[dtype]
    all_fields = {**defs["required"], **defs["optional"]}
    lowered = {c.lower().strip(): c for c in columns}
    # score every (field, column) pair
    candidates = []
    for field, aliases in all_fields.items():
        for alias in [field.replace("_", " ")] + aliases:
            for lc, orig in lowered.items():
                s = _score(field, alias, lc)
                if s:
                    candidates.append((s, field, orig))
    candidates.sort(reverse=True, key=lambda x: x[0])
    mapping = {f: None for f in all_fields}
    used_cols = set()
    for s, field, col in candidates:
        if mapping[field] is None and col not in used_cols:
            mapping[field] = col
            used_cols.add(col)
    return mapping


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


def normalize(rows: list, dtype: str, mapping: dict) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    raw = pd.DataFrame(rows)
    defs = FIELD_DEFS[dtype]
    out = pd.DataFrame()
    out["_row"] = range(2, len(raw) + 2)
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
            views[as_type] = {"mapping": mapping, "frame": normalize(d.get("rows") or [], as_type, mapping)}
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
    # The investor commissioning the audit, and the engagement whose terms are the basis for sending
    # structures to the model (llm-structure-reading.md section 4). Neither ever reaches the model.
    client_name: str
    engagement_reference: str
    structure_reading_consent: bool = True

    _check_target_date = field_validator("target_date")(_validate_target_date)
    _check_as_of_month = field_validator("as_of_month")(_validate_as_of_month)
    _check_required = field_validator("client_name", "engagement_reference")(_required_text)


class AuditUpdate(BaseModel):
    company_name: Optional[str] = None
    reporting_currency: Optional[str] = None
    target_arr: Optional[float] = None
    target_date: Optional[str] = None
    as_of_month: Optional[str] = None
    fiscal_year_end: Optional[int] = Field(default=None, ge=1, le=12)
    client_name: Optional[str] = None
    engagement_reference: Optional[str] = None
    structure_reading_consent: Optional[bool] = None

    _check_target_date = field_validator("target_date")(_validate_target_date)
    _check_as_of_month = field_validator("as_of_month")(_validate_as_of_month)
    _check_required = field_validator("client_name", "engagement_reference")(_required_text)


def _consent_entry(value: bool) -> dict:
    """One change of the consent checkbox, with its time. The user is added when accounts exist."""
    return {"value": bool(value), "at": datetime.now(timezone.utc).isoformat()}


class MappingPayload(BaseModel):
    mapping: dict
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
        "engagement_reference": payload.engagement_reference,
        "structure_reading_consent": payload.structure_reading_consent,
        "consent_log": [_consent_entry(payload.structure_reading_consent)],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "draft",
        "results": None,
        "metrics_stale": False,
    }
    await db.audits.insert_one(dict(audit))
    return audit


@api.get("/audits")
async def list_audits():
    return await db.audits.find({}, {"_id": 0, "results": 0}).sort("created_at", -1).to_list(200)


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
    if consent is True and not (updates.get("engagement_reference") or a.get("engagement_reference")):
        # The basis for sending is the engagement terms: no reference, no AI-assisted reading.
        raise HTTPException(400, "An engagement reference is required before AI-assisted reading can be enabled")
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


@api.delete("/audits/{audit_id}")
async def delete_audit(audit_id: str):
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
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
# Datasets: upload + mapping
# ---------------------------------------------------------------------------
@api.post("/audits/{audit_id}/datasets/{dtype}/upload")
async def upload_dataset(audit_id: str, dtype: str, file: UploadFile = File(...)):
    if dtype not in FIELD_DEFS:
        raise HTTPException(400, "Unknown dataset type")
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    content = await file.read()
    df, sheet = parse_file(content, file.filename)
    columns = list(df.columns)
    rows = df_to_records(df)
    mapping, source, ai_reading = await _prefill_mapping(a, dtype, columns, rows)
    preview = rows[:8]
    await db.datasets.replace_one(
        {"audit_id": audit_id, "dtype": dtype},
        {"audit_id": audit_id, "dtype": dtype, "file": file.filename, "sheet": sheet,
         "columns": columns, "rows": rows, "row_count": len(rows), "mapping": mapping,
         "fx": {}, "billing_terms": {}, "preview": preview, "mapping_source": source, "ai_reading": ai_reading},
        upsert=True,
    )
    await _mark_stale_and_maybe_recompute(audit_id)
    return {
        "dtype": dtype, "file": file.filename, "sheet": sheet, "columns": columns,
        "row_count": len(rows), "suggested_mapping": mapping, "preview": preview,
        "mapping_source": source, "ai_reading": ai_reading,
        "fields": {"required": list(FIELD_DEFS[dtype]["required"]), "optional": list(FIELD_DEFS[dtype]["optional"])},
    }


async def _prefill_mapping(audit: dict, dtype: str, columns: list, rows: list):
    """(mapping, source per field, AI reading) to pre-fill the mapping screen; the analyst confirms it.

    A mapping the analyst confirmed for the same header set is reused and no model is asked. Otherwise
    the column aliases map what they can and, with consent, the model proposes the rest from the
    header stack, samples and profiles (llm-structure-reading.md section 1): those fields are marked
    "ai" and shown as "AI suggestion, not verified". Column-mapping calls are not queued.
    """
    fields = list(FIELD_DEFS[dtype]["required"]) + list(FIELD_DEFS[dtype]["optional"])
    mapping = suggest_mapping(dtype, columns)
    stored = await db[structures.COLUMN_MAPPINGS_COLLECTION].find_one(
        {"audit_id": audit["id"], "dtype": dtype, "header_key": structures.header_key(dtype, columns)}, {"_id": 0})
    if stored:
        kept = {f: c for f, c in (stored.get("mapping") or {}).items() if f in mapping and c in columns}
        return {f: kept.get(f) for f in mapping}, {f: "stored" for f, c in kept.items() if c}, {"status": "stored"}
    source = {f: "rules" for f, c in mapping.items() if c}
    customers = tuple(c for c in [suggest_mapping("revenue", columns).get("customer_id")] if c)
    text = structures.column_mapping_text(columns, rows, audit.get("company_name"),
                                          await llm_redaction.get_map(db, audit["id"]), customers)
    read = await llm_gateway.read_structure(db, audit["id"], text, "column_mapping")
    if read.status == "read":
        await llm_gateway.record_verification(db, audit["id"], read.key, ["suggestion"] * len(read.items))
        used = {c for c in mapping.values() if c}
        for field, col in structures.proposed_mapping(read.items, columns, fields).items():
            if mapping.get(field) is None and col not in used:
                mapping[field], source[field] = col, "ai"
                used.add(col)
    return mapping, source, {"status": read.status, "reason": read.reason}


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


@api.put("/audits/{audit_id}/datasets/{dtype}/mapping")
async def save_mapping(audit_id: str, dtype: str, payload: MappingPayload):
    ds = await db.datasets.find_one({"audit_id": audit_id, "dtype": dtype})
    if not ds:
        raise HTTPException(404, "Dataset not uploaded")
    await db.datasets.update_one(
        {"audit_id": audit_id, "dtype": dtype},
        {"$set": {"mapping": payload.mapping, "fx": payload.fx, "billing_terms": payload.billing_terms,
                  "mapped_at": datetime.now(timezone.utc).isoformat(), "mapping_source": {}}},
    )
    # The analyst's confirmed mapping is kept for this header set and reused on the next upload.
    await db[structures.COLUMN_MAPPINGS_COLLECTION].update_one(
        {"audit_id": audit_id, "dtype": dtype, "header_key": structures.header_key(dtype, ds.get("columns") or [])},
        {"$set": {"audit_id": audit_id, "dtype": dtype,
                  "header_key": structures.header_key(dtype, ds.get("columns") or []),
                  "mapping": payload.mapping, "saved_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    await _add_customers(audit_id, {**ds, "mapping": payload.mapping})
    await _mark_stale_and_maybe_recompute(audit_id)
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
_TARGET_DATE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])|-Q[1-4]|-H[12])?$")


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
async def upload_deck(audit_id: str, file: UploadFile = File(...)):
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
        "structures": deck["structures"], "uploaded_at": datetime.now(timezone.utc).isoformat()})
    for order, c in enumerate(candidates):
        await db[decks.CANDIDATES_COLLECTION].insert_one(
            {**c, "audit_id": audit_id, "deck_id": deck_id, "file": deck["file"], "id": str(uuid.uuid4()),
             "order": len(reviewed) + order, "status": "pending"})
    return {"deck_id": deck_id, "file": deck["file"], "format": deck["format"], "page_unit": deck["page_unit"],
            "pages": deck["pages"], "candidates": len(candidates), "kept_reviewed": len(reviewed)}


@api.get("/audits/{audit_id}/decks")
async def list_deck_candidates(audit_id: str):
    """The audit's decks (no parsed text), most recently uploaded first, and their candidates:
    grouped by deck in that order; within a deck the ones to review first, then by slide or page."""
    if not await db.audits.find_one({"id": audit_id}, {"id": 1}):
        raise HTTPException(404, "Audit not found")
    deck_fields = {"_id": 0, "deck_id": 1, "file": 1, "format": 1, "page_unit": 1, "pages": 1, "uploaded_at": 1}
    found = await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, deck_fields).to_list(100)
    found.sort(key=lambda d: d.get("uploaded_at") or "", reverse=True)
    rank = {d["deck_id"]: i for i, d in enumerate(found)}
    candidates = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id}, {"_id": 0}).to_list(10000)
    candidates.sort(key=lambda c: (rank.get(c.get("deck_id"), len(rank)), c.get("status") != "pending",
                                   _first_page(c), c.get("order", 0)))
    return sanitize({"decks": found, "candidates": candidates})


def _edited_period(value: dict, before: dict, fiscal_year_end: int) -> dict:
    """A value after an edit, its date range re-run. A date the analyst typed is a calendar period
    ("2025", "2025-Q3"), so the deck's stated text goes once the date changes."""
    if value.get("target_date") != before.get("target_date"):
        value["period_text"] = None
    else:
        value["period_text"] = before.get("period_text")
    return deck_claims.resolve_period(value, fiscal_year_end)


def _period_fields(value: dict) -> dict:
    return {k: value.get(k) for k in ("period_text", "period_start", "period_end")}


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
    if edits:
        changes = {**edits, "status": "edited"}
        if "parsed" not in current:       # what the parser found stays next to the analyst's edit
            changes["parsed"] = {k: current.get(k) for k in _EDITABLE if k != "by_period" or rows}
    else:
        if payload.status is None:
            raise HTTPException(400, "status cannot be empty")
        # Approving an edited claim keeps it "edited": it is approved with the analyst's corrections.
        status = "edited" if payload.status == "approved" and "parsed" in current else payload.status
        changes = {"status": status}
    await db[decks.CANDIDATES_COLLECTION].update_one(where, {"$set": changes})
    return sanitize(await db[decks.CANDIDATES_COLLECTION].find_one(where, {"_id": 0}))


@api.get("/audits/{audit_id}/claims")
async def claim_register(audit_id: str):
    """The claim register: approved and edited claims, with what the parser found next to each
    edit. Rejected and unreviewed candidates are not in it (they stay on record in the deck list)."""
    if not await db.audits.find_one({"id": audit_id}, {"id": 1}):
        raise HTTPException(404, "Audit not found")
    claims = await db[decks.CANDIDATES_COLLECTION].find(
        {"audit_id": audit_id, "status": {"$in": list(REGISTER_STATUSES)}}, {"_id": 0}).to_list(10000)
    claims.sort(key=lambda c: (c.get("file") or "", c.get("order", 0)))
    return sanitize({"claims": claims})


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

    rev = normalize(ds["revenue"]["rows"], "revenue", ds["revenue"]["mapping"])
    crm = normalize(ds["crm"]["rows"], "crm", ds["crm"]["mapping"]) if "crm" in ds else pd.DataFrame()
    pnl = normalize(ds["pnl"]["rows"], "pnl", ds["pnl"]["mapping"]) if "pnl" in ds else pd.DataFrame()

    fx = {k.upper(): float(v) for k, v in ds["revenue"].get("fx", {}).items()}
    fx[a["reporting_currency"].upper()] = 1.0
    config = {
        "reporting_currency": a["reporting_currency"], "target_arr": a["target_arr"],
        "target_date": a["target_date"], "fx": fx,
        "billing_terms": ds["revenue"].get("billing_terms", {}), "default_l": 1,
        "as_of_month": a.get("as_of_month"),
    }
    sources = {t: {"file": ds[t]["file"], "sheet": ds[t]["sheet"]} for t in ds}
    results = sanitize(ge.compute_all(rev, crm, pnl, config, sources, files=candidate_views(ds),
                                      on_error=lambda exc: _log_metric_error(exc, audit_id)))
    await db.audits.update_one(
        {"id": audit_id},
        {"$set": {"results": results, "status": "computed", "computed_at": datetime.now(timezone.utc).isoformat(),
                  "metrics_stale": False}},
    )
    return results


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
    keys = ("id", "company_name", "reporting_currency", "target_arr", "target_date", "as_of_month", "status", "computed_at",
            "metrics_stale")
    return sanitize({"audit": {k: a.get(k) for k in keys}, "results": a["results"]})


def build_export_workbook(meta: dict, r: dict, disclosure_text: Optional[str] = None,
                          narratives: Optional[list] = None) -> io.BytesIO:
    """Numeric cells with Excel number formats (see app/formatting.py), so the
    display follows the formatting rules while analysts can still sum and sort."""
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
    try:
        narratives = await llm_gateway.narratives_for_run(db, audit_id)
    except Exception:  # the export never depends on the narrative service
        narratives = []
    block = llm_gateway.disclosure_from(narratives)
    buf = build_export_workbook(a, a["results"], block["text"] if block else None, narratives)
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


# 4: demo audits carry a client name, an engagement reference, consent and a fiscal year-end.
SEED_VERSION = 4


@app.on_event("startup")
async def seed_demo():
    if await db.audits.count_documents({"seed_version": SEED_VERSION}) > 0:
        return
    demo_ids = {"audit_id": {"$in": [a["id"] for a in await db.audits.find({"demo": True}, {"id": 1}).to_list(50)]}}
    for name in ("datasets", decks.TEXT_COLLECTION, decks.CANDIDATES_COLLECTION):
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
            "engagement_reference": spec["engagement_reference"], "structure_reading_consent": True,
            "consent_log": [_consent_entry(True)],
            "created_at": datetime.now(timezone.utc).isoformat(), "status": "computed",
            "computed_at": datetime.now(timezone.utc).isoformat(), "results": sanitize(results), "demo": True,
            "seed_version": SEED_VERSION,
        })
    logger.info("Seeded demo audits")


@app.on_event("startup")
async def ensure_llm_indexes():
    await llm_gateway.guards.ensure_indexes(db)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
