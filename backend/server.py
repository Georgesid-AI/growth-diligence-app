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
from pydantic import BaseModel, Field

import growth_engine as ge
import demo_data

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
class AuditCreate(BaseModel):
    company_name: str
    reporting_currency: str = "EUR"
    target_arr: float = 0
    target_date: Optional[str] = None
    as_of_month: Optional[str] = None


class AuditUpdate(BaseModel):
    company_name: Optional[str] = None
    reporting_currency: Optional[str] = None
    target_arr: Optional[float] = None
    target_date: Optional[str] = None
    as_of_month: Optional[str] = None


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
    return await audit_public(await db.audits.find_one({"id": audit_id}))


@api.delete("/audits/{audit_id}")
async def delete_audit(audit_id: str):
    a = await db.audits.find_one({"id": audit_id})
    if not a:
        raise HTTPException(404, "Audit not found")
    await db.audits.delete_one({"id": audit_id})
    await db.datasets.delete_many({"audit_id": audit_id})
    return {"deleted": audit_id}


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
    return {"ok": True}


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------
@api.post("/audits/{audit_id}/compute")
async def compute_audit(audit_id: str):
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
        {"$set": {"results": results, "status": "computed", "computed_at": datetime.now(timezone.utc).isoformat()}},
    )
    return results


@api.get("/audits/{audit_id}/results")
async def get_results(audit_id: str):
    a = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Audit not found")
    if not a.get("results"):
        raise HTTPException(409, "Audit not computed yet")
    keys = ("id", "company_name", "reporting_currency", "target_arr", "target_date", "as_of_month", "status", "computed_at")
    return sanitize({"audit": {k: a.get(k) for k in keys}, "results": a["results"]})


def build_export_workbook(meta: dict, r: dict) -> io.BytesIO:
    ccy = r.get("reporting_currency", "")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        # Headline
        arr = r.get("arr") or {}
        nrr = r.get("nrr") or {}
        churn = r.get("gross_churn") or {}
        sc = r.get("sales_cycle") or {}
        wr = r.get("win_rate") or {}
        cac = r.get("cac_payback") or {}
        cac_display = None
        if cac:
            L = f"L{cac.get('default_l', 1)}"
            for q in sorted(cac.get("quarters", {})):
                if cac["quarters"][q][L]["months"] is not None:
                    cac_display = f"{cac['quarters'][q][L]['months']} mo ({q}, {L})"
        headline = [
            ("Company", meta.get("company_name")),
            ("As-of month", meta.get("as_of_month") or r.get("as_of_month")),
            ("Reporting currency", ccy),
            ("Ending ARR", arr.get("value")),
            ("Current MRR", arr.get("mrr")),
            ("ARR month", arr.get("month")),
            ("NRR overall %", nrr.get("overall_pct")),
            ("Gross revenue churn %", churn.get("overall_pct")),
            ("CAC payback (default L)", cac_display),
            ("Median sales cycle (days)", sc.get("median_days")),
            ("Win rate %", wr.get("win_rate_pct")),
            ("Deals excluded (close<created)", wr.get("excluded_invalid")),
        ]
        pd.DataFrame(headline, columns=["Metric", "Value"]).to_excel(xw, sheet_name="Headline", index=False)

        # By segment
        seg_rows = {}
        for seg, v in (nrr.get("by_segment") or {}).items():
            seg_rows.setdefault(seg, {})["NRR %"] = v.get("nrr_pct")
            seg_rows[seg]["NRR base n"] = v.get("n")
        for seg, v in (sc.get("by_segment") or {}).items():
            seg_rows.setdefault(seg, {})["Sales cycle median (d)"] = v.get("median_days")
            seg_rows[seg]["Sales cycle n"] = v.get("n")
        for seg, v in ((r.get("acv_path") or {}).get("by_segment") or {}).items():
            seg_rows.setdefault(seg, {})["Customers"] = v.get("customers")
            seg_rows[seg]["ACV"] = v.get("acv")
            seg_rows[seg]["ARR"] = v.get("arr")
        seg_df = pd.DataFrame([{"Segment": s, **vals} for s, vals in seg_rows.items()]) if seg_rows \
            else pd.DataFrame([{"Segment": "(no segment column mapped)"}])
        seg_df.to_excel(xw, sheet_name="By Segment", index=False)

        # NRR by cohort
        cohort_df = pd.DataFrame(
            [{"Cohort": k, "NRR %": v.get("nrr_pct"), "n": v.get("n")} for k, v in (nrr.get("by_cohort") or {}).items()]
        ) if nrr.get("by_cohort") else pd.DataFrame([{"Cohort": "(not computable)"}])
        cohort_df.to_excel(xw, sheet_name="NRR by Cohort", index=False)

        # NRR series
        series_df = pd.DataFrame(nrr.get("series") or [], columns=["month", "nrr_pct"])
        (series_df if not series_df.empty else pd.DataFrame([{"month": "(not computable)"}])).to_excel(
            xw, sheet_name="NRR Series", index=False)

        # CAC by quarter
        cac_rows = []
        for q, v in (cac.get("quarters") or {}).items():
            row = {"Quarter": q, "New MRR": v.get("new_mrr"), "Gross margin %": v.get("gross_margin_pct")}
            for L in ("L0", "L1", "L2"):
                row[f"{L} months"] = v[L].get("months")
                row[f"{L} S&M used"] = v[L].get("sm_expense")
                row[f"{L} reason"] = v[L].get("reason")
            cac_rows.append(row)
        (pd.DataFrame(cac_rows) if cac_rows else pd.DataFrame([{"Quarter": "(P&L not provided)"}])).to_excel(
            xw, sheet_name="CAC by Quarter", index=False)

        # Path to plan
        ap = r.get("acv_path") or {}
        path_rows = [
            ("Current customers", ap.get("current_customers")),
            ("Current ARR", ap.get("current_arr")),
            ("ACV", ap.get("acv")),
            ("Target ARR", ap.get("target_arr")),
            ("Target date", ap.get("target_date")),
            ("Customers needed", ap.get("customers_needed")),
            ("Required net-new / year", ap.get("required_net_new_per_year")),
            ("Observed net-new / year (12m)", ap.get("observed_net_new_per_year_12m")),
            ("Observed net-new / year (24m)", ap.get("observed_net_new_per_year_24m")),
            ("Required ÷ observed (12m)", ap.get("required_vs_observed_12m")),
            ("Required ÷ observed (24m)", ap.get("required_vs_observed_24m")),
        ]
        pd.DataFrame(path_rows, columns=["Metric", "Value"]).to_excel(xw, sheet_name="Path to Plan", index=False)

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
    buf.seek(0)
    return buf


@api.get("/audits/{audit_id}/export")
async def export_audit(audit_id: str):
    a = await db.audits.find_one({"id": audit_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Audit not found")
    if not a.get("results"):
        raise HTTPException(409, "Audit not computed yet")
    buf = build_export_workbook(a, a["results"])
    safe = "".join(c for c in (a.get("company_name") or "audit") if c.isalnum() or c in " -_").strip().replace(" ", "_")
    fname = f"{safe or 'audit'}_growth_diligence.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


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
