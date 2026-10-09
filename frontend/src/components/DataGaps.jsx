import { useState } from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { putIcInputs } from "@/lib/api";
import { describeRequestError } from "@/lib/requestError";
import { seeGlossary } from "@/lib/glossary";
import { GAPS_HEADING, GAP_COLUMNS, REVIEW_LABEL } from "@/lib/verdict";

/** What the company cannot measure (docs/specs/verdict-and-memo.md section 4): the gaps, why each matters, what is requested,
 *  and the date the analyst sets for each, on or before the first quarterly review. `verdict` is the server's answer. */
export default function DataGaps({ auditId, verdict, onChanged }) {
  const [busy, setBusy] = useState(false);
  if (!verdict) return null;
  const gaps = verdict.data_gaps || [];
  const review = verdict.ic_inputs?.first_quarterly_review ?? "";

  const save = (body) => {
    setBusy(true);
    return putIcInputs(auditId, body)
      .then(() => onChanged && onChanged())
      .catch((e) => { toast.error(describeRequestError(e).message); if (onChanged) onChanged(); })
      .finally(() => setBusy(false));
  };

  return (
    <section className="mb-6" data-testid="data-gaps">
      <div className="flex items-end justify-between flex-wrap gap-3 mb-3">
        <h2 className="font-heading text-lg font-semibold text-slate-900">{GAPS_HEADING}</h2>
        <label className="text-xs text-slate-600 flex items-center gap-2">
          {REVIEW_LABEL}
          <Input type="date" value={review} disabled={busy} className="h-8 text-xs font-mono w-40" data-testid="gaps-review-date"
            onChange={(e) => save({ first_quarterly_review: e.target.value || null })} />
        </label>
      </div>
      {gaps.length === 0 ? (
        <p className="text-sm text-slate-600" data-testid="data-gaps-none">None</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-[#E5E7EB] bg-white">
          <table className="w-full text-xs" data-testid="data-gaps-table">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB]">
                {GAP_COLUMNS.map((c) => <th key={c} className="py-2 px-3 font-medium whitespace-nowrap">{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {gaps.map((g) => (
                <tr key={g.item} className="border-b border-[#F1F5F9] align-top" data-testid="data-gap-row">
                  <td className="py-2 px-3 text-slate-900 min-w-[10rem]">{g.item}</td>
                  <td className="py-2 px-3 text-slate-700 min-w-[16rem]" data-testid="data-gap-why">{seeGlossary(g.why)}</td>
                  <td className="py-2 px-3 text-slate-700 min-w-[12rem]">{seeGlossary(g.requested)}</td>
                  <td className="py-2 px-3">
                    <Input type="date" value={g.target_date ?? ""} disabled={busy} className="h-7 text-xs font-mono w-36" data-testid="data-gap-date"
                      onChange={(e) => save({ gap_target_dates: { [g.item]: e.target.value || null } })} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
