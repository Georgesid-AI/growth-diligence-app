import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, Plus, X, Play, Search } from "lucide-react";
import { Layout } from "@/components/Layout";
import DeckPanel from "@/components/DeckPanel";
import DateField from "@/components/DateField";
import UploadChat from "@/components/UploadChat";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getAudit, saveMapping, computeAudit, getRevenueCustomers, updateAudit, reportUsage, saveFx } from "@/lib/api";
import { asOfInputValue, MONTHS, DEFAULT_FISCAL_YEAR_END } from "@/lib/auditForm";

export default function MappingWizard() {
  const { id } = useParams();
  const nav = useNavigate();
  const [audit, setAudit] = useState(null);
  const [views, setViews] = useState([]);
  const [computing, setComputing] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [reading, setReading] = useState(false);        // Calculate is reading files: the header button waits
  const [attached, setAttached] = useState(0);        // files attached in the chat and not read yet
  const calculateRef = useRef(null);                  // UploadChat's Calculate: the header button runs the same path
  const [fxVersion, setFxVersion] = useState(0);      // bumped when a rate is saved: the deck panel reloads

  const load = useCallback(() => getAudit(id).then((a) => { setAudit(a); setAsOf(asOfInputValue(a.as_of_month)); }), [id]);
  useEffect(() => { load(); reportUsage(id, { screen: "mapping" }); }, [load, id]);

  // The fiscal year-end stays editable after creation; saving it re-runs period mapping on the server.
  const saveYearEnd = async (month) => {
    try {
      setAudit(await updateAudit(id, { fiscal_year_end: Number(month) }));
      toast.success("Fiscal year-end saved; claim periods re-mapped");
    } catch (e) {
      toast.error("Could not save the fiscal year-end");
    }
  };

  // Compute waits for the analyst: no AI or unsure row left, every required field of each file mapped (section 4.3).
  const hasRevenue = views.some((v) => v.dtype === "revenue");
  const ready = hasRevenue && views.every((v) => v.pending === 0 && v.missing_required.length === 0);
  // The header button is Calculate: it reads whatever is attached first, so a new file is never left "attached – not read yet"
  // while the old one is computed.
  const headerCompute = () => (calculateRef.current ? calculateRef.current() : runCompute());

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

  // Calculate (UploadChat has read the attached files): with no revenue file the page stops and the banner says why; with
  // a revenue file whose columns all have a decision, the metrics are computed.
  const onCalculate = async (loaded) => {
    if (!loaded.some((v) => v.dtype === "revenue")) return;
    if (!loaded.every((v) => v.pending === 0 && v.missing_required.length === 0)) {
      toast.error("Some columns still wait for your decision");
      return;
    }
    await runCompute();
  };

  if (!audit) {
    return <Layout audit={audit}><div className="flex justify-center py-32 text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /></div></Layout>;
  }

  return (
    <Layout audit={audit}>
      <div className="flex items-end justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">Upload & Column Mapping</h1>
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
            <div className="w-40">
              <DateField testId="asof-month-input" value={asOf} onChange={setAsOf} placeholder="last P&L month" />
            </div>
          </div>
          <Button data-testid="compute-button" onClick={headerCompute} disabled={(!ready && attached === 0) || computing || reading}
            className="bg-sky-600 hover:bg-sky-500 gap-2">
            {computing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Compute Metrics
          </Button>
        </div>
      </div>

      <div className="space-y-5">
        <UploadChat audit={audit} onViews={setViews} onCalculate={onCalculate} calculateRef={calculateRef} onStaged={setAttached} onCalculating={setReading}
          extras={(view) => <RevenueSettings key={`${view.file}-${view.uploaded_at}`} audit={audit} view={view} />} />
        <FxSettings audit={audit} onSaved={() => setFxVersion((n) => n + 1)} />
        <DeckPanel auditId={audit.id} reloadKey={fxVersion} />
      </div>
    </Layout>
  );
}

/** What follows a revenue file's mapping table, unchanged: FX rates and billing terms. They save as they change. */
function RevenueSettings({ audit, view }) {
  const [billingTerms, setBillingTerms] = useState(view.billing_terms || {});
  const first = useRef(true);
  const mapping = view.mapping || {};

  useEffect(() => {
    if (first.current) { first.current = false; return undefined; }
    const timer = setTimeout(() => {
      saveMapping(audit.id, "revenue", { billing_terms: billingTerms })   // never the mapping (a click decides it) and no rates (they are the audit's)
        .catch(() => toast.error("Save failed"));
    }, 600);
    return () => clearTimeout(timer);
  }, [billingTerms]); // eslint-disable-line

  return (
    <div data-testid="revenue-settings">
      <BillingTerms
        auditId={audit.id}
        customerCol={mapping.customer_id}
        hasServiceDates={!!mapping.service_start && !!mapping.service_end}
        billingTerms={billingTerms}
        setBillingTerms={setBillingTerms}
      />
    </div>
  );
}

/** The audit's FX rates: one set for the uploaded files and the deck claims, needing no file. Saved as they change. */
function FxSettings({ audit, onSaved }) {
  const [fx, setFx] = useState({ ...(audit.datasets?.revenue?.fx || {}), ...(audit.fx || {}) });
  const change = async (next) => {
    const before = fx;
    setFx(next);
    try { await saveFx(audit.id, next); onSaved?.(); } catch (e) { setFx(before); toast.error("Save failed"); }
  };
  return (
    <section id="fx-settings" data-testid="fx-settings" className="bg-white border border-[#E5E7EB] rounded-lg px-5 pb-5">
      <FxEditor fx={fx} setFx={change} baseCcy={audit.reporting_currency} />
    </section>
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
    <div className="pt-5">
      <div className="text-xs text-slate-700 mb-2">
        FX rates to {baseCcy} <span className="text-slate-500">(add a rate for each non-{baseCcy} currency in your revenue lines or in the deck claims)</span>
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
