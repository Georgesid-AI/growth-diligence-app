import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash2, ArrowRight, Building2, Loader2 } from "lucide-react";
import { Layout } from "@/components/Layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { listAudits, createAudit, deleteAudit, getUsageTotals } from "@/lib/api";
import { S18_TITLE, S18_BODY, S18_MISMATCH, S19_USAGE_TOTALS } from "@/lib/chatUpload";
import { fmtCurrency } from "@/lib/format";
import { Checkbox } from "@/components/ui/checkbox";
import {
  targetDateError, plainNumber, groupThousands, MONTHS, DEFAULT_FISCAL_YEAR_END, CONSENT_EXPLAINER, CONSENT_LABEL,
  requiredFieldError,
} from "@/lib/auditForm";

export default function AuditHub() {
  const nav = useNavigate();
  const [audits, setAudits] = useState(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [explainerOpen, setExplainerOpen] = useState(false);
  const blank = { company_name: "", reporting_currency: "EUR", target_arr: "", target_date: "", as_of_month: "",
    fiscal_year_end: DEFAULT_FISCAL_YEAR_END, client_name: "", engagement_reference: "", structure_reading_consent: true };
  const [form, setForm] = useState(blank);

  const load = () => listAudits().then(setAudits);
  useEffect(() => { load(); }, []);

  const submit = async () => {
    const missing = requiredFieldError(form);
    if (missing) return toast.error(missing);
    const dateError = targetDateError(form.target_date, form.as_of_month);
    if (dateError) return toast.error(dateError);
    setSaving(true);
    try {
      const a = await createAudit({
        company_name: form.company_name.trim(),
        reporting_currency: form.reporting_currency,
        target_arr: parseFloat(form.target_arr) || 0,
        target_date: form.target_date || null,
        as_of_month: form.as_of_month || null,
        fiscal_year_end: form.fiscal_year_end,
        client_name: form.client_name.trim(),
        engagement_reference: form.engagement_reference.trim(),
        structure_reading_consent: form.structure_reading_consent,
      });
      toast.success("Audit created");
      setOpen(false);
      setForm(blank);
      nav(`/audit/${a.id}/mapping`);
    } catch (e) {
      const detail = e.response?.data?.detail;
      const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
      toast.error(msg || "Failed to create audit");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id, name) => {
    try {
      await deleteAudit(id, name);
      toast.success("Audit deleted");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <Layout>
      <div className="flex items-end justify-between mb-8 gap-4 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">Audit Hub</h1>
          <p className="text-slate-600 mt-2 text-sm max-w-2xl">
            Deterministic growth diligence. Every metric is computed in Python from your source rows —
            nothing is guessed, and every number traces back to its file, sheet and rows.
          </p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button data-testid="create-audit-button" className="bg-sky-600 hover:bg-sky-500 text-slate-900 rounded-md gap-2">
              <Plus className="h-4 w-4" /> New Audit
            </Button>
          </DialogTrigger>
          <DialogContent
            data-testid="audit-dialog"
            className="bg-white border-[#E5E7EB] text-slate-900 flex flex-col max-h-[100dvh] overflow-hidden"
          >
            <DialogHeader className="shrink-0">
              <DialogTitle className="font-heading">Create Growth Audit</DialogTitle>
              <DialogDescription className="text-slate-600">
                Set the company, reporting currency and plan target. You'll add data next.
              </DialogDescription>
            </DialogHeader>
            <div data-testid="audit-dialog-body" className="space-y-4 py-2 flex-1 min-h-0 overflow-y-auto">
              <div>
                <Label className="text-slate-700">Company name</Label>
                <Input
                  data-testid="audit-company-input"
                  value={form.company_name}
                  onChange={(e) => setForm({ ...form, company_name: e.target.value })}
                  placeholder="Acme SaaS Inc."
                  className="mt-1.5 bg-white border-[#E5E7EB]"
                />
              </div>
              <div>
                <Label className="text-slate-700">Client name <span className="text-slate-500 text-xs">(the investor commissioning the audit)</span></Label>
                <Input
                  data-testid="audit-client-input"
                  value={form.client_name}
                  onChange={(e) => setForm({ ...form, client_name: e.target.value })}
                  className="mt-1.5 bg-white border-[#E5E7EB]"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-slate-700">Reporting currency</Label>
                  <Select value={form.reporting_currency} onValueChange={(v) => setForm({ ...form, reporting_currency: v })}>
                    <SelectTrigger data-testid="reporting-currency-select" className="mt-1.5 bg-white border-[#E5E7EB]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-white border-[#E5E7EB] text-slate-900">
                      {["EUR", "USD", "GBP", "JPY"].map((c) => (
                        <SelectItem key={c} value={c}>{c}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-slate-700">Target ARR</Label>
                  <Input
                    data-testid="audit-target-arr-input"
                    type="text"
                    inputMode="decimal"
                    value={groupThousands(form.target_arr)}
                    onChange={(e) => setForm({ ...form, target_arr: plainNumber(e.target.value) })}
                    placeholder="40,000,000"
                    className="mt-1.5 bg-white border-[#E5E7EB] font-mono"
                  />
                </div>
              </div>
              <div>
                <Label className="text-slate-700">Target date</Label>
                <Input
                  data-testid="audit-target-date-input"
                  type="date"
                  min="2000-01-01"
                  max="2100-12-31"
                  value={form.target_date}
                  onChange={(e) => setForm({ ...form, target_date: e.target.value })}
                  className="mt-1.5 bg-white border-[#E5E7EB] font-mono"
                />
              </div>
              <div>
                <Label className="text-slate-700">As-of month <span className="text-slate-500 text-xs">(optional — defaults to last P&L month)</span></Label>
                <Input
                  data-testid="audit-asof-month-input"
                  type="date"
                  min="2000-01-01"
                  max="2100-12-31"
                  value={form.as_of_month}
                  onChange={(e) => setForm({ ...form, as_of_month: e.target.value })}
                  className="mt-1.5 bg-white border-[#E5E7EB] font-mono"
                />
              </div>
              <div>
                <Label className="text-slate-700">Fiscal year-end <span className="text-slate-500 text-xs">(FY25 is the fiscal year that ends in 2025)</span></Label>
                <Select value={String(form.fiscal_year_end)} onValueChange={(v) => setForm({ ...form, fiscal_year_end: Number(v) })}>
                  <SelectTrigger data-testid="audit-fiscal-year-end-select" className="mt-1.5 bg-white border-[#E5E7EB]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-white border-[#E5E7EB] text-slate-900">
                    {MONTHS.map((m, i) => <SelectItem key={m} value={String(i + 1)}>{m}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-slate-700">Engagement reference</Label>
                <Input
                  data-testid="audit-engagement-input"
                  value={form.engagement_reference}
                  onChange={(e) => setForm({ ...form, engagement_reference: e.target.value })}
                  className="mt-1.5 bg-white border-[#E5E7EB] font-mono"
                />
              </div>
              <div className="rounded-md border border-[#E5E7EB] bg-slate-50 p-3 space-y-2" data-testid="audit-consent">
                <label className="flex items-start gap-2 text-xs text-slate-800 cursor-pointer">
                  <Checkbox
                    data-testid="audit-consent-checkbox"
                    checked={form.structure_reading_consent}
                    onCheckedChange={(v) => setForm({ ...form, structure_reading_consent: v === true })}
                    className="mt-0.5"
                  />
                  <span>{CONSENT_LABEL}</span>
                </label>
                <button
                  type="button"
                  data-testid="audit-consent-toggle"
                  aria-expanded={explainerOpen}
                  onClick={() => setExplainerOpen((v) => !v)}
                  className="text-xs text-sky-700 underline underline-offset-2"
                >What is sent</button>
                {explainerOpen && (
                  <p data-testid="audit-consent-explainer" className="text-xs text-slate-600">{CONSENT_EXPLAINER}</p>
                )}
              </div>
            </div>
            <DialogFooter data-testid="audit-dialog-footer" className="shrink-0">
              <Button data-testid="submit-audit-button" onClick={submit} disabled={saving} className="bg-sky-600 hover:bg-sky-500 gap-2">
                {saving && <Loader2 className="h-4 w-4 animate-spin" />} Create & Add Data
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {audits === null ? (
        <div className="flex items-center justify-center py-24 text-slate-500">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : audits.length === 0 ? (
        <div className="border border-dashed border-[#E5E7EB] rounded-xl py-24 text-center">
          <Building2 className="h-10 w-10 text-slate-600 mx-auto mb-4" />
          <p className="text-slate-600">No audits yet. Create your first growth audit to begin.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {audits.map((a) => (
            <div
              key={a.id}
              data-testid={`audit-row-${a.id}`}
              className="group bg-white border border-[#E5E7EB] rounded-lg p-5 hover:border-sky-500/40 transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="font-heading font-semibold text-slate-900 truncate">{a.company_name}</h3>
                  <div className="flex items-center gap-2 mt-1.5">
                    <span className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded border ${
                      a.status === "computed"
                        ? "text-emerald-700 border-emerald-500/40 bg-emerald-500/10"
                        : "text-amber-700 border-amber-500/40 bg-amber-500/10"
                    }`}>
                      {a.status}
                    </span>
                    <span className="text-[10px] font-mono text-slate-500">{a.reporting_currency}</span>
                  </div>
                </div>
                <DeleteAudit audit={a} onDelete={remove} />
              </div>

              <div className="mt-4 pt-4 border-t border-[#E5E7EB] flex items-center justify-between">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500 font-mono">Target ARR</div>
                  <div className="text-lg font-mono font-semibold text-slate-900">{fmtCurrency(a.target_arr, a.reporting_currency)}</div>
                  {a.target_date && <div className="text-[10px] font-mono text-slate-500 mt-0.5">by {a.target_date}</div>}
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => nav(`/audit/${a.id}/mapping`)}
                    className="bg-transparent border-[#E5E7EB] text-slate-700 hover:bg-sky-50 hover:text-slate-900"
                  >
                    Data
                  </Button>
                  <Button
                    data-testid={`open-dashboard-${a.id}`}
                    size="sm"
                    onClick={() => nav(`/audit/${a.id}/dashboard`)}
                    className="bg-sky-600 hover:bg-sky-500 gap-1"
                  >
                    Open <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      <UsageTotals />
    </Layout>
  );
}

/** S18: Delete is enabled only when the typed text is the company name exactly, case included; the name goes in the body. */
export const nameMatches = (typed, company) => !!typed && typed === (company || "");

function DeleteAudit({ audit, onDelete }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const mismatch = typed !== "" && !nameMatches(typed, audit.company_name);
  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) setTyped(""); }}>
      <DialogTrigger asChild>
        <button data-testid={`delete-audit-${audit.id}`} className="text-slate-600 hover:text-rose-700 transition-colors p-1">
          <Trash2 className="h-4 w-4" />
        </button>
      </DialogTrigger>
      <DialogContent className="bg-white border-[#E5E7EB] text-slate-900">
        <DialogHeader>
          <DialogTitle data-testid="delete-dialog-title">{S18_TITLE(audit.company_name)}</DialogTitle>
          <DialogDescription data-testid="delete-dialog-text" className="text-slate-600">
            {S18_BODY[0]}<strong className="font-semibold text-slate-900" data-testid="delete-dialog-name">{audit.company_name}</strong>{S18_BODY[1]}
          </DialogDescription>
        </DialogHeader>
        <Input data-testid={`delete-name-${audit.id}`} value={typed} onChange={(e) => setTyped(e.target.value)}
          autoComplete="off" aria-invalid={mismatch} className="bg-white border-[#E5E7EB]" />
        {mismatch && <p role="alert" className="text-xs text-rose-700 -mt-2" data-testid="delete-mismatch">{S18_MISMATCH}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} className="bg-transparent border-[#E5E7EB] text-slate-700">Cancel</Button>
          <Button data-testid={`confirm-delete-${audit.id}`} disabled={!nameMatches(typed, audit.company_name)}
            onClick={() => { setOpen(false); onDelete(audit.id, typed); }} className="bg-rose-600 hover:bg-rose-500">Delete</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const pairs = (o) => Object.entries(o || {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "none";

/** S19: usage totals across audits, folded. Counts and codes only; no per-audit rows. */
function UsageTotals() {
  const [totals, setTotals] = useState(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (open && !totals) getUsageTotals().then(setTotals).catch(() => setTotals(false)); }, [open]); // eslint-disable-line
  return (
    <details data-testid="usage-totals" className="mt-10 border border-[#E5E7EB] rounded-lg bg-white" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="px-5 py-3 cursor-pointer text-sm font-medium text-slate-800">{S19_USAGE_TOTALS}</summary>
      {open && totals === false && <p className="px-5 pb-4 text-xs text-slate-500">Not available.</p>}
      {open && totals && (
        <dl className="px-5 pb-5 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2 text-xs text-slate-700">
          <Row label="Files uploaded" value={pairs(totals.files?.uploaded)} />
          <Row label="Files refused (by extension)" value={pairs(totals.files?.rejected)} />
          <Row label="Columns by rules, saved, AI, confirmed, corrected" value={["rules", "saved", "ai", "confirmed", "corrected"].map((k) => `${k} ${totals.columns?.[k] ?? 0}`).join(" · ")} />
          <Row label="Corrections by reason" value={pairs(totals.columns?.reasons)} />
          <Row label="Compute runs" value={String(totals.steps?.compute?.runs ?? 0)} />
          <Row label="Compute failures" value={pairs(totals.steps?.compute?.failures)} />
          <Row label="AI mapping calls by status" value={pairs(totals.steps?.mapping_ai)} />
          <Row label="Evidence labels" value={`${pairs(totals.evidence_labels)} · metrics missing ${totals.metrics_missing ?? 0}`} />
          <Row label="Analyst changes" value={String(totals.analyst_changes ?? 0)} />
          <Row label="Median days from first upload to export" value={totals.median_days_to_export == null ? "—" : String(totals.median_days_to_export)} />
          <Row label="Tokens and cost by step" value={Object.entries(totals.tokens_and_cost_by_step || {}).map(([k, v]) => `${k} ${v.input_tokens + v.output_tokens} tokens · $${v.cost_usd}`).join(" · ") || "none"} />
          <div className="md:col-span-2" data-testid="usage-notes">
            <dt className="text-slate-500">“Other” notes, newest first</dt>
            <dd><ul className="mt-1 space-y-0.5">{(totals.other_notes || []).map((n, i) => <li key={i}>{n.note}</li>)}</ul></dd>
          </div>
        </dl>
      )}
    </details>
  );
}

const Row = ({ label, value }) => (<div><dt className="text-slate-500">{label}</dt><dd className="font-mono">{value}</dd></div>);
