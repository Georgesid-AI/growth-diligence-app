import { Provenance } from "@/components/Provenance";
import { MetricCard } from "@/components/MetricCard";
import { fmtCount, fmtCurrency, fmtMonths, fmtPct } from "@/lib/format";

/**
 * The engine on the file map (docs/design/read-check-review.md section 16, PR 4b): what the report shows from `results.role_metrics`.
 * Every figure cites the cell or page it came from; a metric the map cannot give says in one line which row it needs, and the Data gaps table
 * carries the same line.
 */
export const NEEDS_MONTHLY_PNL = "needs a monthly P&L for quarterly payback";

/** A stored role source as the Provenance hover reads it. */
export function roleSource(src) {
  if (!src) return undefined;
  return { file: src.file, sheet: src.sheet, rows: (src.cells || []).join(", "), rule: src.rule };
}

export const metricsOf = (rm, name) => (rm?.metrics || []).filter((m) => m.metric === name);
const first = (rm, name) => metricsOf(rm, name)[0];

/** "+4.2%" for a signed fraction. */
export const signedPct = (v) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${fmtPct(v)}`);

function Missing({ text, testid }) {
  return <p className="text-xs text-slate-600" data-testid={testid}>{text}</p>;
}

/** The metrics the map could not give, one reason each: the lines the Data gaps table also carries. */
export function MissingMetrics({ rm }) {
  const rows = (rm?.metrics || []).filter((m) => m.status !== "computed" && m.metric !== "reconciliation");
  const seen = new Set();
  const unique = rows.filter((m) => (seen.has(m.metric) ? false : seen.add(m.metric)));
  if (!unique.length) return null;
  return (
    <section className="mb-6" data-testid="role-missing">
      <h2 className="font-heading text-lg font-semibold text-slate-900">Not computed from the files</h2>
      <ul className="mt-1 text-sm text-slate-700 list-disc pl-5">
        {unique.map((m) => <li key={m.metric} data-testid={`role-missing-${m.metric}`}><b>{m.name}</b>: <span data-testid={`role-missing-reason-${m.metric}`}>{m.reason}</span></li>)}
      </ul>
    </section>
  );
}

/** The cards that sit with Ending ARR: customer count, monthly churn and growth by year, each with its cell. */
export function RoleCards({ rm, ccy }) {
  if (!rm) return null;
  const customers = first(rm, "customers");
  const churn = first(rm, "monthly_churn");
  const years = rm.growth_by_year || [];
  const last = years[years.length - 1];
  return (
    <>
      <MetricCard id="customers" label="Customers" source={roleSource(customers?.source)}
        value={customers?.status === "computed" ? fmtCount(customers.value) : "n/c"}
        qualifier={customers?.period ? `(${customers.period})` : undefined}
        note={customers?.status === "computed" ? undefined : customers?.reason} caption="Customers at the latest actual month" />
      <MetricCard id="monthly_churn" label="Monthly churn" source={roleSource(churn?.source)}
        value={churn?.status === "computed" ? fmtPct(churn.value) : "n/c"}
        qualifier={churn?.period ? `(${churn.period})` : undefined}
        note={churn?.status === "computed" ? undefined : churn?.reason} caption="As the file states it" />
      <MetricCard id="growth_by_year" label="Growth by year" source={roleSource(last?.source)}
        value={last ? signedPct(last.growth) : "n/c"} qualifier={last ? `(${last.period} on the year before)` : undefined}
        sub={years.length > 1 ? years.slice(0, -1).map((y) => `${y.period} ${signedPct(y.growth)}`).join(" · ") : undefined}
        note={last ? undefined : first(rm, "growth")?.reason || "needs a revenue row with two full years"}
        caption="Revenue of the year against the year before" />
    </>
  );
}

/** Path to Plan: actual to the as-of month against the plan row to the same month. */
export function PlanToDate({ rm, ccy }) {
  const p = rm?.plan_to_date;
  const entry = first(rm, "plan_to_date");
  if (!p) return <Missing testid="plan-to-date-missing" text={entry?.reason || "needs a revenue row and a forecast row"} />;
  const over = p.variance >= 0;
  return (
    <div data-testid="plan-to-date">
      <div className="grid grid-cols-3 gap-3 mb-3">
        {[["Actual", p.actual], ["Plan", p.plan], ["Gap", p.variance]].map(([label, v]) => (
          <div key={label}>
            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-mono">{label}</div>
            <div className="font-mono text-slate-900 text-lg" data-testid={`plan-to-date-${label.toLowerCase()}`}>
              <Provenance source={roleSource(p.source)} id={`plan-${label}`}>{fmtCurrency(v, ccy)}</Provenance>
            </div>
          </div>
        ))}
      </div>
      <div className={`font-mono text-sm ${over ? "text-emerald-700" : "text-amber-700"}`} data-testid="plan-to-date-gap-pct">
        {signedPct(p.variance_pct)} against plan
      </div>
      <div className="text-[11px] text-slate-500 mt-1" data-testid="plan-to-date-note">{p.period}: {p.note}</div>
    </div>
  );
}

/** CAC payback by quarter: the quarterly table is Python's when a monthly P&L exists; with a yearly P&L only, the yearly table. */
export function YearlyPayback({ rm, yearly, ccy }) {
  const years = yearly?.years || [];
  const margin = first(rm, "gross_margin");
  const reason = first(rm, "yearly_cac_payback");
  const share = first(rm, "sm_share");
  return (
    <div data-testid="cac-yearly">
      <p className="text-xs text-slate-600 mb-2" data-testid="cac-needs-monthly">{NEEDS_MONTHLY_PNL}</p>
      {years.length === 0 ? <Missing testid="cac-yearly-missing" text={reason?.reason || "needs a revenue row, a cost_of_revenue row and a sales_marketing row"} /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="cac-yearly-table">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-wider text-slate-500 text-left">
                {["Year", "Revenue", "Gross margin", "S&M % of revenue", "CAC payback (yearly, revenue-based)"].map((h) => <th key={h} className="py-1.5 pr-3">{h}</th>)}
              </tr>
            </thead>
            <tbody className="font-mono text-slate-800">
              {years.map((y) => (
                <tr key={y.period} className="border-t border-[#E5E7EB]" data-testid={`cac-yearly-${y.period}`}>
                  <td className="py-1.5 pr-3">{y.period}</td>
                  <td className="py-1.5 pr-3"><Provenance source={y.source} id={`cac-yearly-rev-${y.period}`}>{fmtCurrency(y.revenue, ccy)}</Provenance></td>
                  <td className="py-1.5 pr-3">{fmtPct(y.gross_margin_pct)}</td>
                  <td className="py-1.5 pr-3">{fmtPct(y.sm_pct_revenue)}</td>
                  <td className="py-1.5 pr-3" title={y.cac_payback_reason || ""}>
                    {y.cac_payback_months != null ? fmtMonths(y.cac_payback_months) : <span className="text-slate-600">n/c</span>}
                    {y.cac_payback_months == null && y.cac_payback_reason && <div className="text-[10px] text-slate-500 font-sans">{y.period === years[years.length - 1].period && reason?.reason ? reason.reason : y.cac_payback_reason}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {[margin, share, reason].filter((m) => m?.detail).map((m) => <p key={m.metric} className="text-[11px] text-slate-500 mt-1" data-testid={`role-detail-${m.metric}`}>{m.name}: {m.detail}</p>)}
    </div>
  );
}

/** Revenue reconciliation: the same year in the file, the P&L and the deck, with the differences. */
export function ReconciliationTable({ rm, ccy }) {
  const years = (rm?.reconciliation || []).filter((r) => r.metric === "revenue" && r.basis === "yearly");
  if (!years.length) return null;
  return (
    <div className="mt-3" data-testid="reconciliation">
      <h3 className="mb-2 text-sm font-semibold text-slate-800">Revenue reconciliation by year</h3>
      <div className="overflow-x-auto rounded-md border border-[#E5E7EB] bg-white">
        <table className="w-full text-xs" data-testid="reconciliation-table">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB]">
              {["Year", "Sources", "Difference", "Difference %", "Result"].map((c) => <th key={c} className="py-2 px-3 font-medium whitespace-nowrap">{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {years.map((y) => (
              <tr key={y.period} className="border-b border-[#F1F5F9] align-top" data-testid={`reconciliation-${y.period}`}>
                <td className="py-2 px-3 font-mono">{y.period}</td>
                <td className="py-2 px-3">
                  {y.sources.map((s, i) => (
                    <div key={i} className="font-mono text-[11px]" data-testid="reconciliation-source">
                      {s.kind === "deck" ? "Deck" : "File"} {s.file} · {s.where} · {fmtCurrency(s.value, ccy)}
                    </div>
                  ))}
                </td>
                <td className="py-2 px-3 font-mono" data-testid="reconciliation-gap">{y.status === "not_compared" ? "—" : fmtCurrency(y.gap, ccy)}</td>
                <td className="py-2 px-3 font-mono">{y.gap_pct == null ? "—" : fmtPct(y.gap_pct)}</td>
                <td className="py-2 px-3">{y.status === "agrees" ? "Agrees" : y.status === "differs" ? "Differs" : y.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
