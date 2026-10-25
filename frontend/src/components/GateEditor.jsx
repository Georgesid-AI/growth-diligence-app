import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import DateField from "@/components/DateField";
import { GATE_BUDGET_MAX, GATE_DIRECTIONS, GATE_METRIC_MAX, GATE_METRIC_PLACEHOLDER, gateContext, gateDraft, gateEdit, needsMetricName } from "@/lib/claimRegister";

/** The edit of one gate (docs/design/simplified-flow.md, Verdict detail): the claimed and observed figures, then the threshold, the date and,
 *  where the claim has no metric of the app, the metric name and the direction. The fields start with the proposal the server wrote from the
 *  claim. The budget decision is optional. Nothing is stored until Save gate; the stored gate then reads "set by the analyst", and "Back to
 *  proposed" gives the proposal back. `onSave(row, edit)` is the PUT of the claim's inputs. */
export default function GateEditor({ row, ccy, onSave }) {
  const [edits, setEdits] = useState({});
  const draft = gateDraft(row, edits);
  const named = needsMetricName(row);
  const set = (k) => (e) => setEdits((all) => ({ ...all, [k]: e.target.value }));
  const done = () => setEdits({});
  const save = () => {
    let edit;
    try { edit = gateEdit(row, draft); } catch (e) { toast.error(e.message); return; }
    if (Object.keys(edit).length) onSave(row, edit).then(done).catch(() => {});
  };
  const reset = () => onSave(row, {
    gate_threshold: null, gate_date: null, gate_budget_decision: null, ...(named ? { gate_metric_name: null, gate_direction: null } : {}),
  }).then(done).catch(() => {});
  return (
    <div className="mt-1 flex flex-wrap items-start gap-x-3 gap-y-1 text-xs" data-testid="gate-editor">
      <div className="basis-full text-slate-600" data-testid="gate-context">{gateContext(row, ccy)}</div>
      {named && (
        <div className="flex gap-1 flex-wrap">
          <Input value={draft.metricName} onChange={set("metricName")} maxLength={GATE_METRIC_MAX} placeholder={GATE_METRIC_PLACEHOLDER} className="h-7 text-xs" data-testid="gate-metric-name" />
          <select value={draft.direction} onChange={set("direction")} className="h-7 rounded-md border border-[#E5E7EB] bg-white px-2 text-xs" data-testid="gate-direction">
            <option value="" />
            {GATE_DIRECTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      )}
      <div className="w-36"><Input value={draft.threshold} onChange={set("threshold")} placeholder="Threshold" inputMode="decimal" className="h-7 text-xs font-mono" data-testid="gate-threshold" /></div>
      <div className="w-40"><DateField testId="gate-date" value={draft.date} onChange={(v) => setEdits((all) => ({ ...all, date: v }))} placeholder="Gate date" className="!mt-0 h-7 text-xs" /></div>
      <div className="w-72"><Input value={draft.budget} onChange={set("budget")} maxLength={GATE_BUDGET_MAX} placeholder="Budget decision (optional, max 200 characters)" className="h-7 text-xs" data-testid="gate-budget" /></div>
      <Button size="sm" onClick={save} className="h-7 bg-sky-600 hover:bg-sky-500" data-testid="gate-save">Save gate</Button>
      {row.gate_saved && <Button size="sm" variant="outline" onClick={reset} className="h-7" data-testid="gate-reset">Back to proposed</Button>}
    </div>
  );
}
