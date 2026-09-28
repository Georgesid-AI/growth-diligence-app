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
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { listAudits, createAudit, deleteAudit } from "@/lib/api";
import { money } from "@/lib/format";

export default function AuditHub() {
  const nav = useNavigate();
  const [audits, setAudits] = useState(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ company_name: "", reporting_currency: "EUR", target_arr: "", target_date: "", as_of_month: "" });

  const load = () => listAudits().then(setAudits);
  useEffect(() => { load(); }, []);

  const targetDateError = () => {
    if (!form.target_date) return null;
    const year = parseInt(form.target_date.slice(0, 4), 10);
    if (!Number.isFinite(year) || year < 2000 || year > 2100) {
      return "Target date year must be between 2000 and 2100";
    }
    if (form.as_of_month && form.target_date.slice(0, 7) <= form.as_of_month) {
      return "Target date must be after the as-of month";
    }
    return null;
  };

  const submit = async () => {
    if (!form.company_name.trim()) return toast.error("Company name is required");
    const dateError = targetDateError();
    if (dateError) return toast.error(dateError);
    setSaving(true);
    try {
      const a = await createAudit({
        company_name: form.company_name.trim(),
        reporting_currency: form.reporting_currency,
        target_arr: parseFloat(form.target_arr) || 0,
        target_date: form.target_date || null,
        as_of_month: form.as_of_month || null,
      });
      toast.success("Audit created");
      setOpen(false);
      setForm({ company_name: "", reporting_currency: "EUR", target_arr: "", target_date: "", as_of_month: "" });
      nav(`/audit/${a.id}/mapping`);
    } catch (e) {
      const detail = e.response?.data?.detail;
      const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
      toast.error(msg || "Failed to create audit");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id) => {
    await deleteAudit(id);
    toast.success("Audit deleted");
    load();
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
          <DialogContent className="bg-white border-[#E5E7EB] text-slate-900">
            <DialogHeader>
              <DialogTitle className="font-heading">Create Growth Audit</DialogTitle>
              <DialogDescription className="text-slate-600">
                Set the company, reporting currency and plan target. You'll add data next.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-2">
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
                    type="number"
                    value={form.target_arr}
                    onChange={(e) => setForm({ ...form, target_arr: e.target.value })}
                    placeholder="40000000"
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
                  type="month"
                  value={form.as_of_month}
                  onChange={(e) => setForm({ ...form, as_of_month: e.target.value })}
                  className="mt-1.5 bg-white border-[#E5E7EB] font-mono"
                />
              </div>
            </div>
            <DialogFooter>
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
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button
                      data-testid={`delete-audit-${a.id}`}
                      className="text-slate-600 hover:text-rose-700 transition-colors p-1"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent className="bg-white border-[#E5E7EB] text-slate-900">
                    <AlertDialogHeader>
                      <AlertDialogTitle>Delete this audit?</AlertDialogTitle>
                      <AlertDialogDescription className="text-slate-600">
                        This permanently removes the audit's files and computed results. This cannot be undone.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel className="bg-transparent border-[#E5E7EB] text-slate-700">Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        data-testid={`confirm-delete-${a.id}`}
                        onClick={() => remove(a.id)}
                        className="bg-rose-600 hover:bg-rose-500"
                      >
                        Delete
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>

              <div className="mt-4 pt-4 border-t border-[#E5E7EB] flex items-center justify-between">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500 font-mono">Target ARR</div>
                  <div className="text-lg font-mono font-semibold text-slate-900">{money(a.target_arr, a.reporting_currency)}</div>
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
    </Layout>
  );
}
