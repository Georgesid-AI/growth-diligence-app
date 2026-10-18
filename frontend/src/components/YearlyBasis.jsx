import { Provenance } from "@/components/Provenance";
import { fmtCurrency, fmtMonths, fmtPct, PLACEHOLDER } from "@/lib/format";

/**
 * Yearly-basis metrics (docs/specs/chat-upload.md section 26.8, S30g): from the actual-tagged year columns of a P&L read as a
 * statement, when no monthly P&L is mapped. Every row carries its basis, "yearly basis, not monthly", and its citation; the metrics
 * that need monthly or per-customer data and were not computed are listed as Missing.
 */
export const S30G_TITLE = "Yearly basis (P&L summary)";
export const YEARS_HEADERS = ["Year", "Revenue", "New revenue", "S&M % of revenue", "Gross margin", "Change", "CAC payback", "Basis"];
export const TRACK_HEADERS = ["Year", "Line", "Forecast", "Actual", "Gap", "Gap %", "Basis"];
export const REPORTED_HEADERS = ["Period", "Reported", "Revenue file", "Gap %", "Basis"];

/** A margin's change from the year before, in points: 0.013 is "+1.3 pts". */
export const fmtPoints = (v) => (v == null ? PLACEHOLDER : `${v > 0 ? "+" : ""}${(Math.round(v * 1000) / 10).toFixed(1)} pts`);

export default function YearlyBasis({ block, ccy }) {
  if (!block) return null;
  const head = (cols) => (
    <thead>
      <tr className="text-[10px] font-mono uppercase tracking-wider text-slate-500 text-left">
        {cols.map((h) => <th key={h} className="py-1.5 pr-3">{h}</th>)}
      </tr>
    </thead>
  );
  const basis = (row) => <td className="py-1.5 pr-3 text-[10px] text-slate-500" data-testid="yearly-basis-label">{row.basis}</td>;
  return (
    <div data-testid="yearly-basis" className="bg-white border border-[#E5E7EB] rounded-lg p-5 space-y-5">
      <h3 className="font-heading font-semibold text-slate-900 text-sm">
        <Provenance source={block.source} id="yearly-basis">{S30G_TITLE}</Provenance>
        <span className="ml-2 text-[10px] font-mono text-slate-500">{block.basis}</span>
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="yearly-years">
          {head(YEARS_HEADERS)}
          <tbody className="font-mono text-slate-800">
            {block.years.map((y) => (
              <tr key={y.period} className="border-t border-[#E5E7EB]" data-testid={`yearly-year-${y.period}`}>
                <td className="py-1.5 pr-3"><Provenance source={y.source} id={`yearly-${y.period}`}>{y.period}</Provenance></td>
                <td className="py-1.5 pr-3">{fmtCurrency(y.revenue, ccy)}</td>
                <td className="py-1.5 pr-3">{fmtCurrency(y.new_revenue, ccy)}</td>
                <td className="py-1.5 pr-3">{fmtPct(y.sm_pct_revenue)}</td>
                <td className="py-1.5 pr-3">{fmtPct(y.gross_margin_pct)}</td>
                <td className="py-1.5 pr-3">{fmtPoints(y.gross_margin_change)}</td>
                <td className="py-1.5 pr-3" title={y.cac_payback_reason || ""}>
                  {y.cac_payback_months != null ? fmtMonths(y.cac_payback_months) : <span className="text-slate-600">n/c</span>}
                </td>
                {basis(y)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {block.track_record.length > 0 && (
        <div className="overflow-x-auto">
          <div className="text-xs font-medium text-slate-700 mb-1">Past forecasts</div>
          <table className="w-full text-sm" data-testid="yearly-track">
            {head(TRACK_HEADERS)}
            <tbody className="font-mono text-slate-800">
              {block.track_record.map((r) => (
                <tr key={`${r.period}-${r.line}-${r.tag}`} className="border-t border-[#E5E7EB]">
                  <td className="py-1.5 pr-3"><Provenance source={r.source} id={`track-${r.period}-${r.line}`}>{r.period}</Provenance></td>
                  <td className="py-1.5 pr-3">{r.line} <span className="text-[10px] text-slate-500">({r.tag})</span></td>
                  <td className="py-1.5 pr-3">{fmtCurrency(r.forecast, ccy)}</td>
                  <td className="py-1.5 pr-3">{fmtCurrency(r.actual, ccy)}</td>
                  <td className="py-1.5 pr-3">{fmtCurrency(r.gap, ccy)}</td>
                  <td className="py-1.5 pr-3">{fmtPct(r.gap_pct)}</td>
                  {basis(r)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {block.reported_vs_file.length > 0 && (
        <div className="overflow-x-auto">
          <div className="text-xs font-medium text-slate-700 mb-1">Reported vs revenue file</div>
          <table className="w-full text-sm" data-testid="yearly-reported">
            {head(REPORTED_HEADERS)}
            <tbody className="font-mono text-slate-800">
              {block.reported_vs_file.map((r) => (
                <tr key={r.period} className="border-t border-[#E5E7EB]">
                  <td className="py-1.5 pr-3"><Provenance source={r.source} id={`reported-${r.period}`}>{r.period}</Provenance></td>
                  <td className="py-1.5 pr-3">{fmtCurrency(r.reported, ccy)}</td>
                  <td className="py-1.5 pr-3">{fmtCurrency(r.revenue_file, ccy)}</td>
                  <td className="py-1.5 pr-3">{fmtPct(r.gap_pct)}</td>
                  {basis(r)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {block.missing.length > 0 && (
        <ul className="text-xs text-slate-600 space-y-1" data-testid="yearly-missing">
          {block.missing.map((m) => <li key={m.metric}>{m.metric} – {m.text}</li>)}
        </ul>
      )}
    </div>
  );
}
