from fastapi import BackgroundTasks, Body, Depends, FastAPI, APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, Response, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import re
import bson
import hashlib
import logging
import uuid
from pathlib import Path
from datetime import date as date_type, datetime, time as time_type, timedelta, timezone
from typing import Dict, List, Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

import growth_engine as ge
import demo_data
from schemas import metrics as contract
from app import as_of as as_of_mod
from app import readings as readings_mod
from app import sheet_reader
from app import reading_export
from app import reviewer
from app import register
from app import cards as cards_mod
from app import checks as checks_mod
from app import flags
from app import deck_figures
from app import role_engine
from app import formatting as fmt
from app import disclosure as disclosure_mod
from app import narrative_export
from app import run_audit
from app import claim_matching
from app import claim_groups
from app import access as access_mod
from app import ic_memo
from app import integrity as integrity_mod
from app import verdict as verdict_mod
from app import decks
from app.decks import pages as deck_pages
from app.decks import render as deck_render
from app import structures
from app import column_rules as cr
from app import stored_sheets as rec
from app import allowance as allowance_mod
from app import usage as usage_mod
from app import tester_view
from app.decks import claims as deck_claims
from app.decks import parser as deck_parser
from app.llm import gateway as llm_gateway
from app.llm import prompt_store
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
    if path.startswith("/api/admin/") or path == "/api/usage/totals":      # owner token only; a tester gets 404
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
            if isinstance(v, (pd.Timestamp, datetime, date_type, time_type)):
                r[k] = v.isoformat()
            elif isinstance(v, timedelta):
                r[k] = v.total_seconds()
            elif isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
                r[k] = None
    return recs


def normalize(rows: list, dtype: str, mapping: dict, row_numbers: Optional[list] = None, unit_scale: int = 1,
              constants: Optional[dict] = None) -> pd.DataFrame:
    """The stored rows read through a mapping. `_row` is the row's number in the sheet it came from
    (`row_numbers`, kept at upload); without it the header is taken to be row 1 with no blank lines. `unit_scale` is
    1,000 when the title rows of the file said the figures are in thousands: the money fields are multiplied by it. `constants` are
    columns the analyst supplied for every row ({"Currency (confirmed)": "EUR"}): a file with no currency column takes the currency
    the analyst confirmed (revenue-file-recognition.md section 2)."""
    if not rows:
        return pd.DataFrame()
    raw = pd.DataFrame(rows)
    for column, value in (constants or {}).items():
        if column not in raw.columns:
            raw[column] = value
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
        for as_type in DTYPE_ORDER:
            mapping = (d.get("mapping") or {}) if as_type == dtype else suggest_mapping(as_type, d.get("columns") or [])
            mapping = {f: c for f, c in mapping.items() if c}
            views[as_type] = {"mapping": mapping, "frame": normalize(d.get("rows") or [], as_type, mapping, d.get("row_numbers"), d.get("unit_scale") or 1,
                                                                 d.get("constants"))}
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
    """A required name: trimmed, and never blank."""
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
    # The analyst's date: dates the memo and the analyst's own text, never a figure (null: today).
    analysis_date: Optional[str] = None
    # The month the company's fiscal year ends in (deck-parser.md section 2). FY25 is the fiscal year
    # that ends in 2025; with December it is the calendar year.
    fiscal_year_end: int = Field(default=12, ge=1, le=12)
    structure_reading_consent: bool = True

    _check_target_date = field_validator("target_date")(_validate_target_date)
    _check_as_of_month = field_validator("as_of_month")(_validate_as_of_month)
    _check_analysis_date = field_validator("analysis_date")(_validate_analysis_date)
    _check_required = field_validator("company_name")(_required_text)


class AuditUpdate(BaseModel):
    company_name: Optional[str] = None
    reporting_currency: Optional[str] = None
    target_arr: Optional[float] = None
    target_date: Optional[str] = None
    as_of_month: Optional[str] = None
    analysis_date: Optional[str] = None
    fiscal_year_end: Optional[int] = Field(default=None, ge=1, le=12)
    structure_reading_consent: Optional[bool] = None

    _check_target_date = field_validator("target_date")(_validate_target_date)
    _check_as_of_month = field_validator("as_of_month")(_validate_as_of_month)
    _check_analysis_date = field_validator("analysis_date")(_validate_analysis_date)
    _check_required = field_validator("company_name")(_required_text)


def _consent_entry(value: bool) -> dict:
    """One change of the consent checkbox, with its time. The user is added when accounts exist."""
    return {"value": bool(value), "at": datetime.now(timezone.utc).isoformat()}




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
    a.pop("token_map", None)      # real name -> token: server side only (read-check-review.md section 8)
    a.pop("usage", None)          # the counters, notes included, are read only through the usage totals
    a["as_of_by"] = _as_of_by(a)
    a.pop("as_of_cue", None)      # the boundary-cue path of PR 199 is gone; the evidence line is `as_of_evidence`
    a["provider_zdr"] = os.environ.get("PROVIDER_ZDR", "").strip().lower() == "true"     # picks the deck sentence of the Upload page text
    a["old_claims"] = flags.old_claims()      # OLD_CLAIMS: the claim register, five claims, reasons, key gates and labels (off by default)
    a["results_stale"] = run_audit.results_stale(a)
    if a["results_stale"]:
        a["results"] = None       # figures of an older engine contract never reach the browser (George, 2026-10-20)
    if a.get("created_at"):
        a["ic_inputs"] = verdict_mod.with_review(a, a.get("ic_inputs"))
    ds = await db.datasets.find({"audit_id": a["id"]}, {"rows": 0, "recognition_sheets": 0, "_id": 0}).to_list(10)
    a["datasets"] = {
        d["dtype"]: {k: d.get(k) for k in ("file", "sheet", "columns", "mapping", "fx", "billing_terms", "preview", "row_count",
                                           "mapping_source", "ai_reading", "months")}
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
        "fiscal_year_end": payload.fiscal_year_end,
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
    text: str      # no max_length here: prompt_store.upload refuses over prompt_store.MAX_TEXT_CHARS with the owner-page message


# Prompt text goes in and never comes out: the list has name, version, date, hash and character count (docs/specs/prompt-store.md). Owner token only
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


class AllowanceSet(BaseModel):
    model_config = {"extra": "forbid"}
    allowance_usd: float = Field(ge=0, le=allowance_mod.MAX_ALLOWANCE_USD)

    @field_validator("allowance_usd")
    @classmethod
    def _cents(cls, v: float) -> float:
        if round(v, 2) != v:
            raise ValueError("at most two decimals")
        return v


@api.get("/admin/usage")
async def admin_usage():
    """The owner's Usage section: counts, tokens and USD per tester link label, this month and all time. No audit field."""
    return await allowance_mod.report(db)


@api.get("/admin/audit-costs")
async def admin_audit_costs():
    """The owner's cost per audit: tester label, creation time, billed calls, tokens and USD. No audit id, company or file name."""
    return await allowance_mod.audit_costs(db)


@api.post("/admin/testers/{tester_id}/allowance")
async def set_tester_allowance(tester_id: str, payload: AllowanceSet):
    if not await allowance_mod.set_allowance(db, tester_id, payload.allowance_usd):
        raise HTTPException(404, "Not found")
    return {"ok": True, "allowance_usd": round(payload.allowance_usd, 2)}


@api.get("/allowance")
async def my_allowance(request: Request):
    """The caller's monthly AI allowance as a percentage and a state, no amount (usage-and-allowance.md sections 4 and 9). The owner
    token gets 404 from the guard."""
    who = getattr(request.state, "principal", None)
    doc = await db[access_mod.COLLECTION].find_one({"id": who[1]}) if who and who[1] else None
    return {k: v for k, v in allowance_mod.status(doc).items() if k in ("percent", "state")} if doc else {"state": "off"}


@api.get("/audits")
async def list_audits(request: Request):
    who = getattr(request.state, "principal", None)
    flt = {"owner": who[1]} if who else {}
    return await db.audits.find(flt, {"_id": 0, "results": 0, "usage": 0, "owner": 0, "token_map": 0}).sort("created_at", -1).to_list(200)


@api.get("/audits/{audit_id}")
async def get_audit(audit_id: str):
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    return await audit_public(a)


@api.put("/audits/{audit_id}")
async def update_audit(audit_id: str, payload: AuditUpdate, background: BackgroundTasks):
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "as_of_month" in payload.model_fields_set:
        # One as-of month (dates-and-periods.md section 2): a typed month is the analyst's and detection leaves it; an explicit null
        # hands it back to detection on Map.
        updates["as_of_by"] = as_of_mod.ANALYST if payload.as_of_month else as_of_mod.DETECTED
        updates["as_of_month"] = payload.as_of_month or None
        if payload.as_of_month and payload.as_of_month != a.get("as_of_month"):
            # A typed month is a dated override of the files' proposal, a record of its own (read-check-review.md section 9).
            await readings_mod.add_override(db, reading="audit", audit_id=audit_id, item="as_of_month", path="as_of_month",
                                            old=a.get("as_of_month"), new=payload.as_of_month, who="analyst", why="typed in the set-up")
    if "analysis_date" in payload.model_fields_set and payload.analysis_date is None:
        updates["analysis_date"] = None     # an explicit null returns the requested analysis date to today
    consent = updates.get("structure_reading_consent")
    ticked_later = consent is True and a.get("structure_reading_consent") is not True
    if consent is not None and consent != (a.get("structure_reading_consent") is True):
        await db.audits.update_one({"id": audit_id},
                                   {"$set": {"consent_log": list(a.get("consent_log") or []) + [_consent_entry(consent)]}})
    if updates:
        changed = {k for k, v in updates.items() if k in STALE_ON_CHANGE_FIELDS and _setup_value(k, v) != _setup_value(k, _stored_setup(a, k))}
        # A changed input marks the stored results stale (George, 2026-10-24); Run audit calculates again. Nothing recomputes on its own.
        await db.audits.update_one({"id": audit_id}, {"$set": {**updates, **({"setup_stale": True} if changed and a.get("results") else {})}})
        if "fiscal_year_end" in updates and updates["fiscal_year_end"] != _fiscal_year_end(a):
            await _remap_periods(audit_id, updates["fiscal_year_end"])
        if "as_of_month" in payload.model_fields_set and not payload.as_of_month or "fiscal_year_end" in updates:
            await _refresh_as_of(audit_id)
    if consent is False and a.get("structure_reading_consent") is True:
        await deck_render.remove(db, audit_id)      # unticked: the stored deck files go (re-upload to read pages with images after ticking again)
    if ticked_later:
        # Consent false to true (chat-upload.md section 23): every deck already uploaded is read through the normal
        # structure path, after the response. Mapped data files are not touched; the sheet reader reads their stored sheets.
        await _queue_stored_reads(audit_id, background)
        for deck_id in await structures.queue_decks(db, audit_id):
            background.add_task(structures.process_deck_safely, db, audit_id, deck_id)
    return await audit_public(await db.audits.find_one({"id": audit_id}))


def _stored_setup(audit: dict, field: str):
    return _fiscal_year_end(audit) if field == "fiscal_year_end" else audit.get(field)


def _setup_value(field: str, value):
    """A set-up value as compared for a change: the target as a number, the dates as text, an empty date as none."""
    if field == "target_arr":
        return float(value or 0)
    return value or None


def _fiscal_year_end(audit: Optional[dict]) -> int:
    """The audit's fiscal year-end month; audits created before the field existed end in December."""
    return int((audit or {}).get("fiscal_year_end") or 12)


async def _remap_periods(audit_id: str, fiscal_year_end: int) -> None:
    """A new fiscal year-end re-runs period mapping: every stored claim's date range moves, its stated
    period and target date stay (deck-parser.md section 2)."""
    found = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id}, {"_id": 0}).to_list(10000)
    for c in deck_claims.remap_periods(found, fiscal_year_end):
        changes = {k: c.get(k) for k in ("period_start", "period_end", "by_period", "sources") if k in c}
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
    await deck_render.remove(db, audit_id)             # the stored deck files the page images are drawn from (rule 22)
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
async def usage_totals():
    """Sums across audits, the median days from first upload to first export and the 50 newest "Other" notes. No
    per-audit rows, names or ids (chat-upload.md section 7). Tokens and cost come from the call log; evidence
    labels and analyst changes are computed on read from what the audits hold. Owner token only: a tester gets 404 from the
    guard (usage-and-allowance.md D3)."""
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
ALLOWED_EXTENSIONS = ("xlsx", "csv")
XLS_REFUSED = "Save as .xlsx or .csv and upload again."       # an old .xls workbook (2026-10-08)
NOTE_REFUSED = "Leave out file names, figures and cell values: this note is kept with the usage counts."
DTYPE_ORDER = ("revenue", "crm", "pnl")
























def _as_of_by(audit: Optional[dict]) -> str:
    """"analyst" when the as-of month was typed, else "detected". An audit stored before the field existed with an as-of month set
    keeps it as the analyst's."""
    a = audit or {}
    return a.get("as_of_by") or (as_of_mod.ANALYST if a.get("as_of_month") else as_of_mod.DETECTED)


async def _refresh_as_of(audit_id: str) -> None:
    """Detect the audit's one as-of month when a file is mapped or read (docs/specs/dates-and-periods.md section 2, read-check-review.md
    section 6) and store it on the audit, unless the analyst typed one. The proposal of the files is always kept (`as_of_proposal`), beside
    a typed month too. A changed month marks computed results stale; nothing recomputes on its own."""
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        return
    found = as_of_mod.detect(await sheet_reader.reads_for(db, audit_id))
    month = as_of_mod.month_end(found["month"]) if found else None
    proposal = {"month": month, "file": found["file"], "evidence": found["evidence"]} if found else None
    if _as_of_by(a) == as_of_mod.ANALYST:
        fields = {"as_of_proposal": proposal}
        month = a.get("as_of_month")
    else:
        fields = {"as_of_month": month, "as_of_by": as_of_mod.DETECTED, "as_of_file": found["file"] if found else None,
                  "as_of_evidence": found["evidence"] if found else None, "as_of_proposal": proposal}
    if all(a.get(k) == v for k, v in fields.items()):
        return
    stale = {"setup_stale": True} if month != a.get("as_of_month") and a.get("results") else {}
    await db.audits.update_one({"id": audit_id}, {"$set": {**fields, **stale}})




































async def _ingest(audit_id: str, upload: UploadFile, background: BackgroundTasks):
    """A spreadsheet in: stored as it is (its sheets, kept to read the file again) and read by the sheet reader after the response
    (read-check-review.md section 3). No type is asked, no column is mapped and nothing waits for an answer: the map is the reading."""
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
    existing = await db.datasets.find_one({"audit_id": audit_id, "file_hash": digest}, {"_id": 0, "recognition_sheets": 0})
    if existing:
        return {**_file_view(existing), "status": "same_file"}
    doc = {"audit_id": audit_id, "dtype": FILE_DTYPE, "file": filename, "file_hash": digest, "size_bytes": len(content), "ext": ext,
           "sheets": len(sheets), "row_count": sum(len(s.frame) for s in sheets), "uploaded_at": usage_mod.now(),
           "recognition_sheets": rec.pack_sheets(sheets)}
    _check_dataset_size(doc)               # a file over the limit is refused with the message, never a raw error
    await db.datasets.insert_one(doc)
    await _usage_update(audit_id, lambda u: usage_mod.record_upload(u, FILE_DTYPE))
    await allowance_mod.record_for_audit(db, audit_id, files=1)
    await _queue_workbook_read(a, audit_id, sheets, digest, filename, background)
    logger.info("upload: run_id=%s sheets=%d", audit_id, len(sheets))
    return {**_file_view(doc), "status": "ok"}


async def _read_workbook_safely(audit_id: str, sheets: list, digest: str, filename: str) -> None:
    """The sheet reader for one stored file (read-check-review.md section 3): read, check, re-read once, store the outcome, then refresh the
    audit's as-of month. After the upload's response, so a long map never holds the request. A failure of any kind leaves the upload as it
    is (rule 20) and is logged by code only."""
    try:
        a = await db.audits.find_one({"id": audit_id})
        if not a:
            return
        doc = await sheet_reader.read_file(db, a, sheets, digest, filename, _fiscal_year_end(a))
        status = doc.get("status", "not_read")
        await _usage_update(audit_id, lambda u: u["steps"].setdefault("sheet_reading", {}).__setitem__(
            status, u["steps"]["sheet_reading"].get(status, 0) + 1))
        await _refresh_as_of(audit_id)
        await _mark_stale_and_maybe_recompute(audit_id)
        logger.info("sheet reading: run_id=%s status=%s month=%s", audit_id, status, doc.get("month") or "-")
    except Exception as exc:
        logger.error("sheet reading failed: run_id=%s error=%s", audit_id, type(exc).__name__)
    finally:
        await db.audits.update_one({"id": audit_id}, {"$inc": {"sheet_reads_pending": -1}})


async def _queue_workbook_read(a: dict, audit_id: str, sheets: list, digest: str, filename: str,
                               background: Optional[BackgroundTasks]) -> None:
    """Queue the sheet reader for a file just stored, with the audit's consent."""
    if a.get("structure_reading_consent") is not True:
        return
    await db.audits.update_one({"id": audit_id}, {"$inc": {"sheet_reads_pending": 1}})
    if background is None:
        await _read_workbook_safely(audit_id, sheets, digest, filename)
    else:
        background.add_task(_read_workbook_safely, audit_id, sheets, digest, filename)


async def _queue_stored_reads(audit_id: str, background: BackgroundTasks) -> None:
    """Consent ticked after the files were uploaded: every stored file is read now. A reading already stored for the file makes no call."""
    a = await db.audits.find_one({"id": audit_id})
    for ds in await db.datasets.find({"audit_id": audit_id}).to_list(50):
        sheets = rec.unpack_sheets(ds.get("recognition_sheets") or [])
        if sheets and ds.get("file_hash") and a:
            await _queue_workbook_read(a, audit_id, sheets, ds["file_hash"], ds.get("file") or "", background)


FILE_DTYPE = "file"       # every stored spreadsheet is one file: its type is the reader's map, not a choice


def _file_view(ds: dict) -> dict:
    """What the upload page shows for one stored file: its name and size. What was read from it is the reading's (ReadingScreen)."""
    return {"dtype": FILE_DTYPE, "file": ds.get("file"), "file_hash": ds.get("file_hash"), "size_bytes": ds.get("size_bytes"),
            "ext": ds.get("ext") or usage_mod.extension_of(ds.get("file") or ""), "row_count": ds.get("row_count"),
            "sheets": ds.get("sheets"), "uploaded_at": ds.get("uploaded_at")}














@api.post("/audits/{audit_id}/datasets/upload")
async def upload_chat_file(audit_id: str, background: BackgroundTasks, file: UploadFile = File(...)):
    """One spreadsheet: stored and read by the sheet reader (read-check-review.md section 3). No type, no mapping, no answer to wait for."""
    return await _ingest(audit_id, file, background)






# A dataset is one MongoDB document (16 MB of BSON); the stored sheets of a recognised file are part of it. Over the limit the upload stops
# with this message: nothing is cut and nothing is stored (decision of the owner on PR 135). The size is the BSON size MongoDB counts, not
# the length of the JSON (review H7); the margin below 16 MiB leaves room for the fields that are added later.
DATASET_MAX_BYTES = 15 * 1024 * 1024
DATASET_TOO_LARGE = "This file is too large to store. Split it or remove empty rows and upload again."
DATASET_UNSTORABLE = "This file holds a value that cannot be stored. Remove it and upload again."


def _check_dataset_size(doc: dict) -> None:
    try:
        size = len(bson.encode(doc))
    except (bson.errors.InvalidDocument, OverflowError):
        raise HTTPException(400, DATASET_UNSTORABLE)
    if size > DATASET_MAX_BYTES:
        raise HTTPException(413, DATASET_TOO_LARGE)


















async def _stored_reading(audit_id: str, file_hash: str) -> tuple:
    """(the audit's stored check outcome of the file, the reading it names): 404 when the audit has read no such file."""
    check = next((c for c in await readings_mod.checks_for(db, audit_id) if c.get("file_hash") == file_hash and c.get("status") == "read"), None)
    doc = await db[readings_mod.READINGS].find_one({"key": check.get("reading_key")}, {"_id": 0}) if check else None
    if not doc:
        raise HTTPException(404, "No reading of this file in this audit")
    return check, doc


@api.get("/audits/{audit_id}/readings/{file_hash}/export")
async def export_reading(audit_id: str, file_hash: str, format: Literal["json", "csv"] = "json"):
    """The full file map of one file's reading with its series (docs/design/read-check-review.md section 9, PR 3 step a): JSON, or CSV with one
    line per row-period. Stored values at full precision; the overrides made on the reading go with the JSON as records of their own."""
    check, doc = await _stored_reading(audit_id, file_hash)
    overrides = await readings_mod.overrides_for(db, audit_id, doc["key"])
    decided = [c for c in await cards_mod.for_audit(db, audit_id) if c["status"] == cards_mod.DECIDED and (c.get("source") or {}).get("file_hash") == file_hash]
    if format == "csv":
        return Response(reading_export.as_csv(doc, overrides, check.get("file") or "", decided), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="reading.csv"'})
    return reading_export.as_json({**doc, "file": check.get("file") or doc.get("file")}, overrides, decided)


@api.get("/audits/{audit_id}/reading")
async def reading_register(audit_id: str):
    """What the audit page shows (docs/design/read-check-review.md section 11): one block per file, the three result tables across all files
    (Confirmed, Rejected, Cannot check), the open cards and the review's summary. Numbers are raw; the screen formats them."""
    if not await db.audits.find_one({"id": audit_id}, {"id": 1}):
        raise HTTPException(404, "Audit not found")
    return sanitize(await register.build(db, audit_id))


@api.get("/audits/{audit_id}/readings/{file_hash}/cell")
async def reading_cell(audit_id: str, file_hash: str, sheet: str, cell: str):
    """The cell a Source cites, with the cells around it, as the stored file holds them (the link of the register's Source column)."""
    got = await register.cell_window(db, audit_id, file_hash, sheet, cell)
    if got is None:
        raise HTTPException(404, "Cell not found")
    return sanitize(got)


class CardDecision(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal["use_cell", "use_reader", "type_value"]
    value: Optional[float] = Field(default=None, allow_inf_nan=False)


@api.post("/audits/{audit_id}/cards/{card_id}")
async def decide_card(audit_id: str, card_id: str, body: CardDecision):
    """The analyst's decision on an open card: use the cell, use the reader, or type a value. A dated override record; the reading is not edited."""
    try:
        card = await cards_mod.decide(db, audit_id, card_id, body.action, body.value)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if card is None:
        raise HTTPException(404, "No open card")
    return sanitize(card)


class ReadingChange(BaseModel):
    model_config = {"extra": "forbid"}
    what: Literal["revenue_row", "boundary"]
    sheet: str = Field(max_length=200)
    row: Optional[int] = Field(default=None, ge=1)
    column: Optional[str] = Field(default=None, max_length=3)


@api.post("/audits/{audit_id}/readings/{file_hash}/change")
async def change_reading(audit_id: str, file_hash: str, body: ReadingChange):
    """The analyst's Change on a spreadsheet's anchors: the revenue row or the actual / plan boundary. Override records; the reading stays."""
    try:
        if body.what == "revenue_row":
            made = await register.change_revenue_row(db, audit_id, file_hash, body.sheet, body.row or 0)
        else:
            made = await register.change_boundary(db, audit_id, file_hash, body.sheet, body.column or "")
    except register.ChangeRefused as exc:
        raise HTTPException(400, str(exc))
    return {"overrides": len(made)}


async def _review_safely(audit_id: str, force: bool = False) -> None:
    """The reviewer for one audit (read-check-review.md section 7; app/reviewer.py), after the audit's files are read and its calculations ran. A
    failure of any kind leaves the register as it is (rule 20) and is logged by its type only."""
    try:
        a = await db.audits.find_one({"id": audit_id})
        if not a or a.get("structure_reading_consent") is not True:
            return
        doc = await reviewer.review_audit(db, a, force=force)
        await _usage_update(audit_id, lambda u: u["steps"].setdefault("reviewer", {}).__setitem__(
            doc["status"], u["steps"]["reviewer"].get(doc["status"], 0) + 1))
        await _refresh_as_of(audit_id)
        logger.info("review: run_id=%s status=%s findings=%d dropped=%d", audit_id, doc["status"], len(doc.get("findings") or []), doc.get("dropped", 0))
    except Exception as exc:
        logger.error("review failed: run_id=%s error=%s", audit_id, type(exc).__name__)


async def _review_if_not_read(audit_id: str, background: BackgroundTasks) -> None:
    """Queue the reviewer when the audit's last stored review is missing or its status is anything other than "read" (not_read, incomplete, none,
    too_large, ...). A review that read is not asked again here: the engine stage asks for a new one only when the input changed (review_audit)."""
    if await llm_gateway.reviewer_startup_problem(db) is not None:
        return
    last = await db[readings_mod.REVIEWS].find_one({"audit_id": audit_id}, {"_id": 0, "status": 1})
    if last is None or last.get("status") != "read":
        background.add_task(_review_safely, audit_id)


@api.post("/audits/{audit_id}/review-readings")
async def review_readings(audit_id: str, background: BackgroundTasks, force: bool = False):
    """Ask for the review of the audit's readings now (the reviewer also runs after the calculations of Run audit). One call per audit and input;
    `force` reviews again an input already reviewed."""
    if not await db.audits.find_one({"id": audit_id}, {"id": 1}):
        raise HTTPException(404, "Audit not found")
    background.add_task(_review_safely, audit_id, force)
    return {"status": "queued"}


@api.get("/audits/{audit_id}/datasets")
async def list_datasets(audit_id: str):
    """One view per stored file, in upload order, for rebuilding the upload list on reload."""
    if not await db.audits.find_one({"id": audit_id}, {"id": 1}):
        raise HTTPException(404, "Audit not found")
    found = await db.datasets.find({"audit_id": audit_id}, {"_id": 0, "rows": 0, "recognition_sheets": 0}).to_list(50)
    found.sort(key=lambda d: d.get("uploaded_at") or "")
    return sanitize({"datasets": [_file_view(d) for d in found]})






























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
    claim_type: Optional[Literal[deck_claims.ANALYST_TYPES + (deck_claims.USE_OF_FUNDS, deck_claims.ACQUISITION_CHANNELS,
                                                            deck_claims.INSTALLED_UNITS, deck_claims.PRICING, "other")]] = None
    value: Optional[float] = None
    value_high: Optional[float] = None          # the high end of a range
    unit: Optional[str] = Field(default=None, min_length=1, max_length=40)   # "%", "months", "paying users"
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    target_date: Optional[str] = Field(default=None, pattern=_TARGET_DATE.pattern)
    by_period: Optional[List[PeriodValue]] = None   # a table row: every value, in the row's order
    # docs/specs/claim-types-and-correction.md section 3: the fields every claim type holds, and why the analyst changed them
    population: Optional[Literal["paying", "registered", "active", "free", "trial", "all", "deals won", "all closed", "open"]] = None
    figure_type: Optional[Literal[deck_claims.FIGURE_TYPES]] = None
    growth_basis: Optional[Literal["mom", "yoy", "annualised", "cumulative", "unknown"]] = None
    reason: Literal[tuple(deck_claims.EDIT_REASONS)] = "parser_misread"
    undo: Optional[bool] = None         # restore a rejected claim to the status it had before (George, 2026-10-26)


class CorrectionAnswer(BaseModel):
    """Undo a correction a check applied, or choose one of the candidates of a correction that waits (claim-matching.md section 33)."""
    index: int = Field(ge=0)
    action: Literal["undo", "choose"]
    option: Optional[int] = Field(default=None, ge=0)


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


async def _upload_ai_status(audit_id: str) -> Optional[str]:
    """The AI read's status a deck starts with, for the upload line: reading (queued) or python_only (consent off); None under the former
    rules read, which has no page read to report. The read itself runs after the response; it never waits for a file (read-check-review.md
    section 12)."""
    if structures.deck_pipeline() != "ai":
        return None
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0, "structure_reading_consent": 1})
    if (audit or {}).get("structure_reading_consent") is not True:
        return structures.PYTHON_ONLY
    return "reading"


@api.post("/audits/{audit_id}/decks/upload")
async def upload_deck(audit_id: str, background: BackgroundTasks, file: UploadFile = File(...)):
    audit = await db.audits.find_one({"id": audit_id}, {"id": 1, "fiscal_year_end": 1, "structure_reading_consent": 1})
    if not audit:
        raise HTTPException(404, "Audit not found")
    content = await file.read(deck_parser.MAX_BYTES + 1)
    try:
        deck = await run_in_threadpool(deck_parser.parse_deck, content, file.filename or "")
    except deck_parser.DeckError as exc:
        raise HTTPException(400, exc.message)
    # The rules read lists candidates only under DECK_PIPELINE=rules (the former path, kept for scripts/compare_pipelines.py).
    # Under the default "ai" (docs/design/ai-reads-rules-check.md, 2026-10-22) the model reads every page after the response and
    # Python checks each claim (structures.pages); Add from deck still reads one line with the rules.
    candidates = deck_claims.detect_candidates(deck["blocks"], deck["file"], _fiscal_year_end(audit)) \
        if structures.deck_pipeline() == "rules" else []
    deck_id = str(uuid.uuid4())
    # The pages with a figure written in digits: the ones the AI read may send (the panel says "M with figures", never "pages read").
    figure_pages = len(deck_pages.sendable(deck_pages.page_grids(deck["blocks"]))) if structures.deck_pipeline() == "ai" else None
    # A file uploaded again replaces its earlier parse and its unreviewed candidates. Approved,
    # edited and rejected candidates stay on record; the same claim found again is not re-added.
    where = {"audit_id": audit_id, "file": deck["file"]}
    earlier = [d["deck_id"] for d in await db[decks.TEXT_COLLECTION].find(where, {"_id": 0, "deck_id": 1}).to_list(1000)]
    await deck_render.remove(db, audit_id, earlier)
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
        "page_unit": deck["page_unit"], "pages": deck["pages"], "blocks": deck["blocks"], "layout": deck.get("layout") or [],
        "structures": deck["structures"], "ai_status": "reading", "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "figure_pages": figure_pages})
    # The page reader draws each page from the file (page-image.md), so it is kept only when a page read can happen: consent ticked and
    # the page pipeline on. A deck uploaded under any other setting leaves no copy of the file behind.
    if audit.get("structure_reading_consent") is True and structures.deck_pipeline() == "ai":
        await deck_render.save(db, audit_id, deck_id, content, deck["format"])
    for order, c in enumerate(candidates):
        await db[decks.CANDIDATES_COLLECTION].insert_one(
            {**c, "audit_id": audit_id, "deck_id": deck_id, "file": deck["file"], "id": str(uuid.uuid4()),
             "order": len(reviewed) + order, "status": "pending"})
    # Its structures are read by the model after the response, or wait for the revenue file
    # (llm-structure-reading.md section 3); with consent unticked, Python's candidates stand alone.
    await allowance_mod.record_for_audit(db, audit_id, files=1)
    background.add_task(structures.process_deck_safely, db, audit_id, deck_id)
    return {"deck_id": deck_id, "file": deck["file"], "format": deck["format"], "page_unit": deck["page_unit"],
            "pages": deck["pages"], "figure_pages": figure_pages, "candidates": len(candidates),
            "ai_status": await _upload_ai_status(audit_id), "kept_reviewed": len(reviewed),
            "structures": len(deck["structures"])}


@api.get("/audits/{audit_id}/decks")
async def list_deck_candidates(audit_id: str):
    """The audit's decks (no parsed text), most recently uploaded first, and their candidates:
    grouped by deck in that order; within a deck the ones to review first, then by slide or page."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    deck_fields = {"_id": 0, "deck_id": 1, "file": 1, "format": 1, "page_unit": 1, "pages": 1, "uploaded_at": 1,
                   "ai_status": 1, "ai_message": 1, "sent": 1, "periods_corrected": 1, "figure_pages": 1, "read_progress": 1,
                   "page_reads": 1, "skipped_pages": 1, "unread_pages": 1, "images_unavailable": 1, "images_need_file": 1, "diagnostics": 1}
    found = await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, deck_fields).to_list(100)
    found.sort(key=lambda d: d.get("uploaded_at") or "", reverse=True)
    for d in found:
        # The deck panel's run log: status and the pages sent to the model (no text, no cost: usage-and-allowance.md section 9).
        d["sent_pages"] = sorted({p for s in d.pop("sent", None) or [] for p in ([s["page"]] if s.get("page") is not None else s.get("pages") or [])})
        # The panel's "AI read" counts (George, 2026-10-23): pages read and pages whose reply was rejected or not read; counts only.
        reads = d.pop("page_reads", None) or []
        d["pages_read"] = sum(len(r.get("pages") or []) for r in reads if r.get("status") == "read")
        d["pages_rejected"] = sum(len(r.get("pages") or []) for r in reads if r.get("status") not in ("read", "stopped"))
        # What masking took out of the page text sent (George, 2026-10-29, review of PR 204): counts only.
        d["personal_removed"] = sum((r.get("masked") or {}).get("personal", 0) for r in reads)
        d["names_replaced"] = sum((r.get("masked") or {}).get("names", 0) for r in reads)
    rank = {d["deck_id"]: i for i, d in enumerate(found)}
    candidates = deck_claims.fold_twins(await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id}, {"_id": 0}).to_list(10000))
    # The claims Python enters on its own read as approved ("auto"), the ones a check asks about as pending (simplified-flow.md section 2).
    kept = {c["id"]: c for c in await _with_entries(audit_id, audit, [c for c in candidates if c.get("status") != "rejected"])}
    candidates = [kept.get(c["id"], c) for c in candidates]
    fx = await _fx(audit_id, audit)
    settings = _register_settings(audit, fx, await _deck_take_rate(audit_id))
    # A turnover claim asks "Revenue or Volume?" in its own row, before it is approved (claim-matching.md section 11
    # point 8), from the register's own code: read before the list adds its display fields to the candidates.
    current = await _current_audit(audit_id, audit, strict=False)
    turnover = claim_matching.turnover_views(candidates, current.get("results"), settings)
    # A gap beyond 50% of the claim asks "Same metric and period?" as a card on the Audit page, in the register or not (claim-matching.md 4.1).
    definition = claim_matching.definition_views(candidates, current.get("results"), settings)
    # A claim Run audit approved on its own reads "Auto-approved – matches revenue file (Δ x.x%)" with the figure's citation (issue #155).
    auto = claim_matching.auto_views(candidates, current.get("results"), settings)
    # What the app made of a registered row: its segment and the total it is a part of (George, 2026-10-26); read from the register's own rows.
    made = _made_of(candidates, current.get("results"), settings)
    sales = claim_matching.sales_questions(candidates, current.get("results"), settings)
    # By the group of the claim type (revenue, P&L, customers and sales, market size, Unknown, Other), then ascending by
    # slide or page across all decks (a tie goes to the more recent deck), then reading order on the page: top to bottom
    # in bands of 2% of the height, then left to right, then the order the parser found them in.
    for c in candidates:
        c["group"] = deck_claims.claim_group(c)         # a best or worst case sorts under Scenarios whatever its type (George, 2026-10-23)
    candidates.sort(key=lambda c: (c["group"], _first_page(c), rank.get(c.get("deck_id"), len(rank)), *_reading(c),
                                   c.get("order", 0)))
    # A claim in another currency than the audit's, with the rate it is converted at (None: "FX rate needed").
    as_of = audit.get("as_of_month") or (current.get("results") or {}).get("as_of_month")
    for c in candidates:
        # Contract 6 (schemas.metrics.DECK_CLAIM_FIELDS): every claim names its basis, scenario and flags, the flags with the one that
        # depends on the as-of month ("basis conflicts with period").
        c["basis"], c["scenario"], c["flags"] = c.get("basis"), c.get("scenario") or "none", claim_matching.flags_of(c, as_of)
        c["fx"] = claim_matching.fx_view(c, settings, as_of)
        if c["fx"] and not as_of and current.get("results_stale"):
            c["fx"]["date_stale"] = True        # the date would come from stale results: the screen reads "Stale – re-run audit"
        c["turnover"] = turnover.get(c["id"])
        c["made_of"] = made.get(c["id"])
        c["definition"] = definition.get(c["id"])
        c.update(auto.get(c["id"]) or {"auto_approval": None, "auto_citation": None})
        # the figure type, population and growth basis as the register reads them, for the editor (claim-types-and-correction.md 3)
        c["claim_fields"] = claim_matching.candidate_fields(c, current.get("results"))
    peers = {}
    for c in candidates:
        peers.setdefault(c.get("deck_id"), []).append(c)
    for c in candidates:
        c["confidence"] = deck_claims.confidence(c, peers[c.get("deck_id")])
    return sanitize({"decks": found, "candidates": candidates, "sales_questions": sales,
                     "attention": await _attention_order(audit_id, audit, current, candidates, settings)})


def _made_of(candidates: list, results: Optional[dict], settings: dict) -> dict:
    """{candidate id: {segment, part_of}} for the candidates in the register, from the rows the register builds (claim_groups.made_of)."""
    registered = [c for c in candidates if c.get("status") in REGISTER_STATUSES]
    if not results or not registered:
        return {}
    rows = claim_matching.build_register(sorted(registered, key=lambda c: (c.get("file") or "", c.get("order", 0))), results, settings, peers=candidates)
    out: dict = {}
    for r in rows:
        out.setdefault(str(r["claim_id"]).split("#")[0], claim_groups.made_of(r, rows))
    return out


async def _attention_order(audit_id: str, audit: dict, current: dict, candidates: list, settings: dict) -> list:
    """The claims that wait for a word, in the order of the selection rule with the five's questions first (simplified-flow.md section 2): a
    claim a check asks about (pending), a Revenue / Volume question open or a Definition check open. Each is read as if it were in the register,
    so its value at stake and shortfall rank it. `in_top5`: one of its rows is among the five in force. Nothing is stored."""
    results = current.get("results")
    live = [c for c in candidates if c.get("status") != "rejected" and c.get("claim_type") not in deck_claims.OTHER_TYPES]
    if not results or not live:
        return []
    asking = {c["id"] for c in live if c.get("status") == "pending" or (c.get("turnover") and any(v.get("turnover_state") == "ask" for v in c["turnover"]))
              or (c.get("definition") and any(v.get("definition_check") == claim_matching.DEFINITION_ASK for v in c["definition"]))}
    trial = [{**c, "status": "approved"} for c in live]
    rows = claim_matching.build_register(sorted(trial, key=lambda c: (c.get("file") or "", c.get("order", 0))), results, settings, peers=trial)
    # a row whose reason asks the analyst to set or confirm something (period not read, a required field unknown ...) is a question too
    to_set = {str(r["claim_id"]).split("#")[0]: r["reason"] for r in rows if claim_matching.asks_analyst(r)}
    to_set = {cid: reason for cid, reason in to_set.items() if cid not in asking}
    kept = {c["id"] for c in live if c.get("undated_kept")}          # "Keep undated": the analyst saw the figure has no period and left it so
    to_set = {cid: reason for cid, reason in to_set.items() if not (reason.startswith(claim_matching.PERIOD_NOT_READ) and cid in kept)}
    undated = claim_matching.undated_by_page([r for r in rows if str(r["claim_id"]).split("#")[0] in to_set], kept)
    asking |= set(to_set)
    if not asking:
        return []
    five = set(verdict_mod.top5_state(rows, (audit.get("ic_inputs") or {}).get("top5"))["in_force"])
    keys: dict = {}
    for r in rows:
        cid = str(r["claim_id"]).split("#")[0]
        if cid in asking:
            keys[cid] = min(keys.get(cid, verdict_mod.selection_key(r)), verdict_mod.selection_key(r))
    in_five = {str(r["claim_id"]).split("#")[0] for r in rows if r["claim_id"] in five} & asking
    last = (True, True, True, 0, 0, 0, 0)            # a claim with no row of its own (not testable) ranks after the others
    ordered = sorted(asking, key=lambda cid: (cid not in in_five, keys.get(cid, last)))
    # figures waiting for a legend item that add up to a stated total (George, 2026-10-26): the card names the total
    waiting = {c["id"] for c in live if c.get("status") == "pending" and any(
        e.get("field") == "segment" and e.get("state") == "choose" for e in c.get("corrections") or ())}
    pages: dict = {}
    for r in rows:
        if str(r["claim_id"]).split("#")[0] in waiting and r.get("claimed_value") is not None:
            pages.setdefault((r["deck_file"], r["page_ref"]), []).append(r)
    adds_up = {}
    for parts in pages.values():
        name = claim_groups.adds_up_to(parts, rows)
        adds_up.update({str(r["claim_id"]).split("#")[0]: name for r in parts} if name else {})
    return [{"id": cid, "in_top5": cid in in_five, **({"set": to_set[cid]} if cid in to_set else {}),
             **({"adds_up_to": adds_up[cid]} if cid in adds_up else {}), **({"undated": undated[cid]} if cid in undated else {})} for cid in ordered]


def _edited_period(value: dict, before: dict, fiscal_year_end: int) -> dict:
    """A value after an edit, its date range re-run. A date the analyst typed follows the same rules as
    a stated one: a year, quarter or half follows the audit's year-end, a month is a calendar month.
    The deck's stated text goes once the date changes."""
    if value.get("target_date") != before.get("target_date"):
        value["period_text"] = None
        value["period_read_note"] = None            # the analyst's date replaces the one Python read (issue #151)
    else:
        value["period_text"] = before.get("period_text")
        value["period_read_note"] = before.get("period_read_note")
    return deck_claims.resolve_period(value, fiscal_year_end)


def _period_fields(value: dict) -> dict:
    return {k: value.get(k) for k in ("period_text", "period_read_note", "period_start", "period_end")}


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
    await deck_render.remove(db, audit_id, [deck_id])
    candidates = await db[decks.CANDIDATES_COLLECTION].delete_many(
        {"audit_id": audit_id, "$or": [{"deck_id": deck_id}, {"file": deck["file"]}]})
    return {"removed": deck_id, "deck_text": text.deleted_count, "deck_candidates": candidates.deleted_count}


class AnalystClaim(BaseModel):
    """A claim the analyst adds from a slide or page the parser could not read (docs/specs/deck-parser.md section 6): the
    metric, a value or a range, the unit, the currency and the period, and where in which deck it is stated."""
    model_config = {"extra": "forbid"}
    claim_type: Literal[deck_claims.ANALYST_TYPES + (deck_claims.ACQUISITION_CHANNELS,)]
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
    """A stored page as the analyst sees it under View page: its text, notes and table lines and its chart labels, in the stored order.
    Nothing is read again from the file."""
    return deck_figures.page_lines(deck, page)


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
    if payload.undo:
        # Undo on a rejected row: the status, and whether Python entered it, as they were before the rejection (George, 2026-10-26).
        # An approved row the analyst accepted is restored the same way (Accept all, George, 2026-10-27).
        if current.get("status") != "rejected" and not (current.get("status") in ("approved", "edited") and current.get("previous_state")):
            raise _rejected("status", "only a rejected or an accepted claim can be restored")
        await db[decks.CANDIDATES_COLLECTION].update_one(where, {"$set": {**(current.get("previous_state") or {"status": "pending"}),
                                                                           "previous_state": None, "excluded_reason": None}})
        return sanitize(await db[decks.CANDIDATES_COLLECTION].find_one(where, {"_id": 0}))
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
        changes = {**edits, "status": "edited", "auto_accepted": False, "auto_note": None}      # an edit makes it Analyst-edited: no longer approved on its own (issue #155)
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
        changes = {"status": status, "auto_accepted": False, "auto_note": None}     # a status the analyst sets is the analyst's decision (PR 157)
        rejecting = status == "rejected" and current.get("status") != "rejected"
        accepting = status in ("approved", "edited") and current.get("status") == "pending"       # Accept all's Undo goes back to the pending row
        if rejecting or accepting:
            changes["previous_state"] = {k: current.get(k) for k in ("status", "auto_accepted", "auto_note")}     # what Undo restores
        if rejecting and "reason" in sent:       # excluded with a reason, one of the closed words of an edit (claim-groups.md section 5)
            changes["excluded_reason"] = payload.reason
    await db[decks.CANDIDATES_COLLECTION].update_one(where, {"$set": changes})
    return sanitize(await db[decks.CANDIDATES_COLLECTION].find_one(where, {"_id": 0}))


class UndatedKept(BaseModel):
    """The claims the analyst keeps without a period ("Keep undated"): they stay Unverified, "Period not read", and ask nothing more."""
    model_config = {"extra": "forbid"}
    claim_ids: List[str] = Field(min_length=1, max_length=500)


@api.put("/audits/{audit_id}/undated-periods")
async def keep_undated(audit_id: str, payload: UndatedKept):
    """Mark the claims `undated_kept` (a flag on the candidate, no deck text). Their Period-not-read question closes; the register is unchanged."""
    if not await db.audits.find_one({"id": audit_id}, {"_id": 1}):
        raise HTTPException(404, "Audit not found")
    done = await db[decks.CANDIDATES_COLLECTION].update_many({"audit_id": audit_id, "id": {"$in": payload.claim_ids}}, {"$set": {"undated_kept": True}})
    logger.info("undated kept: run_id=%s n=%s", audit_id, done.modified_count)
    return {"kept": done.modified_count}


class SalesAnswer(BaseModel):
    """Is "Sales" in this deck revenue or bookings (George, 2026-10-26): one closed word for the deck."""
    model_config = {"extra": "forbid"}
    answer: Literal[claim_matching.SALES_CHOICES] = Field(alias="as")


@api.put("/audits/{audit_id}/decks/{deck_id}/sales")
async def answer_sales(audit_id: str, deck_id: str, payload: SalesAnswer):
    """Save the answer for every Sales claim of the deck, on the audit under the deck id (no deck text). Revenue: the claims are tested against the
    revenue data as revenue. Bookings: they stay Unverified, "bookings not in the data". Gives the questions still open back."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    if not await db[decks.TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id}, {"_id": 1}):
        raise HTTPException(404, "Deck not found")
    await db.audits.update_one({"id": audit_id}, {"$set": {f"sales_choices.{deck_id}": {"as": payload.answer, "saved_at": usage_mod.now()}}})
    logger.info("sales answer: run_id=%s as=%s", audit_id, payload.answer)
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    found = await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id}, {"_id": 0}).to_list(10000)
    current = await _current_audit(audit_id, audit, strict=False)
    settings = _register_settings(audit, await _fx(audit_id, audit), await _deck_take_rate(audit_id))
    return sanitize({"sales_questions": claim_matching.sales_questions(found, current.get("results"), settings)})


@api.post("/audits/{audit_id}/decks/candidates/{candidate_id}/correction")
async def answer_correction(audit_id: str, candidate_id: str, payload: CorrectionAnswer):
    """Undo a correction a check applied before the register (the field goes back to what the model read), or choose one of the candidates
    of a correction that waits (the field is set, the flag that asked goes, the claim is kept like Keep). docs/specs/claim-matching.md 33."""
    where = {"audit_id": audit_id, "id": candidate_id}
    current = await db[decks.CANDIDATES_COLLECTION].find_one(where, {"_id": 0})
    if not current:
        raise HTTPException(404, "Candidate not found")
    entries = list(current.get("corrections") or [])
    if payload.index >= len(entries):
        raise _rejected("index", "this claim has no such correction")
    entry = dict(entries[payload.index])
    changes: dict = {}
    if payload.action == "undo":
        if entry.get("state") != "applied":
            raise _rejected("action", "only an applied correction can be undone")
        changes.update(entry["undo"])
        entry["state"] = "undone"
        if entry.get("field") == "segment":       # the card comes back: no segment, the flag asks again, the claim waits
            inputs = {**(current.get("claim_inputs") or {})}
            kept = {k: v for k, v in inputs.get(candidate_id, {}).items() if k != "segment"}
            inputs.pop(candidate_id, None)
            if kept:
                inputs[candidate_id] = kept
            changes.update(claim_inputs=inputs, status="pending", auto_accepted=False, flags=[*(current.get("flags") or []), entry["reason"]])
            entry["state"] = "choose"
    else:
        options = entry.get("options") or []
        if entry.get("state") != "choose" or payload.option is None or payload.option >= len(options):
            raise _rejected("option", "choose one of the candidates of a correction that waits")
        chosen = options[payload.option]
        changes.update(chosen["set"])
        changes.update(status="approved", auto_accepted=False, auto_note=None)
        changes["flags"] = [f for f in current.get("flags") or [] if f != entry["reason"]]
        if entry.get("field") == "segment":       # a legend item the analyst clicked is the claim's segment: its input, set by the analyst
            inputs = {**(current.get("claim_inputs") or {})}
            inputs[candidate_id] = {**inputs.get(candidate_id, {}), "segment": chosen["segment"]}
            changes["claim_inputs"] = inputs
        entry.update(state="applied", corrected=chosen["value"])
        if entry.get("field") != "segment":       # a segment keeps its options: Undo brings the card back
            entry.pop("options", None)
    entries[payload.index] = entry
    changes["corrections"] = entries
    await db[decks.CANDIDATES_COLLECTION].update_one(where, {"$set": changes})
    return sanitize(await db[decks.CANDIDATES_COLLECTION].find_one(where, {"_id": 0}))


# ---------------------------------------------------------------------------
# Run audit: three stages the analyst starts with one button, and the counts the Audit page opens with
# ---------------------------------------------------------------------------
async def _open_turnover_ids(audit_id: str, audit: dict, found: list) -> set:
    current = await _current_audit(audit_id, audit, strict=False)
    settings = _register_settings(audit, await _fx(audit_id, audit), await _deck_take_rate(audit_id))
    return {cid for cid, views in claim_matching.turnover_views(found, current.get("results"), settings).items()
            if any(v["turnover_set_by"] != "analyst" for v in views)}


async def _entry_plan(audit_id: str, audit: dict, found: list) -> dict:
    """What `_enter_matched_claims` would do, without writing (simplified-flow.md section 2): the pending claims that enter, the ones Python
    entered earlier that a check now asks about (re-opened), the Revenue / Volume questions open and the claims left waiting. A claim enters
    when no check asks about it and, before the first Calculate (no stored results), when the page read gave it High extraction confidence: High is accepted
    without a click, Medium and Low wait for the analyst (George, 2026-10-28). Once results exist the rule is the one above. Nothing is changed."""
    audit = await _current_audit(audit_id, audit, strict=False)
    plan = {"enter": [], "reopen": [], "open_turnover": set(), "waiting": 0}
    pending = [c for c in found if c.get("status") == "pending" and c.get("claim_type") not in deck_claims.OTHER_TYPES]
    entered = [c for c in found if claim_matching.entered_by_python(c)]
    if not pending and not entered:
        return plan
    as_of = audit.get("as_of_month") or (audit.get("results") or {}).get("as_of_month")
    plan["open_turnover"] = await _open_turnover_ids(audit_id, audit, found)
    waits = lambda c: run_audit.needs_a_word({**c, "flags": claim_matching.flags_of(c, as_of)}) or c["id"] in plan["open_turnover"]      # noqa: E731
    peers = {}
    for c in found:
        peers.setdefault(c.get("deck_id"), []).append(c)
    high = lambda c: c.get("origin") == "ai" and deck_claims.confidence(c, peers[c.get("deck_id")])["level"] == "High"      # noqa: E731
    plan["reopen"] = [c["id"] for c in entered if waits(c)]
    plan["enter"] = [c["id"] for c in pending if not waits(c) and (audit.get("results") or high(c))]
    plan["waiting"] = len(pending) - len(plan["enter"]) + len(plan["reopen"])
    return plan


def _apply_plan(found: list, plan: dict) -> list:
    """The candidates as they stand once the plan is applied: copies, the stored ones untouched."""
    enter, reopen = set(plan["enter"]), set(plan["reopen"])
    return [{**c, "status": "approved", "auto_accepted": True, "auto_note": None} if c["id"] in enter
            else {**c, "status": "pending", "auto_accepted": False, "auto_note": claim_matching.AUTO_REVOKED} if c["id"] in reopen else c
            for c in found]


async def _enter_matched_claims(audit_id: str, audit: dict, found: Optional[list] = None) -> dict:
    """George, 2026-10-25 (simplified-flow.md section 2): the claim approval is gone. Every pending claim the page read matched, that no check
    flags for review and whose Revenue / Volume question is not open, enters the register on its own (status "approved", `auto_accepted`
    true: the register reads "auto"). A claim Python entered that a check now asks about (a re-run, a new file, an FX or as-of month change)
    is re-opened: pending again with the note AUTO_REVOKED, and a card on the Audit page. Everything else is the analyst's: a claim the analyst
    answered, edited or added is never touched, an Other figure is never a task. Writes the plan of `_entry_plan` (Run audit's claims stage
    and every calculation); the screens read the same plan without writing (`_with_entries`). No threshold or tolerance is read or changed."""
    if found is None:
        found = deck_claims.fold_twins(await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000))
    plan = await _entry_plan(audit_id, audit, found)
    accepted = []
    for cid in plan["reopen"]:
        await db[decks.CANDIDATES_COLLECTION].update_one(
            {"audit_id": audit_id, "id": cid}, {"$set": {"status": "pending", "auto_accepted": False, "auto_note": claim_matching.AUTO_REVOKED}})
    for cid in plan["enter"]:
        try:
            await db[decks.CANDIDATES_COLLECTION].update_one(
                {"audit_id": audit_id, "id": cid}, {"$set": {"status": "approved", "auto_accepted": True, "auto_note": None}})
            accepted.append(cid)
        except Exception:               # a failed save leaves the claim waiting; the rest go on
            plan["enter"].remove(cid)
    total = [c["id"] for c in _apply_plan(found, plan) if claim_matching.entered_by_python(c)]
    return {"entered": len(total), "entered_ids": total, "reopened": len(plan["reopen"]),
            "open": plan["waiting"],
            "turnover_open": len(plan["open_turnover"] & {c["id"] for c in found if c.get("status") == "pending" or c["id"] in plan["reopen"]})}


async def _with_entries(audit_id: str, audit: dict, found: list) -> list:
    """The candidates as the register and the deck list read them: the claims Python would enter are approved ("auto"), the ones a check now
    asks about are pending. A read; the stored documents change when Run audit calculates (`_enter_matched_claims`)."""
    return _apply_plan(found, await _entry_plan(audit_id, audit, found))




@api.post("/audits/{audit_id}/run/{stage}")
async def run_stage(audit_id: str, stage: str, background: BackgroundTasks):
    """One stage of Run audit, in order: mapping (checks the files are mapped), engine (the calculations), claims (every matched claim no
    check asks about enters the register). It answers 200 with a status: done, waiting (an earlier stage is not done), running (the files or
    the decks are still being read; ask again) or failed (a plain-English message, no exception text). Nothing waits for a confirmation
    (read-check-review.md section 12). Existing endpoints do the work; nothing here is new logic for the engine."""
    if stage not in run_audit.STAGES:
        raise HTTPException(404, "Unknown stage")
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    files = await db.datasets.count_documents({"audit_id": audit_id})
    result = None
    try:
        if stage == "mapping":
            if not files:
                result = run_audit.stage_result(stage, run_audit.FAILED, run_audit.NO_FILES, files=0)
            elif int(audit.get("sheet_reads_pending") or 0) > 0:
                result = run_audit.stage_result(stage, run_audit.RUNNING, run_audit.FILES_READING, files=files)
            else:
                result = run_audit.stage_result(stage, run_audit.DONE, None, files=files)
        elif stage == "engine":
            # Nothing waits for a confirmation: the map is the reading. No month confirmed and none typed: the audit runs everything that
            # does not depend on it (read-check-review.md section 6).
            await _run_compute(audit_id)
            if await llm_gateway.reviewer_startup_problem(db) is None:        # no reviewer prompt: Run audit goes on without the reviewer stage
                background.add_task(_review_safely, audit_id)        # one review per audit and input; a review already made is kept
            result = run_audit.stage_result(stage, run_audit.DONE, None if audit.get("as_of_month") else run_audit.NO_AS_OF)
        else:
            if not audit.get("results"):
                result = run_audit.stage_result(stage, run_audit.WAITING, run_audit.WAIT_ENGINE)
            else:
                # Run audit with every stage done carries on from this last one (the calculations are not repeated): the reviewer runs again here
                # whenever its last stored status is anything other than "read" (PR 4), so a review that was refused, cut off or incomplete is
                # not left behind for want of a new calculation.
                await _review_if_not_read(audit_id, background)
                # A deck the page reader could not read for want of the deck_reading prompt is read again, with no new upload, once the
                # store holds it (George, 2026-10-23, review of PR 164, M6).
                # A deck an older version left "waiting for revenue file" is read again too: nothing waits for a file (section 12, PR 4).
                for deck_id in await structures.queue_prompt_missing(db, audit_id) + await structures.queue_blocked(db, audit_id) + await structures.queue_waiting(db, audit_id):
                    background.add_task(structures.process_deck_safely, db, audit_id, deck_id)
                # A deck with pages a timeout or an error left unread is read again for those pages only (deck page reads, 2026-10-23).
                for deck_id in await structures.queue_unread_pages(db, audit_id) + await structures.queue_stale_reading(db, audit_id):
                    background.add_task(structures.process_deck_safely, db, audit_id, deck_id)
                deck_docs = await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "ai_status": 1}).to_list(100)
                if not deck_docs:
                    result = run_audit.stage_result(stage, run_audit.DONE, run_audit.NO_DECKS, entered=0, open=0, turnover_open=0)
                elif any(d.get("ai_status") == "reading" for d in deck_docs):
                    result = run_audit.stage_result(stage, run_audit.RUNNING, run_audit.DECKS_READING)
                else:
                    missing = llm_gateway.PROMPT_MISSING_TEXT if any(d.get("ai_status") == structures.PROMPT_MISSING for d in deck_docs) else \
                        llm_gateway.PAGE_READER_BLOCKED if any(d.get("ai_status") == structures.BLOCKED for d in deck_docs) else None
                    result = run_audit.stage_result(stage, run_audit.DONE, missing, **(await _enter_matched_claims(audit_id, audit)))
    except Exception as exc:          # plain English to the analyst; the log has the stage and the error type, never the message
        logger.error("run audit stage failed: run_id=%s stage=%s error=%s", audit_id, stage, type(exc).__name__)
        result = run_audit.stage_result(stage, run_audit.FAILED, run_audit.ENGINE_FAILED if stage == "engine" else run_audit.CLAIMS_FAILED)
    logger.info("run audit: run_id=%s stage=%s status=%s", audit_id, stage, result["status"])
    return sanitize(result)


@api.get("/audits/{audit_id}/review")
async def review_summary(audit_id: str):
    """What the Audit page opens with: the columns accepted without a click and the ones waiting, the claims Python entered on its own
    (their ids) and the ones waiting for an answer, the Revenue / Volume questions open and the hard blockers."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    found = deck_claims.fold_twins(await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000))
    found = await _with_entries(audit_id, audit, found)
    auto = [c["id"] for c in found if c.get("auto_accepted") and c.get("status") == "approved"]
    # Other figures are never a task (claim-types-and-correction.md section 4)
    pending = [c for c in found if c.get("status") == "pending" and c.get("claim_type") not in deck_claims.OTHER_TYPES]
    open_turnover = await _open_turnover_ids(audit_id, audit, found) if pending else set()
    return sanitize({
        "claims": {"auto_accepted": len(auto), "auto_accepted_ids": auto, "open": len(pending),
                   "turnover_open": len(open_turnover & {c["id"] for c in pending})},
        "computed": bool(audit.get("results")),
        "results_stale": run_audit.results_stale(audit),
        "engine_stale": run_audit.engine_stale(audit),
        "blockers": await _blocker_list(audit_id, audit)})


def merged_fx(audit: dict, file_fx: Optional[dict]) -> dict:
    """The audit's FX rates, upper-cased, with the reporting currency at 1: the rates saved with the revenue file (older
    audits) under the audit's own rates, which win. One set of rates serves the uploaded files and the deck claims."""
    fx = {str(k).upper(): float(v) for k, v in (file_fx or {}).items()}
    fx.update({str(k).upper(): float(v) for k, v in (audit.get("fx") or {}).items()})
    fx[(audit.get("reporting_currency") or "EUR").upper()] = 1.0
    return fx


async def _fx(audit_id: str, audit: dict) -> dict:
    revenue = await db.datasets.find_one({"audit_id": audit_id, "dtype": "revenue"}, {"fx": 1}) or {}      # rates saved with a file of an older audit
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
    before = await _fx(audit_id, a)
    await db.audits.update_one({"id": audit_id}, {"$set": {"fx": payload.fx}})
    await db.datasets.update_many({"audit_id": audit_id, "dtype": "revenue"}, {"$set": {"fx": {}}})
    if merged_fx({**a, "fx": payload.fx}, None) != before and a.get("results"):
        await db.audits.update_one({"id": audit_id}, {"$set": {"setup_stale": True}})      # the stored results read the old rates (George, 2026-10-24)
    return {"fx": payload.fx}


def _register_settings(audit: dict, fx: dict, deck_take_rate: bool = False) -> dict:
    return {"fiscal_year_end": _fiscal_year_end(audit), "as_of_month": audit.get("as_of_month"),
            "as_of_by": _as_of_by(audit), "reporting_currency": audit.get("reporting_currency") or "EUR", "fx": fx,
            "turnover_choices": audit.get("turnover_choices") or {}, "deck_take_rate": deck_take_rate,
            "sales_choices": audit.get("sales_choices") or {},
            "group_choices": audit.get("group_choices") or {},
            "target_arr": audit.get("target_arr") or None, "target_date": audit.get("target_date") or None,
            "first_quarterly_review": verdict_mod.with_review(audit, audit.get("ic_inputs")).get("first_quarterly_review")}


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
    found = deck_claims.fold_twins(await db[decks.CANDIDATES_COLLECTION].find(
        {"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000))
    found = await _with_entries(audit_id, audit, found)         # the claims Python matched enter on their own (simplified-flow.md section 2)
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
    """The claim register: the claims Python entered and the ones the analyst answered or edited, with what the parser found next to each
    edit, and `register`: one row per claim tested against the computed metrics, in rank order (docs/specs/claim-matching.md). Rejected
    candidates and the ones waiting for an answer are not in it (they stay on record in the deck list)."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    claims, rows = await _claim_rows(audit_id, audit)
    related = _relations(audit, rows)
    # The budget dropdown sits beside the register, never in it: the CSV and the memo read rows.
    return sanitize({"claims": claims, "register": _marked(audit, rows),
                     "budget_decisions": verdict_mod.budget_decisions(rows),
                     "groups": related["groups"], "reviews": related["reviews"], "conflicts": related["conflicts"],
                     "counts": claim_groups.counts(rows),
                     "results_stale": run_audit.results_stale(audit)})      # no rows then: the figures are not shown as current


def _relations(audit: dict, rows: list) -> dict:
    """The groups, the questions and the unresolved conflicts of the register's rows (docs/specs/claim-groups.md), computed on read from the
    rows and the analyst's saved choices: the same result the register, the conclusion, the banner and the memo read."""
    return claim_groups.relate(rows, audit.get("group_choices"), _fiscal_year_end(audit))




def _marked(audit: dict, rows: list) -> list:
    """The register rows with `key_gate` set on the gates of the five in force (the analyst's changed set, else the app's selection)."""
    return verdict_mod.mark_key_gates(rows, verdict_mod.top5_state(rows, (audit.get("ic_inputs") or {}).get("top5"))["in_force"])


async def _open_claim_questions(audit_id: str, audit: dict, rows: list) -> int:
    """The claim questions the Audit page lists: the claims waiting for an answer (a failed check, a Revenue / Volume question) and the
    register rows whose Definition check is open (simplified-flow.md section 2). A count only."""
    found = deck_claims.fold_twins(await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000))
    waiting = (await _entry_plan(audit_id, audit, found))["waiting"]
    definitions = [r for r in rows if r.get("definition_check") == claim_matching.DEFINITION_ASK]
    asked = {str(r["claim_id"]).split("#")[0] for r in definitions}
    to_set = {str(r["claim_id"]).split("#")[0] for r in rows if claim_matching.asks_analyst(r)} - asked      # one card per claim
    related = _relations(audit, rows)
    # a card for each question about a total or a set of parts, and for each conflict that stays unresolved after a figure was chosen
    current = await _current_audit(audit_id, audit, strict=False)
    sales = claim_matching.sales_questions(found, current.get("results"), _register_settings(audit, await _fx(audit_id, audit), False))      # one per deck
    return waiting + len(definitions) + len(to_set) + len({q["id"] for q in [*related["reviews"], *related["conflicts"]]}) + len(sales)


async def _ic_context(audit_id: str, audit: dict, validate: bool = True) -> dict:
    """The register, the top 5 in force, the gaps and the analyst's inputs of an audit: what the verdict and the memo read.
    Pure reads; nothing is sent to a model (docs/specs/verdict-and-memo.md). With `validate`, the stored results are checked
    against MetricsPayload and the unit check first (section 9): on a failure there are no rows, and `contract` names the
    fields (paths only, never a value)."""
    current = await _current_audit(audit_id, audit, strict=False)
    results, stale = current.get("results"), bool(current.get("results_stale"))
    ic = verdict_mod.with_review(audit, audit.get("ic_inputs"))
    if validate and results:
        try:
            contract.validate_for_export(results)
        except contract.ContractError as exc:
            return {"rows": [], "results": results, "ic": ic, "state": verdict_mod.top5_state([], None), "gaps": [],
                    "contract": exc.log_text, "stale": stale, "open_questions": 0, "conflicts": []}
    _, rows = await _claim_rows(audit_id, audit)
    state = verdict_mod.top5_state(rows, ic.get("top5"))
    rows = verdict_mod.mark_key_gates(rows, state["in_force"])
    gaps = verdict_mod.data_gaps(results, rows, state["in_force"], ic.get("gap_target_dates"))
    return {"rows": rows, "results": results, "ic": ic, "state": state, "gaps": gaps, "contract": None, "stale": stale,
            "open_questions": await _open_claim_questions(audit_id, audit, rows), "conflicts": _relations(audit, rows)["conflicts"]}


async def _integrity(audit_id: str, results: Optional[dict], fiscal_year_end: int) -> dict:
    """Both blocks of the Data integrity section and the conclusion (docs/specs/integrity-coverage.md), from the stored results, the
    deck count, the stored candidates and the audit's fiscal year-end (the clustering check's quarters). Pure reads; no model."""
    deck_count = len(await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "deck_id": 1}).to_list(100))
    candidates = deck_claims.fold_twins(await db[decks.CANDIDATES_COLLECTION].find({"audit_id": audit_id, "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000))
    return integrity_mod.assess(results, deck_count=deck_count, candidates=candidates, fiscal_year_end=fiscal_year_end)


@api.get("/audits/{audit_id}/integrity")
async def get_integrity(audit_id: str):
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    results = (await _current_audit(audit_id, audit, strict=False)).get("results")
    out = await _integrity(audit_id, results, _fiscal_year_end(audit))
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
    """Store the analyst's segment, metric or gate edit for one claim of the register, on the candidate's row, and give the
    register back. A gate the analyst edits reads "set by the analyst"; the claim's text, value and period are edited in the claim editor."""
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
    await db[decks.CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": candidate["id"]},
                                                    {"$set": {"claim_inputs": inputs}})
    _, rows = await _claim_rows(audit_id, audit)
    return sanitize({"register": _marked(audit, rows)})


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
    return sanitize({"register": _marked(audit, rows)})


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
    return sanitize({"register": _marked(audit, rows)})


class GroupChoice(BaseModel):
    """The analyst's choice among the candidates of a question the groups raise (claim-groups.md section 5): the identity of the figure to
    use as the annual total, or the name of the set of parts to show. The server re-checks it against the candidates it offers now."""
    model_config = {"extra": "forbid"}
    choice: str = Field(min_length=1, max_length=64)


@api.put("/audits/{audit_id}/claim-groups/{review_id}")
async def choose_group(audit_id: str, review_id: str, payload: GroupChoice):
    """Save the analyst's choice for one question, on the audit under the question's id, bound to its whole context and the identity of every
    candidate (a hash, no deck text), and give the register back. A choice selects nothing else: a figure passed over stays a claim and its
    conflict stays listed until it is corrected, scoped or excluded (claim-review-simplified-design.md section 2)."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    if not audit.get("results"):
        raise HTTPException(409, "Audit not computed yet")
    _, rows = await _claim_rows(audit_id, audit)
    related = _relations(audit, rows)
    review = next((r for r in [*related["reviews"], *related["conflicts"]] if r["id"] == review_id), None)
    if review is None:
        raise HTTPException(404, "No such question")
    if review["kind"] != claim_groups.KIND_TOTAL:
        raise HTTPException(400, "This question has no figure to choose")
    offered = {c.get("identity") for c in review["candidates"]}
    if payload.choice not in offered:
        raise HTTPException(400, "That choice is not one of the options offered")
    await db.audits.update_one({"id": audit_id}, {"$set": {f"group_choices.{review_id}": {
        "kind": review["kind"], "chosen": payload.choice, "context": review["context"], "saved_at": usage_mod.now()}}})
    kind = review["kind"]
    logger.info("group choice saved: run_id=%s kind=%s", audit_id, kind)
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    _, rows = await _claim_rows(audit_id, audit)
    related = _relations(audit, rows)
    return sanitize({"register": _marked(audit, rows), "groups": related["groups"], "reviews": related["reviews"],
                     "conflicts": related["conflicts"], "counts": claim_groups.counts(rows)})


@api.delete("/audits/{audit_id}/claim-groups/{review_id}")
async def undo_group_choice(audit_id: str, review_id: str):
    """Undo a saved choice: the question is asked again. The claims were never changed, so nothing else moves."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    saved = (audit.get("group_choices") or {}).get(review_id)
    if not saved:
        raise HTTPException(404, "No saved choice")
    await db.audits.update_one({"id": audit_id}, {"$unset": {f"group_choices.{review_id}": ""}})
    kind = saved.get("kind")
    logger.info("group choice undone: run_id=%s kind=%s", audit_id, kind)
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    _, rows = await _claim_rows(audit_id, audit)
    related = _relations(audit, rows)
    return sanitize({"register": _marked(audit, rows), "groups": related["groups"], "reviews": related["reviews"],
                     "conflicts": related["conflicts"], "counts": claim_groups.counts(rows)})


# ---------------------------------------------------------------------------
# Blockers: three kinds, and nothing else, at the top of every audit view (CLAUDE.md rule 21)
# ---------------------------------------------------------------------------
BLOCKER_KINDS = ("revenue_file_missing", "claim_contradicted", "revenue_reconciliation")


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
    if audit.get("results_stale"):      # a replacement, not a fourth blocker: one line and no blockers while results are stale
        return [{"kind": "results_stale", "text": run_audit.STALE_LABEL}]
    out = []
    if not [c for c in await readings_mod.checks_for(db, audit_id) if c.get("status") == "read"]:
        out.append({"kind": "revenue_file_missing", "text": "No file has been read yet: upload a file and run the audit."})
    if audit.get("results") and flags.old_claims():          # OLD_CLAIMS off: a contradicted claim is not a blocker (PR 4)
        _, rows = await _claim_rows(audit_id, audit)
        selected = set(verdict_mod.banner_ids(rows, (audit.get("ic_inputs") or {}).get("top5")))
        # a Contradicted part of a selected group is a Top-5 claim contradicted: a verified annual total does not hide it (claim-groups.md section 4)
        by_group = claim_groups.members(rows)
        selected |= {m["claim_id"] for r in rows if r["claim_id"] in selected and r.get("group_role") == claim_groups.TOTAL
                     for m in by_group.get(r["group_id"], ())}
        for r in rows:
            if r["claim_id"] in selected and r["evidence_label"] == "Contradicted" and not claim_groups.is_repeat_of_listed(r, rows):
                claimed = _figure(r["claimed_value"], r["unit"], r["currency"])
                if r.get("claimed_high") is not None:
                    claimed = f"{claimed}–{_figure(r['claimed_high'], r['unit'], r['currency'])}"
                reporting = audit.get("reporting_currency")
                claimed += claim_matching.converted_note(r, lambda v: _figure(v, None, reporting))
                # An amount is observed in the audit's currency, whatever currency the deck states the claim in.
                observed_currency = reporting if (claim_matching.METRICS.get(r.get("metric") or "") or {}).get("unit") == "currency" \
                    else r["currency"]
                cited = f"{r['observed_citation']} " if r.get("observed_citation") else ""      # issue #136: the figure's own citation
                out.append({"kind": "claim_contradicted", "citation": r["observed_source"], "claim_id": r["claim_id"],
                            "text": f"Top-5 claim contradicted: {deck_claims.type_name(r['claim_type'])} {claimed} vs "
                                    f"{_figure(r['observed_value'], r['unit'], observed_currency)} observed "
                                    f"{cited}({r['deck_file']}, {r['page_ref']})."})
    recon = (audit.get("results") or {}).get("revenue_reconciliation")
    if recon and recon.get("available") and recon.get("blocker"):
        pct = "—" if recon["gap_pct"] is None else f"{abs(recon['gap_pct']) * 100:g}"    # a fraction, shown as a percent
        ccy = audit.get("reporting_currency") or ""
        out.append({"kind": "revenue_reconciliation", "citation": recon["source"], "link": f"/audit/{audit_id}/diagnostics",
                    "text": f"Revenue file and P&L differ by {pct}% over {recon['first']}–{recon['last']} "
                            f"({recon['file_total']:,.0f} {ccy} vs {recon['pnl_total']:,.0f} {ccy})."})
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
    ver = verdict_mod.verdict(rows, ctx["results"], ic.get("top5"), ctx["open_questions"], ctx["conflicts"])
    if ctx["contract"]:
        ver = {**ver, "status": "no_verdict", "message": ic_memo.CONTRACT_NO_VERDICT.format(fields=ctx["contract"])}
    elif ctx["stale"]:
        ver = {**ver, "message": f"No conclusion: {run_audit.STALE_LABEL}."}       # results exist but are of an older contract
    five = ver["top5"]["in_force"]
    key = verdict_mod.key_gates(rows, five)
    integrity = await _integrity(audit_id, ctx["results"], _fiscal_year_end(audit))
    rated = verdict_mod.ratings(ctx["results"], integrity, fmt.fmt_pct, fmt.fmt_months) if ctx["results"] and not ctx["contract"] else None
    draft = verdict_mod.default_thesis(audit, ver, key, lambda v: fmt.fmt_currency(v, (ctx["results"] or {}).get("reporting_currency")))
    # Codes and counts only: no value, gate, thesis, metric name, company or file name reaches the log.
    top5 = claim_matching.label_counts([r for r in rows if r["claim_id"] in set(five)])
    logger.info("verdict: run_id=%s outcome=%s top5=%s changed=%s open=%d", audit_id, ver["outcome_code"], top5, ver["top5"]["changed"],
                ctx["open_questions"])
    return sanitize({
        "verdict": ver, "data_gaps": ctx["gaps"], "top_gaps": verdict_mod.top_gaps(ctx["gaps"]),
        "key_gates": {"note": key["note"], "ok": key["ok"], "all_key": key["all_key"], "saved": key["saved"],
                      "sentences": [{"claim_id": g["claim_id"], "rank": g["rank"], "sentence": g["gate_sentence"],
                                     "status": g.get("gate_status"), "text": verdict_mod.gate_text(g)} for g in key["gates"]]},
        "deal_terms": verdict_mod.W13_DEAL_TERMS, "selection_sentence": verdict_mod.SELECTION_SENTENCE,
        "selection_changed": verdict_mod.SELECTION_CHANGED,
        "candidates": [{"claim_id": r["claim_id"], "rank": r["rank"], "claim": verdict_mod.claim_name(r),
                        "evidence_label": r["evidence_label"], "reason": r["reason"]} for r in verdict_mod.sortable(rows)],
        "ic_inputs": {"first_quarterly_review": ic.get("first_quarterly_review"), "thesis": ic.get("thesis"), "note": ic.get("note")},
        "ratings": rated, "benchmark_label": verdict_mod.BENCHMARK,
        "unresolved_questions": verdict_mod.unresolved_questions(ctx["gaps"], ctx["open_questions"], integrity, ctx["results"]),
        "thesis_draft": draft, "thesis_labels": ic_memo.THESIS_LABELS, "thesis_max": verdict_mod.THESIS_MAX,
        "note_max": verdict_mod.NOTE_MAX,
    })


class IcInputs(BaseModel):
    """The analyst's inputs to the verdict and the memo. A key sent as null clears it; a key not sent stays. The ratings and the judgment fields
    are gone (computed, simplified-flow.md); `note` is the one optional free text of the memo."""
    model_config = {"extra": "forbid"}
    top5: Optional[List[str]] = None
    first_quarterly_review: Optional[str] = None
    gap_target_dates: Optional[dict] = None
    thesis: Optional[dict] = None
    note: Optional[str] = Field(default=None, max_length=verdict_mod.NOTE_MAX)

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
    """The IC memo as Markdown, built now from the stored data and never stored (verdict-and-memo.md section 7). It needs no rating,
    judgment, gate edit or confirmation (simplified-flow.md); refused, with the reason named and nothing written, only for the number
    check, the word limit, the contract or an audit with no conclusion."""
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not audit:
        raise HTTPException(404, "Audit not found")
    ctx = await _ic_context(audit_id, audit)
    claims = flags.old_claims()
    rows, results = (ctx["rows"] if claims else []), ctx["results"]       # OLD_CLAIMS off: the report holds no claim (PR 4)
    refusal = None
    text = ""
    try:
        if ctx["contract"]:
            raise ic_memo.MemoRefused("contract", ic_memo.W19_CONTRACT.format(fields=ctx["contract"]))
        if not results:
            raise ic_memo.MemoRefused("no_verdict", ic_memo.WORDING_NOT_IN_W["no_verdict"].format(
                message=f"{run_audit.STALE_LABEL}." if ctx["stale"] else "compute the audit first."))
        try:
            narratives = [n.model_dump() for n in await llm_gateway.narratives_for_run(db, audit_id)]
        except Exception:                                 # the memo never depends on the narrative service
            narratives = []
        datasets = await db.datasets.find({"audit_id": audit_id}, {"dtype": 1, "file": 1, "sheet": 1, "_id": 0}).to_list(10)
        deck_docs = await db[decks.TEXT_COLLECTION].find({"audit_id": audit_id}, {"file": 1, "_id": 0}).to_list(100)
        meta = {**audit, "results": results}
        ver = verdict_mod.verdict(rows, results, ctx["ic"].get("top5"), ctx["open_questions"], ctx["conflicts"]) if claims else \
            {"status": "ok", "outcome": None, "five": [], "top5": {"changed": False, "in_force": []}, "reasons": []}
        try:
            tables = ic_memo.workbook_tables(build_export_workbook(meta, results))
        except (contract.ContractError, fmt.UnitError):
            tables = []                                   # the memo itself refuses on the contract before it reads a figure
        text = ic_memo.build_memo(
            claims=claims, audit=audit, results=results, rows=rows, ver=ver,
            key=verdict_mod.key_gates(rows, ver["top5"]["in_force"]) if claims else {"gates": [], "note": None},
            gaps=ctx["gaps"], ic={**ctx["ic"], "open_questions": ctx["open_questions"]},
            blockers=await _blocker_list(audit_id, audit), narratives=narratives,
            files=[{"dtype": d["dtype"], "file": d.get("file"), "sheet": d.get("sheet")} for d in datasets],
            decks=[{"file": d.get("file")} for d in deck_docs], tables=tables, today=analysis_date(audit),
            integrity=await _integrity(audit_id, results, _fiscal_year_end(audit)))
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
# Setup inputs that change what a computed audit's metrics should be. A change to any of these on a computed audit marks the stored
# results "Stale – re-run audit" (George, 2026-10-24, PR 177); nothing recomputes until Run audit. The FX rates do the same through save_fx.
STALE_ON_CHANGE_FIELDS = {"reporting_currency", "target_arr", "target_date", "as_of_month", "fiscal_year_end"}


async def _role_inputs(audit_id: str, audit: dict) -> dict:
    """The engine's inputs from the stored map (docs/design/read-check-review.md section 16): the role table of the audit's readings, with each
    row's stored series and the overrides in force, and the deck figures that did not fail their page check. Empty when no file has been read."""
    done = [c for c in await readings_mod.checks_for(db, audit_id) if c.get("status") == "read"]
    files = []
    for check in sorted(done, key=lambda c: c.get("file") or ""):
        reading = await db[readings_mod.READINGS].find_one({"key": check.get("reading_key")}, {"_id": 0})
        if not reading:
            continue
        file_map = readings_mod.effective(reading["file_map"], await readings_mod.overrides_for(db, audit_id, reading["key"]))
        items = [i for i in check.get("items") or [] if str(i.get("key", "")).startswith("row:")]
        labels = {f"{sh['sheet']}:{ln['row']}": ln.get("label") for sh in check.get("lines") or [] for ln in sh.get("lines") or []}
        files.append({"file": check.get("file"), "file_map": file_map, "labels": labels,
                      "rejected": [i["key"] for i in items if i["outcome"] == checks_mod.REJECTED],
                      "cannot": [i["key"] for i in items if i["outcome"] == checks_mod.CANNOT]})
    deck = [{**f, "file": d["file"], "page": f["source"]["page"]} for d in await deck_figures.checked(db, audit_id) for f in d["figures"]
            if f["outcome"] != checks_mod.REJECTED]
    return {"table": role_engine.build_table(files), "deck": deck, "fye": _fiscal_year_end(audit)}


async def _run_compute(audit_id: str) -> dict:
    await _refresh_as_of(audit_id)
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    return await _compute_on_the_map(audit_id, a, await _role_inputs(audit_id, a))


async def _compute_on_the_map(audit_id: str, a: dict, roles: dict) -> dict:
    """Run the engine with its inputs from the stored map (read-check-review.md section 16). The metrics that need customer-level revenue
    lines or CRM deals say so. Nothing here waits for an answer."""
    config = {"reporting_currency": a["reporting_currency"], "target_arr": a["target_arr"], "target_date": a["target_date"],
              "fx": merged_fx(a, None), "billing_terms": {}, "default_l": 1, "as_of_month": a.get("as_of_month"), "roles": roles}
    failures = []

    def on_error(exc):
        failures.append(type(exc).__name__)
        _log_metric_error(exc, audit_id)
    try:
        results = sanitize(ge.compute_all(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), config, {}, on_error=on_error))
    except Exception as exc:
        failed = failures + [type(exc).__name__]
        await _usage_update(audit_id, lambda u: usage_mod.record_compute(u, failed))
        raise
    await _usage_update(audit_id, lambda u: usage_mod.record_compute(u, failures))
    await db.audits.update_one(
        {"id": audit_id},
        {"$set": {"results": results, "status": "computed", "computed_at": datetime.now(timezone.utc).isoformat(),
                  "metrics_stale": False, "setup_stale": False}})
    await _enter_matched_claims(audit_id, await db.audits.find_one({"id": audit_id}))
    return results


async def _current_audit(audit_id: str, audit: dict, strict: bool = True) -> dict:
    """The audit with results of the current engine contract (schemas/metrics.py). Results stored under an older contract are stale
    (George, 2026-10-20): never recomputed on a read and never shown as current (the percents of version 0 would read 100 times too
    large). A strict read answers 409 "Stale – re-run audit"; with strict=False the audit is returned without results and with
    `results_stale` set, so a caller that must keep working (the banner, the usage totals) reads "not computed" instead of a figure.
    Run audit calculates again from the stored files (deterministic Python, no model, no cost) and clears it."""
    if not run_audit.results_stale(audit):
        return audit
    if strict:
        raise HTTPException(409, {"code": run_audit.STALE_CODE, "message": run_audit.STALE_LABEL})
    return {**audit, "results": None, "results_stale": True}


@api.post("/audits/{audit_id}/compute")
async def compute_audit(audit_id: str):
    return await _run_compute(audit_id)


async def _mark_stale_and_maybe_recompute(audit_id: str):
    """A setup input (mapping, FX rate, billing terms, target, as-of month, ...)
    changed. If the audit was already computed, recompute it automatically so it
    never silently shows stale results. If recompute isn't possible right now
    (e.g. a required mapping was cleared), leave metrics_stale set so the UI can
    show a warning instead of outdated numbers."""
    await _refresh_as_of(audit_id)
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

        # Churn series: the trailing-12-month rate and the monthly one, side by side by month
        trailing = {d["month"]: d.get("churn_pct") for d in churn.get("series") or ()}
        monthly = {d["month"]: d.get("churn_pct") for d in churn.get("monthly_series") or ()}
        churn_cols = ["Month", "Gross revenue churn (trailing 12 months)", "Gross revenue churn (monthly)"]
        if monthly or trailing:
            table_sheet(xw, "Churn Series", pd.DataFrame(
                [[m, trailing.get(m), monthly.get(m)] for m in sorted({*trailing, *monthly})], columns=churn_cols), {c: fmt.PCT for c in churn_cols[1:]})
        else:
            pd.DataFrame([{"Month": "(not computable)"}]).to_excel(xw, sheet_name="Churn Series", index=False)

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
            *([("CRM rows sharing a deal ID", an["deals_duplicate_id"].get("collapsed"),
                f"{an['deals_duplicate_id'].get('distinct_ids')} distinct deal IDs")] if an.get("deals_duplicate_id") else []),
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


def _last_frame(exc: BaseException) -> str:
    """The traceback's last frame as file:line in function (file name only, no path)."""
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    if tb is None:
        return "unknown"
    return f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno} in {tb.tb_frame.f_code.co_name}"


@app.middleware("http")
async def log_unexpected_errors(request, call_next):
    """Log any exception an endpoint does not handle, and answer with a readable 500.

    Without this an unhandled exception is answered by the server's outermost error layer,
    which sits outside CORS: the browser then sees a bare network failure with no status and
    no text. Registered before the CORS middleware, so this response carries CORS headers and
    the page can show the real status. Only the exception's class name is sent to the client. The log
    also gets the traceback's last frame, file and line (George, 2026-10-23); never the message, the request or a full traceback.
    """
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error("unexpected error handling %s %s: error=%s at=%s", request.method, request.url.path,
                     type(exc).__name__, _last_frame(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": f"Unexpected server error ({type(exc).__name__}); the details are in the server log"},
        )


@app.middleware("http")
async def hide_cost_from_testers(request, call_next):
    """No cost, token or USD field in a response to anyone but the owner token (usage-and-allowance.md section 9). The owner token
    reaches the admin routes only; everyone else, a request with access control off included, gets the JSON without those keys."""
    response = await call_next(request)
    who = getattr(request.state, "principal", None)
    if (who and who[0] == access_mod.OWNER) or not response.headers.get("content-type", "").startswith("application/json"):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    return Response(content=tester_view.strip_body(body), status_code=response.status_code, headers=headers)


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# 4: demo audits carry consent and a fiscal year-end (the client name is gone since 11).
# 5: demo P&L revenue reconciles with the revenue file (one demo audit keeps a deliberate 5% gap).
# 6: results carry contract_version 1 (percents as fractions, whole counts and days).
# 7: results carry contract_version 2 (a citation on every result block).
# 8: demo audits carry no engagement reference (the field is gone).
# 9: results carry contract_version 3 (the latest valid source period and the period of every metric).
# 10: results carry contract_version 4 (repeated CRM rows counted once and flagged, won deals by close month).
# 11: demo audits carry no client name (the field is gone).
# 12: results carry contract_version 5 (demo audits seeded under 11 held version 4 and opened as Stale).
SEED_VERSION = 22          # 22: engine contract 15 (the file map): demo audits held under contract 14 are reseeded. 21: engine contract 14 (P&L lines)
                          # 20: engine contract 13 (deck actuals): demo audits held under contract 12 are reseeded
                          # 19: engine contract 12 (one as-of month): demo audits held under contract 11 are reseeded
                          # 18: engine contract 11 (the page reader's answer form): demo audits held under contract 10 are reseeded
                          # 17: engine contract 10 (the yearly-basis block names two annual payback proxies and the S&M scope): demo audits held under contract 9 are reseeded
                          # 16: engine contract 9 (the simplified flow): demo audits held under contract 8 are reseeded
                          # 15: engine contract 8 (ARR, MRR, Churn, NRR and CAC payback claim types): demo audits held under contract 7 are reseeded
                          # 14: engine contract 7 (the page reader's seven new metrics): demo audits held under contract 6 are reseeded
                           # 13: engine contract 6 (the page reader): demo audits held under contract 5 are reseeded


@app.on_event("startup")
async def seed_demo():
    # The engagement reference is gone from the audit record (2026-10-08): audits created before keep no copy of it.
    await db.audits.update_many({"engagement_reference": {"$exists": True}}, {"$unset": {"engagement_reference": ""}})
    if await db.audits.count_documents({"seed_version": SEED_VERSION}) > 0:
        return
    demo_ids = {"audit_id": {"$in": [a["id"] for a in await db.audits.find({"demo": True}, {"id": 1}).to_list(50)]}}
    for name in ("datasets", decks.TEXT_COLLECTION, decks.CANDIDATES_COLLECTION, structures.COLUMN_MAPPINGS_COLLECTION, deck_render.COLLECTION):
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
            norm[dtype] = normalize(recs, dtype, mapping)
            uploads[dtype] = {"file": meta[dtype]["file"], "sheet": meta[dtype]["sheet"], "columns": list(df.columns),
                              "rows": recs, "mapping": mapping}
        fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
        fx[spec["reporting_currency"].upper()] = 1.0
        found = demo_data.detect_month(uploads)          # detected as on Map, stored once on the audit
        as_of_month = as_of_mod.month_end(found["month"]) if found else None
        config = {"reporting_currency": spec["reporting_currency"], "target_arr": spec["target_arr"],
                  "target_date": spec["target_date"], "fx": fx, "billing_terms": {}, "default_l": 1,
                  "as_of_month": as_of_month}
        sources = {t: {"file": meta[t]["file"], "sheet": meta[t]["sheet"]} for t in datasets}
        results = ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], config, sources,
                                 files=candidate_views(uploads),
                                 on_error=lambda exc: _log_metric_error(exc, audit_id))
        await db.audits.insert_one({
            "id": audit_id, "company_name": spec["company_name"], "reporting_currency": spec["reporting_currency"],
            "target_arr": spec["target_arr"], "target_date": spec["target_date"],
            "fiscal_year_end": spec["fiscal_year_end"],
            "structure_reading_consent": True,
            "consent_log": [_consent_entry(True)],
            "created_at": datetime.now(timezone.utc).isoformat(), "status": "computed",
            "computed_at": datetime.now(timezone.utc).isoformat(), "results": sanitize(results), "demo": True,
            "seed_version": SEED_VERSION, "usage": usage_mod.empty(),
            "as_of_month": as_of_month, "as_of_by": as_of_mod.DETECTED, "as_of_file": found["file"] if found else None,
        })
    logger.info("Seeded demo audits")



@app.on_event("startup")
async def check_page_reader_model():
    """Log an error when the configured page-reader model is not on the allow-list (page-image.md section 2); every page read is then
    blocked, and the check runs again before each read."""
    llm_gateway.page_reader_problem()


@app.on_event("startup")
async def check_sheet_reader():
    """Log one error line when the sheet reader's prompt or model is missing. The app starts either way; spreadsheets show "not read"."""
    try:
        problem = await llm_gateway.sheet_reader_startup_problem(db)
    except Exception as exc:                                       # a store that cannot be read at startup must not stop the server
        logger.error("sheet reader check failed at startup: error=%s", type(exc).__name__)
        return
    if problem:
        logger.error("sheet reader will not read: %s", problem)
    try:
        missing = await llm_gateway.reviewer_startup_problem(db)
    except Exception as exc:
        logger.error("reviewer check failed at startup: error=%s", type(exc).__name__)
        return
    if missing:
        logger.error("reviewer will not run: %s", missing)


@app.on_event("startup")
async def ensure_llm_indexes():
    await llm_gateway.guards.ensure_indexes(db)


@app.on_event("startup")
async def drop_legacy_token_map():
    await llm_gateway.drop_legacy_map(db)        # the former pseudonym_map collection goes once Delete audit has emptied it


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
