import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Check, Circle, Loader2, AlertTriangle } from "lucide-react";
import { Layout } from "@/components/Layout";
import AuditSetup from "@/components/AuditSetup";
import UploadChat from "@/components/UploadChat";
import { BLOCKERS_CHANGED } from "@/components/BlockerBanner";
import { Button } from "@/components/ui/button";
import * as apiModule from "@/lib/api";
import { getAudit, getDatasets, getDecks, getReview, removeDeck, reportUsage } from "@/lib/api";
import { asOfInputValue } from "@/lib/auditForm";
import { TYPE_LABELS, setCalculatePressed } from "@/lib/chatUpload";
import { REMOVE_DECK_CONFIRM } from "@/lib/deckClaims";
import { RETRY_LABEL, RUN_LABEL, STAGES, STAGE_STATUS_TEXT, idleStages, runAudit, splitFiles, stagesFromState } from "@/lib/runAudit";

/**
 * Run audit: attach the files in the chat-style box, press one button. The files are mapped, the metrics calculated and the deck claims read, in that
 * order; the page then opens the review screen. Each stage shows its progress; one that fails says what to do and has a Retry
 * stage button. Every existing page stays under Details. On load each stage shows what the audit already holds (stagesFromState),
 * and the files already uploaded are listed above the box.
 */
export default function RunAudit() {
  const { id } = useParams();
  const nav = useNavigate();
  const [audit, setAudit] = useState(null);
  const [asOf, setAsOf] = useState("");
  const [stored, setStored] = useState({ views: [], deckData: { decks: [], candidates: [] } });   // what the audit holds
  const [stages, setStages] = useState(idleStages());
  const [running, setRunning] = useState(false);
  const [leftover, setLeftover] = useState(null);       // the attached files the last run did not send; the box keeps only those
  const pick = useRef({ data: [], decks: [] });
  const started = useRef(false);                      // a run began: the stored state no longer sets the stages
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  // The audit's real state: its datasets, its results and its deck claims. A read that fails leaves that stage "Not started".
  const readStored = useCallback(async () => {
    const safe = (p, fallback) => p.catch(() => fallback);
    const [views, summary, deckData] = await Promise.all([
      safe(getDatasets(id), []), safe(getReview(id), null), safe(getDecks(id), { decks: [], candidates: [] })]);
    return { views, summary, deckData };
  }, [id]);
  const refreshStored = useCallback(async () => {
    const { views, deckData } = await readStored();
    if (alive.current) setStored({ views, deckData });
  }, [readStored]);

  useEffect(() => {
    getAudit(id).then((a) => { if (alive.current) { setAudit(a); setAsOf(asOfInputValue(a.as_of_month)); } }).catch(() => {});
    readStored().then((state) => {
      if (!alive.current) return;
      setStored({ views: state.views, deckData: state.deckData });
      if (!started.current) setStages(stagesFromState(state));
    });
    reportUsage(id, { screen: "run" });
  }, [id, readStored]);

  // The files attached in the box; a run sends them and takes each off the pick as it goes.
  const attach = useCallback((files) => { pick.current = splitFiles(files); }, []);
  const removeStoredDeck = async (deckId) => {
    try { await removeDeck(id, deckId); toast.success("Deck removed"); await refreshStored(); } catch (e) { toast.error("Could not remove the deck"); }
  };

  const update = useCallback((key, result) => { if (alive.current) setStages((s) => ({ ...s, [key]: result })); }, []);
  const start = useCallback(async (from) => {
    if (running) return;
    setRunning(true);
    started.current = true;
    if (from === "mapping") setStages(idleStages());
    setCalculatePressed(id);                       // the "revenue file missing" blocker shows from the first run, as after Map
    const out = await runAudit({ api: apiModule, auditId: id, pick: pick.current, from, onUpdate: update });
    window.dispatchEvent(new Event(BLOCKERS_CHANGED));
    if (!alive.current) return;
    setRunning(false);
    setLeftover([...pick.current.data, ...pick.current.decks]);
    refreshStored();
    if (out.status === "done" || out.status === "needs_review") nav(`/audit/${id}/review`);
  }, [id, running, update, nav, refreshStored]);

  if (!audit) {
    return <Layout audit={audit}><div className="flex justify-center py-32 text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /></div></Layout>;
  }
  const failed = STAGES.find((s) => stages[s.key].status === "failed");

  return (
    <Layout audit={audit}>
      <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 mb-1">Run audit</h1>
      <p className="text-sm text-slate-600 mb-6 max-w-3xl">
        Add the files and press Run audit. The columns are mapped, the metrics calculated and the deck claims read. You stop only
        where a decision is yours, on the review screen.
      </p>

      <AuditSetup audit={audit} setAudit={setAudit} asOf={asOf} setAsOf={setAsOf} />

      <UploadedFiles stored={stored} onRemoveDeck={removeStoredDeck} />

      <div className="mt-5">
        <UploadChat audit={audit} deferred onFiles={attach} leftover={leftover} />
      </div>

      <div className="mt-5 flex items-center gap-3">
        <Button data-testid="run-audit" onClick={() => start("mapping")} disabled={running} className="bg-sky-600 hover:bg-sky-500 gap-2">
          {running && <Loader2 className="h-4 w-4 animate-spin" />}{RUN_LABEL}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => nav(`/audit/${id}/review`)} data-testid="run-to-review">Go to the review screen</Button>
      </div>

      <ol className="mt-6 space-y-2 max-w-3xl" data-testid="run-stages">
        {STAGES.map((s) => {
          const st = stages[s.key];
          return (
            <li key={s.key} data-testid={`stage-${s.key}`} data-status={st.status}
              className="flex items-start gap-3 rounded-md border border-[#E5E7EB] bg-white px-4 py-3">
              <StageIcon status={st.status} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-slate-900">{s.label}</div>
                <div className="text-xs text-slate-600" data-testid={`stage-${s.key}-status`}>{STAGE_STATUS_TEXT[st.status]}</div>
                {st.message && <p className={`mt-1 text-xs ${st.status === "failed" ? "text-rose-800" : "text-slate-600"}`} data-testid={`stage-${s.key}-message`}>{st.message}</p>}
              </div>
              {st.status === "failed" && (
                <Button size="sm" variant="outline" disabled={running} data-testid={`retry-${s.key}`} onClick={() => start(s.key)}>{RETRY_LABEL}</Button>
              )}
            </li>
          );
        })}
      </ol>
      {failed && <p className="mt-2 text-xs text-slate-500">Nothing already done is lost: Retry stage carries on from the stage that failed.</p>}
    </Layout>
  );
}

function StageIcon({ status }) {
  if (status === "running") return <Loader2 className="h-4 w-4 mt-0.5 animate-spin text-sky-700" />;
  if (status === "done") return <Check className="h-4 w-4 mt-0.5 text-emerald-700" />;
  if (status === "failed") return <AlertTriangle className="h-4 w-4 mt-0.5 text-rose-700" />;
  if (status === "needs_review") return <AlertTriangle className="h-4 w-4 mt-0.5 text-amber-700" />;
  return <Circle className="h-4 w-4 mt-0.5 text-slate-400" />;
}

const dateOf = (iso) => (iso ? String(iso).slice(0, 10) : "—");

/** The files already uploaded for this audit: name, type, date. A deck has a remove control (it asks first); a data file is replaced by uploading another of its type. */
function UploadedFiles({ stored, onRemoveDeck }) {
  const [confirming, setConfirming] = useState(null);
  const rows = [
    ...stored.views.map((v) => ({ key: `data-${v.dtype}`, name: v.file, type: TYPE_LABELS[v.dtype] || v.dtype, at: v.uploaded_at })),
    ...stored.deckData.decks.map((d) => ({ key: `deck-${d.deck_id}`, name: d.file, type: "Deck", at: d.uploaded_at, deckId: d.deck_id })),
  ];
  return (
    <section className="mt-5 bg-white border border-[#E5E7EB] rounded-lg p-5" data-testid="run-uploaded">
      <h2 className="text-sm font-medium text-slate-900">Files already uploaded</h2>
      {rows.length === 0 ? <p className="mt-1 text-xs text-slate-500" data-testid="run-uploaded-none">No file has been uploaded for this audit yet.</p> : (
        <ul className="mt-2 space-y-1.5" data-testid="run-uploaded-list">
          {rows.map((r) => (
            <li key={r.key} data-testid="run-uploaded-row" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-700">
              <span className="font-mono">{r.name}</span>
              <span className="text-slate-500" data-testid="run-uploaded-type">{r.type}</span>
              <span className="font-mono text-slate-500" data-testid="run-uploaded-date">{dateOf(r.at)}</span>
              {r.deckId && (confirming === r.deckId ? (
                <span className="flex items-center gap-2" data-testid="run-remove-confirm">
                  <span className="text-rose-700">{REMOVE_DECK_CONFIRM}</span>
                  <Button size="sm" className="h-7 bg-rose-600 hover:bg-rose-500" data-testid="run-remove-yes" onClick={() => { setConfirming(null); onRemoveDeck(r.deckId); }}>Remove</Button>
                  <Button size="sm" variant="outline" className="h-7" onClick={() => setConfirming(null)}>Cancel</Button>
                </span>
              ) : (
                <Button size="sm" variant="outline" className="h-7" data-testid="run-remove-deck" aria-label={`Remove ${r.name}`} onClick={() => setConfirming(r.deckId)}>Remove deck</Button>
              ))}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
