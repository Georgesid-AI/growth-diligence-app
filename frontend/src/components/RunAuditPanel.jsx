import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Check, Clock, Circle } from "lucide-react";
import { BLOCKERS_CHANGED } from "@/components/BlockerBanner";
import * as apiModule from "@/lib/api";
import { continueWithoutPages, getDatasets, getDecks, getReview } from "@/lib/api";
import { setCalculatePressed } from "@/lib/chatUpload";
import { RETRY_LABEL, RUN_LABEL, STAGES, firstStageNotDone, idleStages, runAudit, stagesFromState } from "@/lib/runAudit";
import { OPEN_UNCERTAIN, UNCERTAIN_NOTICE_LINK, readiness, steps, uncertainNotice } from "@/lib/uploadView";

/**
 * The run card (docs/design/audit-page-mockup.html): Run audit, the line beside it saying what it waits for, and the two steps - Reading and checking files,
 * Calculating results. The first follows the files the cards list (lib/uploadView.js); the second follows the run's own stages
 * (lib/runAudit.js). Run audit is held while any file is being read. Files are sent the moment they are picked, so a run sends none: it calculates
 * from what the audit holds, from the first stage that is not done, and the Audit page opens when it is done. A stage that fails says what to do and
 * has a Retry stage button.
 */
export default function RunAuditPanel({ auditId, sheets = [], decks = [], now = Date.now(), readClock, onRunning, uncertain = 0 }) {
  const nav = useNavigate();
  const [stages, setStages] = useState(idleStages());
  const [running, setRunning] = useState(false);
  const [clock, setClock] = useState({ start: null, end: null, tick: Date.now() });
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

  useEffect(() => {
    if (!running) return undefined;
    const t = setInterval(() => setClock((c) => ({ ...c, tick: Date.now() })), 1000);
    return () => clearInterval(t);
  }, [running]);

  const update = useCallback((key, result) => { if (alive.current) setStages((s) => ({ ...s, [key]: result })); }, []);
  const start = useCallback(async (stage) => {
    if (running) return;
    setRunning(true);
    onRunning?.(true);
    started.current = true;
    setClock({ start: Date.now(), end: null, tick: Date.now() });
    // Run audit asks the audit where it stands now (a mapping may have been confirmed since the last run) and carries on from there.
    let from = stage;
    if (!from) {
      const read = await readState();
      from = firstStageNotDone(read);
      if (alive.current) setStages(read);
    }
    setCalculatePressed(auditId);                  // the "revenue file missing" blocker shows from the first run
    const out = await runAudit({ api: apiModule, auditId, from, onUpdate: update });
    window.dispatchEvent(new Event(BLOCKERS_CHANGED));
    onRunning?.(false);
    if (!alive.current) return;
    setRunning(false);
    setClock((c) => ({ ...c, end: Date.now() }));
    if (out.status === "done") nav(`/audit/${auditId}/dashboard`);
  }, [auditId, running, update, nav, onRunning, readState]);

  // "Continue without page N": offered on the claims failure for a page that can never be read; stored on the server, then the stage runs again.
  const offers = (stages.claims.status === "failed" && stages.claims.can_continue) || [];
  const continueWithout = useCallback(async (offer) => {
    try { await continueWithoutPages(auditId, offer.deck_id, offer.pages.map((p) => p.page)); } catch (e) { return; }
    start("claims");
  }, [auditId, start]);

  const ready = readiness(sheets, decks);
  // Calculating results follows the engine and claims stages of the run.
  const later = [stages.engine, stages.claims];
  const calcStatus = later.some((s) => s.status === "failed") ? "failed" : later.some((s) => s.status === "running") ? "running"
    : later.every((s) => s.status === "done") ? "done" : "idle";
  const seconds = clock.start ? ((clock.end ?? clock.tick) - clock.start) / 1000 : null;
  const rows = steps(sheets, decks, { status: calcStatus, seconds }, now, readClock, uncertain);
  const notice = uncertainNotice(uncertain);
  const failed = STAGES.find((s) => stages[s.key].status === "failed");
  const retryable = failed ? stages[failed.key].retryable : undefined;          // false: the token cap stopped the claims; the same run would be refused again

  return (
    <section className="panel" data-testid="run-audit-panel">
      {notice && (
        <p className="note" data-testid="uncertain-notice">
          {notice}{" "}
          <a href="#uncertain-list" onClick={(e) => { e.preventDefault(); window.dispatchEvent(new Event(OPEN_UNCERTAIN)); }}>{UNCERTAIN_NOTICE_LINK}</a>
        </p>
      )}
      <div className="runrow">
        <button type="button" className="btn" data-testid="run-audit" disabled={running || ready.held} onClick={() => start()}>{RUN_LABEL}</button>
        <p data-testid="run-readiness">{ready.text}</p>
      </div>
      <div className="steps" data-testid="run-steps">
        {rows.map((r) => (
          <div key={r.key} className={`step ${r.tone === "run" ? "run" : r.tone === "done" ? "done" : r.tone === "bad" ? "bad" : "wait"}`} data-testid={`step-${r.key}`} data-tone={r.tone}>
            <StepIcon tone={r.tone} />
            <b>{r.label}</b>
            <span className={r.tone === "run" || r.tone === "done" ? "t" : ""} data-testid={`step-${r.key}-second`}>{r.second}</span>
            {r.error && <p className="bad" role="alert" data-testid={`step-${r.key}-error`}>{r.error}</p>}
          </div>
        ))}
      </div>
      {failed && (
        <div className="stage-failed" data-testid={`stage-${failed.key}`} data-status="failed">
          {stages[failed.key].message && <p className="bad" role="alert" data-testid={`stage-${failed.key}-message`}>{stages[failed.key].message}</p>}
          {offers.map((o) => (
            <button key={o.deck_id} type="button" className="btn quiet" disabled={running} data-testid={`continue-without-${o.deck_id}`} onClick={() => continueWithout(o)}>
              {`Continue without page ${o.pages.map((p) => p.page).join(", ")}`}
            </button>
          ))}
          <button type="button" className="btn quiet" disabled={running || retryable === false} data-testid={`retry-${failed.key}`} onClick={() => start(failed.key)}>{RETRY_LABEL}</button>
          {retryable !== false && <p className="muted">Nothing already done is lost: Retry stage carries on from the stage that failed.</p>}
        </div>
      )}
    </section>
  );
}

function StepIcon({ tone }) {
  const props = { width: 18, height: 18, "aria-hidden": true };
  if (tone === "done") return <Check {...props} />;
  if (tone === "run") return <Clock {...props} />;
  if (tone === "bad") return <AlertTriangle {...props} />;
  return <Circle {...props} />;
}
