import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getMemo, putIcInputs } from "@/lib/api";
import { describeRequestError } from "@/lib/requestError";
import {
  CONFIRM, MEMO_BUTTON, OTHER_GATES, PART_FIVE, PART_GAPS, PART_INPUTS, PART_KEY_GATES, PART_REASONS, PROPOSED, REPLACE, REVIEW_LABEL,
  THESIS_MAX, TOP5_HEADING, TOP5_STATEMENT, VERDICT_HEADING, RATING_OPTIONS, candidateText, initialPicks, refusalText, replacePick, samePicks,
} from "@/lib/verdict";

const selectClass = "h-8 rounded-md border border-[#E5E7EB] bg-white px-2 text-xs";
const LABEL_STYLE = {
  Verified: "text-emerald-800 border-emerald-500/50 bg-emerald-50",
  Contradicted: "text-rose-800 border-rose-500/50 bg-rose-50",
  Unverified: "text-amber-800 border-amber-500/50 bg-amber-50",
  Unsupported: "text-slate-700 border-slate-400/60 bg-slate-50",
};

/** The top 5: the proposed or confirmed five, a pick per row from the register, and Confirm (verdict-and-memo.md section 6.1). */
function TopFive({ verdict, candidates, onConfirm, busy }) {
  const stored = initialPicks(verdict);
  const [picks, setPicks] = useState(stored);
  const key = stored.join("|");
  useEffect(() => setPicks(key ? key.split("|") : []), [key]);
  const byId = Object.fromEntries(candidates.map((c) => [c.claim_id, c]));
  const confirmed = verdict.top5.confirmed;
  const changed = !confirmed || !samePicks(picks, stored);
  return (
    <div className="mb-4" data-testid="verdict-top5">
      <h3 className="text-sm font-semibold text-slate-900">{TOP5_HEADING}</h3>
      <p className="text-xs text-slate-600 mb-2" data-testid="verdict-top5-note">{confirmed ? TOP5_STATEMENT : PROPOSED}</p>
      <ul className="space-y-1.5">
        {picks.map((id, i) => (
          <li key={i} className="flex flex-wrap items-center gap-2 text-xs" data-testid="verdict-pick-row">
            <span className="text-slate-900 min-w-[16rem]">{byId[id] ? candidateText(byId[id]) : id}</span>
            <select value="" onChange={(e) => e.target.value && setPicks((p) => replacePick(p, i, e.target.value))} className={`${selectClass} max-w-[16rem]`}
              data-testid="verdict-pick-select" aria-label={REPLACE}>
              <option value="">{REPLACE}</option>
              {candidates.filter((c) => !picks.includes(c.claim_id)).map((c) => <option key={c.claim_id} value={c.claim_id}>{candidateText(c)}</option>)}
            </select>
          </li>
        ))}
      </ul>
      <Button size="sm" disabled={busy || !changed} onClick={() => onConfirm(picks)} className="mt-2 h-8 bg-sky-600 hover:bg-sky-500" data-testid="verdict-confirm">
        {CONFIRM}
      </Button>
    </div>
  );
}

function Inputs({ auditId, verdict, onChanged }) {
  const ic = verdict.ic_inputs || {};
  const [thesis, setThesis] = useState(ic.thesis || {});
  const stored = JSON.stringify(ic.thesis || {});
  useEffect(() => setThesis(JSON.parse(stored)), [stored]);
  const save = (body) => putIcInputs(auditId, body).then(() => onChanged && onChanged())
    .catch((e) => { toast.error(describeRequestError(e).message); if (onChanged) onChanged(); });
  const download = async () => {
    try {
      const r = await getMemo(auditId);
      const name = /filename="([^"]+)"/.exec(r.headers?.["content-disposition"] || "")?.[1] || "ic_memo.md";
      const url = URL.createObjectURL(new Blob([r.data], { type: "text/markdown" }));
      const a = document.createElement("a");
      a.href = url; a.download = name; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast.error(refusalText(e)); }
  };
  return (
    <div data-testid="verdict-inputs">
      <h3 className="text-sm font-semibold text-slate-900 mb-2">{PART_INPUTS}</h3>
      <div className="grid gap-3 md:grid-cols-2 text-xs">
        <label className="flex items-center gap-2 text-slate-700">
          {REVIEW_LABEL}
          <Input type="date" value={ic.first_quarterly_review ?? ""} className="h-8 text-xs font-mono w-40" data-testid="inputs-review-date"
            onChange={(e) => save({ first_quarterly_review: e.target.value || null })} />
        </label>
        {Object.entries(verdict.ratings_for || {}).map(([row, label]) => (
          <label key={row} className="flex items-center gap-2 text-slate-700">
            {label}
            <select value={ic.ratings?.[row] ?? ""} className={selectClass} data-testid={`inputs-rating-${row}`}
              onChange={(e) => save({ ratings: { [row]: e.target.value || null } })}>
              <option value="" />
              {RATING_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
        ))}
        {Object.entries(verdict.thesis_labels || {}).map(([part, label]) => (
          <label key={part} className="flex flex-col gap-1 text-slate-700 md:col-span-2">
            {label}
            <textarea value={thesis[part] ?? ""} maxLength={THESIS_MAX} rows={2} data-testid={`inputs-thesis-${part}`}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
              onChange={(e) => setThesis((t) => ({ ...t, [part]: e.target.value }))}
              onBlur={() => (thesis[part] ?? "") !== (ic.thesis?.[part] ?? "") && save({ thesis: { [part]: thesis[part] || null } })} />
          </label>
        ))}
      </div>
      <Button size="sm" variant="outline" onClick={download} className="mt-3 h-8" data-testid="verdict-memo">
        <Download className="h-3.5 w-3.5 mr-1.5" />{MEMO_BUTTON}
      </Button>
    </div>
  );
}

/** The Verdict section (docs/specs/verdict-and-memo.md section 6.4). `verdict` is GET /audits/{id}/verdict, read again by the
 *  parent after every change. */
export default function Verdict({ auditId, verdict, onChanged }) {
  const [busy, setBusy] = useState(false);
  if (!verdict) return null;
  const v = verdict.verdict;
  const confirm = (ids) => {
    setBusy(true);
    return putIcInputs(auditId, { top5: ids }).then(() => onChanged && onChanged())
      .catch((e) => toast.error(describeRequestError(e).message))
      .finally(() => setBusy(false));
  };
  const key = verdict.key_gates;
  return (
    <section className="mb-6 rounded-md border border-[#E5E7EB] bg-white p-4" data-testid="verdict">
      <h2 className="font-heading text-lg font-semibold text-slate-900 mb-3">{VERDICT_HEADING}</h2>
      {v.status !== "no_verdict" && <TopFive verdict={v} candidates={verdict.candidates || []} onConfirm={confirm} busy={busy} />}
      {v.message && <p className="text-sm text-slate-800 mb-3" data-testid="verdict-message">{v.message}</p>}
      {v.status === "ok" && (
        <div className="mb-4" data-testid="verdict-outcome">
          <p className="text-base font-semibold text-slate-900">{v.outcome}</p>
          <p className="text-sm text-slate-700" data-testid="verdict-rule">{v.rule}</p>
        </div>
      )}
      {v.five?.length > 0 && (
        <div className="mb-4" data-testid="verdict-five">
          <h3 className="text-sm font-semibold text-slate-900 mb-1">{PART_FIVE}</h3>
          <ul className="space-y-1 text-xs">
            {v.five.map((f) => (
              <li key={f.claim_id} data-testid="verdict-five-row">
                <span className="font-mono text-slate-700">#{f.rank}</span> {f.claim}{" "}
                <span className={`text-[10px] font-mono border rounded px-1.5 py-0.5 ${LABEL_STYLE[f.evidence_label] || ""}`}>{f.evidence_label}</span>
                <span className="text-slate-600"> · {f.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {v.status === "ok" && (
        <>
          <div className="mb-4" data-testid="verdict-reasons">
            <h3 className="text-sm font-semibold text-slate-900 mb-1">{PART_REASONS}</h3>
            <ol className="list-decimal pl-5 space-y-1 text-xs text-slate-800">{v.reasons.map((r) => <li key={r}>{r}</li>)}</ol>
          </div>
          <div className="mb-4" data-testid="verdict-key-gates">
            <h3 className="text-sm font-semibold text-slate-900 mb-1">{PART_KEY_GATES}</h3>
            {key.note && <p className="text-xs text-slate-600">{key.note}</p>}
            <ul className="space-y-1 text-xs text-slate-800">{key.sentences.map((s) => <li key={s.claim_id}>{s.sentence}</li>)}</ul>
          </div>
          <p className="text-xs text-slate-700 mb-4" data-testid="verdict-deal-terms">{verdict.deal_terms}</p>
          <div className="mb-4" data-testid="verdict-top-gaps">
            <h3 className="text-sm font-semibold text-slate-900 mb-1">{PART_GAPS}</h3>
            <ul className="space-y-1 text-xs text-slate-800">{verdict.top_gaps.map((g) => <li key={g.item}>{g.item} · {g.why}</li>)}</ul>
          </div>
          {verdict.gates_still_needed > 0 && <p className="text-xs text-slate-700 mb-4" data-testid="verdict-other-gates">{OTHER_GATES(verdict.gates_still_needed)}</p>}
        </>
      )}
      <Inputs auditId={auditId} verdict={verdict} onChanged={onChanged} />
    </section>
  );
}
