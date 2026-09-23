import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Loader2, ShieldAlert, CheckCircle2, ArrowRight } from "lucide-react";
import { Layout } from "@/components/Layout";
import { getAudit, getResults } from "@/lib/api";

export default function Diagnostics() {
  const { id } = useParams();
  const nav = useNavigate();
  const [audit, setAudit] = useState(null);
  const [data, setData] = useState(null);

  useEffect(() => {
    getAudit(id).then(setAudit).catch(() => {});
    getResults(id).then(setData).catch(() => setData(false));
  }, [id]);

  if (data === null) return <Layout audit={audit}><div className="flex justify-center py-32 text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /></div></Layout>;
  if (data === false) return <Layout audit={audit}><div className="py-24 text-center text-slate-400">Not computed yet.</div></Layout>;

  const r = data.results;
  const anomalies = [
    { label: "Months with negative MRR", items: r.anomalies.negative_mrr_months, note: "Refunds/credits pushed a month's total MRR below zero." },
    { label: "Customers with revenue gaps > 2 months that later resume", items: r.anomalies.revenue_gap_then_resume, note: "May indicate a churn-and-return or a billing gap." },
  ];

  return (
    <Layout audit={audit}>
      <div className="mb-6">
        <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight text-white">Forensic Diagnostics</h1>
        <p className="text-slate-400 text-sm mt-2 max-w-2xl">
          Why certain metrics are not computable, and exactly which field or file unlocks each. The engine never fabricates a number.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-7 bg-[#111726] border border-[#1E293B] rounded-lg p-5">
          <h3 className="font-heading font-semibold text-white text-sm mb-4">Missing Data</h3>
          {r.missing_data.length === 0 ? (
            <div className="flex items-center gap-2 text-emerald-400 text-sm py-6">
              <CheckCircle2 className="h-4 w-4" /> Every metric computed. No inputs missing.
            </div>
          ) : (
            <div className="space-y-3">
              {r.missing_data.map((m, i) => (
                <div key={i} data-testid={`missing-item-${i}`} className="border border-[#1E293B] rounded-md p-4 bg-[#0F172A]">
                  <div className="flex items-start gap-3">
                    <ShieldAlert className="h-4 w-4 text-amber-400 mt-0.5 shrink-0" />
                    <div>
                      <div className="text-slate-100 font-medium text-sm">{m.metric}</div>
                      <div className="text-xs text-slate-400 mt-1">{m.reason}</div>
                      <div className="text-[11px] text-sky-400 mt-2 flex items-center gap-1.5">
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
          <div className="bg-[#111726] border border-[#1E293B] rounded-lg p-5">
            <h3 className="font-heading font-semibold text-white text-sm mb-4">Anomaly Flags</h3>
            <div className="space-y-4">
              {anomalies.map((a) => (
                <div key={a.label}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-300">{a.label}</span>
                    <span className={`font-mono text-xs px-2 py-0.5 rounded ${a.items.length ? "bg-amber-500/15 text-amber-400" : "bg-slate-700/40 text-slate-500"}`}>{a.items.length}</span>
                  </div>
                  {a.items.length > 0 && <div className="text-[11px] font-mono text-slate-500 mt-1">{a.items.slice(0, 12).join(", ")}</div>}
                  <div className="text-[10px] text-slate-600 mt-1">{a.note}</div>
                </div>
              ))}
              <div className="border-t border-[#1E293B] pt-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-300">Revenue lines missing customer ID</span>
                  <span className="font-mono text-xs text-slate-100">{r.anomalies.revenue_missing_customer_id.count}</span>
                </div>
                <div className="flex items-center justify-between text-sm mt-2">
                  <span className="text-slate-300">Deals close-before-created (flagged & excluded)</span>
                  <span className="font-mono text-xs text-slate-100">{r.anomalies.deals_close_before_created.excluded_count}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
