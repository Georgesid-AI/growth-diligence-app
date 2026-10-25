import { fmtCurrency } from "@/lib/format";
import { MONTHS, DEFAULT_FISCAL_YEAR_END } from "@/lib/auditForm";
import { monthName, periodText } from "@/lib/periods";

export const CHANGE_LABEL = "Change";
export const DEFAULT_MARK = "default";

/** The settings the results stand on, one read-only line (docs/design/simplified-flow.md, The Audit page, item 2): each shows its
 *  stored value, a defaulted as-of month is marked. One Change link opens the settings on Upload & Mapping, where they are edited. */
export default function AssumptionsStrip({ audit, results, onChange }) {
  const ccy = audit?.reporting_currency ?? results?.reporting_currency;
  const asOf = audit?.as_of_month || results?.as_of_month;
  const items = [
    ["currency", "Currency", ccy || "—"],
    ["period", "Reporting period", periodText(audit?.datasets?.revenue?.months) || "—"],
    ["target-arr", "Target ARR", Number(audit?.target_arr) ? fmtCurrency(audit.target_arr, ccy) : "—"],
    ["target-date", "Target date", audit?.target_date || "—"],
    ["as-of", "As-of month", asOf ? `${monthName(asOf)}${audit?.as_of_month ? "" : ` (${DEFAULT_MARK})`}` : "—"],
    ["fy-end", "FY end", MONTHS[(Number(audit?.fiscal_year_end) || DEFAULT_FISCAL_YEAR_END) - 1]],
  ];
  return (
    <div data-testid="assumptions-strip" className="mb-6 flex flex-wrap items-baseline gap-x-5 gap-y-1 rounded-md border border-[#E5E7EB] bg-slate-50 px-4 py-2 text-xs">
      {items.map(([key, label, value]) => (
        <span key={key} className="text-slate-600" data-testid={`assumption-${key}`}>
          {label} <span className="font-mono text-slate-900">{value}</span>
        </span>
      ))}
      <button type="button" onClick={onChange} data-testid="assumptions-change" className="ml-auto text-sky-700 underline underline-offset-2">{CHANGE_LABEL}</button>
    </div>
  );
}
