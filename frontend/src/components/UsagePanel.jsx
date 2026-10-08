import { useEffect, useState } from "react";
import { getLlmUsage } from "@/lib/api";
import { USAGE_COLUMNS, USAGE_HEADING, usageRows } from "@/lib/verdict";

/** AI usage and cost of this audit by step (docs/specs/verdict-and-memo.md section 8): the table Appendix D of the memo shows. */
export default function UsagePanel({ auditId, refresh }) {
  const [usage, setUsage] = useState(null);
  useEffect(() => {
    let cancelled = false;
    getLlmUsage(auditId).then((u) => { if (!cancelled) setUsage(u); }).catch(() => {});
    return () => { cancelled = true; };
  }, [auditId, refresh]);
  const rows = usageRows(usage);
  if (!rows.length) return null;
  return (
    <section className="mb-6" data-testid="usage-panel">
      <h2 className="font-heading text-lg font-semibold text-slate-900 mb-3">{USAGE_HEADING}</h2>
      <div className="overflow-x-auto rounded-md border border-[#E5E7EB] bg-white">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB]">
              {USAGE_COLUMNS.map((c, i) => <th key={c} className={`py-2 px-3 font-medium whitespace-nowrap ${i ? "text-right" : ""}`}>{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className={`border-b border-[#F1F5F9] ${r.key === "total" ? "font-semibold" : ""}`} data-testid="usage-row">
                <td className="py-2 px-3 text-slate-900">{r.step}</td>
                <td className="py-2 px-3 text-right font-mono">{r.calls}</td>
                <td className="py-2 px-3 text-right font-mono">{r.cacheHits}</td>
                <td className="py-2 px-3 text-right font-mono">{r.input.toLocaleString("en-US")}</td>
                <td className="py-2 px-3 text-right font-mono">{r.output.toLocaleString("en-US")}</td>
                <td className="py-2 px-3 text-right font-mono">{r.cost}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
