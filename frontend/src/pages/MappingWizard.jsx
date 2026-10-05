import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Upload, CheckCircle2, Loader2, FileSpreadsheet, Plus, X, Play, Search } from "lucide-react";
import { Layout } from "@/components/Layout";
import DeckPanel from "@/components/DeckPanel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getAudit, getFields, uploadDataset, saveMapping, computeAudit, getRevenueCustomers, updateAudit } from "@/lib/api";
import { asOfInputValue, MONTHS, DEFAULT_FISCAL_YEAR_END } from "@/lib/auditForm";

const DTYPES = [
  { key: "revenue", label: "Revenue Lines", desc: "Recurring & one-off invoices — the basis for MRR/ARR, NRR and churn.", required: true },
  { key: "crm", label: "CRM Deals", desc: "Pipeline for sales cycle and win rate.", required: false },
  { key: "pnl", label: "P&L (monthly)", desc: "S&M expense, revenue and cost of revenue — needed for CAC payback.", required: false },
];
const NONE = "__none__";

export default function MappingWizard() {
  const { id } = useParams();
  const nav = useNavigate();
  const [audit, setAudit] = useState(null);
  const [fields, setFields] = useState(null);
  const [computing, setComputing] = useState(false);
  const [asOf, setAsOf] = useState("");

  const load = useCallback(() => getAudit(id).then((a) => { setAudit(a); setAsOf(asOfInputValue(a.as_of_month)); }), [id]);
  useEffect(() => { load(); getFields().then(setFields); }, [load]);

  // The fiscal year-end stays editable after creation; saving it re-runs period mapping on the server.
  const saveYearEnd = async (month) => {
    try {
      setAudit(await updateAudit(id, { fiscal_year_end: Number(month) }));
      toast.success("Fiscal year-end saved; claim periods re-mapped");
    } catch (e) {
      toast.error("Could not save the fiscal year-end");
    }
  };

  const runCompute = async () => {
    setComputing(true);
    try {
      await updateAudit(id, { as_of_month: asOf || null });
      await computeAudit(id);
      toast.success("Metrics computed");
      nav(`/audit/${id}/dashboard`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Compute failed — check required fields are mapped");
    } finally {
      setComputing(false);
    }
  };

  if (!audit || !fields) {
    return <Layout audit={audit}><div className="flex justify-center py-32 text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /></div></Layout>;
  }

  const hasRevenue = !!audit.datasets?.revenue;

  return (
    <Layout audit={audit}>
      <div className="flex items-end justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">Upload & Column Mapping</h1>
          <p className="text-slate-600 text-sm mt-2 max-w-2xl">
            Upload <span className="font-mono text-slate-700">.xlsx</span> or <span className="font-mono text-slate-700">.csv</span> files.
            Confirm every mapping — nothing is guessed. Required fields must be mapped; optional fields left blank move the
            dependent metric to the diagnostics panel.
          </p>
        </div>
        <div className="flex items-end gap-3">
          <div>
            <label className="text-[11px] font-mono uppercase tracking-wider text-slate-600 block mb-1">Fiscal year-end</label>
            <Select value={String(audit.fiscal_year_end || DEFAULT_FISCAL_YEAR_END)} onValueChange={saveYearEnd}>
              <SelectTrigger data-testid="fiscal-year-end-select" className="h-9 w-36 bg-white border-[#E5E7EB]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-white border-[#E5E7EB] text-slate-900">
                {MONTHS.map((m, i) => <SelectItem key={m} value={String(i + 1)}>{m}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-[11px] font-mono uppercase tracking-wider text-slate-600 block mb-1">As-of month</label>
            <Input
              data-testid="asof-month-input"
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="h-9 w-40 bg-white border-[#E5E7EB] font-mono"
              placeholder="last P&L month"
            />
          </div>
          <Button data-testid="compute-button" onClick={runCompute} disabled={!hasRevenue || computing}
            className="bg-sky-600 hover:bg-sky-500 gap-2">
            {computing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Compute Metrics
          </Button>
        </div>
      </div>

      <div className="space-y-5">
        {DTYPES.map((dt) => (
          <DatasetPanel key={dt.key} audit={audit} dtype={dt} fields={fields[dt.key]} onChange={load} />
        ))}
        <DeckPanel auditId={audit.id} />
      </div>
    </Layout>
  );
}

function DatasetPanel({ audit, dtype, fields, onChange }) {
  const existing = audit.datasets?.[dtype.key];
  const [uploading, setUploading] = useState(false);
  const [columns, setColumns] = useState(existing?.columns || null);
  const [mapping, setMapping] = useState(existing?.mapping || {});
  const [fx, setFx] = useState(existing?.fx || {});
  const [billingTerms, setBillingTerms] = useState(existing?.billing_terms || {});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (existing) {
      setColumns(existing.columns); setMapping(existing.mapping || {});
      setFx(existing.fx || {}); setBillingTerms(existing.billing_terms || {});
    }
  }, [existing?.file]); // eslint-disable-line

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await uploadDataset(audit.id, dtype.key, file);
      setColumns(res.columns);
      setMapping(res.suggested_mapping);
      toast.success(`${res.file}: ${res.row_count} rows · auto-mapped`);
      onChange();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await saveMapping(audit.id, dtype.key, { mapping, fx, billing_terms: billingTerms });
      toast.success("Mapping saved");
      onChange();
    } catch (err) {
      toast.error("Save failed");
    } finally {
      setSaving(false);
    }
  };

  const setField = (field, val) => setMapping((m) => ({ ...m, [field]: val === NONE ? null : val }));
  const requiredUnmapped = fields.required.filter((f) => !mapping[f]);

  return (
    <div className="bg-white border border-[#E5E7EB] rounded-lg p-5" data-testid={`dataset-panel-${dtype.key}`}>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className={`h-9 w-9 rounded-md flex items-center justify-center ${columns ? "bg-emerald-500/15 border border-emerald-500/40" : "bg-sky-50 border border-[#E5E7EB]"}`}>
            {columns ? <CheckCircle2 className="h-4 w-4 text-emerald-700" /> : <FileSpreadsheet className="h-4 w-4 text-slate-600" />}
          </div>
          <div>
            <h3 className="font-heading font-semibold text-slate-900 flex items-center gap-2">
              {dtype.label}
              {dtype.required && <span className="text-[9px] font-mono uppercase text-sky-700 border border-sky-500/40 rounded px-1.5 py-0.5">required</span>}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5 max-w-xl">{dtype.desc}</p>
            {existing && <p className="text-[11px] font-mono text-slate-600 mt-1">{existing.file} · {existing.row_count} rows</p>}
          </div>
        </div>
        <label className="cursor-pointer">
          <input type="file" accept=".xlsx,.csv,.xls" className="hidden" onChange={onFile} data-testid={`upload-dropzone-${dtype.key}`} />
          <span className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md bg-sky-50 border border-[#D1D5DB] text-sm text-slate-800 hover:bg-slate-100 transition-colors">
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {columns ? "Replace file" : "Upload file"}
          </span>
        </label>
      </div>

      {columns && (
        <div className="mt-5 pt-5 border-t border-[#E5E7EB]">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[...fields.required, ...fields.optional].map((field) => {
              const isReq = fields.required.includes(field);
              return (
                <div key={field}>
                  <label className="text-xs text-slate-700 flex items-center gap-1.5 mb-1">
                    {field.replace(/_/g, " ")}
                    {isReq ? <span className="text-sky-700">*</span> : <span className="text-slate-600 text-[10px]">optional</span>}
                  </label>
                  <Select value={mapping[field] || NONE} onValueChange={(v) => setField(field, v)}>
                    <SelectTrigger data-testid={`map-column-${field}`} className={`bg-white border-[#E5E7EB] h-9 ${isReq && !mapping[field] ? "border-amber-500/50" : ""}`}>
                      <SelectValue placeholder="— none —" />
                    </SelectTrigger>
                    <SelectContent className="bg-white border-[#E5E7EB] text-slate-900 max-h-64">
                      <SelectItem value={NONE}>— none —</SelectItem>
                      {columns.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              );
            })}
          </div>

          {dtype.key === "revenue" && (
            <FxEditor fx={fx} setFx={setFx} baseCcy={audit.reporting_currency} />
          )}

          {dtype.key === "revenue" && (
            <BillingTerms
              auditId={audit.id}
              customerCol={mapping.customer_id}
              hasServiceDates={!!mapping.service_start && !!mapping.service_end}
              billingTerms={billingTerms}
              setBillingTerms={setBillingTerms}
            />
          )}

          <div className="flex items-center justify-between mt-4">
            <div className="text-xs font-mono">
              {requiredUnmapped.length > 0
                ? <span className="text-amber-700">{requiredUnmapped.length} required field(s) unmapped: {requiredUnmapped.join(", ")}</span>
                : <span className="text-emerald-700">All required fields mapped</span>}
            </div>
            <Button data-testid={`confirm-mapping-button-${dtype.key}`} size="sm" onClick={save} disabled={saving}
              className="bg-sky-600 hover:bg-sky-500 gap-2">
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Confirm mapping
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function FxEditor({ fx, setFx, baseCcy }) {
  const [ccy, setCcy] = useState("");
  const [rate, setRate] = useState("");
  const add = () => {
    if (!ccy.trim() || !parseFloat(rate)) return;
    setFx({ ...fx, [ccy.trim().toUpperCase()]: parseFloat(rate) });
    setCcy(""); setRate("");
  };
  const remove = (k) => { const n = { ...fx }; delete n[k]; setFx(n); };
  return (
    <div className="mt-5 pt-5 border-t border-[#E5E7EB]">
      <div className="text-xs text-slate-700 mb-2">
        FX rates to {baseCcy} <span className="text-slate-500">(add a rate for each non-{baseCcy} currency in your revenue lines)</span>
      </div>
      <div className="flex flex-wrap gap-2 mb-3">
        {Object.entries(fx).map(([k, v]) => (
          <span key={k} className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-sky-50 border border-[#D1D5DB] text-xs font-mono text-slate-800">
            1 {k} = {v} {baseCcy}
            <button onClick={() => remove(k)} className="text-slate-500 hover:text-rose-700"><X className="h-3 w-3" /></button>
          </span>
        ))}
        {Object.keys(fx).length === 0 && <span className="text-xs text-slate-600 font-mono">no FX rates — single-currency assumed</span>}
      </div>
      <div className="flex gap-2 items-center">
        <Input value={ccy} onChange={(e) => setCcy(e.target.value)} placeholder="USD" className="w-24 h-9 bg-white border-[#E5E7EB] font-mono uppercase" data-testid="fx-ccy-input" />
        <span className="text-slate-500 text-sm">=</span>
        <Input value={rate} onChange={(e) => setRate(e.target.value)} placeholder="0.92" type="number" step="0.0001" className="w-28 h-9 bg-white border-[#E5E7EB] font-mono" data-testid="fx-rate-input" />
        <span className="text-slate-500 text-sm">{baseCcy}</span>
        <Button size="sm" variant="outline" onClick={add} className="bg-transparent border-[#D1D5DB] text-slate-800 gap-1"><Plus className="h-3.5 w-3.5" /> Add</Button>
      </div>
    </div>
  );
}

const TERMS = ["monthly", "quarterly", "annual"];

function BillingTerms({ auditId, customerCol, hasServiceDates, billingTerms, setBillingTerms }) {
  const [customers, setCustomers] = useState(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (hasServiceDates || !customerCol) { setCustomers(null); return; }
    setLoading(true);
    getRevenueCustomers(auditId, customerCol)
      .then((d) => setCustomers(d.customers))
      .catch(() => setCustomers([]))
      .finally(() => setLoading(false));
  }, [auditId, customerCol, hasServiceDates]);

  if (hasServiceDates) {
    return (
      <div className="mt-5 pt-5 border-t border-[#E5E7EB]">
        <div className="text-xs text-slate-700 mb-1">Billing terms</div>
        <p className="text-[11px] text-slate-500">
          Service start & end dates are mapped — MRR is spread across the exact service months, so per-customer billing terms aren't needed.
        </p>
      </div>
    );
  }

  const setTerm = (cust, term) => {
    const next = { ...billingTerms };
    if (term === "monthly") delete next[cust]; else next[cust] = term;
    setBillingTerms(next);
  };
  const applyAll = (term) => {
    if (!customers) return;
    const next = {};
    if (term !== "monthly") customers.forEach((c) => { next[c] = term; });
    setBillingTerms(next);
  };

  const filtered = (customers || []).filter((c) => c.toLowerCase().includes(query.toLowerCase()));
  const overrideCount = Object.keys(billingTerms).length;

  return (
    <div className="mt-5 pt-5 border-t border-[#E5E7EB]" data-testid="billing-terms-section">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
        <div className="text-xs text-slate-700">
          Billing terms <span className="text-slate-500">(no service dates — each invoice is spread over its term. Default: monthly = 1 month.)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-slate-500">apply to all:</span>
          {TERMS.map((t) => (
            <button key={t} data-testid={`billing-apply-all-${t}`} onClick={() => applyAll(t)}
              className="text-[10px] font-mono px-2 py-1 rounded bg-sky-50 border border-[#D1D5DB] text-slate-700 hover:bg-slate-100 capitalize">
              {t}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500 text-xs py-4"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading customers…</div>
      ) : !customerCol ? (
        <p className="text-[11px] text-amber-700">Map the customer ID column first to set billing terms.</p>
      ) : (customers && customers.length === 0) ? (
        <p className="text-[11px] text-slate-500">No customers found in the mapped column.</p>
      ) : (
        <>
          <div className="relative mb-2">
            <Search className="h-3.5 w-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search customers…"
              className="h-8 pl-8 bg-white border-[#E5E7EB] text-xs" data-testid="billing-search-input" />
          </div>
          <div className="text-[10px] font-mono text-slate-500 mb-2">
            {customers?.length} customers · {overrideCount} non-monthly override{overrideCount === 1 ? "" : "s"}
          </div>
          <div className="max-h-56 overflow-y-auto pr-1 space-y-1.5">
            {filtered.slice(0, 200).map((cust) => (
              <div key={cust} className="flex items-center justify-between gap-3" data-testid={`billing-row-${cust}`}>
                <span className="text-xs font-mono text-slate-700 truncate">{cust}</span>
                <Select value={billingTerms[cust] || "monthly"} onValueChange={(v) => setTerm(cust, v)}>
                  <SelectTrigger data-testid={`billing-term-${cust}`} className="h-7 w-32 bg-white border-[#E5E7EB] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-white border-[#E5E7EB] text-slate-900">
                    {TERMS.map((t) => <SelectItem key={t} value={t} className="capitalize">{t}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            ))}
            {filtered.length > 200 && <div className="text-[10px] text-slate-600 py-1">Showing first 200 — use search to narrow.</div>}
          </div>
        </>
      )}
    </div>
  );
}
