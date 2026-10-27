import { useEffect, useRef, useState } from "react";
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
import * as api from "@/lib/api";
import { listAudits, createAudit, deleteAudit } from "@/lib/api";
import { BLOCKERS_CHANGED } from "@/lib/useBlockers";
import { setCalculatePressed } from "@/lib/chatUpload";
import { RUN_LABEL, runFromList } from "@/lib/runAudit";
import { S18_TITLE, S18_BODY, S18_MISMATCH } from "@/lib/chatUpload";
import { fmtCurrency } from "@/lib/format";
import { describeRequestError } from "@/lib/requestError";
import { DEFAULT_FISCAL_YEAR_END, NEW_AUDIT_TITLE, NEW_AUDIT_PARAGRAPHS, NOT_SET, formatCreated, requiredFieldError } from "@/lib/auditForm";

export default function AuditHub() {
  const nav = useNavigate();
  const [audits, setAudits] = useState(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const blank = { company_name: "" };
  const [form, setForm] = useState(blank);

  const [loadError, setLoadError] = useState(null);   // why the list could not be read: shown instead of a spinner, with Retry
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = () => listAudits().then((list) => { if (alive.current) { setLoadError(null); setAudits(list); } })
    .catch((e) => { if (alive.current) setLoadError(describeRequestError(e).message); });
  const retry = () => { setLoadError(null); setAudits(null); load(); };
  useEffect(() => { load(); }, []); // eslint-disable-line

  const submit = async () => {
    const missing = requiredFieldError(form);
    if (missing) return toast.error(missing);
    setSaving(true);
    try {
      const a = await createAudit({
        company_name: form.company_name.trim(),
        // The set-up fields are filled in at the top of the next page (docs/specs/chat-upload.md section 2).
        reporting_currency: "EUR",
        target_arr: 0,
        target_date: null,
        as_of_month: null,
        fiscal_year_end: DEFAULT_FISCAL_YEAR_END,
        // New audits start with AI reading on (logged as the first consent entry); it is changed on the Upload page.
        structure_reading_consent: true,
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

  // Run audit on a tile runs the audit as the button on Upload & Mapping does and ends on the Audit page. Only an audit that cannot run, or whose run
  // stopped, opens Upload & Mapping, with one line saying why (George, 2026-10-27).
  const [running, setRunning] = useState(null);       // the id of the audit being run
  const run = async (audit) => {
    if (running) return;
    setRunning(audit.id);
    try {
      const out = await runFromList({ api, audit, onStart: () => setCalculatePressed(audit.id) });
      window.dispatchEvent(new Event(BLOCKERS_CHANGED));
      nav(out.to, out.line ? { state: { missing: out.line } } : undefined);
    } finally {
      if (alive.current) setRunning(null);
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
              <DialogTitle className="font-heading">{NEW_AUDIT_TITLE}</DialogTitle>
            </DialogHeader>
            <div data-testid="audit-dialog-body" className="space-y-4 py-2 flex-1 min-h-0 overflow-y-auto">
              <DialogDescription asChild>
                <div data-testid="audit-dialog-intro" className="text-slate-600 space-y-3 text-sm">
                  {NEW_AUDIT_PARAGRAPHS.map((p) => <p key={p}>{p}</p>)}
                </div>
              </DialogDescription>
              <div>
                <Label className="text-slate-700">Project or company name</Label>
                <Input
                  data-testid="audit-company-input"
                  value={form.company_name}
                  onChange={(e) => setForm({ ...form, company_name: e.target.value })}
                  placeholder="Acme SaaS Inc."
                  className="mt-1.5 bg-white border-[#E5E7EB]"
                />
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

      {loadError ? (
        <div className="py-24 text-center" data-testid="audits-load-error">
          <p className="text-sm text-slate-900">The audit list could not be loaded.</p>
          <p className="mt-1 text-sm text-rose-800 font-mono break-words">{loadError}</p>
          <Button size="sm" onClick={retry} data-testid="audits-load-retry" className="mt-4">Retry</Button>
        </div>
      ) : audits === null ? (
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

              <dl className="mt-4 pt-4 border-t border-[#E5E7EB] grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs" data-testid={`audit-facts-${a.id}`}>
                <dt className="uppercase tracking-wider text-slate-500 font-mono text-[10px] self-center">Target ARR</dt>
                <dd className="font-mono text-slate-900" data-testid="audit-target-arr">{Number(a.target_arr) ? fmtCurrency(a.target_arr, a.reporting_currency) : NOT_SET}</dd>
                <dt className="uppercase tracking-wider text-slate-500 font-mono text-[10px] self-center">Target date</dt>
                <dd className="font-mono text-slate-900" data-testid="audit-target-date">{a.target_date || NOT_SET}</dd>
                <dd className="col-span-2 h-3" aria-hidden="true" data-testid="audit-facts-gap" />
                <dt className="uppercase tracking-wider text-slate-500 font-mono text-[10px] self-center">Created</dt>
                <dd className="font-mono text-slate-900" data-testid="audit-created">{formatCreated(a.created_at)}</dd>
              </dl>
              <div className="mt-3 flex justify-end">
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    data-testid={`run-audit-${a.id}`}
                    disabled={running !== null}
                    onClick={() => run(a)}
                    className="bg-transparent border-[#E5E7EB] text-slate-700 hover:bg-sky-50 hover:text-slate-900 gap-1"
                  >
                    {running === a.id && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{RUN_LABEL}
                  </Button>
                  <Button
                    data-testid={`open-dashboard-${a.id}`}
                    size="sm"
                    onClick={() => nav(`/audit/${a.id}/mapping`)}
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
    </Layout>
  );
}

/** S18: Delete is enabled only when the typed text, trimmed, is the company name exactly, case included; the name goes in the body. */
export const nameMatches = (typed, company) => !!typed.trim() && typed.trim() === (company || "").trim();
export const MISMATCH_DELAY_MS = 1000;

function DeleteAudit({ audit, onDelete }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [settled, setSettled] = useState(false);       // S18b waits for a pause in typing, or for the box to lose focus
  useEffect(() => {
    setSettled(false);
    const timer = setTimeout(() => setSettled(true), MISMATCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [typed]);
  const mismatch = settled && typed.trim() !== "" && !nameMatches(typed, audit.company_name);
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
        <Input data-testid={`delete-name-${audit.id}`} value={typed} onChange={(e) => setTyped(e.target.value)} onBlur={() => setSettled(true)}
          autoComplete="off" aria-invalid={mismatch} className="bg-white border-[#E5E7EB]" />
        {mismatch && <p role="alert" className="text-xs text-rose-700 -mt-2" data-testid="delete-mismatch">{S18_MISMATCH}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} className="bg-transparent border-[#E5E7EB] text-slate-700">Cancel</Button>
          <Button data-testid={`confirm-delete-${audit.id}`} disabled={!nameMatches(typed, audit.company_name)}
            onClick={() => { setOpen(false); onDelete(audit.id, typed.trim()); }} className="bg-rose-600 hover:bg-rose-500">Delete</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
