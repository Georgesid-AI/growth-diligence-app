import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import DateField from "@/components/DateField";
import { getAudit, updateAudit } from "@/lib/api";
import { describeRequestError } from "@/lib/requestError";
import { s2Explainer, S3_EXPLAINER_NO_CONSENT } from "@/lib/chatUpload";
import {
  CONSENT_LABEL, VERIFIED_LINE, DEFAULT_FISCAL_YEAR_END, MONTHS, REPORTING_CURRENCIES, SETUP_HELP, SETUP_LABELS, AS_OF_PLACEHOLDER, asOfInputValue, asOfDisplay, asOfSourceText, parseMonthYear, asOfWarning, revenueLastMonth, groupThousands, plainNumber, storedNumberInput,
  targetDateError,
} from "@/lib/auditForm";

const label = "text-[11px] font-mono uppercase tracking-wider text-slate-600 block";
const help = "mt-1 text-[11px] leading-snug text-slate-500";
const link = "text-sky-700 underline underline-offset-2";

/** A monthly revenue series is mapped once the revenue file's months are known (the Path to plan card waits for it). */
export const hasMonthlySeries = (audit) => !!audit?.datasets?.revenue?.months?.last;

/** Saves one set-up field (PUT /audits/{id}); a save that fails names the field and the server's reason. */
function useSave(audit, setAudit) {
  return async (field, patch, success) => {
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
}

/**
 * The top of the Upload page (docs/specs/chat-upload.md section 23): the consent text, the AI reading tick under it, then the
 * mapping text (S2 with the deck sentence the server's PROVIDER_ZDR flag picks, or S3 when the tick is off).
 */
export function ConsentBlock({ audit, setAudit }) {
  const save = useSave(audit, setAudit);
  const consent = audit.structure_reading_consent === true;
  return (
    <section data-testid="consent-block" className="bg-white border border-[#E5E7EB] rounded-lg p-5 mb-5">
      <p className="text-xs text-slate-800" data-testid="setup-consent-label">{CONSENT_LABEL}</p>
      <p className="mt-2 text-xs text-slate-800" data-testid="setup-verified-line">{VERIFIED_LINE}</p>
      <label className="mt-3 flex items-center gap-2 text-xs text-slate-800">
        <input type="checkbox" data-testid="setup-consent-checkbox" checked={consent}
          onChange={(e) => save("structure_reading_consent", { structure_reading_consent: e.target.checked })} />
        <span data-testid="setup-consent-tick-label">{SETUP_LABELS.structure_reading_consent}</span>
      </label>
      <p data-testid="chat-explainer" className="mt-4 text-xs text-slate-600">
        {consent ? s2Explainer(audit.provider_zdr === true) : S3_EXPLAINER_NO_CONSENT}
      </p>
    </section>
  );
}

/**
 * The assumptions strip under the mapped files: reporting currency, as-of month and (not December, or changed) fiscal year-end, each read-only
 * with a Change link that opens its field. The as-of month is a typed month and year, detected from the files unless set; the page holds it
 * (`asOf`, `setAsOf`) and sends it when it computes.
 */
export function AssumptionsSetup({ audit, setAudit, asOf, setAsOf }) {
  const save = useSave(audit, setAudit);
  const [editing, setEditing] = useState(null);                  // "currency" | "as_of" | "fy" | null
  const [fyOpened, setFyOpened] = useState(false);               // fiscal year-end was opened in this session: it stays shown
  // The server holds the one as-of month (detected on Map or typed): the page follows it.
  useEffect(() => { setAsOf(asOfInputValue(audit.as_of_month)); }, [audit.as_of_month]);       // eslint-disable-line react-hooks/exhaustive-deps
  const [asOfText, setAsOfText] = useState(asOfDisplay(asOf));
  useEffect(() => { setAsOfText(asOfDisplay(asOf)); }, [asOf]);
  const fy = Number(audit.fiscal_year_end) || DEFAULT_FISCAL_YEAR_END;
  const showFy = fy !== DEFAULT_FISCAL_YEAR_END || fyOpened;

  const commitAsOf = async () => {
    const typed = asOfText.trim();
    const next = typed ? parseMonthYear(typed) : null;
    if (typed && !next) { toast.error("As-of month must be a month and year, e.g. Jun 2021"); setAsOfText(asOfDisplay(asOf)); return; }
    setEditing(null);
    if (next === (asOf ? parseMonthYear(asOfDisplay(asOf)) : null)) return;
    const refused = targetDateError(audit.target_date || "", next);
    if (refused) { toast.error(refused); return; }
    setAsOf(next);
    await save("as_of_month", { as_of_month: next || null });      // cleared: back to detection on Map
  };

  const item = (key, name, value, open, field) => (
    <span key={key} className="text-slate-600" data-testid={`setup-${key}`}>
      {name}: <span className="font-mono text-slate-900">{value}</span>{" "}
      <button type="button" className={link} data-testid={`setup-${key}-change`} onClick={() => setEditing(open ? null : key)}>Change</button>
      {open && <span className="block mt-1">{field}</span>}
    </span>
  );

  return (
    <section data-testid="audit-setup" className="mt-5 rounded-md border border-[#E5E7EB] bg-slate-50 px-4 py-3 text-xs">
      <div className="flex flex-wrap items-start gap-x-8 gap-y-2">
        {item("currency", SETUP_LABELS.reporting_currency, audit.reporting_currency || "EUR", editing === "currency",
          <>
            <Select value={audit.reporting_currency || "EUR"} onValueChange={async (v) => { if (await save("reporting_currency", { reporting_currency: v })) setEditing(null); }}>
              <SelectTrigger data-testid="setup-currency-select" className="h-8 w-28 bg-white border-[#E5E7EB]"><SelectValue /></SelectTrigger>
              <SelectContent className="bg-white border-[#E5E7EB] text-slate-900">
                {REPORTING_CURRENCIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
              </SelectContent>
            </Select>
            <p className={help} data-testid="setup-help-reporting_currency">{SETUP_HELP.reporting_currency}</p>
          </>)}
        {item("as_of", SETUP_LABELS.as_of_month,
          audit.as_of_month ? `${asOfDisplay(audit.as_of_month)} ${asOfSourceText(audit)}`.trim() : "not set", editing === "as_of",
          <>
            <Input data-testid="asof-month-input" type="text" value={asOfText} placeholder={AS_OF_PLACEHOLDER} autoFocus
              onChange={(e) => setAsOfText(e.target.value)} onBlur={commitAsOf}
              onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} className="h-8 w-40 bg-white border-[#E5E7EB] font-mono" />
            <p className={help} data-testid="setup-help-as_of_month">{SETUP_HELP.as_of_month}</p>
          </>)}
        {showFy && item("fy", SETUP_LABELS.fiscal_year_end, MONTHS[fy - 1], editing === "fy",
          <>
            <Select value={String(fy)} onValueChange={async (v) => { if (await save("fiscal_year_end", { fiscal_year_end: Number(v) }, "Fiscal year-end saved; claim periods re-mapped")) setEditing(null); }}>
              <SelectTrigger data-testid="fiscal-year-end-select" className="h-8 w-36 bg-white border-[#E5E7EB]"><SelectValue /></SelectTrigger>
              <SelectContent className="bg-white border-[#E5E7EB] text-slate-900">
                {MONTHS.map((m, i) => <SelectItem key={m} value={String(i + 1)}>{m}</SelectItem>)}
              </SelectContent>
            </Select>
            <p className={help} data-testid="setup-help-fiscal_year_end">{SETUP_HELP.fiscal_year_end}</p>
          </>)}
        {!showFy && (
          <button type="button" className={link} data-testid="setup-fy-open" onClick={() => { setFyOpened(true); setEditing("fy"); }}>Set fiscal year-end</button>
        )}
      </div>
      {asOfWarning(asOf, revenueLastMonth(audit)) && (
        <p className="mt-2 text-[11px] leading-snug text-amber-700" data-testid="setup-warning-as_of_month">{asOfWarning(asOf, revenueLastMonth(audit))}</p>
      )}
    </section>
  );
}

const CARD = "rounded-lg border border-[#E5E7EB] bg-slate-100 p-5";
export const PATH_TO_PLAN_TITLE = "Path to plan (needs more data)";
export const PATH_TO_PLAN_TEXT = "Calculates the growth rate the plan needs to reach the target. Needs a monthly revenue series (MRR or ARR) up to the as-of month. The expansion-adjusted version also needs revenue by customer and month.";
export const QUARTERLY_TITLE = "Quarterly review (parked)";
export const QUARTERLY_TEXT = "Used to date monitoring gates. Gates are parked; this date is stored and not shown elsewhere.";

/**
 * The two parked blocks at the bottom of the page: grey cards, a title, one sentence and fields. Path to plan takes its fields once a monthly
 * revenue series is mapped (stored values are kept); the quarterly review date is stored and never required.
 */
export function ParkedBlocks({ audit, setAudit, asOf }) {
  const save = useSave(audit, setAudit);
  const [arr, setArr] = useState(storedNumberInput(audit.target_arr));
  const [targetDate, setTargetDate] = useState(audit.target_date || "");
  useEffect(() => { setArr(storedNumberInput(audit.target_arr)); setTargetDate(audit.target_date || ""); }, [audit.target_arr, audit.target_date]);
  const active = hasMonthlySeries(audit);

  // The target must fall in a later month than the as-of month (the engine's rule): checked before anything is sent.
  const saveDate = async (next) => {
    const refused = targetDateError(next, asOf);
    if (refused) { toast.error(refused); return; }
    setTargetDate(next);
    if (next) await save("target_date", { target_date: next });
  };
  const saveArr = () => {
    const next = parseFloat(arr) || 0;
    if (next !== Number(audit.target_arr || 0)) save("target_arr", { target_arr: next });
  };
  return (
    <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-5" data-testid="parked-blocks">
      <section className={CARD} data-testid="parked-path-to-plan">
        <h3 className="text-sm font-semibold text-slate-800">{PATH_TO_PLAN_TITLE}</h3>
        <p className={help} data-testid="parked-path-to-plan-text">{PATH_TO_PLAN_TEXT}</p>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className={label}>{SETUP_LABELS.target_arr}</label>
            <Input data-testid="setup-target-arr-input" type="text" inputMode="decimal" disabled={!active} value={groupThousands(arr)} placeholder="40,000,000"
              onChange={(e) => setArr(plainNumber(e.target.value))} onBlur={saveArr}
              onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} className="mt-1 h-9 bg-white border-[#E5E7EB] font-mono disabled:bg-slate-100" />
          </div>
          <div>
            <label className={label}>{SETUP_LABELS.target_date}</label>
            <DateField testId="setup-target-date-input" value={targetDate} disabled={!active} onChange={saveDate} clearable={false} className="!mt-1" />
          </div>
        </div>
      </section>
      <section className={CARD} data-testid="parked-quarterly">
        <h3 className="text-sm font-semibold text-slate-800">{QUARTERLY_TITLE}</h3>
        <p className={help} data-testid="parked-quarterly-text">{QUARTERLY_TEXT}</p>
        <div className="mt-3">
          <label className={label}>{SETUP_LABELS.first_quarterly_review}</label>
          <DateField testId="setup-review-date-input" value={audit.ic_inputs?.first_quarterly_review || ""} disabled onChange={() => {}} className="!mt-1" />
        </div>
      </section>
    </div>
  );
}
