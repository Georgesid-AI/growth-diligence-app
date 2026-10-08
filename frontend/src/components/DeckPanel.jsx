import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Check, FileText, Loader2, Pencil, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getDecks, removeDeck, updateCandidate, uploadDeck } from "@/lib/api";
import {
  ALL_DECKS, CLAIM_TYPES, CLAIM_UNITS, REMOVE_DECK_CONFIRM, claimsForDeck, deckTabs, defaultDeck, CLAIMS_CHOICES, CLAIMS_HEADING, CLAIMS_INTRO, COLUMNS, DECK_ACCEPT, DECK_SCOPE_CANNOT,
  DECK_SCOPE_INTRO, DECK_SCOPE_OUTRO, INCONSISTENCY_LABEL, OTHER_TYPE_NOTE, PLACEHOLDER, STATUS_LABELS, VERIFIED_LABEL, claimDate, claimValue, deckRunLog,
  confidenceText, needsType, readingChoices, rowEdit, sourceRef, statusCounts, typeLabel,
} from "@/lib/deckClaims";

const STATUS_STYLE = {
  pending: "text-slate-600 border-[#D1D5DB]",
  approved: "text-emerald-700 border-emerald-500/40",
  rejected: "text-rose-700 border-rose-500/40",
  edited: "text-sky-700 border-sky-500/40",
};
const CONFIDENCE_STYLE = { High: "text-emerald-700", Medium: "text-amber-800", Low: "text-rose-700" };
const selectClass = "h-8 rounded-md border border-[#E5E7EB] bg-white px-2 text-xs";

/** Board deck or growth plan: the scope message, the upload, and the candidate approval list. */
export default function DeckPanel({ auditId }) {
  const [data, setData] = useState({ decks: [], candidates: [] });
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState(null);            // deck id or ALL_DECKS; null until the first load
  const [confirming, setConfirming] = useState(null);

  // After a load, keep the chosen tab if its deck still exists; otherwise show the most recent deck.
  const load = useCallback((select) => getDecks(auditId).then((d) => {
    setData(d);
    setTab((current) => {
      const wanted = select || current;
      return wanted && (wanted === ALL_DECKS || d.decks.some((x) => x.deck_id === wanted)) ? wanted : defaultDeck(d.decks);
    });
  }).catch(() => toast.error("Could not load deck claims")), [auditId]);
  useEffect(() => { load(); }, [load]);

  // A deck's structures are read after its upload returns: check back while one is still being read.
  const polls = useRef(0);
  useEffect(() => {
    if (!data.decks.some((d) => d.ai_status === "reading") || polls.current >= 24) return undefined;
    const timer = setTimeout(() => { polls.current += 1; load(); }, 5000);
    return () => clearTimeout(timer);
  }, [data, load]);

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const res = await uploadDeck(auditId, file);
      toast.success(`${res.file}: ${res.pages} ${res.page_unit}s read · ${res.candidates} candidate claims`);
      await load(res.deck_id);
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

  const remove = async (deckId) => {
    try {
      await removeDeck(auditId, deckId);
      setConfirming(null);
      toast.success("Deck removed");
      await load(defaultDeck(data.decks.filter((d) => d.deck_id !== deckId)));
    } catch (err) {
      toast.error("Could not remove the deck");
    }
  };

  const shown = claimsForDeck(data.candidates, tab);
  const counts = statusCounts(shown);
  const selectedDeck = data.decks.find((d) => d.deck_id === tab);

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

      {data.decks.length > 0 && (
        <div className="mt-5 pt-5 border-t border-[#E5E7EB]" data-testid="deck-candidates">
          <div className="text-xs text-slate-700 mb-3 max-w-3xl space-y-1" data-testid="claims-instructions">
            <h4 className="font-heading font-semibold text-sm text-slate-900">{CLAIMS_HEADING}</h4>
            <p>{CLAIMS_INTRO}</p>
            {CLAIMS_CHOICES.map(([choice, text]) => (
              <p key={choice}><span className="font-semibold">{choice}</span> {text}</p>
            ))}
          </div>
          <div className="flex flex-wrap gap-1 border-b border-[#E5E7EB] mb-3" role="tablist" data-testid="deck-tabs">
            {deckTabs(data.decks, data.candidates).map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => { setTab(t.id); setConfirming(null); }}
                className={`px-3 py-1.5 text-xs -mb-px border-b-2 ${tab === t.id ? "border-sky-600 text-slate-900 font-semibold" : "border-transparent text-slate-500 hover:text-slate-800"}`}
                data-testid={`deck-tab-${t.id}`}>
                {t.label} <span className="font-mono text-slate-400">({t.count})</span>
              </button>
            ))}
          </div>
          {selectedDeck && (
            <div className="flex items-center gap-3 flex-wrap text-[11px] mb-2" data-testid="deck-actions">
              <span className="font-mono text-slate-600">{selectedDeck.file} · {selectedDeck.pages} {selectedDeck.page_unit}s</span>
              {confirming === selectedDeck.deck_id ? (
                <span className="flex items-center gap-2" data-testid="remove-deck-confirm">
                  <span className="text-rose-700">{REMOVE_DECK_CONFIRM}</span>
                  <Button size="sm" onClick={() => remove(selectedDeck.deck_id)} className="h-7 bg-rose-600 hover:bg-rose-500" data-testid="remove-deck-yes">Remove</Button>
                  <Button size="sm" variant="outline" onClick={() => setConfirming(null)} className="h-7">Cancel</Button>
                </span>
              ) : (
                <Button size="sm" variant="outline" onClick={() => setConfirming(selectedDeck.deck_id)} className="h-7" data-testid="remove-deck">Remove deck</Button>
              )}
            </div>
          )}
          {selectedDeck && deckRunLog(selectedDeck).length > 0 && (
            <div className="text-[11px] font-mono text-slate-600 mb-2 space-y-0.5" data-testid="deck-run-log">
              {deckRunLog(selectedDeck).map((line) => <div key={line}>{line}</div>)}
            </div>
          )}
          <div className="text-[11px] text-slate-500 font-mono mb-2">
            {counts.pending} to review · {counts.approved} approved · {counts.edited} edited · {counts.rejected} rejected
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] font-mono uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB]">
                  {COLUMNS.map((name) => <th key={name} className="py-2 pr-3">{name}</th>)}
                </tr>
              </thead>
              <tbody>
                {shown.map((c) => <CandidateRow key={c.id} candidate={c} onSave={save} />)}
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
  const isRow = Boolean(c.by_period?.length);      // a table row: its values by period
  const choices = readingChoices(c);               // a figure that reads two ways: the default is pre-selected
  // Edit, optionally starting from the other reading of an ambiguous figure.
  const startEdit = (value) => setDraft({
    claim_type: c.claim_type, value: value ?? c.value ?? "", value_high: c.value_high ?? "", unit: c.unit ?? "", currency: c.currency ?? "", target_date: c.target_date ?? "",
    values: (c.by_period || []).map((i) => i.value ?? ""),
  });
  const saveEdit = async () => {
    const common = {
      claim_type: draft.claim_type,
      unit: draft.unit || null,
      currency: draft.currency.trim() ? draft.currency.trim().toUpperCase() : null,
    };
    const payload = isRow ? { ...common, by_period: rowEdit(c, draft.values) } : {
      ...common,
      value: draft.value === "" ? null : Number(draft.value),
      value_high: draft.value_high === "" ? null : Number(draft.value_high),
      target_date: draft.target_date.trim() || null,
    };
    if (await onSave(c, payload)) setDraft(null);
  };
  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  const setValue = (k) => (e) => setDraft((d) => ({ ...d, values: d.values.map((v, i) => (i === k ? e.target.value : v)) }));

  return (
    <tr className="border-b border-[#F1F5F9] align-top" data-testid={`candidate-row-${c.id}`}>
      {draft ? (
        <>
          <td className="py-2 pr-3">
            <select value={draft.claim_type} onChange={set("claim_type")} className={selectClass} data-testid="edit-claim-type">
              {needsType(draft) && <option value={draft.claim_type} disabled>{typeLabel(draft.claim_type)}{draft.claim_type === "unknown" ? "" : ": choose a type"}</option>}
              {CLAIM_TYPES.map((t) => <option key={t} value={t}>{typeLabel(t)}</option>)}
            </select>
          </td>
          <td className="py-2 pr-3">
            <div className="flex gap-1 flex-wrap">
              {isRow ? c.by_period.map((i, k) => (
                <label key={k} className="flex flex-col text-[10px] font-mono text-slate-500">
                  {i.period || i.target_date || PLACEHOLDER}
                  <Input value={draft.values[k]} onChange={setValue(k)} type="number" className="h-8 w-24 text-xs font-mono" data-testid={`edit-period-value-${k}`} />
                </label>
              )) : (
                <>
                  <Input value={draft.value} onChange={set("value")} type="number" className="h-8 w-28 text-xs font-mono" data-testid="edit-value" />
                  <Input value={draft.value_high} onChange={set("value_high")} type="number" placeholder="to (range)" className="h-8 w-28 text-xs font-mono" data-testid="edit-value-high" />
                </>
              )}
              <Input value={draft.unit} onChange={set("unit")} list="claim-units" placeholder="unit" className="h-8 w-28 text-xs font-mono" data-testid="edit-unit" />
              <datalist id="claim-units">{CLAIM_UNITS.map((u) => <option key={u} value={u} />)}</datalist>
              <Input value={draft.currency} onChange={set("currency")} placeholder="EUR" className="h-8 w-16 text-xs font-mono uppercase" data-testid="edit-currency" />
            </div>
          </td>
          <td className="py-2 pr-3">
            {isRow ? <span className="font-mono text-slate-700 whitespace-nowrap">{claimDate(c)}</span> : (
              <Input value={draft.target_date} onChange={set("target_date")} placeholder="2025-Q4" className="h-8 w-24 text-xs font-mono" data-testid="edit-target-date" />
            )}
          </td>
        </>
      ) : (
        <>
          <td className="py-2 pr-3 text-slate-800 whitespace-nowrap">
            {typeLabel(c.claim_type)}
            {needsType(c) && <div className="text-[10px] text-amber-800 mt-0.5" data-testid="candidate-needs-type">{OTHER_TYPE_NOTE}</div>}
          </td>
          <td className={`py-2 pr-3 font-mono text-slate-900 ${isRow ? "" : "whitespace-nowrap"}`}>
            {choices.length ? (
              <select value={0} onChange={(e) => Number(e.target.value) && startEdit(choices[Number(e.target.value)].value)}
                className={selectClass} title="This figure reads two ways. Approve the first reading, or choose the other to edit the claim."
                data-testid="candidate-readings">
                {choices.map((r, i) => <option key={i} value={i}>{r.label}</option>)}
              </select>
            ) : claimValue(c)}
          </td>
          <td className="py-2 pr-3 font-mono text-slate-700 whitespace-nowrap">{claimDate(c)}</td>
        </>
      )}
      <td className="py-2 pr-3 whitespace-nowrap" data-testid="candidate-confidence">
        <span className={CONFIDENCE_STYLE[c.confidence?.level] || "text-slate-500"}>{confidenceText(c)}</span>
      </td>
      <td className="py-2 pr-3 text-slate-700 max-w-md">
        <div>{c.snippet}</div>
        {c.label_from && <div className="text-slate-400 mt-0.5" data-testid="candidate-label">Label from: {c.label_from}</div>}
        {c.date_from && <div className="text-slate-400 mt-0.5" data-testid="candidate-date-from">Date from: {c.date_from}</div>}
      </td>
      <td className="py-2 pr-3 font-mono text-[11px] text-slate-600" data-testid="candidate-source">
        {c.sources.map((s, i) => <div key={i}>{sourceRef(s)}</div>)}
      </td>
      <td className="py-2 pr-3">
        <span className={`text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap ${STATUS_STYLE[c.status] || ""}`}>
          {STATUS_LABELS[c.status] || c.status}
        </span>
        {c.ai_label && (
          <div className={`mt-1 text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap ${c.ai_label === VERIFIED_LABEL
            ? "text-emerald-800 border-emerald-500/50 bg-emerald-50" : "text-amber-800 border-amber-500/50 bg-amber-50"}`}
            data-testid="candidate-ai-label">
            {c.ai_label}
          </div>
        )}
        {c.inconsistent_dates?.length > 0 && (
          <div className="mt-1 text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap text-amber-800 border-amber-500/50 bg-amber-50"
            title={`This deck gives another value for the same type and period: ${c.inconsistent_dates.join(", ")}`}
            data-testid="candidate-inconsistency">
            {INCONSISTENCY_LABEL}
          </div>
        )}
      </td>
      <td className="py-2 whitespace-nowrap">
        {draft ? (
          <div className="flex gap-1">
            <Button size="sm" onClick={saveEdit} disabled={needsType(draft)} className="h-7 bg-sky-600 hover:bg-sky-500" data-testid="edit-save">Save and approve</Button>
            <Button size="sm" variant="outline" onClick={() => setDraft(null)} className="h-7">Cancel</Button>
          </div>
        ) : (
          <div className="flex gap-1">
            <Button size="sm" variant="outline" title={needsType(c) ? OTHER_TYPE_NOTE : "Approve"} disabled={needsType(c)}
              onClick={() => onSave(c, { status: "approved" })} className="h-7 px-2" data-testid="candidate-approve">
              <Check className="h-3.5 w-3.5 text-emerald-700" />
            </Button>
            <Button size="sm" variant="outline" title="Reject" onClick={() => onSave(c, { status: "rejected" })} className="h-7 px-2" data-testid="candidate-reject">
              <X className="h-3.5 w-3.5 text-rose-700" />
            </Button>
            <Button size="sm" variant="outline" title="Edit" onClick={() => startEdit()} className="h-7 px-2" data-testid="candidate-edit">
              <Pencil className="h-3.5 w-3.5 text-slate-700" />
            </Button>
          </div>
        )}
      </td>
    </tr>
  );
}
