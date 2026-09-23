import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Upload, CheckCircle2, Loader2, FileSpreadsheet, Plus, X, Play } from "lucide-react";
import { Layout } from "@/components/Layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getAudit, getFields, uploadDataset, saveMapping, computeAudit } from "@/lib/api";

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

  const load = useCallback(() => getAudit(id).then(setAudit), [id]);
  useEffect(() => { load(); getFields().then(setFields); }, [load]);

  const runCompute = async () => {
    setComputing(true);
    try {
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
          <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight text-white">Upload & Column Mapping</h1>
          <p className="text-slate-400 text-sm mt-2 max-w-2xl">
            Upload <span className="font-mono text-slate-300">.xlsx</span> or <span className="font-mono text-slate-300">.csv</span> files.
            Confirm every mapping — nothing is guessed. Required fields must be mapped; optional fields left blank move the
            dependent metric to the diagnostics panel.
          </p>
        </div>
        <Button data-testid="compute-button" onClick={runCompute} disabled={!hasRevenue || computing}
          className="bg-sky-600 hover:bg-sky-500 gap-2">
          {computing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Compute Metrics
        </Button>
      </div>

      <div className="space-y-5">
        {DTYPES.map((dt) => (
          <DatasetPanel key={dt.key} audit={audit} dtype={dt} fields={fields[dt.key]} onChange={load} />
        ))}
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
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (existing) { setColumns(existing.columns); setMapping(existing.mapping || {}); setFx(existing.fx || {}); }
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
      await saveMapping(audit.id, dtype.key, { mapping, fx, billing_terms: {} });
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
    <div className="bg-[#111726] border border-[#1E293B] rounded-lg p-5" data-testid={`dataset-panel-${dtype.key}`}>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className={`h-9 w-9 rounded-md flex items-center justify-center ${columns ? "bg-emerald-500/15 border border-emerald-500/40" : "bg-[#1D2840] border border-[#1E293B]"}`}>
            {columns ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <FileSpreadsheet className="h-4 w-4 text-slate-400" />}
          </div>
          <div>
            <h3 className="font-heading font-semibold text-white flex items-center gap-2">
              {dtype.label}
              {dtype.required && <span className="text-[9px] font-mono uppercase text-sky-400 border border-sky-500/40 rounded px-1.5 py-0.5">required</span>}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5 max-w-xl">{dtype.desc}</p>
            {existing && <p className="text-[11px] font-mono text-slate-400 mt-1">{existing.file} · {existing.row_count} rows</p>}
          </div>
        </div>
        <label className="cursor-pointer">
          <input type="file" accept=".xlsx,.csv,.xls" className="hidden" onChange={onFile} data-testid={`upload-dropzone-${dtype.key}`} />
          <span className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md bg-[#1D2840] border border-[#334155] text-sm text-slate-200 hover:bg-[#22304E] transition-colors">
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {columns ? "Replace file" : "Upload file"}
          </span>
        </label>
      </div>

      {columns && (
        <div className="mt-5 pt-5 border-t border-[#1E293B]">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[...fields.required, ...fields.optional].map((field) => {
              const isReq = fields.required.includes(field);
              return (
                <div key={field}>
                  <label className="text-xs text-slate-300 flex items-center gap-1.5 mb-1">
                    {field.replace(/_/g, " ")}
                    {isReq ? <span className="text-sky-400">*</span> : <span className="text-slate-600 text-[10px]">optional</span>}
                  </label>
                  <Select value={mapping[field] || NONE} onValueChange={(v) => setField(field, v)}>
                    <SelectTrigger data-testid={`map-column-${field}`} className={`bg-[#0B0F17] border-[#1E293B] h-9 ${isReq && !mapping[field] ? "border-amber-500/50" : ""}`}>
                      <SelectValue placeholder="— none —" />
                    </SelectTrigger>
                    <SelectContent className="bg-[#111726] border-[#1E293B] text-slate-100 max-h-64">
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

          <div className="flex items-center justify-between mt-4">
            <div className="text-xs font-mono">
              {requiredUnmapped.length > 0
                ? <span className="text-amber-400">{requiredUnmapped.length} required field(s) unmapped: {requiredUnmapped.join(", ")}</span>
                : <span className="text-emerald-400">All required fields mapped</span>}
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
    <div className="mt-5 pt-5 border-t border-[#1E293B]">
      <div className="text-xs text-slate-300 mb-2">
        FX rates to {baseCcy} <span className="text-slate-500">(add a rate for each non-{baseCcy} currency in your revenue lines)</span>
      </div>
      <div className="flex flex-wrap gap-2 mb-3">
        {Object.entries(fx).map(([k, v]) => (
          <span key={k} className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-[#1D2840] border border-[#334155] text-xs font-mono text-slate-200">
            1 {k} = {v} {baseCcy}
            <button onClick={() => remove(k)} className="text-slate-500 hover:text-rose-400"><X className="h-3 w-3" /></button>
          </span>
        ))}
        {Object.keys(fx).length === 0 && <span className="text-xs text-slate-600 font-mono">no FX rates — single-currency assumed</span>}
      </div>
      <div className="flex gap-2 items-center">
        <Input value={ccy} onChange={(e) => setCcy(e.target.value)} placeholder="USD" className="w-24 h-9 bg-[#0B0F17] border-[#1E293B] font-mono uppercase" data-testid="fx-ccy-input" />
        <span className="text-slate-500 text-sm">=</span>
        <Input value={rate} onChange={(e) => setRate(e.target.value)} placeholder="0.92" type="number" step="0.0001" className="w-28 h-9 bg-[#0B0F17] border-[#1E293B] font-mono" data-testid="fx-rate-input" />
        <span className="text-slate-500 text-sm">{baseCcy}</span>
        <Button size="sm" variant="outline" onClick={add} className="bg-transparent border-[#334155] text-slate-200 gap-1"><Plus className="h-3.5 w-3.5" /> Add</Button>
      </div>
    </div>
  );
}
