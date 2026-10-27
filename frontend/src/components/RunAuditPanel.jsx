import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { Check, Circle, Loader2, AlertTriangle } from "lucide-react";
import { BLOCKERS_CHANGED } from "@/components/BlockerBanner";
import { Button } from "@/components/ui/button";
import * as apiModule from "@/lib/api";
import { getDatasets, getDecks, getReview } from "@/lib/api";
import { setCalculatePressed } from "@/lib/chatUpload";
import { RETRY_LABEL, RUN_BUTTON_CLASS, RUN_LABEL, STAGES, STAGE_STATUS_TEXT, firstStageNotDone, idleStages, runAudit, stagesFromState } from "@/lib/runAudit";

/**
 * Run audit, on the Upload & Mapping page (docs/specs/chat-upload.md section 24): one button, then the files attached in the
 * page's box are mapped, the metrics calculated and the deck claims read, in that order; the Audit page opens when the run is
 * done or waits for the analyst. It is the only way to calculate: it carries on from the first stage that is not done, and the
 * engine counts as not done when a mapping was confirmed or corrected after the last calculation. Each stage shows its progress; one that fails says what to do and has a Retry stage button.
 * On load each stage shows what the audit already holds (stagesFromState).
 *
 * `pick` is a ref to {data, decks}, the attached files not yet sent; `onRan(leftover)` hands back the ones the run did not send;
 * `onRunning(bool)` lets the page hold Map while a run is in progress; `blocked` holds this button while it runs.
 * `topHost` is an element at the top of the page: a second Run audit button is drawn into it (George, 2026-10-27); it and the one below share this
 * panel's run, so they are one run and one state.
 */
export default function RunAuditPanel({ auditId, pick, onRan, onRunning, blocked = false, topHost = null }) {
  const nav = useNavigate();
  const [stages, setStages] = useState(idleStages());
  const [running, setRunning] = useState(false);
  const started = useRef(false);                      // a run began: the stored state no longer sets the stages
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  // The audit's real state: its datasets, its results and its deck claims. A read that fails leaves that stage "Not started".
  const readState = useCallback(() => {
    const safe = (p, fallback) => p.catch(() => fallback);
    return Promise.all([safe(getDatasets(auditId), []), safe(getReview(auditId), null), safe(getDecks(auditId), { decks: [], candidates: [] })])
      .then(([views, summary, deckData]) => stagesFromState({ views, summary, deckData }));
  }, [auditId]);
  useEffect(() => {
    readState().then((read) => { if (alive.current && !started.current) setStages(read); });
  }, [readState]);

  const update = useCallback((key, result) => { if (alive.current) setStages((s) => ({ ...s, [key]: result })); }, []);
  const start = useCallback(async (stage) => {
    if (running) return;
    setRunning(true);
    onRunning?.(true);
    started.current = true;
    // Run audit asks the audit where it stands now (a mapping may have been confirmed since the last run) and carries on from there.
    let from = stage;
    if (!from) {
      const read = await readState();
      from = firstStageNotDone(read, pick.current);
      if (alive.current) setStages(read);
    }
    setCalculatePressed(auditId);                  // the "revenue file missing" blocker shows from the first run, as after Map
    const out = await runAudit({ api: apiModule, auditId, pick: pick.current, from, onUpdate: update });
    window.dispatchEvent(new Event(BLOCKERS_CHANGED));
    onRunning?.(false);
    if (!alive.current) return;
    setRunning(false);
    onRan?.([...pick.current.data, ...pick.current.decks]);
    if (out.status === "done" || out.status === "needs_review") nav(`/audit/${auditId}/dashboard`);
  }, [auditId, running, update, nav, pick, onRan, onRunning, readState]);

  const runButton = (testId) => (
    <Button data-testid={testId} onClick={() => start()} disabled={running || blocked} className={`bg-sky-600 hover:bg-sky-500 gap-2 ${RUN_BUTTON_CLASS}`}>
      {running && <Loader2 className="h-4 w-4 animate-spin" />}{RUN_LABEL}
    </Button>
  );
  const failed = STAGES.find((s) => stages[s.key].status === "failed");
  return (
    <section className="mt-5" data-testid="run-audit-panel">
      <p className="text-sm text-slate-600 mb-3 max-w-3xl">
        Attach the files in the box below and press Run audit. The columns are mapped, the metrics calculated and the deck claims read.
        You stop only where a decision is yours, on the Audit page.
      </p>
      {runButton("run-audit")}
      {topHost && createPortal(runButton("run-audit-top"), topHost)}

      <ol className="mt-4 space-y-2 max-w-3xl" data-testid="run-stages">
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
                <Button size="sm" variant="outline" disabled={running || blocked} data-testid={`retry-${s.key}`} onClick={() => start(s.key)}>{RETRY_LABEL}</Button>
              )}
            </li>
          );
        })}
      </ol>
      {failed && <p className="mt-2 text-xs text-slate-500">Nothing already done is lost: Retry stage carries on from the stage that failed.</p>}
    </section>
  );
}

function StageIcon({ status }) {
  if (status === "running") return <Loader2 className="h-4 w-4 mt-0.5 animate-spin text-sky-700" />;
  if (status === "done") return <Check className="h-4 w-4 mt-0.5 text-emerald-700" />;
  if (status === "failed") return <AlertTriangle className="h-4 w-4 mt-0.5 text-rose-700" />;
  if (status === "needs_review") return <AlertTriangle className="h-4 w-4 mt-0.5 text-amber-700" />;
  return <Circle className="h-4 w-4 mt-0.5 text-slate-400" />;
}
