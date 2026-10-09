import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Check, ChevronDown, ChevronRight, FileText, Loader2, Pencil, Plus, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import FxText from "@/components/FxText";
import { TurnoverCell, TurnoverReason } from "@/components/ClaimRegister";
import { NO_FILE_PERIOD, UNVERIFIED, answerReady, metricOptions, turnoverHeading, turnoverOf } from "@/lib/claimRegister";
import { addClaim, answerTurnover, getDecks, removeDeck, updateCandidate, uploadDeck } from "@/lib/api";
import { describeRequestError } from "@/lib/requestError";
import {
  ALL_DECKS, CLAIM_GROUPS, CLAIM_TYPES, CLAIM_UNITS, COUNT_UNIT_HINT, COUNT_TYPES, COUNT_UNIT, FX_SETTINGS_ANCHOR, FX_SETTINGS_LABEL, conversionHover, inconsistencyText, REMOVE_DECK_CONFIRM, claimsForDeck, deckTabs, defaultDeck, ADD_CLAIM_LABEL, ADD_CLAIM_NEEDS_SOURCE, CLAIMS_CHOICES, CLAIMS_HEADING, CLAIMS_INTRO, newClaimPayload, COLUMNS, DECK_ACCEPT, DECK_SCOPE_CANNOT,
  DECK_SCOPE_INTRO, DECK_SCOPE_OUTRO, CONFIDENCE_HOVER, DECK_UPLOAD_HELP, INCONSISTENCY_LABEL, OTHER_TYPE_NOTE, PLACEHOLDER, STATUS_LABELS, VERIFIED_LABEL, claimPeriod, claimSections, claimValue, deckRunLog,
  confidenceText, needsType, readingChoices, rowEdit, sourceRef, statusCounts, typeLabel,
} from "@/lib/deckClaims";

// The status is a label, not a control: plain coloured text, no border or chip, so it never reads as a button (George,
// 2026-10-09). Approve, Reject and Edit are the buttons of the Action column.
const STATUS_STYLE = {
  pending: "text-slate-600",
  approved: "text-emerald-700",
  rejected: "text-rose-700",
  edited: "text-sky-700",
};
const CONFIDENCE_STYLE = { High: "text-emerald-700", Medium: "text-amber-800", Low: "text-rose-700" };
export const MOVE_NOTICE_MS = 4000;
const selectClass = "h-8 rounded-md border border-[#E5E7EB] bg-white px-2 text-xs";
// The edit form's metric list holds one entry that is not a claim type: a turnover claim answered Transaction volume.
const VOLUME_OPTION = "transaction_volume";
const VOLUME_LABEL = "Transaction volume";
const ASK_OPTION = "turnover_ask";
/** What the edit form's metric dropdown shows: the stored answer of a turnover claim, else its type. */
const typeValue = (d) => (d.claim_type !== "revenue" || !d.answer ? d.claim_type
  : d.answer === "volume" ? VOLUME_OPTION : d.answer === "ask" ? ASK_OPTION : d.claim_type);

/** Board deck or growth plan: the scope message, the upload, and the candidate approval list. */
export default function DeckPanel({ auditId, reloadKey = 0 }) {
  const [data, setData] = useState({ decks: [], candidates: [] });
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState(null);            // deck id or ALL_DECKS; null until the first load
  const [confirming, setConfirming] = useState(null);
  const [adding, setAdding] = useState(false);       // the Add claim row is open
  const [expanded, setExpanded] = useState({});     // group -> opened or closed by the analyst; groups 5 and 6 start closed

  // After a load, keep the chosen tab if its deck still exists; otherwise show the most recent deck.
  // A background poll (silent) that meets an error, a 404 included, stops for good and shows nothing; so does a
  // reply that lands after the panel is left or the audit is deleted.
  const alive = useRef(true);
  const stopped = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback((select, silent = false) => getDecks(auditId).then((d) => {
    if (!alive.current) return undefined;
    setData(d);
    setTab((current) => {
      const wanted = select || current;
      return wanted && (wanted === ALL_DECKS || d.decks.some((x) => x.deck_id === wanted)) ? wanted : defaultDeck(d.decks);
    });
    return d;
  }).catch(() => {
    if (silent) { stopped.current = true; return undefined; }
    if (alive.current) toast.error("Could not load deck claims");
    return undefined;
  }), [auditId]);
  useEffect(() => { load(); }, [load]);
  // A rate saved on the page changes every claim's converted figure: read the claims again, keeping the open tab.
  const first = useRef(true);
  useEffect(() => { if (first.current) { first.current = false; return; } load(undefined, true); }, [reloadKey]); // eslint-disable-line

  // A deck's structures are read after its upload returns: check back while one is still being read.
  const polls = useRef(0);
  useEffect(() => {
    if (!data.decks.some((d) => d.ai_status === "reading") || polls.current >= 24 || stopped.current) return undefined;
    const timer = setTimeout(() => { polls.current += 1; load(undefined, true); }, 5000);
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

  // An approved claim that lands in another category: a toast with Undo and a highlight on its new row, both for 4 seconds.
  const [flash, setFlash] = useState(null);
  const flashTimer = useRef(null);
  useEffect(() => () => clearTimeout(flashTimer.current), []);
  const announceMove = (moved, previousType) => {
    const title = (CLAIM_GROUPS.find(([group]) => group === moved.group) || [])[1] || typeLabel(moved.claim_type);
    setExpanded((e) => ({ ...e, [moved.group]: true }));            // the new place is shown even if its group starts closed
    setFlash(moved.id);
    clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlash(null), MOVE_NOTICE_MS);
    toast.message(`Claim moved to ${title}`, {
      duration: MOVE_NOTICE_MS,
      action: { label: "Undo", onClick: () => { clearTimeout(flashTimer.current); setFlash(null); save(moved, { claim_type: previousType }, true); } },
    });
  };

  const save = async (candidate, payload, quiet = false) => {
    try {
      const updated = await updateCandidate(auditId, candidate.id, payload);
      setData((d) => ({ ...d, candidates: d.candidates.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)) }));
      // the group, the order and the confidence follow the type and the figure: read them again
      const fresh = await load();
      const moved = fresh?.candidates.find((c) => c.id === updated.id);
      if (!quiet && payload.claim_type && payload.claim_type !== candidate.claim_type && moved && moved.group !== candidate.group
          && ["approved", "edited"].includes(moved.status)) {
        announceMove(moved, candidate.claim_type);
      }
      return true;
    } catch (err) {
      toast.error(describeRequestError(err).message);      // names the rejected field and the reason: "HTTP 422 — unit: ..."
      return false;
    }
  };

  // Revenue or Volume for a turnover claim, answered in its row before it is approved (claim-matching.md section 11 point 8).
  const answer = async (row, payload) => {
    try {
      await answerTurnover(auditId, row.claim_id, payload);
      await load();
    } catch (err) {
      toast.error(describeRequestError(err).message);
      throw err;
    }
  };

  const add = async (payload) => {
    try {
      const created = await addClaim(auditId, payload);
      setAdding(false);
      toast.success("Claim added");
      await load(created.deck_id);
      return true;
    } catch (err) {
      toast.error(describeRequestError(err).message);
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
      <p className="mb-3 text-xs text-slate-600 max-w-3xl" data-testid="deck-upload-help">{DECK_UPLOAD_HELP}</p>
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
          <div className="flex items-start justify-between gap-4 flex-wrap mb-3">
            <div className="text-xs text-slate-700 max-w-3xl space-y-1" data-testid="claims-instructions">
              <h4 className="font-heading font-semibold text-sm text-slate-900">{CLAIMS_HEADING}</h4>
              <p>{CLAIMS_INTRO}</p>
              {CLAIMS_CHOICES.map(([choice, text]) => (
                <p key={choice}><span className="font-semibold">{choice}</span> {text}</p>
              ))}
            </div>
            <Button size="sm" variant="outline" onClick={() => setAdding(true)} disabled={adding} className="h-8" data-testid="add-claim">
              <Plus className="h-3.5 w-3.5 mr-1" />{ADD_CLAIM_LABEL}
            </Button>
          </div>
          {adding && <AddClaimRow decks={data.decks} initialDeck={data.decks.some((d) => d.deck_id === tab) ? tab : data.decks[0].deck_id}
            onSave={add} onCancel={() => setAdding(false)} />}
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
                {claimSections(shown).map((section) => {
                  const open = expanded[section.group] ?? !section.collapsed;
                  return (
                    <Fragment key={section.group}>
                      <tr className="bg-slate-50 border-b border-[#E5E7EB]" data-testid={`claim-group-${section.group}`}>
                        <td colSpan={COLUMNS.length} className="py-1.5 px-2">
                          <button type="button" aria-expanded={open} data-testid={`claim-group-toggle-${section.group}`}
                            onClick={() => setExpanded((e) => ({ ...e, [section.group]: !open }))}
                            className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
                            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                            {section.title} <span className="font-mono font-normal text-slate-500">({section.claims.length})</span>
                          </button>
                        </td>
                      </tr>
                      {open && section.claims.map((c) => <CandidateRow key={c.id} candidate={c} onSave={save} onAnswer={answer} highlight={flash === c.id} />)}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/** Add claim: one row with the metric (the same list as the other rows), a value or a range, unit, currency, period, the
 *  source document and the page. Source document and page are required: Save stays off until both are filled. */
function AddClaimRow({ decks, initialDeck, onSave, onCancel }) {
  const [draft, setDraft] = useState({ claim_type: CLAIM_TYPES[0], value: "", value_high: "", unit: "", currency: "", target_date: "", deck_id: initialDeck, page: "", metric: "" });
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  const setType = (e) => {
    const claim_type = e.target.value;
    setDraft((d) => (COUNT_TYPES.includes(claim_type) && !COUNT_TYPES.includes(d.claim_type)
      ? { ...d, claim_type, currency: "", unit: COUNT_UNIT } : { ...d, claim_type }));
  };
  // The register metrics that measure this claim's unit; the analyst chooses one, none is preselected.
  const metrics = metricOptions(draft).filter((m) => m !== "none");
  const metric = metrics.includes(draft.metric) ? draft.metric : "";
  const payload = newClaimPayload({ ...draft, metric });
  const save = async () => { setSaving(true); await onSave(payload); setSaving(false); };
  return (
    <div className="mb-3 p-3 border border-[#E5E7EB] rounded-md bg-slate-50 flex flex-wrap items-end gap-2" data-testid="add-claim-row">
      <label className="flex flex-col text-[10px] font-mono text-slate-500">Metric
        <select value={draft.claim_type} onChange={setType} className={selectClass} data-testid="add-claim-type">
          {CLAIM_TYPES.map((t) => <option key={t} value={t}>{typeLabel(t)}</option>)}
        </select>
      </label>
      <label className="flex flex-col text-[10px] font-mono text-slate-500">Value
        <Input value={draft.value} onChange={set("value")} type="number" className="h-8 w-28 text-xs font-mono" data-testid="add-claim-value" />
      </label>
      <label className="flex flex-col text-[10px] font-mono text-slate-500">To (range)
        <Input value={draft.value_high} onChange={set("value_high")} type="number" className="h-8 w-28 text-xs font-mono" data-testid="add-claim-value-high" />
      </label>
      <label className="flex flex-col text-[10px] font-mono text-slate-500">Unit
        <Input value={draft.unit} onChange={set("unit")} list="add-claim-units" className="h-8 w-28 text-xs font-mono" data-testid="add-claim-unit" />
        <datalist id="add-claim-units">{CLAIM_UNITS.map((u) => <option key={u} value={u} label={u === "count" ? COUNT_UNIT_HINT : undefined} />)}</datalist>
      </label>
      <label className="flex flex-col text-[10px] font-mono text-slate-500">Currency
        <Input value={draft.currency} onChange={set("currency")} placeholder="EUR" className="h-8 w-16 text-xs font-mono uppercase" data-testid="add-claim-currency" />
      </label>
      <label className="flex flex-col text-[10px] font-mono text-slate-500">Date or period
        <Input value={draft.target_date} onChange={set("target_date")} placeholder="2025-Q4" className="h-8 w-24 text-xs font-mono" data-testid="add-claim-date" />
      </label>
      <label className="flex flex-col text-[10px] font-mono text-slate-500">Metric tested (required)
        <select value={metric} onChange={set("metric")} className={selectClass} data-testid="add-claim-metric">
          <option value="" disabled>Choose a metric</option>
          {metrics.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </label>
      <label className="flex flex-col text-[10px] font-mono text-slate-500">Source document (required)
        <select value={draft.deck_id} onChange={set("deck_id")} className={selectClass} data-testid="add-claim-deck">
          {decks.map((d) => <option key={d.deck_id} value={d.deck_id}>{d.file}</option>)}
        </select>
      </label>
      <label className="flex flex-col text-[10px] font-mono text-slate-500">Page (required)
        <Input value={draft.page} onChange={set("page")} type="number" min="1" className="h-8 w-20 text-xs font-mono" data-testid="add-claim-page" />
      </label>
      <Button size="sm" onClick={save} disabled={!payload || saving} title={payload ? undefined : ADD_CLAIM_NEEDS_SOURCE} className="h-8 bg-sky-600 hover:bg-sky-500" data-testid="add-claim-save">Save</Button>
      <Button size="sm" variant="outline" onClick={onCancel} className="h-8" data-testid="add-claim-cancel">Cancel</Button>
    </div>
  );
}

function CandidateRow({ candidate: c, onSave, onAnswer, highlight }) {
  const [draft, setDraft] = useState(null);
  const [why, setWhy] = useState(false);
  const explanation = inconsistencyText(c);
  const isRow = Boolean(c.by_period?.length);      // a table row: its values by period
  const turnover = turnoverOf(c);                  // a turnover claim never reads "Revenue" before the analyst confirms it
  const choices = readingChoices(c);               // a figure that reads two ways: the default is pre-selected
  // Edit, optionally starting from the other reading of an ambiguous figure.
  // A turnover claim's metric is what the analyst answered: Revenue, Transaction volume, or nothing yet ("ask"). The edit form
  // opens on that answer; changing it is answering "Revenue or volume?" and needs a reason, as the row's buttons do.
  const answered = turnover.views.map((v) => (v.turnover_set_by === "analyst" ? v.turnover_state : "ask"));
  const initialAnswer = answered.length && answered.every((a) => a === answered[0]) ? answered[0] : "ask";
  const reasonRow = { file_note: turnover.views.length && turnover.views.every((v) => v.file_note === NO_FILE_PERIOD) ? NO_FILE_PERIOD : null };
  const startEdit = (value) => setDraft({
    claim_type: c.claim_type, value: value ?? c.value ?? "", value_high: c.value_high ?? "", unit: c.unit ?? "", currency: c.currency ?? "", target_date: c.target_date ?? "",
    values: (c.by_period || []).map((i) => i.value ?? ""),
    answer: turnover.views.length ? initialAnswer : null, reason: "",
  });
  // The answer to send: only a turnover claim that stays a revenue-type claim, whose Revenue / Transaction volume was changed.
  const newAnswer = (d) => (turnover.views.length && d.claim_type === "revenue" && d.answer !== initialAnswer && ["revenue", "volume"].includes(d.answer) ? d.answer : null);
  const answerBlocked = (d) => { const a = newAnswer(d); return a !== null && !answerReady(a, d.reason, reasonRow); };
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
    if (!(await onSave(c, payload))) return;
    const as = newAnswer(draft);
    if (as) {
      try {
        for (const view of turnover.views) await onAnswer(view, { as, reason: draft.reason });     // as the Revenue / Volume buttons record it
      } catch (e) { return; }                                  // the toast names the refusal; the form stays open
    }
    setDraft(null);
  };
  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  // A claim changed to a count type is a count: no currency, and the unit "count" (the analyst may type the noun counted).
  const setType = (e) => {
    const claim_type = e.target.value;
    if (turnover.views.length && claim_type === VOLUME_OPTION) { setDraft((d) => ({ ...d, answer: "volume" })); return; }
    setDraft((d) => {
      const answer = turnover.views.length ? (claim_type === "revenue" ? "revenue" : initialAnswer) : d.answer;    // another type is not an answer
      return COUNT_TYPES.includes(claim_type) && !COUNT_TYPES.includes(d.claim_type)
        ? { ...d, claim_type, answer, currency: "", unit: COUNT_UNIT } : { ...d, claim_type, answer };
    });
  };
  const setValue = (k) => (e) => setDraft((d) => ({ ...d, values: d.values.map((v, i) => (i === k ? e.target.value : v)) }));

  return (
    <tr className={`border-b border-[#F1F5F9] align-top transition-colors ${highlight ? "bg-amber-100" : ""}`}
      data-testid={`candidate-row-${c.id}`} data-highlight={highlight ? "true" : undefined}>
      {draft ? (
        <>
          <td className="py-2 pr-3">
            <select value={typeValue(draft)} onChange={setType} className={selectClass} data-testid="edit-claim-type">
              {needsType(draft) && <option value={draft.claim_type} disabled>{typeLabel(draft.claim_type)}{draft.claim_type === "unknown" ? "" : ": choose a type"}</option>}
              {turnover.views.length > 0 && draft.claim_type === "revenue" && draft.answer === "ask" && <option value={ASK_OPTION} disabled>Turnover – choose</option>}
              {CLAIM_TYPES.flatMap((t) => (t === "revenue" && turnover.views.length ? [t, VOLUME_OPTION] : [t])).map((t) => (
                <option key={t} value={t}>{t === VOLUME_OPTION ? VOLUME_LABEL : typeLabel(t)}</option>))}
            </select>
            {newAnswer(draft) ? (
              <div className="mt-1 min-w-[16rem]">
                <TurnoverReason row={reasonRow} reason={draft.reason} setReason={(reason) => setDraft((d) => ({ ...d, reason }))}
                  testId="edit-turnover-reason" />
              </div>
            ) : null}
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
              <datalist id="claim-units">{CLAIM_UNITS.map((u) => <option key={u} value={u} label={u === "count" ? COUNT_UNIT_HINT : undefined} />)}</datalist>
              <Input value={draft.currency} onChange={set("currency")} placeholder="EUR" className="h-8 w-16 text-xs font-mono uppercase" data-testid="edit-currency" />
            </div>
          </td>
          <td className="py-2 pr-3">
            {isRow ? <span className="font-mono text-slate-700 whitespace-nowrap">{claimPeriod(c)}</span> : (
              <Input value={draft.target_date} onChange={set("target_date")} placeholder="2025-Q4" className="h-8 w-24 text-xs font-mono" data-testid="edit-target-date" />
            )}
          </td>
        </>
      ) : (
        <>
          <td className={`py-2 pr-3 text-slate-800 ${turnover.views.length ? "min-w-[14rem]" : "whitespace-nowrap"}`} data-testid="candidate-type">
            {turnover.views.length ? turnover.views.map((v) => (
              <TurnoverCell key={v.claim_id} row={v} onAnswer={onAnswer} heading={turnoverHeading(v, isRow)} />
            )) : typeLabel(c.claim_type)}
            {needsType(c) && <div className="text-[10px] text-amber-800 mt-0.5" data-testid="candidate-needs-type">{OTHER_TYPE_NOTE}</div>}
          </td>
          <td className={`py-2 pr-3 font-mono text-slate-900 ${isRow || claimValue(c).includes(FX_SETTINGS_LABEL) ? "" : "whitespace-nowrap"}`}>
            {choices.length ? (
              <select value={0} onChange={(e) => Number(e.target.value) && startEdit(choices[Number(e.target.value)].value)}
                className={selectClass} title="This figure reads two ways. Approve the first reading, or choose the other to edit the claim."
                data-testid="candidate-readings">
                {choices.map((r, i) => <option key={i} value={i}>{r.label}</option>)}
              </select>
            ) : <span title={conversionHover(c) || undefined} data-testid="candidate-value"><FxText text={claimValue(c)} href={`#${FX_SETTINGS_ANCHOR}`} testId="fx-settings-link" /></span>}
          </td>
          <td className="py-2 pr-3 font-mono text-slate-700 whitespace-nowrap">{claimPeriod(c)}</td>
        </>
      )}
      <td className="py-2 pr-3 whitespace-nowrap" data-testid="candidate-confidence">
        <span className={CONFIDENCE_STYLE[c.confidence?.level] || "text-slate-500"} title={CONFIDENCE_HOVER} data-testid="candidate-confidence-text">{confidenceText(c)}</span>
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
        <span className={`text-[10px] font-mono whitespace-nowrap cursor-default ${STATUS_STYLE[c.status] || ""}`} data-testid="candidate-status">
          {STATUS_LABELS[c.status] || c.status}
        </span>
        {turnover.open && (
          <div className="mt-1 text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap text-amber-800 border-amber-500/50 bg-amber-50"
            data-testid="candidate-turnover-label">
            {UNVERIFIED}
          </div>
        )}
        {c.ai_label && (
          <div className={`mt-1 text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap ${c.ai_label === VERIFIED_LABEL
            ? "text-emerald-800 border-emerald-500/50 bg-emerald-50" : "text-amber-800 border-amber-500/50 bg-amber-50"}`}
            data-testid="candidate-ai-label">
            {c.ai_label}
          </div>
        )}
        {explanation && (
          <div className="mt-1">
            <button type="button" aria-expanded={why} onClick={() => setWhy((v) => !v)} title={explanation}
              className="text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap text-amber-800 border-amber-500/50 bg-amber-50"
              data-testid="candidate-inconsistency">
              {INCONSISTENCY_LABEL}
            </button>
            {why && <p className="mt-1 max-w-[16rem] whitespace-normal text-[11px] text-slate-700" data-testid="candidate-inconsistency-text">{explanation}</p>}
          </div>
        )}
      </td>
      <td className="py-2 whitespace-nowrap">
        {draft ? (
          <div className="flex gap-1">
            <Button size="sm" onClick={saveEdit} disabled={needsType(draft) || answerBlocked(draft)} title={answerBlocked(draft) ? "Choose a reason for the answer first." : undefined} className="h-7 bg-sky-600 hover:bg-sky-500" data-testid="edit-save">Save and approve</Button>
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
