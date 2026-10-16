from fastapi import BackgroundTasks, Body, Depends, FastAPI, APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, Response, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import re
import asyncio
import hashlib
import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

import growth_engine as ge
import demo_data
from schemas import metrics as contract
from app import formatting as fmt
from app import disclosure as disclosure_mod
from app import narrative_export
from app import run_audit
from app import claim_matching
from app import access as access_mod
from app import ic_memo
from app import integrity as integrity_mod
from app import verdict as verdict_mod
from app import decks
from app import structures
from app import column_rules as cr
from app import usage as usage_mod
from app.decks import claims as deck_claims
from app.decks import parser as deck_parser
from app.llm import gateway as llm_gateway
from app.llm import prompt_store
from app.llm import redaction as llm_redaction
from app.logsafety import install_secret_redaction

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="Growth Diligence Engine")


async def access_guard(request: Request):
    """docs/specs/access-links.md section 3, on every route of the router: 401 for no, unknown, expired or revoked token; the
    owner token reaches usage totals and the admin routes only (404 elsewhere); a tester reaches an audit (or run) id only when
    their token owns it, and gets the missing-audit answer otherwise."""
    path = request.url.path
    # ACCESS_DISABLED opens the audit routes (local development, the test suite) and never the owner routes: they stay locked.
    if (access_mod.disabled() and not path.startswith("/api/admin/")) or path in access_mod.OPEN_PATHS or request.method == "OPTIONS":
        request.state.principal = None
        return
    who = await access_mod.principal(db, access_mod.bearer(request.headers.get("authorization")))
    if who is None:
        raise HTTPException(401, "Invalid or missing access link")
    role, tester_id = who
    request.state.principal = who
    if path == "/api/usage/totals":
        return                      # a tester reads the totals of their own audits, the owner token those of all (usage_totals)
    if path.startswith("/api/admin/"):
        if role != access_mod.OWNER:
            raise HTTPException(404, "Not found")
        return
    if role == access_mod.OWNER:
        raise HTTPException(404, "Audit not found")
    audit_id = request.path_params.get("audit_id") or request.path_params.get("run_id")
    if audit_id is not None:
        owned = await db.audits.find_one({"id": audit_id, "owner": tester_id}, {"id": 1})
        if not owned:
            raise HTTPException(404, "Audit not found")


api = APIRouter(prefix="/api", dependencies=[Depends(access_guard)])

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
    elif filename.lower().endswith(".xlsx"):
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


def normalize(rows: list, dtype: str, mapping: dict, row_numbers: Optional[list] = None, unit_scale: int = 1) -> pd.DataFrame:
    """The stored rows read through a mapping. `_row` is the row's number in the sheet it came from
    (`row_numbers`, kept at upload); without it the header is taken to be row 1 with no blank lines. `unit_scale` is
    1,000 when the title rows of the file said the figures are in thousands: the money fields are multiplied by it."""
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
            out[f] = pd.to_numeric(out[f], errors="coerce") * (unit_scale or 1)
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
            views[as_type] = {"mapping": mapping, "frame": normalize(d.get("rows") or [], as_type, mapping, d.get("row_numbers"), d.get("unit_scale") or 1)}
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


def _validate_analysis_date(v: Optional[str]) -> Optional[str]:
    """The requested analysis date (docs/specs/dates-and-periods.md section 2): YYYY-MM-DD, a year from 2000 to 2100, or none."""
    if not v:
        return None
    try:
        dt = datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        dt = None
    if dt is None or dt.strftime("%Y-%m-%d") != v or not 2000 <= dt.year <= 2100:
        raise ValueError("analysis_date must be an ISO date (YYYY-MM-DD) with a year between 2000 and 2100")
    return v


class AuditCreate(BaseModel):
    company_name: str                       # the target company
    reporting_currency: str = "EUR"
    target_arr: float = 0
    target_date: Optional[str] = None
    as_of_month: Optional[str] = None
    # The analyst's date: dates the memo and the analyst's own text, never a figure (null: today). The box "Last month is
    # complete" marks the revenue file's last month Complete (dates-and-periods.md section 2).
    analysis_date: Optional[str] = None
    last_month_complete: bool = False
    # The month the company's fiscal year ends in (deck-parser.md section 2). FY25 is the fiscal year
    # that ends in 2025; with December it is the calendar year.
    fiscal_year_end: int = Field(default=12, ge=1, le=12)
    # The investor commissioning the audit; the name never reaches the model.
    client_name: str
    structure_reading_consent: bool = True

    _check_target_date = field_validator("target_date")(_validate_target_date)
    _check_as_of_month = field_validator("as_of_month")(_validate_as_of_month)
    _check_analysis_date = field_validator("analysis_date")(_validate_analysis_date)
    _check_required = field_validator("client_name")(_required_text)


class AuditUpdate(BaseModel):
    company_name: Optional[str] = None
    reporting_currency: Optional[str] = None
    target_arr: Optional[float] = None
    target_date: Optional[str] = None
    as_of_month: Optional[str] = None
    analysis_date: Optional[str] = None
    last_month_complete: Optional[bool] = None
    fiscal_year_end: Optional[int] = Field(default=None, ge=1, le=12)
    client_name: Optional[str] = None
    structure_reading_consent: Optional[bool] = None

    _check_target_date = field_validator("target_date")(_validate_target_date)
    _check_as_of_month = field_validator("as_of_month")(_validate_as_of_month)
    _check_analysis_date = field_validator("analysis_date")(_validate_analysis_date)
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
    if a.get("created_at"):
        a["ic_inputs"] = verdict_mod.with_review(a, a.get("ic_inputs"))
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
async def create_audit(payload: AuditCreate, request: Request):
    audit = {
        "id": str(uuid.uuid4()),
        "company_name": payload.company_name,
        "reporting_currency": payload.reporting_currency,
        "target_arr": payload.target_arr,
        "target_date": payload.target_date,
        "as_of_month": payload.as_of_month,
        "analysis_date": payload.analysis_date,
        "last_month_complete": payload.last_month_complete,
        "fiscal_year_end": payload.fiscal_year_end,
        "client_name": payload.client_name,
        "structure_reading_consent": payload.structure_reading_consent,
        "consent_log": [_consent_entry(payload.structure_reading_consent)],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "draft",
        "results": None,
        "metrics_stale": False,
    }
    audit["ic_inputs"] = verdict_mod.with_review(audit, None)       # the first quarterly review: creation date + 90 days
    who = getattr(request.state, "principal", None)
    owner = {"owner": who[1]} if who and who[1] else {}              # the tester token's id, never the token
    await db.audits.insert_one({**audit, **owner, "usage": usage_mod.empty()})
    return audit


class TesterCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)


def _link(request: Request, token: str) -> str:
    base = os.environ.get("PUBLIC_APP_URL") or str(request.base_url)
    return f"{base.rstrip('/')}/t/{token}"


class PromptUpload(BaseModel):
    name: str
    text: str


# Prompt text goes in and never comes out: the list has name, version, date and hash (docs/specs/prompt-store.md). Owner token only
# (access_guard, /api/admin/...).
@api.get("/admin/prompts")
async def admin_prompts():
    return {"names": list(prompt_store.NAMES), "prompts": await prompt_store.list_versions(db),
            "missing": await prompt_store.missing(db)}


@api.post("/admin/prompts")
async def admin_upload_prompt(payload: PromptUpload):
    try:
        row = await prompt_store.upload(db, payload.name, payload.text)
    except prompt_store.PromptRefused as exc:
        raise HTTPException(422, str(exc))
    logger.info("prompt uploaded: name=%s version=%s", row["name"], row["version"])
    return row


@api.post("/admin/testers")
async def issue_tester(payload: TesterCreate, request: Request):
    """The owner issues one link per tester. The link is returned once; only its hash is stored."""
    tester_id, token = await access_mod.issue(db, payload.label.strip())
    return {"id": tester_id, "label": payload.label.strip(), "link": _link(request, token)}


@api.get("/admin/testers")
async def list_testers():
    return await access_mod.testers(db)


@api.post("/admin/testers/{tester_id}/revoke")
async def revoke_tester(tester_id: str):
    if not await access_mod.revoke(db, tester_id):
        raise HTTPException(404, "Not found")
    return {"ok": True}


@api.post("/admin/testers/{tester_id}/reissue")
async def reissue_tester(tester_id: str, request: Request):
    token = await access_mod.reissue(db, tester_id)
    if token is None:
        raise HTTPException(404, "Not found")
    return {"id": tester_id, "link": _link(request, token)}


@api.get("/audits")
async def list_audits(request: Request):
    who = getattr(request.state, "principal", None)
    flt = {"owner": who[1]} if who else {}
    return await db.audits.find(flt, {"_id": 0, "results": 0, "usage": 0, "owner": 0}).sort("created_at", -1).to_list(200)


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
    if "as_of_month" in payload.model_fields_set and payload.as_of_month is None:
        updates["as_of_month"] = None       # an explicit null clears the as-of month back to the default (last P&L month)
    if "analysis_date" in payload.model_fields_set and payload.analysis_date is None:
        updates["analysis_date"] = None     # an explicit null returns the requested analysis date to today
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
    screen: Optional[Literal["mapping", "dashboard", "diagnostics", "review", "run"]] = None
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
async def usage_totals(request: Request):
    """Sums across audits, the median days from first upload to first export and the 50 newest "Other" notes. No
    per-audit rows, names or ids (chat-upload.md section 7). Tokens and cost come from the call log; evidence
    labels and analyst changes are computed on read from what the audits hold. A tester token sums its own audits
    only, notes included; the owner token sums all (access-links.md section 3)."""
    who = getattr(request.state, "principal", None)
    mine = {"owner": who[1]} if who and who[0] == access_mod.TESTER else {}
    audits = await db.audits.find(mine, {"_id": 0}).to_list(100000)
    calls = await db[llm_gateway.CALLS_COLLECTION].find({}, {"_id": 0}).to_list(1000000)
    if mine:
        own = {a["id"] for a in audits}
        calls = [c for c in calls if c.get("run_id") in own]
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
        "tokens_and_cost_by_step": steps, "evidence_labels": labels, "metrics_missing": missing, "analyst_changes": changes,
        "scope": "own" if mine else "all"}))       # the screen words its title from this


# ---------------------------------------------------------------------------
# Datasets: upload with type detection, the mapping rule, decisions, saved mappings
# (docs/specs/chat-upload.md sections 3-5)
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = ("xlsx", "csv")
XLS_REFUSED = "Save as .xlsx or .csv and upload again."       # an old .xls workbook (2026-10-08)
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
    return sorted((s["column"], s.get("field"), s.get("money_kind")) for s in states)


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
        "columns": [{k: s.get(k) for k in ("column", "field", "source", "confidence", "decision", "reason", "money_kind")} for s in states]})
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
        rows.append({**s, "position": i + 1, "pending": s["state"] in cr.PENDING or cr.needs_money(s),
                     "money_ask": cr.asks_money(s)})
    return {
        "status": status, "dtype": dtype, "file": ds.get("file"), "size_bytes": ds.get("size_bytes"),
        "ext": usage_mod.extension_of(ds.get("file") or ""), "row_count": ds.get("row_count"),
        "header_row": ds.get("header_row"), "months": ds.get("months"), "columns": rows,
        "pending": cr.pending_count(states), "missing_required": cr.missing_required(dtype, states),
        "version": version, "ai_reading": ds.get("ai_reading"), "uploaded_at": ds.get("uploaded_at"),
        "fields": {"required": list(FIELD_DEFS[dtype]["required"]), "optional": list(FIELD_DEFS[dtype]["optional"])},
        "mapping": mapping, "suggested_mapping": mapping, "mapping_source": ds.get("mapping_source") or _source_map(states),
        "fx": ds.get("fx") or {}, "billing_terms": ds.get("billing_terms") or {}, "preview": ds.get("preview") or [],
        "saved": bool(ds.get("mapped_at")), "sheet": ds.get("sheet"), "type_source": ds.get("type_source"),
        "unit_note": ds.get("unit_note"), "looks": ds.get("looks"), "miss": _miss(dtype, states, mapping, ds.get("looks")),
    }


def _miss(dtype: str, states: list, mapping: dict, looks: Optional[dict]) -> Optional[dict]:
    """The file cannot supply the type's required fields (a summary or forecast table, or at most half of them mapped): the
    screen shows one message in place of the mapping rows. Closed words and counts only (chat-upload.md section 19)."""
    if not cr.is_miss(dtype, mapping, looks):
        return None
    return {"missing": cr.missing_required(dtype, states), "looks": looks or {"shape": "table", "rows": 0, "columns": len(states)}}


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


async def _stored_file_type(audit_id: str, digest: str) -> Optional[dict]:
    """The type the model gave this file (by its hash) earlier in this audit, kept with the saved mappings."""
    return await db[structures.COLUMN_MAPPINGS_COLLECTION].find_one(
        {"audit_id": audit_id, "kind": "file_type", "file_hash": digest}, {"_id": 0})


def _file_type_sheets(audit: dict, sheets: list, mapping: dict) -> str:
    """The text the model reads to tell the file's type (chat-upload.md section 19): sheet names, the title rows above
    each header, the header row and the masked sample. Built in memory; never stored, never logged."""
    parts = []
    for sheet in sheets[:structures.redact.FILE_MAX_SHEETS]:
        rows = df_to_records(sheet.frame.head(structures.MAPPING_SAMPLE_ROWS))
        parts.append(structures.file_type_sheet(
            sheet.sheet, sheet.titles, sheet.header_row, sheet.headers, sheet.columns, rows,
            tuple(cr.customer_columns(sheet, cr.analyse("revenue", sheet)[0])) if not sheet.wide else (), sheet.raw_headers))
    return structures.file_type_text(parts, audit.get("company_name"), mapping, structures.redact.file_type_withheld(audit))


async def _ask_file_type(audit: dict, sheets: list, digest: str):
    """The rules found no type at 80: the model is asked once for the file, with the consent of the audit, and the answer is
    kept by the file's hash (it is not asked again for the same bytes). Returns (type or None, status). A file the model
    cannot place, a failure, a timeout or no consent leaves the type to the analyst (S6)."""
    if audit.get("structure_reading_consent") is not True:
        return None, "no_consent"
    kept = await _stored_file_type(audit["id"], digest)
    if kept:
        return (kept.get("file_type") if kept.get("file_type") in DTYPE_ORDER else None), "stored"
    text = _file_type_sheets(audit, sheets, await llm_redaction.get_map(db, audit["id"]))
    try:
        read = await asyncio.wait_for(llm_gateway.read_structure(db, audit["id"], text, "file_type"), MAPPING_AI_SECONDS)
    except asyncio.TimeoutError:
        return None, "timeout"
    if read.status != "read":
        return None, read.status
    await db[structures.COLUMN_MAPPINGS_COLLECTION].insert_one({
        "audit_id": audit["id"], "kind": "file_type", "file_hash": digest, "file_type": read.file_type,
        "saved_at": usage_mod.now()})
    return (read.file_type if read.file_type in DTYPE_ORDER else None), "read"


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
        raise HTTPException(400, XLS_REFUSED if ext == "xls" else "Only .xlsx and .csv files are supported")
    try:
        sheets = await run_in_threadpool(cr.read_workbook, content, filename)
    except cr.SheetError:
        raise HTTPException(400, "This file could not be read as a sheet")
    digest = hashlib.sha256(content).hexdigest()
    detected, _, _ = cr.detect_workbook(sheets)
    chosen, source, type_status = dtype or detected, "you" if dtype else "rules", None
    if chosen is None:
        chosen, type_status = await _ask_file_type(a, sheets, digest)
        source = "ai"
    if chosen is None:
        return {"status": "unknown_type", "file": filename, "size_bytes": len(content), "row_count": len(sheets[0].frame),
                "ext": ext, "types": list(DTYPE_ORDER), "sheets": len(sheets)}
    return await _load(a, audit_id, chosen, cr.best_sheet(sheets, chosen), filename, len(content), digest, replace,
                       background, source, detected == chosen, type_status)


async def _load(a: dict, audit_id: str, chosen: str, sheet: "cr.Sheet", filename: str, size: int, digest: str, replace: bool,
                background: Optional[BackgroundTasks], type_source: str, detected: bool, type_status: Optional[str] = None,
                drop: Optional[str] = None):
    """A sheet stored as the audit's file of one type: the saved mapping of its bytes or its headers, else the rules, then
    the model for the columns the rules could not decide (unless the sheet is a summary table, which no column mapping can
    read), then the analyst. `drop` is the type this file was stored as before, when the analyst changed its type."""
    existing = await db.datasets.find_one({"audit_id": audit_id, "dtype": chosen}, {"_id": 0, "rows": 0})
    versions = await _versions(audit_id, chosen)
    if existing and existing.get("file_hash") == digest and drop is None:
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
    looks = cr.describe(sheet)
    ai_reading = {"status": "rules", "reason": None}
    # A saved mapping that is itself a miss (at most half of the required fields mapped, as when every column was left
    # out as "Not used") is no mapping to reuse: the rules and the model run again for this file.
    reusable = [v for v in (same or headers)
                if not cr.is_miss(chosen, {c.get("field"): c["column"] for c in _saved_columns(v) if c.get("field")}, looks)]
    if reusable and (same or headers):
        states = cr.states_from_saved(chosen, sheet, _saved_columns(reusable[-1]), scale=not any(v in same for v in reusable))
        ai_reading = {"status": "stored", "reason": None}
    else:
        proposals, open_fields = cr.analyse(chosen, sheet)
        states = cr.states_from_rules(proposals)
        sent = cr.to_send(states)
        if sent and looks["shape"] != "summary":
            states, ai_reading = await _ask_model(a, chosen, sheet, rows, states, sent, proposals, open_fields)
            await _usage_update(audit_id, lambda u: u["steps"]["mapping_ai"].__setitem__(
                ai_reading["status"], u["steps"]["mapping_ai"].get(ai_reading["status"], 0) + 1))
    mapping = cr.mapping_of(chosen, states)
    doc = {"audit_id": audit_id, "dtype": chosen, "file": filename, "sheet": sheet.sheet, "columns": sheet.columns,
           "headers": sheet.headers, "header_row": sheet.header_row, "rows": rows, "row_numbers": sheet.row_numbers,
           "row_count": len(rows), "mapping": mapping, "fx": (existing or {}).get("fx") or {},
           "billing_terms": {}, "preview": rows[:8],
           "mapping_source": _source_map(states), "ai_reading": ai_reading, "columns_state": states,
           "months": _months_for(chosen, states, sheet.columns, rows), "file_hash": digest, "size_bytes": size,
           "uploaded_at": usage_mod.now(), "mapped_at": None, "type_source": type_source, "looks": looks,
           "unit_scale": sheet.unit_scale, "unit_note": sheet.unit_note, "wide": sheet.wide, "raw_headers": sheet.raw_headers}
    await db.datasets.replace_one({"audit_id": audit_id, "dtype": chosen}, doc, upsert=True)
    if drop and drop != chosen:
        await db.datasets.delete_one({"audit_id": audit_id, "dtype": drop})

    def count(u):
        usage_mod.record_upload(u, chosen)
        for s in states:
            kind = {"rules": "rules", "saved": "saved", "ai": "ai"}.get(s.get("source"))
            if kind and s["state"] in cr.MAPPED:
                usage_mod.record_columns(u, kind)
    await _usage_update(audit_id, count)
    version = await _commit_mapping(audit_id, chosen, background)
    await _mark_stale_and_maybe_recompute(audit_id)
    logger.info("upload: run_id=%s type=%s detected=%s source=%s pending=%d ai=%s type_ai=%s", audit_id, chosen, detected,
                type_source, cr.pending_count(states), ai_reading["status"], type_status or "-")
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


class RetypeBody(BaseModel):
    to: str
    replace: bool = False


@api.post("/audits/{audit_id}/datasets/{dtype}/type")
async def change_dataset_type(audit_id: str, dtype: str, body: RetypeBody, background: BackgroundTasks):
    """The analyst changes the type a stored file was read as (chat-upload.md section 19). The stored sheet is read again as the
    new type: the rules, then the model for the columns they cannot decide. The file is not uploaded again, and no
    model is asked what the file is. A file already stored under the new type needs `replace`."""
    if dtype not in FIELD_DEFS or body.to not in FIELD_DEFS:
        raise HTTPException(400, "Unknown dataset type")
    a = await db.audits.find_one({"id": audit_id})
    ds = await db.datasets.find_one({"audit_id": audit_id, "dtype": dtype})
    if not a or not ds:
        raise HTTPException(404, "Dataset not found")
    if body.to == dtype:
        return _dataset_view({k: v for k, v in ds.items() if k not in ("_id", "rows")}, None)
    columns = ds.get("columns") or []
    frame = pd.DataFrame([[r.get(c) for c in columns] for r in ds.get("rows") or []], columns=columns, dtype=object)
    sheet = cr.Sheet(ds.get("sheet") or "", ds.get("header_row") or 1, columns, ds.get("headers") or columns, frame,
                     ds.get("row_numbers") or [], [], ds.get("unit_scale") or 1, ds.get("unit_note"), ds.get("wide"),
                     ds.get("raw_headers"))
    return await _load(a, audit_id, body.to, sheet, ds.get("file") or "", ds.get("size_bytes") or 0, ds.get("file_hash") or "",
                       body.replace, background, "you", False, drop=dtype)


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
    money_kind: Optional[Literal["revenue", "volume"]] = None       # the answer to "revenue or volume?" (chat-upload.md section 15)


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
    saved = {"billing_terms": payload.billing_terms}
    if "fx" in payload.model_fields_set:       # the rates live on the audit now (PUT /fx); an older client may still send them
        saved["fx"] = payload.fx
    await db.datasets.update_one({"audit_id": audit_id, "dtype": dtype}, {"$set": saved})
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


def _rejected(field: str, reason: str) -> HTTPException:
    """A 400 that names the field the server refused and why ("unit: ..."), so the screen never says only that a save failed."""
    return HTTPException(400, f"{field}: {reason}")


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
    # Use of funds is accepted so that correcting a figure of that type keeps the type (deck-parser.md section 2): the
    # claim stays out of the top 5, the banner and the verdict. The analyst's list of types does not offer it. Acquisition
    # channels is accepted and offered (chat-upload.md section 17).
    claim_type: Optional[Literal[deck_claims.CLAIM_TYPES + (deck_claims.USE_OF_FUNDS, deck_claims.ACQUISITION_CHANNELS, "other")]] = None
    value: Optional[float] = None
    value_high: Optional[float] = None          # the high end of a range
    unit: Optional[str] = Field(default=None, min_length=1, max_length=40)   # "%", "months", "paying users"
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    target_date: Optional[str] = Field(default=None, pattern=_TARGET_DATE.pattern)
    by_period: Optional[List[PeriodValue]] = None   # a table row: every value, in the row's order
    # docs/specs/claim-types-and-correction.md section 3: the fields every claim type holds, and why the analyst changed them
    population: Optional[Literal["paying", "registered", "active", "deals won", "all closed", "open"]] = None
    figure_type: Optional[Literal[deck_claims.FIGURE_TYPES]] = None
    growth_basis: Optional[Literal["mom", "yoy", "annualised", "cumulative", "unknown"]] = None
    reason: Literal[tuple(deck_claims.EDIT_REASONS)] = "parser_misread"


_EDITABLE = ("claim_type", "value", "value_high", "unit", "currency", "target_date", "by_period")
_CLAIM_FIELDS = ("population", "figure_type", "growth_basis")       # each with *_set_by "analyst" once edited
ADDED_FROM_DECK = "Added from deck by analyst"
_ROW_FIELDS = ("value", "value_high", "target_date")     # held per period on a table row candidate
# Approved and edited claims make up the claim register; rejected ones stay on record, unused.
REGISTER_STATUSES = ("approved", "edited")
ADDED_BY_ANALYST = "Added by analyst"


def _claim_key(c: dict) -> tuple:
    """What the parser found, so a re-upload can tell an already reviewed claim."""
    found = c.get("parsed") or c
    return tuple(tuple(tuple(i.get(f) for f in _ROW_FIELDS) for i in found.get(k) or ()) if k == "by_period"
                 else found.get(k) for k in _EDITABLE) + (c.get("channel"),)


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
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
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
    fx = await _fx(audit_id, audit)
    settings = _register_settings(audit, fx, await _deck_take_rate(audit_id))
    # A turnover claim asks "Revenue or Volume?" in its own row, before it is approved (claim-matching.md section 11
    # point 8), from the register's own code: read before the list adds its display fields to the candidates.
    current = await _current_audit(audit_id, audit, strict=False)
    turnover = claim_matching.turnover_views(candidates, current.get("results"), settings)
    # A gap beyond 50% of the claim asks "Same metric and period?" on the review screen, approved or not (claim-matching.md 4.1).
    definition = claim_matching.definition_views(candidates, current.get("results"), settings)
    # By the group of the claim type (revenue, P&L, customers and sales, market size, Unknown, Other), then ascending by
    # slide or page across all decks (a tie goes to the more recent deck), then reading order on the page: top to bottom
    # in bands of 2% of the height, then left to right, then the order the parser found them in.
    for c in candidates:
        c["group"] = deck_claims.type_group(c.get("claim_type"))
    candidates.sort(key=lambda c: (c["group"], _first_page(c), rank.get(c.get("deck_id"), len(rank)), *_reading(c),
                                   c.get("order", 0)))
    # A claim in another currency than the audit's, with the rate it is converted at (None: "FX rate needed").
    as_of = audit.get("as_of_month") or (audit.get("results") or {}).get("as_of_month")
    for c in candidates:
        c["fx"] = claim_matching.fx_view(c, settings, as_of)
        c["turnover"] = turnover.get(c["id"])
        c["definition"] = definition.get(c["id"])
        # the figure type, population and growth basis as the register reads them, for the editor (claim-types-and-correction.md 3)
        c["claim_fields"] = claim_matching.candidate_fields(c, current.get("results"))
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


class AnalystClaim(BaseModel):
    """A claim the analyst adds from a slide or page the parser could not read (docs/specs/deck-parser.md section 6): the
    metric, a value or a range, the unit, the currency and the period, and where in which deck it is stated."""
    model_config = {"extra": "forbid"}
    claim_type: Literal[deck_claims.CLAIM_TYPES + (deck_claims.ACQUISITION_CHANNELS,)]
    value: float = Field(allow_inf_nan=False)
    value_high: Optional[float] = Field(default=None, allow_inf_nan=False)
    unit: Optional[str] = Field(default=None, min_length=1, max_length=40)
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    target_date: Optional[str] = Field(default=None, pattern=_TARGET_DATE.pattern)
    deck_id: str
    page: int = Field(ge=1)
    metric: Optional[str] = None    # the register metric the claim is tested against (claim-matching.md table 2a); required, no default,
    #                                 except for acquisition channels, which no metric tests
    label: Optional[str] = Field(default=None, min_length=1, max_length=deck_claims.CHANNEL_NAME_MAX)    # the platform (acquisition channels only)

    @model_validator(mode="after")
    def _metric_or_platform(self):
        if self.claim_type == deck_claims.ACQUISITION_CHANNELS:
            if self.metric is not None:
                raise ValueError("acquisition channels are tested against no metric")
            if not (self.label or "").strip():
                raise ValueError("name the platform")
        elif self.metric is None or self.label is not None:
            raise ValueError("choose a metric" if self.metric is None else "a platform belongs to acquisition channels only")
        return self


@api.post("/audits/{audit_id}/decks/candidates")
async def add_analyst_claim(audit_id: str, payload: AnalystClaim):
    """Add a claim by hand. It is approved at once (it is the analyst's own), tagged origin "analyst", and sits in the
    register like any other claim: matched and labelled by the same code. Its source is the deck and page the analyst cites."""
    audit = await db.audits.find_one({"id": audit_id}, {"id": 1, "fiscal_year_end": 1})
    if not audit:
        raise HTTPException(404, "Audit not found")
    deck = await db[decks.TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": payload.deck_id},
                                                    {"_id": 0, "file": 1, "page_unit": 1, "pages": 1})
    if not deck:
        raise _rejected("deck_id", "choose one of the uploaded documents")
    if deck.get("pages") and payload.page > deck["pages"]:
        raise _rejected("page", f"this document has {deck['pages']} {deck.get('page_unit') or 'page'}s")
    acquisition = payload.claim_type == deck_claims.ACQUISITION_CHANNELS
    if not acquisition and not claim_matching.fits_metric(payload.metric, payload.unit, payload.currency):
        raise _rejected("metric", "choose a metric in the claim's unit")
    if payload.value_high is not None and payload.value_high < payload.value:
        raise _rejected("value_high", "the high end of a range is not below the low end")
    page_key = "slide" if deck.get("page_unit") == "slide" else "page"
    existing = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "order": 1}).to_list(10000)
    candidate = {
        "claim_type": payload.claim_type, "value": payload.value, "value_high": payload.value_high, "unit": payload.unit,
        "currency": payload.currency, "target_date": payload.target_date, "snippet": ADDED_BY_ANALYST, "label_from": None,
        "date_from": None, "sources": [{"file": deck["file"], page_key: payload.page, "kind": "analyst"}],
        "inconsistent_dates": [], "origin": "analyst", "claim_direction": None,
        **_period_fields(_edited_period({"target_date": payload.target_date}, {}, _fiscal_year_end(audit))),
        "audit_id": audit_id, "deck_id": payload.deck_id, "file": deck["file"], "id": str(uuid.uuid4()),
        "order": max((c.get("order", 0) for c in existing), default=-1) + 1, "status": "approved",
    }
    if acquisition:
        candidate.update(channel=payload.label.strip(), unit=deck_claims.COUNT, currency=None)    # a count per platform
    else:
        candidate["claim_inputs"] = {candidate["id"]: {"metric": payload.metric}}      # the analyst's metric, as the register stores it
    await db[decks.CANDIDATES_COLLECTION].insert_one(candidate)
    return sanitize(await db[decks.CANDIDATES_COLLECTION].find_one({"audit_id": audit_id, "id": candidate["id"]}, {"_id": 0}))


SNIPPET_MAX = 300           # the longest passage Add from deck takes (claim-types-and-correction.md section 5)


def _page_lines(deck: dict, page: int) -> List[dict]:
    """A stored page as the analyst sees it under View page: its text, notes and table lines ("b{n}", the block's index in the
    stored deck) and its chart labels ("c{structure}:{cell}"), in the stored order. Nothing is read again from the file."""
    key = "slide" if deck.get("page_unit") == "slide" else "page"
    lines = [{"ref": f"b{n}", "kind": b.get("kind"), "text": b.get("text") or ""}
             for n, b in enumerate(deck.get("blocks") or []) if b.get(key) == page and (b.get("text") or "").strip()]
    for s, structure in enumerate(deck.get("structures") or []):
        if structure.get("type") == "chart" and structure.get(key) == page:
            lines += [{"ref": f"c{s}:{n}", "kind": "chart", "text": cell.get("text") or ""}
                      for n, cell in enumerate(structure.get("cells") or []) if (cell.get("text") or "").strip()]
    return lines


async def _stored_deck(audit_id: str, deck_id: str) -> dict:
    deck = await db[decks.TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id}, {"_id": 0})
    if not deck:
        raise HTTPException(404, "Deck not found")
    return deck


@api.get("/audits/{audit_id}/decks/{deck_id}/pages/{page}")
async def deck_page(audit_id: str, deck_id: str, page: int):
    """One stored page of one of the audit's decks, for Add from deck (claim-types-and-correction.md section 5). The text goes to the
    analyst's browser only, as the deck list's snippets do; the log line holds the run id and a count."""
    deck = await _stored_deck(audit_id, deck_id)
    if page < 1 or (deck.get("pages") and page > deck["pages"]):
        raise HTTPException(404, "Page not found")
    lines = _page_lines(deck, page)
    logger.info("deck page: run_id=%s lines=%d", audit_id, len(lines))
    return sanitize({"deck_id": deck_id, "file": deck.get("file"), "page_unit": deck.get("page_unit"), "page": page,
                     "pages": deck.get("pages"), "lines": lines})


class AddFromDeck(BaseModel):
    """A line of a stored deck page, by reference: the server reads its text, the client never sends claim text."""
    model_config = {"extra": "forbid"}
    page: int = Field(ge=1)
    ref: str = Field(pattern=r"^(b\d+|c\d+:\d+)$")


@api.post("/audits/{audit_id}/decks/{deck_id}/add-from-deck")
async def add_from_deck(audit_id: str, deck_id: str, payload: AddFromDeck):
    """Recover a claim the parser missed (claim-types-and-correction.md section 5): a candidate from one stored line, its snippet the
    line verbatim, its source the deck, page and cell, origin "deck_analyst", pending. The parser reads its fields from that text;
    with no figure or no type it is Other with no value, for the analyst to type in the editor."""
    audit = await db.audits.find_one({"id": audit_id}, {"id": 1, "fiscal_year_end": 1})
    if not audit:
        raise HTTPException(404, "Audit not found")
    deck = await _stored_deck(audit_id, deck_id)
    line = next((x for x in _page_lines(deck, payload.page) if x["ref"] == payload.ref), None)
    if line is None:
        raise _rejected("ref", "choose a line of this page")
    text = line["text"]
    if len(text) > SNIPPET_MAX:
        raise _rejected("ref", f"Select a shorter passage ({SNIPPET_MAX} characters at most)")
    key = "slide" if deck.get("page_unit") == "slide" else "page"
    if payload.ref.startswith("b"):
        block = deck["blocks"][int(payload.ref[1:])]
        source = {k: block[k] for k in ("table", "row", "col", "box") if block.get(k) is not None}
    else:
        s, n = (int(x) for x in payload.ref[1:].split(":"))
        cell = deck["structures"][s]["cells"][n]
        block = {key: payload.page, "text": text}
        source = {"chart": deck["structures"][s].get("chart"), "row": cell.get("row"), "col": cell.get("col")}
    found = deck_claims.detect_candidates([{key: payload.page, "text": text, "kind": "text", **{
        k: v for k, v in block.items() if k in ("box", "top", "left", "width", "height")}}], deck["file"], _fiscal_year_end(audit))
    parsed = found[0] if found and found[0].get("claim_type") else {}
    existing = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "order": 1}).to_list(10000)
    candidate = {
        "claim_type": parsed.get("claim_type") or deck_claims.UNKNOWN, "value": parsed.get("value"),
        "value_high": parsed.get("value_high"), "unit": parsed.get("unit"), "currency": parsed.get("currency"),
        "target_date": parsed.get("target_date"), "period_text": parsed.get("period_text"), "label_from": None,
        "date_from": parsed.get("date_from"), "inconsistent_dates": [], "claim_direction": parsed.get("claim_direction"),
        **{k: parsed[k] for k in ("qualifier", "growth_basis", "figure_type", "figure_type_set_by", "population", "population_set_by",
                                  "type_from") if parsed.get(k) is not None},
        "snippet": text, "sources": [{"file": deck["file"], key: payload.page, "kind": "deck_analyst", **source}],
        "origin": "deck_analyst", "audit_id": audit_id, "deck_id": deck_id, "file": deck["file"], "id": str(uuid.uuid4()),
        "order": max((c.get("order", 0) for c in existing), default=-1) + 1, "status": "pending",
    }
    deck_claims.resolve_period(candidate, _fiscal_year_end(audit))
    await db[decks.CANDIDATES_COLLECTION].insert_one(candidate)
    logger.info("add from deck: run_id=%s figures=%d", audit_id, len(found))
    return sanitize(await db[decks.CANDIDATES_COLLECTION].find_one({"audit_id": audit_id, "id": candidate["id"]}, {"_id": 0}))


@api.put("/audits/{audit_id}/decks/candidates/{candidate_id}")
async def update_candidate(audit_id: str, candidate_id: str, payload: CandidateUpdate):
    where = {"audit_id": audit_id, "id": candidate_id}
    current = await db[decks.CANDIDATES_COLLECTION].find_one(where, {"_id": 0})
    if not current:
        raise HTTPException(404, "Candidate not found")
    sent = payload.model_fields_set
    edits = {k: getattr(payload, k) for k in _EDITABLE + _CLAIM_FIELDS if k in sent}
    if not edits and "status" not in sent:
        raise HTTPException(400, "Nothing to change")
    if edits and "status" in sent:
        raise _rejected("status", "edit the fields or change the status, not both at once")
    rows = current.get("by_period") or []
    year_end = _fiscal_year_end(await db.audits.find_one({"id": audit_id}, {"fiscal_year_end": 1}))
    if "by_period" in edits:
        # One value of a row can be corrected; the row keeps its periods and cells.
        if not rows or edits["by_period"] is None or len(edits["by_period"]) != len(rows):
            raise _rejected("by_period", "send one value per period of the row")
        edits["by_period"] = [_edited_period({**old, **new.model_dump()}, old, year_end)
                              for old, new in zip(rows, edits["by_period"])]
    if rows and set(edits) & set(_ROW_FIELDS):
        raise _rejected("value", "this claim is a table row; edit its values in by_period")
    if "target_date" in edits:
        edits.update(_period_fields(_edited_period({"target_date": edits["target_date"]}, current, year_end)))
    if current.get("claim_type") in deck_claims.OTHER_TYPES and (payload.status == "approved" or (
            edits and edits.get("claim_type", current["claim_type"]) in deck_claims.OTHER_TYPES)):
        # An Other figure (the model's "other", a figure no heading names a type for) is never a task and never approved: it enters
        # the register only once the analyst retypes it (claim-types-and-correction.md section 4). An edit approves, so it needs
        # the type too.
        raise _rejected("claim_type", "choose a claim type for this item before approving it")
    if edits:
        changes = {**edits, "status": "edited"}
        for field in _CLAIM_FIELDS:
            if field in edits:
                changes[f"{field}_set_by"] = "analyst"
        # Each change keeps its reason code, who made it and the previous value; the provenance stays (section 3)
        log = list(current.get("edit_log") or [])
        now = datetime.now(timezone.utc).isoformat()
        shown = claim_matching.candidate_fields(current, (await db.audits.find_one({"id": audit_id}, {"results": 1}) or {}).get("results"))
        for field, value in edits.items():
            before = current.get(field) if field != "by_period" else [{k: i.get(k) for k in _ROW_FIELDS} for i in rows]
            if field in _CLAIM_FIELDS and before is None:
                before = shown.get(field)
            after = value if field != "by_period" else [{k: i.get(k) for k in _ROW_FIELDS} for i in value]
            if after != before:
                log.append({"field": field, "previous": before, "value": after, "by": "analyst", "at": now, "reason": payload.reason})
        changes["edit_log"] = log
        if current.get("claim_inputs"):
            # a re-typed claim is asked "Same metric and period?" again (claim-matching.md section 4.1); a growth basis set here
            # replaces the one set on the register row
            changes["claim_inputs"] = claim_matching.without_definition_answer(current["claim_inputs"])
            if "growth_basis" in edits:
                changes["claim_inputs"] = {cid: kept for cid, kept in (
                    (cid, {k: v for k, v in inputs.items() if k != "growth_basis"}) for cid, inputs in changes["claim_inputs"].items()) if kept}
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
            raise _rejected("status", "cannot be empty")
        # Approving an edited claim keeps it "edited": it is approved with the analyst's corrections.
        status = "edited" if payload.status == "approved" and "parsed" in current else payload.status
        changes = {"status": status}
    await db[decks.CANDIDATES_COLLECTION].update_one(where, {"$set": changes})
    return sanitize(await db[decks.CANDIDATES_COLLECTION].find_one(where, {"_id": 0}))


class ApproveAll(BaseModel):
    """Approve every claim to review of one category of the list (chat-upload.md section 17): `group` is the category's number
    (deck_claims.GROUPS), `deck_id` the deck tab the analyst is on (none: all decks)."""
    model_config = {"extra": "forbid"}
    group: int = Field(ge=1, le=max(deck_claims.GROUPS))
    deck_id: Optional[str] = None


@api.post("/audits/{audit_id}/decks/candidates/approve-all")
async def approve_all_candidates(audit_id: str, payload: ApproveAll):
    """One call, one category: every claim with status "pending" in the category is approved as a single Approve does it
    ("edited" when it carries the parser's values under "parsed"). Left pending and counted as skipped: a turnover claim whose
    Revenue / Volume question the analyst has not answered, a claim whose type still has to be chosen (Other, Unknown), and a claim
    whose save fails. A claim with an open Definition check is approved like any other: it enters the register as an open check,
    which blocks the verdict (claim-matching.md section 4.1); `open_definition` counts the approved ones. Nothing else changes."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    found = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id}, {"_id": 0}).to_list(10000)
    current = await _current_audit(audit_id, audit, strict=False)
    settings = _register_settings(audit, await _fx(audit_id, audit), await _deck_take_rate(audit_id))
    open_turnover = {cid for cid, views in claim_matching.turnover_views(found, current.get("results"), settings).items()
                     if any(v["turnover_set_by"] != "analyst" for v in views)}
    approved, skipped = [], []
    for c in found:
        if c.get("status") != "pending" or deck_claims.type_group(c.get("claim_type")) != payload.group \
                or (payload.deck_id and c.get("deck_id") != payload.deck_id):
            continue
        if c.get("claim_type") in deck_claims.OTHER_TYPES:      # never a task: neither approved nor counted (section 4)
            continue
        if c["id"] in open_turnover:
            skipped.append(c["id"])
            continue
        try:
            await db[decks.CANDIDATES_COLLECTION].update_one(
                {"audit_id": audit_id, "id": c["id"]}, {"$set": {"status": "edited" if "parsed" in c else "approved"}})
            approved.append(c["id"])
        except Exception:                      # a failed save leaves the claim to review and is counted; the rest go on
            skipped.append(c["id"])
    logger.info("approve all: run_id=%s group=%d approved=%d skipped=%d", audit_id, payload.group, len(approved), len(skipped))
    # The check as the register now holds it: a claim read as an AI suggestion while pending may ask once it is approved.
    after = [{**c, "status": "edited" if "parsed" in c else "approved"} if c["id"] in approved else c for c in found]
    open_definition = claim_matching.open_definition_ids(claim_matching.definition_views(after, current.get("results"), settings))
    return {"approved": len(approved), "skipped": len(skipped), "approved_ids": approved, "skipped_ids": skipped,
            "open_definition": len(open_definition & set(approved))}


# ---------------------------------------------------------------------------
# Run audit: three stages the analyst starts with one button, and the counts the review screen shows
# ---------------------------------------------------------------------------
async def _open_turnover_ids(audit_id: str, audit: dict, found: list) -> set:
    current = await _current_audit(audit_id, audit, strict=False)
    settings = _register_settings(audit, await _fx(audit_id, audit), await _deck_take_rate(audit_id))
    return {cid for cid, views in claim_matching.turnover_views(found, current.get("results"), settings).items()
            if any(v["turnover_set_by"] != "analyst" for v in views)}


async def _accept_within_tolerance(audit_id: str, audit: dict) -> dict:
    """Approve, as approve-all does, every pending claim the register would label Verified within tolerance (not a beat, which the
    analyst reviews, and not a Definition check, section 4.1). A claim whose
    Revenue / Volume question is open, whose type is still to be chosen, or that is not Verified stays pending for the review
    screen. Each accepted claim is marked `auto_accepted`, so the review screen can list it and the analyst can still edit or
    reject it. No threshold or tolerance is read or changed here."""
    audit = await _current_audit(audit_id, audit, strict=False)
    found = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000)
    pending = [c for c in found if c.get("status") == "pending" and c.get("claim_type") not in deck_claims.OTHER_TYPES]
    skipped_turnover = await _open_turnover_ids(audit_id, audit, found)
    decided = [c for c in pending if c["id"] not in skipped_turnover]
    # The register as it would stand with these claims approved; the register's own code labels them.
    trial = [{**c, "status": "edited" if "parsed" in c else "approved"} for c in decided]
    kept = [c for c in found if c.get("status") in REGISTER_STATUSES]
    rows = claim_matching.build_register(
        sorted(kept + trial, key=lambda c: (c.get("file") or "", c.get("order", 0))), audit.get("results"),
        _register_settings(audit, await _fx(audit_id, audit), await _deck_take_rate(audit_id)), peers=found)
    ids = set(run_audit.within_tolerance_ids(rows, [c["id"] for c in decided]))
    accepted = []
    for c in decided:
        if c["id"] not in ids:
            continue
        try:
            await db[decks.CANDIDATES_COLLECTION].update_one(
                {"audit_id": audit_id, "id": c["id"]},
                {"$set": {"status": "edited" if "parsed" in c else "approved", "auto_accepted": True}})
            accepted.append(c["id"])
        except Exception:
            continue
    return {"accepted": len(accepted), "accepted_ids": accepted, "open": len(pending) - len(accepted),
            "turnover_open": len(skipped_turnover & {c["id"] for c in pending})}


@api.post("/audits/{audit_id}/run/{stage}")
async def run_stage(audit_id: str, stage: str):
    """One stage of Run audit, in order: mapping (checks the files are mapped), engine (the calculations), claims (the deck claims
    within tolerance are accepted). It answers 200 with a status: done, needs_review (the analyst must decide something on the
    review screen), waiting (an earlier stage is not done), running (the decks are still being read; ask again) or failed (a
    plain-English message, no exception text). Existing endpoints do the work; nothing here is new logic for the engine."""
    if stage not in run_audit.STAGES:
        raise HTTPException(404, "Unknown stage")
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    datasets = await db.datasets.find({"audit_id": audit_id}, {"_id": 0, "rows": 0}).to_list(10)
    counts = run_audit.mapping_counts(datasets)
    mapped = bool(datasets) and any(d["dtype"] == "revenue" for d in datasets) and not counts["open"] and not counts["missing_required"]
    result = None
    try:
        if stage == "mapping":
            if not datasets:
                result = run_audit.stage_result(stage, run_audit.FAILED, run_audit.NO_FILES, **counts)
            elif not any(d["dtype"] == "revenue" for d in datasets):
                result = run_audit.stage_result(stage, run_audit.FAILED, run_audit.NO_REVENUE, **counts)
            elif not mapped:
                result = run_audit.stage_result(stage, run_audit.NEEDS_REVIEW, None, **counts)
            else:
                result = run_audit.stage_result(stage, run_audit.DONE, None, **counts)
        elif stage == "engine":
            if not mapped:
                result = run_audit.stage_result(stage, run_audit.WAITING, run_audit.WAIT_MAPPING)
            else:
                await _run_compute(audit_id)
                result = run_audit.stage_result(stage, run_audit.DONE)
        else:
            if not audit.get("results"):
                result = run_audit.stage_result(stage, run_audit.WAITING, run_audit.WAIT_ENGINE)
            else:
                deck_docs = await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "ai_status": 1}).to_list(100)
                if not deck_docs:
                    result = run_audit.stage_result(stage, run_audit.DONE, run_audit.NO_DECKS, accepted=0, open=0, turnover_open=0)
                elif any(d.get("ai_status") in ("reading", structures.WAITING) for d in deck_docs):
                    waiting = any(d.get("ai_status") == structures.WAITING for d in deck_docs)
                    result = run_audit.stage_result(
                        stage, run_audit.NEEDS_REVIEW if waiting else run_audit.RUNNING,
                        structures.WAITING_TEXT if waiting else run_audit.DECKS_READING)
                else:
                    result = run_audit.stage_result(stage, run_audit.DONE, None, **(await _accept_within_tolerance(audit_id, audit)))
    except Exception as exc:          # plain English to the analyst; the log has the stage and the error type, never the message
        logger.error("run audit stage failed: run_id=%s stage=%s error=%s", audit_id, stage, type(exc).__name__)
        result = run_audit.stage_result(stage, run_audit.FAILED, run_audit.ENGINE_FAILED if stage == "engine" else run_audit.CLAIMS_FAILED)
    logger.info("run audit: run_id=%s stage=%s status=%s", audit_id, stage, result["status"])
    return sanitize(result)


@api.get("/audits/{audit_id}/review")
async def review_summary(audit_id: str):
    """What the review screen opens with: the columns accepted without a click and the ones waiting, the claims accepted within
    tolerance (their ids, to show them) and the ones waiting, the Revenue / Volume questions open and the hard blockers."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    datasets = await db.datasets.find({"audit_id": audit_id}, {"_id": 0, "rows": 0}).to_list(10)
    found = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000)
    auto = [c["id"] for c in found if c.get("auto_accepted") and c.get("status") in REGISTER_STATUSES]
    # Other figures are never a task (claim-types-and-correction.md section 4)
    pending = [c for c in found if c.get("status") == "pending" and c.get("claim_type") not in deck_claims.OTHER_TYPES]
    open_turnover = await _open_turnover_ids(audit_id, audit, found) if pending else set()
    return sanitize({
        "mappings": run_audit.mapping_counts(datasets),
        "claims": {"auto_accepted": len(auto), "auto_accepted_ids": auto, "open": len(pending),
                   "turnover_open": len(open_turnover & {c["id"] for c in pending})},
        "computed": bool(audit.get("results")),
        "blockers": await _blocker_list(audit_id, audit)})


def merged_fx(audit: dict, file_fx: Optional[dict]) -> dict:
    """The audit's FX rates, upper-cased, with the reporting currency at 1: the rates saved with the revenue file (older
    audits) under the audit's own rates, which win. One set of rates serves the uploaded files and the deck claims."""
    fx = {str(k).upper(): float(v) for k, v in (file_fx or {}).items()}
    fx.update({str(k).upper(): float(v) for k, v in (audit.get("fx") or {}).items()})
    fx[(audit.get("reporting_currency") or "EUR").upper()] = 1.0
    return fx


async def _fx(audit_id: str, audit: dict) -> dict:
    revenue = await db.datasets.find_one({"audit_id": audit_id, "dtype": "revenue"}, {"fx": 1}) or {}
    return merged_fx(audit, revenue.get("fx"))


class FxPayload(BaseModel):
    """The audit's FX rates: currency code to the rate into the reporting currency (docs/specs/claim-matching.md section 2)."""
    model_config = {"extra": "forbid"}
    fx: Dict[str, float]

    @field_validator("fx")
    @classmethod
    def _rates(cls, v):
        out = {}
        for code, rate in v.items():
            code = code.strip().upper()
            if not re.fullmatch(r"[A-Z]{3}", code):
                raise ValueError("a currency is a 3-letter code")
            if not (rate > 0 and rate < float("inf")):
                raise ValueError("a rate is a positive number")
            out[code] = float(rate)
        return out


@api.put("/audits/{audit_id}/fx")
async def save_fx(audit_id: str, payload: FxPayload):
    """Save the audit's FX rates: the whole set, as the screen shows it. They need no file: they apply to the uploaded files
    and to the deck claims alike. Rates an older version saved with the revenue file are in that set (the screen merges
    them), so they move to the audit here and the file's copy is cleared: a rate the analyst removes stays removed."""
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    await db.audits.update_one({"id": audit_id}, {"$set": {"fx": payload.fx}})
    await db.datasets.update_many({"audit_id": audit_id, "dtype": "revenue"}, {"$set": {"fx": {}}})
    await _mark_stale_and_maybe_recompute(audit_id)
    return {"fx": payload.fx}


def _register_settings(audit: dict, fx: dict, deck_take_rate: bool = False) -> dict:
    return {"fiscal_year_end": _fiscal_year_end(audit), "as_of_month": audit.get("as_of_month"),
            "reporting_currency": audit.get("reporting_currency") or "EUR", "fx": fx,
            "turnover_choices": audit.get("turnover_choices") or {}, "deck_take_rate": deck_take_rate}


async def _deck_take_rate(audit_id: str) -> bool:
    """Whether any parsed deck of the audit says "take rate" (claim-matching.md section 11).
    Python reads the stored deck text; only the yes or no is used."""
    decks_found = await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "blocks": 1}).to_list(1000)
    return claim_matching.mentions_take_rate(decks_found)


async def _claim_rows(audit_id: str, audit: dict) -> tuple:
    """(register candidates, register rows in rank order). The rows are computed on read from the stored results and
    the analyst's inputs on the candidates (docs/specs/claim-matching.md section 6); nothing is sent to a model."""
    audit = await _current_audit(audit_id, audit, strict=False)
    # Every candidate not rejected: the register holds the approved and edited ones; the deck hint (claim-matching.md
    # section 11 point 7) reads the pending ones too.
    found = await db[decks.CANDIDATES_COLLECTION].find(
        {"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000)
    claims = [c for c in found if c.get("status") in REGISTER_STATUSES]
    claims.sort(key=lambda c: (c.get("file") or "", c.get("order", 0)))
    # The extraction confidence the deck list shows, read over every candidate of the deck as the list reads it (evidence-labels.md)
    every = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id}, {"_id": 0}).to_list(10000)
    claims = claim_matching.with_confidence(claims, every)
    rows = claim_matching.build_register(
        claims, audit.get("results"), _register_settings(audit, await _fx(audit_id, audit), await _deck_take_rate(audit_id)),
        peers=found)
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
    review = verdict_mod.with_review(audit, audit.get("ic_inputs")).get("first_quarterly_review")
    # The gate fields' starting values and the budget dropdown sit beside the register, never in it: the CSV and the memo read rows.
    return sanitize({"claims": claims, "register": rows, "gate_prefill": verdict_mod.gate_prefill(rows, review),
                     "budget_decisions": verdict_mod.budget_decisions(rows)})


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
    ic = verdict_mod.with_review(audit, audit.get("ic_inputs"))
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


async def _integrity(audit_id: str, results: Optional[dict]) -> dict:
    """Both blocks of the Data integrity section and the conclusion (docs/specs/integrity-coverage.md), from the stored results, the
    deck count and the stored candidates. Pure reads; no model."""
    deck_count = len(await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "deck_id": 1}).to_list(100))
    candidates = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000)
    return integrity_mod.assess(results, deck_count=deck_count, candidates=candidates)


@api.get("/audits/{audit_id}/integrity")
async def get_integrity(audit_id: str):
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    results = (await _current_audit(audit_id, audit, strict=False)).get("results")
    out = await _integrity(audit_id, results)
    logger.info("integrity: run_id=%s conclusion=%s completed=%d applicable=%d", audit_id, out["code"], out["completed"],
                out["applicable"])
    return sanitize(out)


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
    # dates-and-periods.md section 5: the one-click "Set growth basis" of a growth claim
    growth_basis: Optional[Literal["mom", "yoy", "annualised", "cumulative"]] = None

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
        raise _rejected("metric", "choose a metric in the claim's unit, or none")
    if segment is not None and segment not in (claim_matching.WHOLE, claim_matching.NOT_IN_DATA,
                                               *claim_matching.data_segments(audit["results"])):
        raise _rejected("segment", "choose a segment of the data, Whole company or Not in the data")
    candidate = next(c for c in claims if c["id"] == claim_id.split("#")[0])
    inputs = {**(candidate.get("claim_inputs") or {})}
    if {"metric", "segment", "growth_basis"} & sent:  # a re-matched claim is asked "Same metric and period?" again (section 4.1)
        inputs = claim_matching.without_definition_answer(inputs, {claim_id})
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
        after = claim_matching.build_register(trial, current.get("results"), _register_settings(audit, await _fx(audit_id, audit), await _deck_take_rate(audit_id)))
        after_row = next(r for r in after if r["claim_id"] == claim_id)
        if not after_row["gate_saved"]:
            raise _rejected("key_gate", "a key gate needs a saved gate")
        if sum(1 for r in after if r["key_gate"]) > verdict_mod.MAX_KEY_GATES:
            raise HTTPException(400, verdict_mod.W5_SIXTH)
    await db[decks.CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": candidate["id"]},
                                                    {"$set": {"claim_inputs": inputs}})
    _, rows = await _claim_rows(audit_id, audit)
    return sanitize({"register": rows})


class GateBatch(BaseModel):
    """Save all gates: the gates the analyst has filled, each with the fields of one claim, in one call."""
    model_config = {"extra": "forbid"}
    gates: List[dict] = Field(min_length=1, max_length=500)


@api.put("/audits/{audit_id}/claim-gates")
async def save_all_gates(audit_id: str, payload: GateBatch):
    """Save every gate sent, together or not at all. Each entry is a claim_id and the gate fields of PUT /claims/{claim_id}; the
    result is the register as it reads after the save. A gate that would not be complete, or a sixth key gate, refuses the lot."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    if not audit.get("results"):
        raise HTTPException(409, "Audit not computed yet")
    claims, rows = await _claim_rows(audit_id, audit)
    by_id = {r["claim_id"]: r for r in rows}
    by_candidate = {c["id"]: {**(c.get("claim_inputs") or {})} for c in claims}
    for entry in payload.gates:
        claim_id = entry.get("claim_id")
        if claim_id not in by_id:
            raise HTTPException(404, "Claim not in the register")
        try:
            values = ClaimInputs(**{k: v for k, v in entry.items() if k in ("gate_threshold", "gate_budget_decision", "gate_date",
                                                                            "gate_metric_name", "gate_direction", "key_gate")}).model_dump(exclude_unset=True)
        except ValidationError as exc:
            raise HTTPException(400, f"{claim_id}: {exc.errors()[0]['msg']}")
        for text_field in ("gate_budget_decision", "gate_metric_name"):
            if isinstance(values.get(text_field), str):
                values[text_field] = values[text_field].strip() or None
        if values.get("key_gate") is False:
            values["key_gate"] = None
        inputs = by_candidate[claim_id.split("#")[0]]
        kept = {**inputs.get(claim_id, {}), **{k: v for k, v in values.items() if v is not None}}
        for k, v in values.items():
            if v is None:
                kept.pop(k, None)
        inputs[claim_id] = kept
    trial = [{**c, "claim_inputs": by_candidate[c["id"]]} for c in claims]
    current = await _current_audit(audit_id, audit, strict=False)
    after = claim_matching.build_register(trial, current.get("results"), _register_settings(audit, await _fx(audit_id, audit), await _deck_take_rate(audit_id)))
    for r in after:
        sent_key = any(e.get("claim_id") == r["claim_id"] and e.get("key_gate") for e in payload.gates)
        if sent_key and not r["gate_saved"]:
            raise _rejected("key_gate", "a key gate needs a saved gate")
    if sum(1 for r in after if r["key_gate"]) > verdict_mod.MAX_KEY_GATES:
        raise HTTPException(400, verdict_mod.W5_SIXTH)
    for c in claims:
        await db[decks.CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": c["id"]},
                                                        {"$set": {"claim_inputs": by_candidate[c["id"]]}})
    _, rows = await _claim_rows(audit_id, audit)
    return sanitize({"register": rows})


class TurnoverAnswer(BaseModel):
    """The one-click answer to the turnover question (claim-matching.md section 11): closed words only."""
    model_config = {"extra": "forbid"}
    answer: Literal["revenue", "volume"] = Field(alias="as")
    reason: Literal[claim_matching.TURNOVER_REASONS]

    @model_validator(mode="after")
    def _reason_fits_the_answer(self):
        if (self.answer, self.reason) in claim_matching.CONTRADICTORY_ANSWERS:
            raise ValueError("The reason contradicts the answer")
        return self


@api.put("/audits/{audit_id}/claims/{claim_id}/turnover")
async def answer_turnover(audit_id: str, claim_id: str, payload: TurnoverAnswer):
    """Save the analyst's Revenue or Volume answer for a turnover claim, on the claim and on the audit (under a hash of the
    term and the period, no deck text) so the same term and period reuse it. Gives the register back. The claim may still
    be pending (the deck list asks in its row, section 11 point 8) and the audit not yet computed: the answer needs neither."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    claims = await db[decks.CANDIDATES_COLLECTION].find(
        {"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000)
    candidate = next((c for c in claims if c["id"] == claim_id.split("#")[0]), None)
    if candidate is None or not any(c["claim_id"] == claim_id for c in claim_matching._expand([candidate])):
        raise HTTPException(404, "Claim not found")
    current = await _current_audit(audit_id, audit, strict=False)
    views = claim_matching.turnover_views(claims, current.get("results"), _register_settings(
        audit, await _fx(audit_id, audit), await _deck_take_rate(audit_id)))
    if not any(v["claim_id"] == claim_id for v in views.get(candidate["id"]) or ()):
        raise HTTPException(400, "This claim is not a turnover claim")
    expanded = next(c for c in claim_matching._expand([candidate]) if c["claim_id"] == claim_id)
    inputs = claim_matching.without_definition_answer(candidate.get("claim_inputs"), {claim_id})     # re-matched: asked again
    inputs[claim_id] = {**inputs.get(claim_id, {}), "turnover_as": payload.answer, "turnover_reason": payload.reason}
    await db[decks.CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": candidate["id"]},
                                                    {"$set": {"claim_inputs": inputs}})
    await db.audits.update_one({"id": audit_id}, {"$set": {f"turnover_choices.{claim_matching.turnover_key(expanded)}": {
        "as": payload.answer, "reason": payload.reason, "saved_at": usage_mod.now()}}})
    logger.info("turnover answer: run_id=%s as=%s reason=%s", audit_id, payload.answer, payload.reason)
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    _, rows = await _claim_rows(audit_id, audit)
    return sanitize({"register": rows})


class DefinitionAnswer(BaseModel):
    """The answer to "Same metric and period?" for a gap beyond 50% of the claim (claim-matching.md section 4.1)."""
    model_config = {"extra": "forbid"}
    answer: Literal[claim_matching.DEFINITION_ANSWERS]


@api.put("/audits/{audit_id}/claims/{claim_id}/definition-check")
async def answer_definition_check(audit_id: str, claim_id: str, payload: DefinitionAnswer):
    """Save the analyst's Yes or No on the claim's inputs and give the register back. The claim may still be pending (the review
    screen asks before it is approved); it must have a Definition check now, asked or answered, so an answer can be changed."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    claims = await db[decks.CANDIDATES_COLLECTION].find(
        {"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000)
    candidate = next((c for c in claims if c["id"] == claim_id.split("#")[0]), None)
    if candidate is None or not any(c["claim_id"] == claim_id for c in claim_matching._expand([candidate])):
        raise HTTPException(404, "Claim not found")
    current = await _current_audit(audit_id, audit, strict=False)
    if not current.get("results"):
        raise HTTPException(409, "Audit not computed yet")
    found = claim_matching.definition_rows(claims, current.get("results"), _register_settings(
        audit, await _fx(audit_id, audit), await _deck_take_rate(audit_id)))
    row = next((r for r in found.get(candidate["id"]) or () if r["claim_id"] == claim_id), None)
    if row is None:
        raise HTTPException(400, "This claim has no definition check")
    inputs = {**(candidate.get("claim_inputs") or {})}      # the answer is kept with the figures it was given against
    inputs[claim_id] = {**inputs.get(claim_id, {}), "definition_check": payload.answer,
                        "definition_basis": claim_matching.definition_basis(row)}
    await db[decks.CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": candidate["id"]},
                                                    {"$set": {"claim_inputs": inputs}})
    logger.info("definition check: run_id=%s answer=%s", audit_id, payload.answer)
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
                        "evidence_label": r["evidence_label"], "reason": r["reason"]} for r in verdict_mod.sortable(rows)],
        "ic_inputs": {k: ic.get(k) for k in ("first_quarterly_review", "ratings", "thesis", "judgment")},
        "ratings": list(verdict_mod.RATINGS), "ratings_for": {k: ic_memo.RATING_LABELS[k] for k in verdict_mod.RATED_ROWS},
        "thesis_labels": ic_memo.THESIS_LABELS, "thesis_max": verdict_mod.THESIS_MAX,
        "judgment_labels": verdict_mod.JUDGMENT_LABELS, "judgment_max": verdict_mod.JUDGMENT_MAX,
    })


class IcInputs(BaseModel):
    """The analyst's inputs to the verdict and the memo. A key sent as null clears it; a key not sent stays."""
    model_config = {"extra": "forbid"}
    top5: Optional[List[str]] = None
    first_quarterly_review: Optional[str] = None
    gap_target_dates: Optional[dict] = None
    ratings: Optional[dict] = None
    thesis: Optional[dict] = None
    judgment: Optional[dict] = None         # claim-review-conclusion.md section 3: Reasons, Unresolved questions

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

    @field_validator("judgment")
    @classmethod
    def _known_judgment(cls, v):
        for part, text in (v or {}).items():
            if part not in verdict_mod.JUDGMENT_PARTS or (text is not None and (not isinstance(text, str) or len(text) > verdict_mod.JUDGMENT_MAX)):
                raise ValueError(f"the analyst judgment is Reasons and Unresolved questions, each at most {verdict_mod.JUDGMENT_MAX} characters")
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
    changes = {k: getattr(payload, k) for k in sent}
    if "first_quarterly_review" in sent and payload.first_quarterly_review is None:
        # Required: clearing it returns the date to the default, it never leaves the audit without one.
        changes["first_quarterly_review"] = verdict_mod.default_review(audit.get("created_at"))
    try:
        ic = verdict_mod.apply_ic_inputs(ctx["ic"], changes, ctx["rows"], ctx["gaps"],
                                         datetime.now(timezone.utc).isoformat())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await db.audits.update_one({"id": audit_id}, {"$set": {"ic_inputs": ic}})
    return await get_verdict(audit_id)


def analysis_date(audit: dict) -> str:
    """The requested analysis date: the analyst's, else today (dates-and-periods.md section 2). It dates the memo and the analyst's
    text and is never printed next to a figure."""
    return audit.get("analysis_date") or datetime.now(timezone.utc).date().isoformat()


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
            decks=[{"file": d.get("file")} for d in deck_docs], tables=tables, today=analysis_date(audit),
            integrity=await _integrity(audit_id, results))
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
RECOMPUTE_TRIGGER_FIELDS = {"reporting_currency", "target_arr", "target_date", "as_of_month", "last_month_complete"}


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

    def read(dtype):
        d = ds[dtype]
        return normalize(d["rows"], dtype, d["mapping"], d.get("row_numbers"), d.get("unit_scale") or 1)
    rev = read("revenue")
    crm = read("crm") if "crm" in ds else pd.DataFrame()
    pnl = read("pnl") if "pnl" in ds else pd.DataFrame()

    fx = merged_fx(a, ds["revenue"].get("fx"))
    config = {
        "reporting_currency": a["reporting_currency"], "target_arr": a["target_arr"],
        "target_date": a["target_date"], "fx": fx,
        "billing_terms": ds["revenue"].get("billing_terms", {}), "default_l": 1,
        "as_of_month": a.get("as_of_month"),
        "last_month_complete": bool(a.get("last_month_complete")),
    }
    sources = {t: {"file": ds[t]["file"], "sheet": ds[t]["sheet"]} for t in ds}
    failures = []

    def on_error(exc):
        failures.append(type(exc).__name__)
        _log_metric_error(exc, audit_id)
    try:
        results = sanitize(ge.compute_all(rev, crm, pnl, config, sources, files=candidate_views(ds), on_error=on_error))
    except Exception as exc:
        failed = failures + [type(exc).__name__]        # bound before the lambda: `exc` is unbound once the block ends
        await _usage_update(audit_id, lambda u: usage_mod.record_compute(u, failed))
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
            # the evidence end and the latest valid source period, never the as-of setting as a period (dates-and-periods.md)
            ("Evidence to", None, ((r.get("source_period") or {}).get("evidence_to") or r.get("as_of_month"))),
            ("Latest valid source period", None, fmt.source_period_text(r.get("source_period"))),
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
        as_of = (r.get("source_period") or {}).get("evidence_to") or r.get("as_of_month") or ""     # the active customers' month
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


@api.get("/runs/{run_id}/narratives/estimate")
async def narratives_estimate(run_id: str):
    """The steps "Write all narratives" would run and what they would cost at most. Read-only: no provider call."""
    await _recompute_if_old(run_id)
    try:
        return await llm_gateway.estimate_narratives(db, run_id)
    except llm_gateway.GatewayError as exc:
        if exc.reason in ("run_not_found", "not_computed"):
            raise HTTPException(404 if exc.reason == "run_not_found" else 409, str(exc))
        raise


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
# 9: results carry contract_version 3 (the latest valid source period and the period of every metric).
SEED_VERSION = 9


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
