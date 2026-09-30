from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from pydantic import BaseModel, Field, field_validator

import growth_engine as ge
import demo_data
from app import formatting as fmt
from app.llm import gateway as llm_gateway

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="Growth Diligence Engine")
api = APIRouter(prefix="/api")
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
    for f in defs["dates"]:
        if f in out.columns:
            out[f] = pd.to_datetime(out[f], errors="coerce")
    for f in defs["numeric"]:
        if f in out.columns:
            out[f] = pd.to_numeric(out[f], errors="coerce")
    return out


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
        raise ValueError("target_date must be in YYYY-MM-DD format")
    if not (2000 <= dt.year <= 2100):
        raise ValueError(f"target_date year must be between 2000 and 2100, got {dt.year}")
    return v


class AuditCreate(BaseModel):
    company_name: str
    reporting_currency: str = "EUR"
    target_arr: float = 0
    target_date: Optional[str] = None
    as_of_month: Optional[str] = None

    _check_target_date = field_validator("target_date")(_validate_target_date)


class AuditUpdate(BaseModel):
    company_name: Optional[str] = None
    reporting_currency: Optional[str] = None
    target_arr: Optional[float] = None
    target_date: Optional[str] = None
    as_of_month: Optional[str] = None

    _check_target_date = field_validator("target_date")(_validate_target_date)


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
        d["dtype"]: {k: d.get(k) for k in ("file", "sheet", "columns", "mapping", "fx", "billing_terms", "preview", "row_count")}
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
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if updates:
        await db.audits.update_one({"id": audit_id}, {"$set": updates})
        if RECOMPUTE_TRIGGER_FIELDS & updates.keys():
            await _mark_stale_and_maybe_recompute(audit_id)
    return await audit_public(await db.audits.find_one({"id": audit_id}))


@api.delete("/audits/{audit_id}")
async def delete_audit(audit_id: str):
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    await db.audits.delete_one({"id": audit_id})
    await db.datasets.delete_many({"audit_id": audit_id})
    # Narratives, call log and pseudonym mapping are scoped to the run and must
    # not outlive it.
    purged = await llm_gateway.purge_run(db, audit_id)
    return {"deleted": audit_id, "llm_purged": purged}


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
    mapping = suggest_mapping(dtype, columns)
    preview = rows[:8]
    await db.datasets.replace_one(
        {"audit_id": audit_id, "dtype": dtype},
        {"audit_id": audit_id, "dtype": dtype, "file": file.filename, "sheet": sheet,
         "columns": columns, "rows": rows, "row_count": len(rows), "mapping": mapping,
         "fx": {}, "billing_terms": {}, "preview": preview},
        upsert=True,
    )
    await _mark_stale_and_maybe_recompute(audit_id)
    return {
        "dtype": dtype, "file": file.filename, "sheet": sheet, "columns": columns,
        "row_count": len(rows), "suggested_mapping": mapping, "preview": preview,
        "fields": {"required": list(FIELD_DEFS[dtype]["required"]), "optional": list(FIELD_DEFS[dtype]["optional"])},
    }


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
        {"$set": {"mapping": payload.mapping, "fx": payload.fx, "billing_terms": payload.billing_terms}},
    )
    await _mark_stale_and_maybe_recompute(audit_id)
    return {"ok": True}


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
    results = sanitize(ge.compute_all(rev, crm, pnl, config, sources))
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


def build_export_workbook(meta: dict, r: dict, disclosure_text: Optional[str] = None) -> io.BytesIO:
    """Numeric cells with Excel number formats (see app/formatting.py), so the
    display follows the formatting rules while analysts can still sum and sort."""
    ccy = r.get("reporting_currency", "")
    money = f" ({ccy})" if ccy else ""

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
        cac_label, cac_value = "CAC payback, months (no complete quarter)", None
        if cac:
            L = f"L{cac.get('default_l', 1)}"
            hq = cac.get("headline_quarter")
            if hq is None and "headline_quarter" not in cac:  # results computed before partial quarters were flagged
                done = [q for q in sorted(cac.get("quarters", {}))
                        if not cac["quarters"][q].get("partial") and cac["quarters"][q][L]["months"] is not None]
                hq = done[-1] if done else None
            if hq:
                cac_value = cac["quarters"][hq][L]["months"]
                cac_label = f"CAC payback, months ({hq}, {L}, latest complete quarter)"
        kv_sheet(xw, "Headline", [
            ("Company", None, meta.get("company_name")),
            ("As-of month", None, meta.get("as_of_month") or r.get("as_of_month")),
            ("Reporting currency", None, ccy),
            (f"Ending ARR{money}", fmt.CURRENCY, arr.get("value")),
            (f"Current MRR{money}", fmt.CURRENCY, arr.get("mrr")),
            ("ARR month", None, arr.get("month")),
            ("NRR overall", fmt.PCT, nrr.get("overall_pct")),
            ("Gross revenue churn", fmt.PCT, churn.get("overall_pct")),
            (cac_label, fmt.MONTHS, cac_value),
            ("Median sales cycle (days)", fmt.DAYS, sc.get("median_days")),
            ("Win rate", fmt.PCT, wr.get("win_rate_pct")),
            ("Deals excluded (close<created)", fmt.COUNT, wr.get("excluded_invalid")),
        ])
        if disclosure_text:
            # Foot of the summary sheet: the same block the dashboard shows (app/disclosure.py).
            ws = xw.sheets["Headline"]
            ws.cell(row=ws.max_row + 2, column=1).value = "AI disclosure"
            ws.cell(row=ws.max_row, column=2).value = disclosure_text

        # By segment
        seg_rows = {}
        for seg, v in (nrr.get("by_segment") or {}).items():
            seg_rows.setdefault(seg, {})["NRR"] = v.get("nrr_pct")
            seg_rows[seg]["NRR base n"] = v.get("n")
        for seg, v in (sc.get("by_segment") or {}).items():
            seg_rows.setdefault(seg, {})["Sales cycle median (d)"] = v.get("median_days")
            seg_rows[seg]["Sales cycle n"] = v.get("n")
        for seg, v in ((r.get("acv_path") or {}).get("by_segment") or {}).items():
            seg_rows.setdefault(seg, {})["Customers"] = v.get("customers")
            seg_rows[seg][f"ACV{money}"] = v.get("acv")
            seg_rows[seg][f"ARR{money}"] = v.get("arr")
        if seg_rows:
            table_sheet(xw, "By Segment", pd.DataFrame([{"Segment": s, **vals} for s, vals in seg_rows.items()]), {
                "NRR": fmt.PCT, "NRR base n": fmt.COUNT, "Sales cycle median (d)": fmt.DAYS,
                "Sales cycle n": fmt.COUNT, "Customers": fmt.COUNT,
                f"ACV{money}": fmt.CURRENCY, f"ARR{money}": fmt.CURRENCY,
            })
        else:
            pd.DataFrame([{"Segment": "(no segment column mapped)"}]).to_excel(xw, sheet_name="By Segment", index=False)

        # NRR by cohort
        if nrr.get("by_cohort"):
            table_sheet(xw, "NRR by Cohort", pd.DataFrame(
                [{"Cohort": k, "NRR": v.get("nrr_pct"), "n": v.get("n")} for k, v in nrr["by_cohort"].items()]
            ), {"NRR": fmt.PCT, "n": fmt.COUNT})
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
                   f"New MRR{money}": v.get("new_mrr"), "Gross margin": v.get("gross_margin_pct")}
            for L in ("L0", "L1", "L2"):
                row[f"{L} months"] = v[L].get("months")
                row[f"{L} S&M used{money}"] = v[L].get("sm_expense")
                row[f"{L} reason"] = v[L].get("reason")
            cac_rows.append(row)
        if cac_rows:
            kinds = {f"New MRR{money}": fmt.CURRENCY, "Gross margin": fmt.PCT}
            for L in ("L0", "L1", "L2"):
                kinds[f"{L} months"] = fmt.MONTHS
                kinds[f"{L} S&M used{money}"] = fmt.CURRENCY
            table_sheet(xw, "CAC by Quarter", pd.DataFrame(cac_rows), kinds)
        else:
            pd.DataFrame([{"Quarter": "(P&L not provided)"}]).to_excel(xw, sheet_name="CAC by Quarter", index=False)

        # Path to plan
        ap = r.get("acv_path") or {}
        kv_sheet(xw, "Path to Plan", [
            ("Current customers", fmt.COUNT, ap.get("current_customers")),
            (f"Current ARR{money}", fmt.CURRENCY, ap.get("current_arr")),
            (f"ACV (average contract value){money}", fmt.CURRENCY, ap.get("acv")),
            (f"Target ARR{money}", fmt.CURRENCY, ap.get("target_arr")),
            ("Target date", None, ap.get("target_date")),
            ("Customers needed", fmt.COUNT_UP, ap.get("customers_needed")),
            ("Required net-new / year", fmt.COUNT_UP, ap.get("required_net_new_per_year")),
            ("Observed net-new / year (12m)", fmt.COUNT, ap.get("observed_net_new_per_year_12m")),
            ("Observed net-new / year (24m)", fmt.COUNT, ap.get("observed_net_new_per_year_24m")),
            ("Required ÷ observed (12m)", fmt.RATIO, ap.get("required_vs_observed_12m")),
            ("Required ÷ observed (24m)", fmt.RATIO, ap.get("required_vs_observed_24m")),
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

        # Anomalies
        an = r.get("anomalies") or {}
        an_rows = [
            ("Months with negative MRR", len(an.get("negative_mrr_months", [])), ", ".join(an.get("negative_mrr_months", []))),
            ("Customers with gaps > 2 months then resume", len(an.get("revenue_gap_then_resume", [])), ", ".join(an.get("revenue_gap_then_resume", [])[:50])),
            ("Revenue lines missing customer ID", an.get("revenue_missing_customer_id", {}).get("count"), ""),
            ("Deals close-before-created (excluded)", an.get("deals_close_before_created", {}).get("excluded_count"), ""),
        ]
        pd.DataFrame(an_rows, columns=["Flag", "Count", "Detail"]).to_excel(xw, sheet_name="Anomalies", index=False)

        # Missing data
        md = r.get("missing_data") or []
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
        block = await llm_gateway.disclosure_for_run(db, audit_id)
    except Exception:  # the export never depends on the narrative service
        block = None
    buf = build_export_workbook(a, a["results"], block["text"] if block else None)
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
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def seed_demo():
    if await db.audits.count_documents({"seed_version": 3}) > 0:
        return
    await db.datasets.delete_many({"audit_id": {"$in": [a["id"] for a in await db.audits.find({"demo": True}, {"id": 1}).to_list(50)]}})
    await db.audits.delete_many({"demo": True})
    for spec in demo_data.DEMO_AUDITS:
        datasets, meta = demo_data.build(spec)
        audit_id = str(uuid.uuid4())
        norm = {}
        for dtype, (df, mapping) in datasets.items():
            recs = df_to_records(df)
            await db.datasets.replace_one(
                {"audit_id": audit_id, "dtype": dtype},
                {"audit_id": audit_id, "dtype": dtype, "file": meta[dtype]["file"], "sheet": meta[dtype]["sheet"],
                 "columns": list(df.columns), "rows": recs, "row_count": len(recs),
                 "mapping": mapping, "fx": meta.get("fx", {}), "billing_terms": {}, "preview": recs[:8]},
                upsert=True,
            )
            norm[dtype] = normalize(recs, dtype, mapping)
        fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
        fx[spec["reporting_currency"].upper()] = 1.0
        config = {"reporting_currency": spec["reporting_currency"], "target_arr": spec["target_arr"],
                  "target_date": spec["target_date"], "fx": fx, "billing_terms": {}, "default_l": 1,
                  "as_of_month": None}
        sources = {t: {"file": meta[t]["file"], "sheet": meta[t]["sheet"]} for t in datasets}
        results = ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], config, sources)
        await db.audits.insert_one({
            "id": audit_id, "company_name": spec["company_name"], "reporting_currency": spec["reporting_currency"],
            "target_arr": spec["target_arr"], "target_date": spec["target_date"],
            "created_at": datetime.now(timezone.utc).isoformat(), "status": "computed",
            "computed_at": datetime.now(timezone.utc).isoformat(), "results": sanitize(results), "demo": True, "seed_version": 3,
        })
    logger.info("Seeded demo audits")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
