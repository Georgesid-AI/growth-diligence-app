import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import DateField from "@/components/DateField";
import { getAudit, updateAudit } from "@/lib/api";
import { describeRequestError } from "@/lib/requestError";
import {
  DEFAULT_FISCAL_YEAR_END, MONTHS, REPORTING_CURRENCIES, SETUP_HELP, SETUP_LABELS, asOfInputValue, groupThousands, plainNumber, storedNumberInput,
  targetDateError,
} from "@/lib/auditForm";

const label = "text-[11px] font-mono uppercase tracking-wider text-slate-600 block";
const help = "mt-1 text-[11px] leading-snug text-slate-500";

/**
 * The audit's set-up fields at the top of the upload and mapping page: reporting currency, Target ARR, target date, as-of
 * month and fiscal year-end, each with one line of help. Each saves as it changes; a save that fails names the field and
 * the server's reason. The as-of month is held by the page (`asOf`, `setAsOf`), which also sends it when it computes.
 */
export default function AuditSetup({ audit, setAudit, asOf, setAsOf }) {
  const [arr, setArr] = useState(storedNumberInput(audit.target_arr));
  const [targetDate, setTargetDate] = useState(audit.target_date || "");
  useEffect(() => { setArr(storedNumberInput(audit.target_arr)); setTargetDate(audit.target_date || ""); }, [audit.target_arr, audit.target_date]);

  const save = async (field, patch, success) => {
    try {
      const saved = await updateAudit(audit.id, patch);
      setAudit((a) => ({ ...a, ...patch, ...(saved || {}) }));
      // Refetch so the header (and anything else the audit feeds) shows what the server holds, with no reload.
      try { setAudit(await getAudit(audit.id)); } catch { /* the merge above stands */ }
      if (success) toast.success(success);
      return true;
    } catch (e) {
      toast.error(`${SETUP_LABELS[field]} could not be saved: ${describeRequestError(e).message}`);
      return false;
    }
  };
  // The target must fall in a later month than the as-of month (the engine's rule): checked before anything is sent.
  const dates = async (field, nextTarget, nextAsOf) => {
    const refused = targetDateError(nextTarget, nextAsOf);
    if (refused) { toast.error(refused); return; }
    if (field === "target_date") {
      setTargetDate(nextTarget);
      if (nextTarget) await save(field, { target_date: nextTarget });
    } else {
      setAsOf(nextAsOf);
      await save(field, { as_of_month: nextAsOf || null });      // cleared: back to the default, the last P&L month
    }
  };
  const saveArr = () => {
    const next = parseFloat(arr) || 0;
    if (next !== Number(audit.target_arr || 0)) save("target_arr", { target_arr: next });
  };

  return (
    <section data-testid="audit-setup" className="bg-white border border-[#E5E7EB] rounded-lg p-5 mb-5">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-x-6 gap-y-4">
        <div>
          <label className={label}>{SETUP_LABELS.reporting_currency}</label>
          <Select value={audit.reporting_currency || "EUR"} onValueChange={(v) => save("reporting_currency", { reporting_currency: v })}>
            <SelectTrigger data-testid="setup-currency-select" className="mt-1 h-9 bg-white border-[#E5E7EB]"><SelectValue /></SelectTrigger>
            <SelectContent className="bg-white border-[#E5E7EB] text-slate-900">
              {REPORTING_CURRENCIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
            </SelectContent>
          </Select>
          <p className={help} data-testid="setup-help-reporting_currency">{SETUP_HELP.reporting_currency}</p>
        </div>
        <div>
          <label className={label}>{SETUP_LABELS.target_arr}</label>
          <Input data-testid="setup-target-arr-input" type="text" inputMode="decimal" value={groupThousands(arr)} placeholder="40,000,000"
            onChange={(e) => setArr(plainNumber(e.target.value))} onBlur={saveArr}
            onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} className="mt-1 h-9 bg-white border-[#E5E7EB] font-mono" />
          <p className={help} data-testid="setup-help-target_arr">{SETUP_HELP.target_arr}</p>
        </div>
        <div>
          <label className={label}>{SETUP_LABELS.target_date}</label>
          <DateField testId="setup-target-date-input" value={targetDate} onChange={(v) => dates("target_date", v, asOf)} clearable={false} className="!mt-1" />
          <p className={help} data-testid="setup-help-target_date">{SETUP_HELP.target_date}</p>
        </div>
        <div>
          <label className={label}>{SETUP_LABELS.as_of_month}</label>
          <DateField testId="asof-month-input" value={asOfInputValue(asOf)} onChange={(v) => dates("as_of_month", targetDate, v)} placeholder="last P&L month" className="!mt-1" />
          <p className={help} data-testid="setup-help-as_of_month">{SETUP_HELP.as_of_month}</p>
        </div>
        <div>
          <label className={label}>{SETUP_LABELS.fiscal_year_end}</label>
          <Select value={String(audit.fiscal_year_end || DEFAULT_FISCAL_YEAR_END)}
            onValueChange={(v) => save("fiscal_year_end", { fiscal_year_end: Number(v) }, "Fiscal year-end saved; claim periods re-mapped")}>
            <SelectTrigger data-testid="fiscal-year-end-select" className="mt-1 h-9 bg-white border-[#E5E7EB]"><SelectValue /></SelectTrigger>
            <SelectContent className="bg-white border-[#E5E7EB] text-slate-900">
              {MONTHS.map((m, i) => <SelectItem key={m} value={String(i + 1)}>{m}</SelectItem>)}
            </SelectContent>
          </Select>
          <p className={help} data-testid="setup-help-fiscal_year_end">{SETUP_HELP.fiscal_year_end}</p>
        </div>
      </div>
    </section>
  );
}
