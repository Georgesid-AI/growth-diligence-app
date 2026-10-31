import { formatCreated } from "@/lib/auditForm";
import { fmtNumber, fmtUsd } from "@/lib/format";

// The owner's "Cost per audit" list (docs/specs/usage-and-allowance.md section 9): the tester link label, when the audit was created
// (the viewer's local time), billed AI calls, then text tokens and cost, and image tokens and cost apart (docs/design/page-image.md section 6).
// No audit, company or file name: the server sends none.
const num = (n) => fmtNumber(n);
const usd = (n) => fmtUsd(n);

export default function OwnerAuditCosts({ costs }) {
  if (!costs) return null;
  return (
    <section data-testid="owner-audit-costs">
      <h2 className="font-heading text-lg font-semibold text-slate-900 mb-2">Cost per audit</h2>
      <p className="text-xs text-slate-500 mb-2">One row per stored audit, newest first. Times are in your local time.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="owner-audit-costs-table">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="py-1">Tester</th><th>Audit created</th><th>AI calls</th><th>Text tokens</th><th>Text cost</th><th>Image tokens</th><th>Image cost</th>
            </tr>
          </thead>
          <tbody>
            {costs.audits.map((a, i) => (
              <tr key={i} className="border-t border-[#E5E7EB]" data-testid="owner-audit-cost-row">
                <td className="py-1">{a.tester ?? "no tester"}</td>
                <td className="font-mono">{formatCreated(a.created_at)}</td>
                <td className="font-mono">{num(a.calls)}</td>
                <td className="font-mono">{num(a.tokens)}</td>
                <td className="font-mono">{usd(a.cost_usd)}</td>
                <td className="font-mono" data-testid="owner-audit-image-tokens">{num(a.image_tokens ?? 0)}</td>
                <td className="font-mono" data-testid="owner-audit-image-cost">{usd(a.image_cost_usd ?? 0)}</td>
              </tr>
            ))}
            {costs.audits.length === 0 && <tr><td colSpan={7} className="py-2 text-slate-500">No audit yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
