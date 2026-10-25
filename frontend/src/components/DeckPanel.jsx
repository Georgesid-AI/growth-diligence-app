import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Check, ChevronDown, ChevronRight, FileText, Loader2, Pencil, Plus, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import FxText from "@/components/FxText";
import { TurnoverCell, TurnoverReason } from "@/components/ClaimRegister";
import { NO_FILE_PERIOD, UNVERIFIED, answerReady, metricOptions, turnoverHeading, turnoverOf } from "@/lib/claimRegister";
import { addClaim, addFromDeck, answerTurnover, getDeckPage, getDecks, removeDeck, updateCandidate, uploadDeck } from "@/lib/api";
import { describeRequestError } from "@/lib/requestError";
import {
  ACQUISITION_CHANNELS, ADD_CLAIM_PLATFORM_LABEL, ALL_DECKS, CLAIM_GROUPS, CLAIM_TYPES, CLAIM_UNITS, COUNT_UNIT_HINT, COUNT_TYPES, COUNT_UNIT, FX_SETTINGS_ANCHOR, FX_SETTINGS_LABEL, conversionHover, inconsistencyText, MIXED_SLIDE_LABEL, REMOVE_DECK_CONFIRM, claimsForDeck, deckTabs, defaultDeck, ADD_CLAIM_LABEL, ADD_CLAIM_NEEDS_SOURCE, CLAIMS_CHOICES, CLAIMS_HEADING, CLAIMS_INTRO, newClaimPayload, COLUMNS, DECK_ACCEPT, DECK_SCOPE_CANNOT,
  DECK_SCOPE_CANNOT_LEAD, DECK_SCOPE_INTRO, DECK_SCOPE_OUTRO, DECK_TYPE_REFUSED, isDeckFile, CONFIDENCE_HOVER, DECK_UPLOAD_HELP, INCONSISTENCY_LABEL, PLACEHOLDER, VERIFIED_LABEL, badgeText, claimPeriod, claimSections, claimValue, deckReadLine, deckRunLog, uploadLineText,
  confidenceText, countLine, readingChoices, rowEdit, sourceRef, statusCounts, statusText, typeLabel,
  ADD_FROM_DECK_LABEL, ADDED_FROM_DECK_TAG, DEFAULT_EDIT_REASON, EDIT_REASONS, EDIT_TYPES, FIGURE_TYPE_OPTIONS, GROWTH_BASIS_OPTIONS, GROWTH_TYPES,
  OTHER_GROUP, POPULATION_OPTIONS, VIEW_PAGE_LABEL, claimFields, editLogText, isOther,
  CLAIMS_VIEW, REVIEW_VIEW, VIEW_LABELS, REVIEW_INTRO, claimsForView, flagsText, scenarioText,
} from "@/lib/deckClaims";

// The status is a label, not a control: plain coloured text, no border or chip, so it never reads as a button (George,
// 2026-10-09). Keep (on a claim that waits for an answer), Reject and Edit are the buttons of the Action column.
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
/** What the edit form's metric dropdown shows: the stored answer of a turnover claim, else its type (a figure with no type: Other). */
const typeValue = (d) => (d.claim_type === "unknown" ? "other" : d.claim_type !== "revenue" || !d.answer ? d.claim_type
  : d.answer === "volume" ? VOLUME_OPTION : d.answer === "ask" ? ASK_OPTION : d.claim_type);

/** Board deck or growth plan: the scope message, the upload, and the candidate approval list. */
export default function DeckPanel({ auditId, reloadKey = 0 }) {
  const [data, setData] = useState({ decks: [], candidates: [] });
  const [lines, setLines] = useState([]);          // one status line per file of the last drops: waiting / uploading / done / refused / failed
  const [tab, setTab] = useState(null);            // deck id or ALL_DECKS; null until the first load
  const [confirming, setConfirming] = useState(null);
  const [adding, setAdding] = useState(false);       // the Add claim row is open
  const [expanded, setExpanded] = useState({});     // group -> opened or closed by the analyst; Other starts closed
  const [editing, setEditing] = useState(null);     // a claim just added from the deck with no type: opened in the editor
  const [view, setView] = useState(CLAIMS_VIEW);    // Claims (no flag) or Review (the claims the checks flagged)

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

  // Files go one after another, in drop order, one status line each; a refused type or a failed upload does not stop the others.
  const queue = useRef(Promise.resolve());
  const seq = useRef(0);
  const setLine = (id, patch) => { if (alive.current) setLines((all) => all.map((l) => (l.id === id ? { ...l, ...patch } : l))); };
  const takeFiles = (list) => {
    const files = Array.from(list || []);
    if (!files.length) return;
    const added = files.map((file) => ({ id: (seq.current += 1), file, name: file.name, state: isDeckFile(file.name) ? "waiting" : "refused",
      text: isDeckFile(file.name) ? "waiting" : `refused – ${DECK_TYPE_REFUSED}` }));
    setLines((all) => [...all.filter((l) => l.state === "waiting" || l.state === "uploading"), ...added]);
    for (const line of added.filter((l) => l.state === "waiting")) queue.current = queue.current.then(() => sendFile(line));
    return queue.current;
  };

  const onFile = (e) => {
    const picked = Array.from(e.target.files || []);
    e.target.value = "";
    return takeFiles(picked);
  };

  // The box is also a drop zone: dropped files take the same path as picked ones, with the same type check and refusal.
  const onDrop = (e) => {
    e.preventDefault();
    return takeFiles(e.dataTransfer?.files);
  };

  const sendFile = async (line) => {
    setLine(line.id, { state: "uploading", text: "uploading…" });
    try {
      const res = await uploadDeck(auditId, line.file);
      // The page read has its own line (chat-upload.md section 28); the former rules read still lists candidates at upload.
      const summary = res.ai_status ? deckReadLine(res) : `${res.pages} ${res.page_unit}s parsed · ${res.candidates} candidate claims`;
      toast.success(`${res.file}: ${summary}`);
      setLine(line.id, { state: "done", text: `done · ${summary}`, deckId: res.ai_status ? res.deck_id : null });
      await load(res.deck_id);
    } catch (err) {
      setLine(line.id, { state: "failed", text: `failed – ${err.response?.data?.detail || "Upload failed"}` });
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

  // Add from deck (claim-types-and-correction.md section 5): the server reads the line's text; its group is shown open, and a figure
  // with no type opens in the editor.
  const addLine = async (deckId, page, ref) => {
    try {
      const created = await addFromDeck(auditId, deckId, { page, ref });
      toast.success("Claim added from the deck");
      const fresh = await load(deckId);
      const listed = fresh?.candidates.find((c) => c.id === created.id) || created;
      setExpanded((e) => ({ ...e, [listed.group ?? OTHER_GROUP]: true }));
      if (isOther(listed)) setEditing(listed.id);
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

  const underTab = claimsForDeck(data.candidates, tab);
  const shown = claimsForView(underTab, view);
  const counts = statusCounts(shown);
  const viewCount = (v) => claimsForView(underTab, v).length;
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
          </div>
        </div>
      </div>

      <label className="mt-3 block cursor-pointer rounded-md border border-dashed border-[#D1D5DB] bg-sky-50/50 p-4 hover:bg-sky-50 transition-colors" data-testid="deck-upload-box"
        onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
        <input type="file" accept={DECK_ACCEPT} className="hidden" onChange={onFile} data-testid="deck-upload-input" />
        <div className="text-xs text-slate-600 max-w-2xl space-y-1" data-testid="deck-scope-message">
          <p>{DECK_SCOPE_INTRO}</p>
          <p>{DECK_SCOPE_CANNOT_LEAD}</p>
          <ul className="list-disc pl-5">
            {DECK_SCOPE_CANNOT.map((line) => <li key={line}>{line}</li>)}
          </ul>
          <p>{DECK_SCOPE_OUTRO}</p>
        </div>
        <span className="mt-3 inline-flex items-center gap-2 px-3.5 py-2 rounded-md bg-white border border-[#D1D5DB] text-sm text-slate-800">
          {lines.some((l) => l.state === "waiting" || l.state === "uploading") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Upload deck
        </span>
      </label>

      {lines.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm" data-testid="deck-upload-status">
          {lines.map((l) => (
            <li key={l.id} data-testid="deck-upload-line" data-state={l.state}
              className={l.state === "refused" || l.state === "failed" ? "text-rose-700" : l.state === "done" ? "text-emerald-700" : "text-slate-600"}
              role={l.state === "refused" || l.state === "failed" ? "alert" : undefined}>
              {l.name}: {uploadLineText(l, data.decks)}
            </li>
          ))}
        </ul>
      )}

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
          {selectedDeck && <DeckPageView key={selectedDeck.deck_id} auditId={auditId} deck={selectedDeck} onAdd={addLine} />}
          {selectedDeck && deckRunLog(selectedDeck).length > 0 && (
            <div className="text-[11px] font-mono text-slate-600 mb-2 space-y-0.5" data-testid="deck-run-log">
              {deckRunLog(selectedDeck).map((line) => <div key={line}>{line}</div>)}
            </div>
          )}
          <div className="flex flex-wrap gap-1 mb-2" role="tablist" data-testid="claims-views">
            {[CLAIMS_VIEW, REVIEW_VIEW].map((v) => (
              <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
                className={`px-2.5 py-1 text-xs rounded-md border ${view === v ? "border-sky-600 bg-sky-50 text-slate-900 font-semibold" : "border-[#E5E7EB] text-slate-500 hover:text-slate-800"}`}
                data-testid={`claims-view-${v}`}>
                {VIEW_LABELS[v]} <span className="font-mono font-normal text-slate-400">({viewCount(v)})</span>
              </button>
            ))}
          </div>
          {view === REVIEW_VIEW && <p className="text-xs text-slate-600 mb-2 max-w-3xl" data-testid="review-intro">{REVIEW_INTRO}</p>}
          <div className="text-[11px] text-slate-500 font-mono mb-2">
            {countLine(counts)}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] font-mono uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB]">
                  {COLUMNS.map((name) => <th key={name} className="py-2 pr-3" title={name === "Extraction confidence" ? CONFIDENCE_HOVER : undefined}>{name}</th>)}
                </tr>
              </thead>
              <tbody>
                {claimSections(shown).map((section, index) => {
                  const open = expanded[section.group] ?? !section.collapsed;
                  const other = section.group === OTHER_GROUP;       // never a task: no count
                  return (
                    <Fragment key={section.group}>
                      {index > 0 && (
                        <tr aria-hidden="true" data-testid={`claim-group-gap-${section.group}`}>
                          <td colSpan={COLUMNS.length} className="py-3.5"><div className="border-t border-[#E5E7EB]" /></td>
                        </tr>
                      )}
                      <tr className="bg-slate-50 border-b border-[#E5E7EB]" data-testid={`claim-group-${section.group}`}>
                        <td colSpan={COLUMNS.length} className="py-1.5 px-2">
                          <div className="flex items-center justify-between gap-3">
                            <button type="button" aria-expanded={open} data-testid={`claim-group-toggle-${section.group}`}
                              onClick={() => setExpanded((e) => ({ ...e, [section.group]: !open }))}
                              className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
                              {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                              {section.title}{!other && <span className="font-mono font-normal text-slate-500"> ({section.claims.length})</span>}
                            </button>
                          </div>
                        </td>
                      </tr>
                      {open && section.claims.map((c) => <CandidateRow key={c.id} candidate={c} onSave={save} onAnswer={answer} highlight={flash === c.id}
                        autoEdit={editing === c.id} />)}
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
  const [draft, setDraft] = useState({ claim_type: CLAIM_TYPES[0], value: "", value_high: "", unit: "", currency: "", target_date: "", deck_id: initialDeck, page: "", metric: "", label: "" });
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  const setType = (e) => {
    const claim_type = e.target.value;
    setDraft((d) => (COUNT_TYPES.includes(claim_type) && !COUNT_TYPES.includes(d.claim_type)
      ? { ...d, claim_type, currency: "", unit: COUNT_UNIT } : { ...d, claim_type }));
  };
  // The register metrics that measure this claim's unit; the analyst chooses one, none is preselected.
  const channel = draft.claim_type === ACQUISITION_CHANNELS;       // a platform, tested against no metric
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
      {channel ? (
        <label className="flex flex-col text-[10px] font-mono text-slate-500">{ADD_CLAIM_PLATFORM_LABEL}
          <Input value={draft.label} onChange={set("label")} maxLength={40} placeholder="Telegram" className="h-8 w-32 text-xs font-mono" data-testid="add-claim-platform" />
        </label>
      ) : (
        <label className="flex flex-col text-[10px] font-mono text-slate-500">Metric tested (required)
          <select value={metric} onChange={set("metric")} className={selectClass} data-testid="add-claim-metric">
            <option value="" disabled>Choose a metric</option>
            {metrics.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
      )}
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

/** View page: one stored page of the selected deck, its lines, cells and chart labels; the analyst selects one and adds it as a claim.
 *  The server reads the text of the line it is sent by reference, never text from here. */
function DeckPageView({ auditId, deck, onAdd }) {
  const [page, setPage] = useState("");
  const [shown, setShown] = useState(null);
  const [picked, setPicked] = useState(null);
  const [busy, setBusy] = useState(false);
  const number = Number(page);
  const valid = Number.isInteger(number) && number >= 1 && (!deck.pages || number <= deck.pages);
  const show = async () => {
    setBusy(true);
    try {
      setShown(await getDeckPage(auditId, deck.deck_id, number));
      setPicked(null);
    } catch (err) {
      toast.error(describeRequestError(err).message);
    } finally {
      setBusy(false);
    }
  };
  const add = async () => {
    setBusy(true);
    if (await onAdd(deck.deck_id, shown.page, picked)) setPicked(null);
    setBusy(false);
  };
  return (
    <div className="mb-3 text-[11px]" data-testid="deck-page-view">
      <div className="flex items-end gap-2">
        <label className="flex flex-col text-[10px] font-mono text-slate-500">{VIEW_PAGE_LABEL} ({deck.page_unit || "page"})
          <Input value={page} onChange={(e) => setPage(e.target.value)} type="number" min="1" className="h-7 w-20 text-xs font-mono" data-testid="deck-page-input" />
        </label>
        <Button size="sm" variant="outline" onClick={show} disabled={!valid || busy} className="h-7" data-testid="deck-page-show">Show page</Button>
        {shown && <Button size="sm" onClick={add} disabled={!picked || busy} className="h-7 bg-sky-600 hover:bg-sky-500" data-testid="add-from-deck">
          <Plus className="h-3.5 w-3.5 mr-1" />{ADD_FROM_DECK_LABEL}</Button>}
      </div>
      {shown && (
        <ul className="mt-2 max-h-64 overflow-y-auto border border-[#E5E7EB] rounded-md divide-y divide-[#F1F5F9]" data-testid="deck-page-lines">
          {shown.lines.length === 0 && <li className="px-2 py-1.5 text-slate-500">No text on this {shown.page_unit || "page"}.</li>}
          {shown.lines.map((line) => (
            <li key={line.ref}>
              <button type="button" aria-pressed={picked === line.ref} onClick={() => setPicked(line.ref)} data-testid={`deck-page-line-${line.ref}`}
                className={`w-full text-left px-2 py-1.5 ${picked === line.ref ? "bg-sky-50 text-slate-900" : "text-slate-700 hover:bg-slate-50"}`}>
                <span className="font-mono text-slate-400 mr-2">{line.kind}</span>{line.text}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CandidateRow({ candidate: c, onSave, onAnswer, highlight, autoEdit = false }) {
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
  const fields = claimFields(c);                   // figure type, population and growth basis as the register reads them
  const startEdit = (value) => setDraft({
    claim_type: c.claim_type, value: value ?? c.value ?? "", value_high: c.value_high ?? "", unit: c.unit ?? "", currency: c.currency ?? "", target_date: c.target_date ?? "",
    values: (c.by_period || []).map((i) => i.value ?? ""),
    answer: turnover.views.length ? initialAnswer : null, reason: "", ...fields, edit_reason: DEFAULT_EDIT_REASON,
  });
  useEffect(() => { if (autoEdit) startEdit(); }, [autoEdit]); // eslint-disable-line react-hooks/exhaustive-deps
  // An Other figure stays out of matching until it is given a claim type; typing a claim Other is allowed (it leaves the register).
  const stillOther = (d) => isOther(c) && isOther(d);
  // The answer to send: only a turnover claim that stays a revenue-type claim, whose Revenue / Transaction volume was changed.
  const newAnswer = (d) => (turnover.views.length && d.claim_type === "revenue" && d.answer !== initialAnswer && ["revenue", "volume"].includes(d.answer) ? d.answer : null);
  const answerBlocked = (d) => { const a = newAnswer(d); return a !== null && !answerReady(a, d.reason, reasonRow); };
  const saveEdit = async () => {
    const common = {
      claim_type: draft.claim_type,
      unit: draft.unit || null,
      currency: draft.currency.trim() ? draft.currency.trim().toUpperCase() : null,
    };
    // the claim fields that changed, and why (claim-types-and-correction.md section 3)
    const changed = {};
    if (draft.figure_type !== fields.figure_type) changed.figure_type = draft.figure_type;
    if (POPULATION_OPTIONS[draft.claim_type] && draft.population !== fields.population) changed.population = draft.population || null;
    if (GROWTH_TYPES.includes(draft.claim_type) && draft.growth_basis !== fields.growth_basis) changed.growth_basis = draft.growth_basis;
    const payload = isRow ? { ...common, ...changed, by_period: rowEdit(c, draft.values), reason: draft.edit_reason } : {
      ...common,
      ...changed,
      value: draft.value === "" ? null : Number(draft.value),
      value_high: draft.value_high === "" ? null : Number(draft.value_high),
      target_date: draft.target_date.trim() || null,
      reason: draft.edit_reason,
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
              {["use_of_funds", "pricing", "installed_units"].includes(draft.claim_type) && <option value={draft.claim_type}>{typeLabel(draft.claim_type)}</option>}
              {turnover.views.length > 0 && draft.claim_type === "revenue" && draft.answer === "ask" && <option value={ASK_OPTION} disabled>Turnover – choose</option>}
              {EDIT_TYPES.flatMap((t) => (t === "revenue" && turnover.views.length ? [t, VOLUME_OPTION] : [t])).map((t) => (
                <option key={t} value={t}>{t === VOLUME_OPTION ? VOLUME_LABEL : typeLabel(t)}</option>))}
            </select>
            {!isOther(draft) && (
              <div className="mt-1 flex flex-col gap-1">
                <label className="flex flex-col text-[10px] font-mono text-slate-500">Figure type
                  <select value={draft.figure_type} onChange={set("figure_type")} className={selectClass} data-testid="edit-figure-type">
                    {FIGURE_TYPE_OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                  </select>
                </label>
                {POPULATION_OPTIONS[draft.claim_type] && (
                  <label className="flex flex-col text-[10px] font-mono text-slate-500">Population
                    <select value={draft.population} onChange={set("population")} className={selectClass} data-testid="edit-population">
                      <option value="">Unknown</option>
                      {POPULATION_OPTIONS[draft.claim_type].map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                    </select>
                  </label>
                )}
                {GROWTH_TYPES.includes(draft.claim_type) && (
                  <label className="flex flex-col text-[10px] font-mono text-slate-500">Growth basis
                    <select value={draft.growth_basis} onChange={set("growth_basis")} className={selectClass} data-testid="edit-growth-basis">
                      {GROWTH_BASIS_OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                    </select>
                  </label>
                )}
              </div>
            )}
            <label className="mt-1 flex flex-col text-[10px] font-mono text-slate-500">Reason for the change
              <select value={draft.edit_reason} onChange={set("edit_reason")} className={selectClass} data-testid="edit-reason">
                {EDIT_REASONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
            </label>
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
            {scenarioText(c) && <div className="text-[10px] font-mono text-slate-500" data-testid="candidate-scenario">{scenarioText(c)}</div>}
            {c.channel && <div className="text-[10px] text-slate-500 mt-0.5" data-testid="candidate-channel">{c.channel}</div>}
          </td>
          <td className={`py-2 pr-3 font-mono text-slate-900 ${isRow || claimValue(c).includes(FX_SETTINGS_LABEL) ? "" : "whitespace-nowrap"}`}>
            {choices.length ? (
              <select value={0} onChange={(e) => Number(e.target.value) && startEdit(choices[Number(e.target.value)].value)}
                className={selectClass} title="This figure reads two ways. Keep the first reading, or choose the other to edit the claim."
                data-testid="candidate-readings">
                {choices.map((r, i) => <option key={i} value={i}>{r.label}</option>)}
              </select>
            ) : <span title={conversionHover(c) || undefined} data-testid="candidate-value"><FxText text={claimValue(c)} href={`#${FX_SETTINGS_ANCHOR}`} testId="fx-settings-link" /></span>}
          </td>
          <td className="py-2 pr-3 font-mono text-slate-700 whitespace-nowrap">
            {claimPeriod(c)}
            {c.target_date && c.period_read_note ? <div className="font-sans text-[11px] text-slate-500 whitespace-normal" data-testid="candidate-period-note">{c.period_read_note}</div> : null}
          </td>
        </>
      )}
      <td className="py-2 pr-3 whitespace-nowrap" data-testid="candidate-confidence">
        <span className={CONFIDENCE_STYLE[c.confidence?.level] || "text-slate-500"} title={CONFIDENCE_HOVER} data-testid="candidate-confidence-text">{confidenceText(c)}</span>
      </td>
      <td className="py-2 pr-3 text-slate-700 max-w-md">
        <div>{c.snippet}</div>
        {c.origin === "deck_analyst" && <div className="text-slate-400 mt-0.5" data-testid="candidate-added-from-deck">{ADDED_FROM_DECK_TAG}</div>}
        {c.label_from && <div className="text-slate-400 mt-0.5" data-testid="candidate-label">Label from: {c.label_from}</div>}
        {c.date_from && <div className="text-slate-400 mt-0.5" data-testid="candidate-date-from">Date from: {c.date_from}</div>}
      </td>
      <td className="py-2 pr-3 font-mono text-[11px] text-slate-600" data-testid="candidate-source">
        {c.sources.map((s, i) => <div key={i}>{sourceRef(s)}</div>)}
      </td>
      <td className="py-2 pr-3">
        <span className={`text-[10px] font-mono whitespace-nowrap cursor-default ${STATUS_STYLE[c.status] || ""}`} title={[editLogText(c), c.auto_approval && c.auto_citation].filter(Boolean).join("\n") || undefined}
          data-testid="candidate-status">
          {statusText(c)}
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
            {badgeText(c.ai_label)}
          </div>
        )}
        {flagsText(c) && (
          <div className="mt-1 text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-normal max-w-[14rem] text-amber-800 border-amber-500/50 bg-amber-50"
            data-testid="candidate-flags">
            {flagsText(c)}
          </div>
        )}
        {c.mixed_slide && (
          <div className="mt-1">
            <span className="text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap text-amber-800 border-amber-500/50 bg-amber-50"
              data-testid="candidate-mixed-slide">
              {MIXED_SLIDE_LABEL}
            </span>
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
            <Button size="sm" onClick={saveEdit} disabled={stillOther(draft) || answerBlocked(draft)}
              title={answerBlocked(draft) ? "Choose a reason for the answer first." : stillOther(draft) ? "Choose a claim type first." : undefined}
              className="h-7 bg-sky-600 hover:bg-sky-500" data-testid="edit-save">Save</Button>
            <Button size="sm" variant="outline" onClick={() => setDraft(null)} className="h-7">Cancel</Button>
          </div>
        ) : (
          <div className="flex gap-1">
            {!isOther(c) && c.status === "pending" && (
              <Button size="sm" variant="outline" title="Keep" onClick={() => onSave(c, { status: "approved" })} className="h-7 px-2" data-testid="candidate-keep">
                <Check className="h-3.5 w-3.5 text-emerald-700" />
              </Button>
            )}
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
