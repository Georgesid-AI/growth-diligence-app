import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import DateField from "@/components/DateField";
import { DefinitionCell, TurnoverCell } from "@/components/ClaimRegister";
import { CandidateRow } from "@/components/DeckPanel";
import { BLOCKERS_CHANGED } from "@/lib/useBlockers";
import { answerCorrection, answerDefinitionCheck, answerSales, answerTurnover, chooseGroup, getClaimRegister, getDecks, keepUndated, undoGroupChoice, updateCandidate } from "@/lib/api";
import { CHOOSE_FIGURE, CHOSEN, CLAIMS_LIST_ID, EXCLUDE, EXCLUDE_REASON, KEPT_NOTE, OPEN_CLAIMS, TOO_MANY_NOTE, UNDO_CHOICE, figureText, questionTitle, sourceText, tooMany } from "@/lib/claimGroups";
import { EDIT_REASONS } from "@/lib/deckClaims";
import { POPULATION_ANSWERS, POPULATION_QUESTION, asksPopulationOnly, claimPeriod, claimValue, flagsText, scenarioText, sourceRef, typeLabel, waitingCorrections } from "@/lib/deckClaims";
import { definitionOf, turnoverHeading, turnoverOf } from "@/lib/claimRegister";
import { ATTENTION_HEADING, KEEP_UNDATED, SALES_ANSWERS, UNDATED_ACTION, undatedTitle, SALES_QUESTION, SHOWN_QUESTIONS, addsUpText, attentionCount, salesCount, lessLabel, moreLabel, openQuestions } from "@/lib/attention";
import { describeRequestError } from "@/lib/requestError";

const safe = (call, fallback) => Promise.resolve().then(call).catch(() => fallback);

function ClaimCard({ item, busy, act, auditId, addsUp }) {
  const { c } = item;
  const asks = definitionOf(c).open;
  const legend = waitingCorrections(c).some((e) => e.field === "segment");      // a legend item names the figure: Keep would make a slice a rival total
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 text-xs" data-testid="attention-claim">
      <div>
        <div className="text-slate-900">{typeLabel(c.claim_type)} · <span className="font-mono">{claimValue(c)}</span> · <span className="font-mono text-slate-600">{claimPeriod(c)}</span></div>
        {scenarioText(c) && <div className="text-[10px] font-mono text-slate-500">{scenarioText(c)}</div>}
        <div className="font-mono text-slate-500">{sourceRef(c.sources?.[0])}</div>
        {legend && addsUp && <div className="text-[11px] text-slate-700" data-testid="attention-adds-up">{addsUpText(addsUp)}</div>}
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
            {waitingCorrections(c).map((e) => e.options.map((o, i) => (
              <Button key={`${e.index}-${i}`} size="sm" variant="outline" className="h-7 mr-1.5" disabled={busy !== null} data-testid="attention-correction"
                title={`Use ${e.field}: ${o.value}`}
                onClick={() => act(c.id, () => answerCorrection(auditId, c.id, { index: e.index, action: "choose", option: i }))}>{o.value}</Button>
            )))}
            {!legend && (
              <Button size="sm" variant="outline" className="h-7 mr-1.5" disabled={busy !== null} data-testid="attention-keep"
                onClick={() => act(c.id, () => updateCandidate(auditId, c.id, { status: "approved" }))}>Keep</Button>
            )}
            <Button size="sm" variant="ghost" className="h-7" disabled={busy !== null} data-testid="attention-reject"
              onClick={() => act(c.id, () => updateCandidate(auditId, c.id, { status: "rejected" }))}>Not a company claim</Button>
          </>
        )}
      </div>
    </div>
  );
}

/** A question the groups raise (docs/specs/claim-groups.md section 5): which annual figure, with each candidate, its source
 *  and the reconciliation hint. Nothing is selected for the analyst. A figure passed over stays a claim; it can be excluded here with a reason,
 *  or corrected or scoped in the claims list. A conflict that stays after a choice offers Undo. */
function GroupCard({ item, busy, act, auditId }) {
  const q = item.q;
  const [reason, setReason] = useState("");
  const chosen = q.candidates.some((c) => c.chosen);
  if (q.kind === "segment_size") {         // a slice larger than the company total: nothing to choose, the figures are listed and the claims list is where they are corrected
    return (
      <div className="text-xs" data-testid="attention-group">
        <div className="text-slate-900 font-medium" data-testid="attention-group-title">{questionTitle(q)}</div>
        <div className="text-amber-800 mb-1" data-testid="attention-group-reason">{q.reason}</div>
        <ul className="space-y-1">
          {q.candidates.map((c) => (
            <li key={c.identity} data-testid="attention-group-candidate">
              <span className="font-mono text-slate-900">{figureText(c)}</span>
              {c.hint && <span className="text-slate-700"> · {c.hint}</span>}
              <span className="font-mono text-slate-500"> · {sourceText(c)}</span>
            </li>
          ))}
        </ul>
        <Button size="sm" variant="outline" className="h-7 mt-1" data-testid="attention-group-open-claims"
          onClick={() => document.getElementById(CLAIMS_LIST_ID)?.scrollIntoView({ behavior: "smooth", block: "start" })}>{OPEN_CLAIMS}</Button>
      </div>
    );
  }
  return (
    <div className="text-xs" data-testid="attention-group">
      <div className="text-slate-900 font-medium" data-testid="attention-group-title">{questionTitle(q)}</div>
      <div className="text-amber-800 mb-1" data-testid="attention-group-reason">{q.reason}</div>
      {tooMany(q) && (
        <div className="flex flex-wrap items-center gap-2" data-testid="attention-group-too-many-line">
          <span className="text-slate-900" data-testid="attention-group-too-many">{TOO_MANY_NOTE(q.candidates.length)}</span>
          <Button size="sm" variant="outline" className="h-7" data-testid="attention-group-open-claims"
            onClick={() => document.getElementById(CLAIMS_LIST_ID)?.scrollIntoView({ behavior: "smooth", block: "start" })}>{OPEN_CLAIMS}</Button>
        </div>
      )}
      <ul className="space-y-1.5">
        {(tooMany(q) ? [] : q.candidates).map((c) => (
          <li key={c.identity} className="flex flex-wrap items-start justify-between gap-2" data-testid="attention-group-candidate">
            <div>
              <span className="font-mono text-slate-900">{figureText(c)}</span>
              <span className="font-mono text-slate-500"> · {sourceText(c)}</span>
              {c.hint && <div className="text-[11px] text-slate-600" data-testid="attention-group-hint">{c.hint}</div>}
            </div>
            <div className="whitespace-nowrap">
              {c.chosen ? <span className="text-[11px] font-mono text-slate-600 mr-1.5" data-testid="attention-group-chosen">{CHOSEN}</span> : (
                <Button size="sm" variant="outline" className="h-7 mr-1.5" disabled={busy !== null} data-testid="attention-group-choose"
                  onClick={() => act(q.id, () => chooseGroup(auditId, q.id, c.identity))}>{CHOOSE_FIGURE}</Button>
              )}
              {!c.chosen && (c.claim_ids || [c.claim_id]).every((id) => !String(id).includes("#")) && (
                <>
                  <select value={reason} onChange={(e) => setReason(e.target.value)} className="h-7 rounded-md border border-[#E5E7EB] bg-white px-1 text-xs mr-1.5" data-testid="attention-group-reason-select" aria-label={EXCLUDE_REASON}>
                    <option value="">{EXCLUDE_REASON}</option>
                    {EDIT_REASONS.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                  </select>
                  <Button size="sm" variant="ghost" className="h-7" disabled={busy !== null || !reason} data-testid="attention-group-exclude"
                    onClick={() => act(q.id, () => Promise.all((c.claim_ids || [c.claim_id]).map((id) => updateCandidate(auditId, id.split("#")[0], { status: "rejected", reason }))))}>{EXCLUDE}</Button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[11px] text-slate-500" data-testid="attention-group-kept">{KEPT_NOTE}</p>
      {chosen && (
        <Button size="sm" variant="ghost" className="h-7 mt-1" disabled={busy !== null} data-testid="attention-group-undo"
          onClick={() => act(q.id, () => undoGroupChoice(auditId, q.id))}>{UNDO_CHOICE}</Button>
      )}
    </div>
  );
}

/** The undated figures of one page (George, 2026-10-27): one card, one date applied to every one of them, or all kept without a period. */
function UndatedCard({ item, busy, act, auditId }) {
  const [date, setDate] = useState("");
  const ids = item.cs.map((c) => c.id);
  return (
    <div className="text-xs" data-testid="attention-undated">
      <div className="text-slate-900 font-medium" data-testid="attention-undated-title">{undatedTitle(item.n, item.page)}</div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-48"><DateField value={date} onChange={setDate} testId="attention-undated-date" clearable /></div>
        <Button size="sm" variant="outline" className="h-7" disabled={busy !== null || !date} data-testid="attention-undated-set"
          onClick={() => act(item.key, () => Promise.all(ids.map((id) => updateCandidate(auditId, id, { target_date: date }))))}>{UNDATED_ACTION}</Button>
        <Button size="sm" variant="ghost" className="h-7" disabled={busy !== null} data-testid="attention-undated-keep"
          onClick={() => act(item.key, () => keepUndated(auditId, ids))}>{KEEP_UNDATED}</Button>
      </div>
    </div>
  );
}

/** "Is 'Sales' in this deck revenue or bookings?": one card per deck; the answer applies to every Sales claim of the deck. */
function SalesCard({ item, busy, act, auditId }) {
  const { q } = item;
  return (
    <div className="text-xs" data-testid="attention-sales">
      <div className="text-slate-900 font-medium" data-testid="attention-sales-title">{SALES_QUESTION}</div>
      <div className="text-slate-600 mb-1.5">{q.file} · {salesCount(q.claims)}</div>
      {SALES_ANSWERS.map(([value, label]) => (
        <Button key={value} size="sm" variant="outline" className="h-7 mr-1.5" disabled={busy !== null} data-testid={`attention-sales-${value}`}
          onClick={() => act(`sales-${q.deck_id}`, () => answerSales(auditId, q.deck_id, value))}>{label}</Button>
      ))}
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

/** A claim in the register that its own reason asks the analyst to set or confirm (a period not read, a required field unknown): the claim as
 *  the claims list prints it, with that list's own editor. */
function SetCard({ item, save, answer }) {
  if (asksPopulationOnly(item.reason)) {
    return (
      <div className="text-xs" data-testid="attention-population">
        <div className="text-slate-900 mb-1">{typeLabel(item.c.claim_type)} · <span className="font-mono">{claimValue(item.c)}</span> · <span className="font-mono text-slate-600">{claimPeriod(item.c)}</span></div>
        <div className="text-amber-800 mb-1.5" data-testid="attention-set-reason">{POPULATION_QUESTION}</div>
        {POPULATION_ANSWERS.map(([population, label]) => (
          <Button key={population} size="sm" variant="outline" className="h-7 mr-1.5" data-testid={`attention-population-${population}`}
            onClick={() => save(item.c, { population })}>{label}</Button>
        ))}
      </div>
    );
  }
  return (
    <div className="text-xs" data-testid="attention-set">
      <div className="text-amber-800 mb-1" data-testid="attention-set-reason">{item.reason}</div>
      <table className="w-full"><tbody><CandidateRow candidate={item.c} onSave={save} onAnswer={answer} /></tbody></table>
    </div>
  );
}

/** The questions that wait for the analyst, as cards on the Audit page: at most three, the rest behind "n more". An answer closes
 *  the card and the page reads the results again; nothing is deleted. Hidden at 0. `computed` is false while the results do not
 *  exist yet: the last answered column then carries the run on, as Review did. */
export default function NeedsAttention({ auditId, computed = true, onChanged }) {
  const [candidates, setCandidates] = useState([]);
  const [attention, setAttention] = useState([]);
  const [groups, setGroups] = useState(null);
  const [sales, setSales] = useState([]);
  const [all, setAll] = useState(false);
  const [busy, setBusy] = useState(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const reload = useCallback(async () => {
    const [d, g] = await Promise.all([safe(() => getDecks(auditId), { decks: [], candidates: [] }), safe(() => getClaimRegister(auditId), null)]);
    if (!alive.current) return;
    setCandidates(d?.candidates || []); setAttention(d?.attention || []); setSales(d?.sales_questions || []); setGroups(g);
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
  const answer = async (row, payload) => {
    try { await answerTurnover(auditId, row.claim_id, payload); await changed(); } catch (e) { toast.error(describeRequestError(e).message); throw e; }
  };

  // the claims list's save: true once stored, false after a refusal (the toast names it)
  const save = async (candidate, payload) => {
    try { await updateCandidate(auditId, candidate.id, payload); await changed(); return true; } catch (e) { toast.error(describeRequestError(e).message); return false; }
  };

  const questions = openQuestions(candidates, attention, groups, sales);
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
            {item.kind === "claim" && <ClaimCard item={item} busy={busy} act={act} auditId={auditId} addsUp={attention.find((a) => a.id === item.c.id)?.adds_up_to} />}
            {item.kind === "sales" && <SalesCard item={item} busy={busy} act={act} auditId={auditId} />}
            {item.kind === "turnover" && <TurnoverCard item={item} answer={answer} />}
            {item.kind === "undated" && <UndatedCard item={item} busy={busy} act={act} auditId={auditId} />}
            {item.kind === "set" && <SetCard item={item} save={save} answer={answer} />}
            {item.kind === "group" && <GroupCard item={item} busy={busy} act={act} auditId={auditId} />}
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
