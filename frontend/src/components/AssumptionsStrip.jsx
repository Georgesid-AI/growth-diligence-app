import { fmtCurrency } from "@/lib/format";
import { MONTHS, DEFAULT_FISCAL_YEAR_END, asOfEvidenceLine } from "@/lib/auditForm";
import { monthName, periodText } from "@/lib/periods";

export const CHANGE_LABEL = "Change";
export const DEFAULT_MARK = "default";
export const NOT_DETERMINED = "not determined";

/** The first and last month of the supplied revenue data: the dataset's own months, else the revenue series the engine read. */
const revenuePeriod = (audit, results) => {
  const months = (results?.revenue_series?.months || []).filter(Boolean).slice().sort();
  return periodText(audit?.datasets?.revenue?.months) || (months.length ? periodText({ first: months[0], last: months[months.length - 1] }) : null);
};

/** The settings the results stand on, one read-only line (docs/design/simplified-flow.md, The Audit page, item 2): each shows its
 *  stored value, a defaulted as-of month is marked, a typed one reads "set by analyst", and with no confirmed month it reads "not determined".
 *  Under the line, the as-of month's evidence in the reader's words (read-check-review.md section 6). One Change link opens the settings
 *  on Upload & Mapping, where they are edited. */
export default function AssumptionsStrip({ audit, results, onChange }) {
  const ccy = audit?.reporting_currency ?? results?.reporting_currency;
  const asOf = audit?.as_of_month || results?.as_of_month;
  const evidence = asOfEvidenceLine(audit);
  const items = [
    ["currency", "Currency", ccy || "—"],
    ["period", "Reporting period", revenuePeriod(audit, results) || "—"],
    ["target-arr", "Target ARR", Number(audit?.target_arr) ? fmtCurrency(audit.target_arr, ccy) : "—"],
    ["target-date", "Target date", audit?.target_date || "—"],
    ["as-of", "As-of month", asOf ? `${monthName(asOf)}${audit?.as_of_month ? (audit.as_of_by === "analyst" ? " (set by analyst)" : "") : ` (${DEFAULT_MARK})`}` : NOT_DETERMINED],
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
      {evidence && <span data-testid="assumption-as-of-evidence" className="basis-full text-slate-500">{evidence}</span>}
    </div>
  );
}
