import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, FileText, Loader2, Pencil, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getDecks, updateCandidate, uploadDeck } from "@/lib/api";
import {
  CLAIM_TYPES, CLAIM_UNITS, DECK_ACCEPT, DECK_SCOPE_CANNOT, DECK_SCOPE_INTRO, DECK_SCOPE_OUTRO, PLACEHOLDER,
  STATUS_LABELS, claimValue, sourceRef, statusCounts,
} from "@/lib/deckClaims";

const STATUS_STYLE = {
  pending: "text-slate-600 border-[#D1D5DB]",
  approved: "text-emerald-700 border-emerald-500/40",
  rejected: "text-rose-700 border-rose-500/40",
  edited: "text-sky-700 border-sky-500/40",
};
const selectClass = "h-8 rounded-md border border-[#E5E7EB] bg-white px-2 text-xs";

/** Board deck or growth plan: the scope message, the upload, and the candidate approval list. */
export default function DeckPanel({ auditId }) {
  const [data, setData] = useState({ decks: [], candidates: [] });
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(() => getDecks(auditId).then(setData).catch(() => toast.error("Could not load deck claims")), [auditId]);
  useEffect(() => { load(); }, [load]);

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const res = await uploadDeck(auditId, file);
      toast.success(`${res.file}: ${res.pages} ${res.page_unit}s read · ${res.candidates} candidate claims`);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const save = async (candidate, payload) => {
    try {
      const updated = await updateCandidate(auditId, candidate.id, payload);
      setData((d) => ({ ...d, candidates: d.candidates.map((c) => (c.id === updated.id ? updated : c)) }));
      return true;
    } catch (err) {
      toast.error(typeof err.response?.data?.detail === "string" ? err.response.data.detail : "Could not save");
      return false;
    }
  };

  const counts = statusCounts(data.candidates);

  return (
    <div className="bg-white border border-[#E5E7EB] rounded-lg p-5" data-testid="deck-panel">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="h-9 w-9 rounded-md flex items-center justify-center bg-sky-50 border border-[#E5E7EB]">
            <FileText className="h-4 w-4 text-slate-600" />
          </div>
          <div>
            <h3 className="font-heading font-semibold text-slate-900">Board deck or growth plan</h3>
            <div className="text-xs text-slate-600 mt-1 max-w-2xl space-y-1" data-testid="deck-scope-message">
              <p>{DECK_SCOPE_INTRO}</p>
              <p>We cannot read:</p>
              <ul className="list-disc pl-5">
                {DECK_SCOPE_CANNOT.map((line) => <li key={line}>{line}</li>)}
              </ul>
              <p>{DECK_SCOPE_OUTRO}</p>
            </div>
            {data.decks.map((d) => (
              <p key={d.deck_id} className="text-[11px] font-mono text-slate-600 mt-1">{d.file} · {d.pages} {d.page_unit}s</p>
            ))}
          </div>
        </div>
        <label className="cursor-pointer">
          <input type="file" accept={DECK_ACCEPT} className="hidden" onChange={onFile} data-testid="deck-upload-input" />
          <span className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md bg-sky-50 border border-[#D1D5DB] text-sm text-slate-800 hover:bg-slate-100 transition-colors">
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Upload deck
          </span>
        </label>
      </div>

      {error && <p className="mt-3 text-sm text-rose-700" role="alert" data-testid="deck-upload-error">{error}</p>}

      {data.candidates.length > 0 && (
        <div className="mt-5 pt-5 border-t border-[#E5E7EB]" data-testid="deck-candidates">
          <div className="text-xs text-slate-700 mb-3">
            Candidate claims <span className="text-slate-500 font-mono">· {counts.pending} to review · {counts.approved} approved ·
            {" "}{counts.edited} edited · {counts.rejected} rejected</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] font-mono uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB]">
                  <th className="py-2 pr-3">Type</th><th className="py-2 pr-3">Value</th><th className="py-2 pr-3">Date</th>
                  <th className="py-2 pr-3">From the deck</th><th className="py-2 pr-3">Source</th><th className="py-2 pr-3">Status</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {data.candidates.map((c) => <CandidateRow key={c.id} candidate={c} onSave={save} />)}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function CandidateRow({ candidate: c, onSave }) {
  const [draft, setDraft] = useState(null);
  const startEdit = () => setDraft({
    claim_type: c.claim_type, value: c.value ?? "", value_high: c.value_high ?? "", unit: c.unit ?? "", currency: c.currency ?? "", target_date: c.target_date ?? "",
  });
  const saveEdit = async () => {
    const payload = {
      claim_type: draft.claim_type,
      value: draft.value === "" ? null : Number(draft.value),
      value_high: draft.value_high === "" ? null : Number(draft.value_high),
      unit: draft.unit || null,
      currency: draft.currency.trim() ? draft.currency.trim().toUpperCase() : null,
      target_date: draft.target_date.trim() || null,
    };
    if (await onSave(c, payload)) setDraft(null);
  };
  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));

  return (
    <tr className="border-b border-[#F1F5F9] align-top" data-testid={`candidate-row-${c.id}`}>
      {draft ? (
        <>
          <td className="py-2 pr-3">
            <select value={draft.claim_type} onChange={set("claim_type")} className={selectClass} data-testid="edit-claim-type">
              {CLAIM_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </td>
          <td className="py-2 pr-3">
            <div className="flex gap-1">
              <Input value={draft.value} onChange={set("value")} type="number" className="h-8 w-28 text-xs font-mono" data-testid="edit-value" />
              <Input value={draft.value_high} onChange={set("value_high")} type="number" placeholder="to (range)" className="h-8 w-28 text-xs font-mono" data-testid="edit-value-high" />
              <select value={draft.unit} onChange={set("unit")} className={selectClass} data-testid="edit-unit">
                <option value="">no unit</option>
                {CLAIM_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
              <Input value={draft.currency} onChange={set("currency")} placeholder="EUR" className="h-8 w-16 text-xs font-mono uppercase" data-testid="edit-currency" />
            </div>
          </td>
          <td className="py-2 pr-3">
            <Input value={draft.target_date} onChange={set("target_date")} placeholder="2025-Q4" className="h-8 w-24 text-xs font-mono" data-testid="edit-target-date" />
          </td>
        </>
      ) : (
        <>
          <td className="py-2 pr-3 capitalize text-slate-800">{c.claim_type}</td>
          <td className="py-2 pr-3 font-mono text-slate-900 whitespace-nowrap">{claimValue(c)}</td>
          <td className="py-2 pr-3 font-mono text-slate-700 whitespace-nowrap">{c.target_date || PLACEHOLDER}</td>
        </>
      )}
      <td className="py-2 pr-3 text-slate-700 max-w-md">{c.snippet}</td>
      <td className="py-2 pr-3 font-mono text-[11px] text-slate-600" data-testid="candidate-source">
        {c.sources.map((s, i) => <div key={i}>{sourceRef(s)}</div>)}
      </td>
      <td className="py-2 pr-3">
        <span className={`text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap ${STATUS_STYLE[c.status] || ""}`}>
          {STATUS_LABELS[c.status] || c.status}
        </span>
      </td>
      <td className="py-2 whitespace-nowrap">
        {draft ? (
          <div className="flex gap-1">
            <Button size="sm" onClick={saveEdit} className="h-7 bg-sky-600 hover:bg-sky-500" data-testid="edit-save">Save</Button>
            <Button size="sm" variant="outline" onClick={() => setDraft(null)} className="h-7">Cancel</Button>
          </div>
        ) : (
          <div className="flex gap-1">
            <Button size="sm" variant="outline" title="Approve" onClick={() => onSave(c, { status: "approved" })} className="h-7 px-2" data-testid="candidate-approve">
              <Check className="h-3.5 w-3.5 text-emerald-700" />
            </Button>
            <Button size="sm" variant="outline" title="Reject" onClick={() => onSave(c, { status: "rejected" })} className="h-7 px-2" data-testid="candidate-reject">
              <X className="h-3.5 w-3.5 text-rose-700" />
            </Button>
            <Button size="sm" variant="outline" title="Edit" onClick={startEdit} className="h-7 px-2" data-testid="candidate-edit">
              <Pencil className="h-3.5 w-3.5 text-slate-700" />
            </Button>
          </div>
        )}
      </td>
    </tr>
  );
}
