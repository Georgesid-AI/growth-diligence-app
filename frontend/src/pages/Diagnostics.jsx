import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Loader2, ShieldAlert, CheckCircle2, ArrowRight } from "lucide-react";
import { Layout } from "@/components/Layout";
import { Provenance } from "@/components/Provenance";
import { getAudit, getResults, reportUsage } from "@/lib/api";
import { S22_RECONCILIATION } from "@/lib/chatUpload";
import { fmtCurrency } from "@/lib/format";
import { ANOMALIES_NOT_COMPUTED } from "@/lib/gapLists";

export default function Diagnostics() {
  const { id } = useParams();
  const nav = useNavigate();
  const [audit, setAudit] = useState(null);
  const [data, setData] = useState(null);

  useEffect(() => {
    reportUsage(id, { screen: "diagnostics" });
    getAudit(id).then(setAudit).catch(() => {});
    getResults(id).then(setData).catch(() => setData(false));
  }, [id]);

  if (data === null) return <Layout audit={audit}><div className="flex justify-center py-32 text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /></div></Layout>;
  if (data === false) return <Layout audit={audit}><div className="py-24 text-center text-slate-600">Not computed yet.</div></Layout>;

  const r = data.results;
  const anomalies = r.anomalies && [
    { label: "Months with negative MRR", items: r.anomalies.negative_mrr_months, note: "Refunds/credits pushed a month's total MRR below zero." },
    { label: "Customers with revenue gaps > 2 months that later resume", items: r.anomalies.revenue_gap_then_resume, note: "May indicate a churn-and-return or a billing gap." },
  ];

  return (
    <Layout audit={audit}>
      <div className="mb-6">
        <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">Forensic Diagnostics</h1>
        <p className="text-slate-600 text-sm mt-2 max-w-2xl">
          Why certain metrics are not computable, and exactly which field or file unlocks each. The engine never fabricates a number.
        </p>
      </div>

      <ReconciliationTable rec={r.revenue_reconciliation} currency={r.reporting_currency} />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-7 bg-white border border-[#E5E7EB] rounded-lg p-5">
          <h3 className="font-heading font-semibold text-slate-900 text-sm mb-4">Missing Data</h3>
          {r.missing_data.length === 0 ? (
            <div className="flex items-center gap-2 text-emerald-700 text-sm py-6">
              <CheckCircle2 className="h-4 w-4" /> Every metric computed. No inputs missing.
            </div>
          ) : (
            <div className="space-y-3">
              {r.missing_data.map((m, i) => (
                <div key={i} data-testid={`missing-item-${i}`} className="border border-[#E5E7EB] rounded-md p-4 bg-white">
                  <div className="flex items-start gap-3">
                    <ShieldAlert className="h-4 w-4 text-amber-700 mt-0.5 shrink-0" />
                    <div>
                      <div className="text-slate-900 font-medium text-sm">{m.metric}</div>
                      <div className="text-xs text-slate-600 mt-1">{m.reason}</div>
                      <div className="text-[11px] text-sky-700 mt-2 flex items-center gap-1.5">
                        <ArrowRight className="h-3 w-3" /> {m.unlocked_by}
                      </div>
                      {m.file && <div className="text-[10px] font-mono text-slate-600 mt-1">file: {m.file}</div>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="lg:col-span-5 space-y-6">
          <div className="bg-white border border-[#E5E7EB] rounded-lg p-5">
            <h3 className="font-heading font-semibold text-slate-900 text-sm mb-4">
              <Provenance source={r.anomalies?.source} id="diagnostics-anomalies">Anomaly Flags</Provenance>
            </h3>
            {!anomalies ? <div className="text-sm text-slate-600">{ANOMALIES_NOT_COMPUTED}</div> : (
            <div className="space-y-4">
              {anomalies.map((a) => (
                <div key={a.label}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-700">{a.label}</span>
                    <span className={`font-mono text-xs px-2 py-0.5 rounded ${a.items.length ? "bg-amber-500/15 text-amber-700" : "bg-slate-100 text-slate-500"}`}>{a.items.length}</span>
                  </div>
                  {a.items.length > 0 && <div className="text-[11px] font-mono text-slate-500 mt-1">{a.items.slice(0, 12).join(", ")}</div>}
                  <div className="text-[10px] text-slate-600 mt-1">{a.note}</div>
                </div>
              ))}
              <div className="border-t border-[#E5E7EB] pt-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-700">Revenue lines missing customer ID</span>
                  <span className="font-mono text-xs text-slate-900">{r.anomalies.revenue_missing_customer_id.count}</span>
                </div>
                <div className="flex items-center justify-between text-sm mt-2">
                  <span className="text-slate-700">Deals close-before-created (flagged & excluded)</span>
                  <span className="font-mono text-xs text-slate-900">{r.anomalies.deals_close_before_created.excluded_count}</span>
                </div>
              </div>
            </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}

/** S22: the revenue file against the P&L, month by month, the window total last. Hidden without a P&L. Never a blocker per month. */
export function ReconciliationTable({ rec, currency }) {
  if (!rec) return null;
  const money = (v) => (v == null ? "—" : fmtCurrency(v, currency));
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 10000) / 100}%`);   // gap_pct is a fraction (0.035 is 3.5%)
  return (
    <section data-testid="reconciliation" className="bg-white border border-[#E5E7EB] rounded-lg p-5 mb-6">
      <h3 className="font-heading font-semibold text-slate-900 text-sm mb-4">{S22_RECONCILIATION}</h3>
      {!rec.available ? <p className="text-xs text-slate-600">{rec.reason}</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-500 border-b border-[#E5E7EB]">
                {["Month", "Revenue file", "P&L", "Gap", "Gap %"].map((h) => <th key={h} className="py-1.5 pr-4 font-medium">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {rec.by_month.map((m) => (
                <tr key={m.month} data-testid="reconciliation-row" className="border-b border-[#F1F5F9]"
                  title={`${m.source.revenue_file.file} ${m.source.revenue_file.rows} · ${m.source.pnl.file} ${m.source.pnl.rows}`}>
                  <td className="py-1.5 pr-4 font-mono">{m.month}</td><td className="pr-4 font-mono">{money(m.revenue_file)}</td>
                  <td className="pr-4 font-mono">{money(m.pnl)}</td><td className="pr-4 font-mono">{money(m.gap)}</td><td className="font-mono">{pct(m.gap_pct)}</td>
                </tr>
              ))}
              <tr data-testid="reconciliation-total" className="font-semibold">
                <td className="py-1.5 pr-4">Window total</td><td className="pr-4 font-mono">{money(rec.file_total)}</td>
                <td className="pr-4 font-mono">{money(rec.pnl_total)}</td><td className="pr-4 font-mono">{money(rec.gap)}</td><td className="font-mono">{pct(rec.gap_pct)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
