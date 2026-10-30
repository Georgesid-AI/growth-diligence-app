import { fmtNumber, fmtUsd } from "@/lib/format";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// The owner's Usage section (docs/specs/usage-and-allowance.md section 3): counts, tokens and USD per tester link label, this month
// and all time, and each link's monthly AI allowance. No company, file or audit name: the server sends none.
const usd = (n) => fmtUsd(n);
const num = (n) => fmtNumber(n);
const HEAD = ["Files uploaded", "AI calls", "Tokens", "Cost"];
const cells = (t) => [num(t.files), num(t.calls), num(t.tokens), usd(t.cost_usd)];

export default function OwnerUsage({ usage, busy, onSave }) {
  const [drafts, setDrafts] = useState({});
  if (!usage) return null;
  const draftOf = (r) => drafts[r.id] ?? String(r.allowance_usd);
  const valid = (v) => /^\d{1,4}(\.\d{1,2})?$/.test(v.trim()) && Number(v) <= 1000;
  return (
    <section data-testid="owner-usage">
      <h2 className="font-heading text-lg font-semibold text-slate-900 mb-2">Usage</h2>
      <p className="text-xs text-slate-500 mb-2">Counts, tokens and cost in USD by tester link. This month is {usage.month} (UTC).</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="owner-usage-table">
          <thead>
            <tr className="text-left text-slate-500">
              <th rowSpan={2} className="py-1 align-bottom">Tester link</th>
              <th colSpan={4} className="text-center border-l border-[#E5E7EB]">This month</th>
              <th colSpan={4} className="text-center border-l border-[#E5E7EB]">All time</th>
              <th rowSpan={2} className="align-bottom border-l border-[#E5E7EB] pl-2">Monthly AI allowance (USD)</th>
            </tr>
            <tr className="text-left text-slate-500 text-xs">
              {[0, 1].flatMap((g) => HEAD.map((h, i) => <th key={`${g}-${h}`} className={i === 0 ? "border-l border-[#E5E7EB] pl-2" : ""}>{h}</th>))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-[#E5E7EB] font-semibold" data-testid="owner-usage-totals">
              <td className="py-1">All testers</td>
              {[...cells(usage.totals.this_month), ...cells(usage.totals.all_time)].map((c, i) => <td key={i} className="font-mono">{c}</td>)}
              <td />
            </tr>
            {usage.testers.map((r) => (
              <tr key={r.id} className="border-t border-[#E5E7EB]" data-testid="owner-usage-row">
                <td className="py-1">{r.label}</td>
                {[...cells(r.this_month), ...cells(r.all_time)].map((c, i) => <td key={i} className="font-mono">{c}</td>)}
                <td className="pl-2 whitespace-nowrap">
                  <Input value={draftOf(r)} inputMode="decimal" onChange={(e) => setDrafts({ ...drafts, [r.id]: e.target.value })}
                    className="inline-block w-24 h-8" aria-label={`Allowance for ${r.label}`} data-testid="owner-allowance-input" />
                  <Button size="sm" variant="outline" className="ml-2" data-testid="owner-allowance-save"
                    disabled={busy || !valid(draftOf(r)) || Number(draftOf(r)) === r.allowance_usd}
                    onClick={() => onSave(r, Number(draftOf(r)))}>Save</Button>
                </td>
              </tr>
            ))}
            {usage.testers.length === 0 && <tr><td colSpan={10} className="py-2 text-slate-500">No tester link yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
