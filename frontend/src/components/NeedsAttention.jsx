import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ColumnRow } from "@/components/UploadChat";
import { DefinitionCell, TurnoverCell } from "@/components/ClaimRegister";
import { BLOCKERS_CHANGED } from "@/lib/useBlockers";
import * as apiModule from "@/lib/api";
import { answerDefinitionCheck, answerTurnover, decideColumns, getDatasets, getDecks, updateCandidate } from "@/lib/api";
import { claimPeriod, claimValue, flagsText, scenarioText, sourceRef, typeLabel } from "@/lib/deckClaims";
import { definitionOf, turnoverHeading, turnoverOf } from "@/lib/claimRegister";
import { MAPPING_HEADERS, S13_status } from "@/lib/chatUpload";
import { ATTENTION_HEADING, SHOWN_QUESTIONS, attentionCount, lessLabel, moreLabel, openQuestions, openViews } from "@/lib/attention";
import { describeRequestError } from "@/lib/requestError";
import { runAudit } from "@/lib/runAudit";

const safe = (call, fallback) => Promise.resolve().then(call).catch(() => fallback);

function MappingCard({ item, decide, lastReason, setLastReason }) {
  const { view, row } = item;
  return (
    <div data-testid="attention-mapping">
      <div className="text-xs font-medium text-slate-900">{view.file} <span className="font-mono text-amber-700">· {S13_status(view)}</span></div>
      <table className="w-full text-xs mt-1">
        <thead><tr className="text-left text-slate-500 border-b border-[#E5E7EB]">{MAPPING_HEADERS.map((h, i) => <th key={i} className="py-1.5 pr-3 font-medium">{h}</th>)}</tr></thead>
        <tbody><ColumnRow row={row} view={view} decide={decide} lastReason={lastReason} setLastReason={setLastReason} /></tbody>
      </table>
    </div>
  );
}

function ClaimCard({ item, busy, act, auditId }) {
  const { c } = item;
  const asks = definitionOf(c).open;
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 text-xs" data-testid="attention-claim">
      <div>
        <div className="text-slate-900">{typeLabel(c.claim_type)} · <span className="font-mono">{claimValue(c)}</span> · <span className="font-mono text-slate-600">{claimPeriod(c)}</span></div>
        {scenarioText(c) && <div className="text-[10px] font-mono text-slate-500">{scenarioText(c)}</div>}
        <div className="font-mono text-slate-500">{sourceRef(c.sources?.[0])}</div>
        {flagsText(c) && <div className="mt-1 text-[10px] border rounded px-1.5 py-0.5 max-w-[24rem] text-amber-800 border-amber-500/50 bg-amber-50" data-testid="attention-claim-flags">{flagsText(c)}</div>}
      </div>
      <div className="whitespace-nowrap">
        {asks ? (
          definitionOf(c).views.filter((v) => v.definition_check === "ask").map((v) => (
            <DefinitionCell key={v.claim_id} row={v} heading={c.by_period?.length ? v.period : undefined}
              onAnswer={(row, value) => act(row.claim_id, () => answerDefinitionCheck(auditId, row.claim_id, value))} />
          ))
        ) : (
          <>
            <Button size="sm" variant="outline" className="h-7 mr-1.5" disabled={busy !== null} data-testid="attention-keep"
              onClick={() => act(c.id, () => updateCandidate(auditId, c.id, { status: "approved" }))}>Keep</Button>
            <Button size="sm" variant="ghost" className="h-7" disabled={busy !== null} data-testid="attention-reject"
              onClick={() => act(c.id, () => updateCandidate(auditId, c.id, { status: "rejected" }))}>Not a company claim</Button>
          </>
        )}
      </div>
    </div>
  );
}

function TurnoverCard({ item, answer }) {
  const { c } = item;
  return (
    <div className="text-xs" data-testid="attention-turnover">
      <div className="text-slate-900">{typeLabel(c.claim_type)} · <span className="font-mono">{claimValue(c)}</span> · <span className="font-mono">{claimPeriod(c)}</span></div>
      {turnoverOf(c).views.map((v) => <TurnoverCell key={v.claim_id} row={v} onAnswer={answer} heading={turnoverHeading(v, Boolean(c.by_period?.length))} />)}
    </div>
  );
}

/** The questions that wait for the analyst, as cards on the Audit page: at most three, the rest behind "n more". An answer closes
 *  the card and the page reads the results again; nothing is deleted. Hidden at 0. `computed` is false while the results do not
 *  exist yet: the last answered column then carries the run on, as Review did. */
export default function NeedsAttention({ auditId, computed = true, onChanged }) {
  const [views, setViews] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [attention, setAttention] = useState([]);
  const [all, setAll] = useState(false);
  const [busy, setBusy] = useState(null);
  const [lastReason, setLastReason] = useState("header_misleading");
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const reload = useCallback(async () => {
    const [v, d] = await Promise.all([safe(() => getDatasets(auditId), []), safe(() => getDecks(auditId), { decks: [], candidates: [] })]);
    if (!alive.current) return;
    setViews(v || []); setCandidates(d?.candidates || []); setAttention(d?.attention || []);
    return v || [];
  }, [auditId]);
  useEffect(() => { reload(); }, [reload]);

  const changed = useCallback(async () => {
    await reload();
    window.dispatchEvent(new Event(BLOCKERS_CHANGED));
    if (onChanged) onChanged();
  }, [reload, onChanged]);

  const act = async (key, fn) => {
    setBusy(key);
    try { await fn(); await changed(); } catch (e) { toast.error(describeRequestError(e).message); } finally { if (alive.current) setBusy(null); }
  };
  const decide = async (view, decisions) => {
    const next = await decideColumns(auditId, view.dtype, decisions);
    const fresh = await reload();
    if (!computed && openViews(fresh).length === 0) {
      await runAudit({ api: apiModule, auditId, from: "mapping" });
      await changed();
    } else await changed();
    return next;
  };
  const answer = async (row, payload) => {
    try { await answerTurnover(auditId, row.claim_id, payload); await changed(); } catch (e) { toast.error(describeRequestError(e).message); throw e; }
  };

  const questions = openQuestions(views, candidates, attention);
  if (!questions.length) return null;
  const shown = all ? questions : questions.slice(0, SHOWN_QUESTIONS);
  const more = questions.length - SHOWN_QUESTIONS;
  return (
    <section className="mb-6 rounded-md border border-amber-300 bg-amber-50/40 p-4" data-testid="needs-attention">
      <h2 className="font-heading text-lg font-semibold text-slate-900">{ATTENTION_HEADING}</h2>
      <p className="text-xs text-slate-600 mb-2" data-testid="attention-count">{attentionCount(questions.length)}</p>
      <ul className="space-y-3">
        {shown.map((item) => (
          <li key={item.key} className="rounded-md border border-[#E5E7EB] bg-white p-3" data-testid="attention-card">
            {item.kind === "mapping" && <MappingCard item={item} decide={decide} lastReason={lastReason} setLastReason={setLastReason} />}
            {item.kind === "claim" && <ClaimCard item={item} busy={busy} act={act} auditId={auditId} />}
            {item.kind === "turnover" && <TurnoverCard item={item} answer={answer} />}
          </li>
        ))}
      </ul>
      {more > 0 && (
        <button type="button" className="mt-2 text-xs text-sky-700 underline underline-offset-2" aria-expanded={all} data-testid="attention-more" onClick={() => setAll((a) => !a)}>
          {all ? lessLabel : moreLabel(more)}
        </button>
      )}
    </section>
  );
}
