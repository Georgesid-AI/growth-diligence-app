import { useCallback, useState } from "react";
import { toast } from "sonner";
import { saveAllGatesCall } from "@/lib/api";
import { saveAllGates } from "@/lib/claimRegister";
import { describeRequestError } from "@/lib/requestError";

/** What the analyst has changed in the gate fields (only that), and the one "Save all gates" press, for the rows on screen. The
 *  register and the review screen share it. `afterSave(register, ids)` runs once the server has saved. */
export function useGateEdits({ auditId, rows, prefill, afterSave }) {
  const [edits, setEdits] = useState({});
  const onEdit = useCallback((row, change) => setEdits((all) => ({ ...all, [row.claim_id]: { ...all[row.claim_id], ...change } })), []);
  const clear = useCallback((ids) => setEdits((all) => Object.fromEntries(Object.entries(all).filter(([id]) => !ids.includes(id)))), []);
  const saveAll = () => {
    let plan;
    try { plan = saveAllGates(rows, prefill, edits); } catch (e) { toast.error(e.message); return Promise.resolve(); }
    if (!plan.gates.length) { toast.error("No gate is filled in yet. Pick a budget decision on each gate first."); return Promise.resolve(); }
    const ids = plan.gates.map((g) => g.claim_id);
    return saveAllGatesCall(auditId, plan.gates)
      .then((d) => { clear(ids); return afterSave(d, ids); })
      .then(() => { if (plan.incomplete) toast.message(`${plan.incomplete} gate(s) still need a budget decision or a field.`); })
      .catch((e) => toast.error(describeRequestError(e).message));
  };
  return { edits, onEdit, clear, saveAll };
}
