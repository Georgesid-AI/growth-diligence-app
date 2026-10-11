import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Provenance } from "@/components/Provenance";
import DateField from "@/components/DateField";
import { answerTurnover, claimsCsvUrl, getClaimRegister, updateClaimInputs } from "@/lib/api";
import {
  DOWNLOAD_LABEL, GATE_BUDGET_MAX, GATE_DIRECTIONS, GATE_METRIC_MAX, GATE_METRIC_PLACEHOLDER, GATE_NEEDED, KEY_GATE_LABEL, NO_METRIC, OTHER_DECISION, PREFILLED, gateDraft,
  REGISTER_COLUMNS, REGISTER_HEADING, TURNOVER_QUESTION, answerReady, reasonsFor, claimCellText, rateHover, takeRateText, evidenceLines, gapText, gateContext, gateEdit, metricOptions, needsMetricName,
  observedText, overlapsText, readingText, registerRows, segmentOptions, valueAtStakeText,
} from "@/lib/claimRegister";
import { CALCULATE_CLASS } from "@/lib/chatUpload";
import { useGateEdits } from "@/lib/useGateEdits";
import { describeRequestError } from "@/lib/requestError";
import { seeGlossary } from "@/lib/glossary";
import FxText from "@/components/FxText";
import { NO_DATE } from "@/lib/deckClaims";

// The button the dropdown points at is drawn like Map and Compute; the other is the same style, paler. Any other reason: both pale.
const ACTIVE_REASON = { deck_says_gross_revenue: "revenue", deck_says_processed_volume: "volume" };
const selectClass ="h-8 rounded-md border border-[#E5E7EB] bg-white px-2 text-xs max-w-[11rem]";
const LABEL_STYLE = {
  Verified: "text-emerald-800 border-emerald-500/50 bg-emerald-50",
  Contradicted: "text-rose-800 border-rose-500/50 bg-rose-50",
  Unverified: "text-amber-800 border-amber-500/50 bg-amber-50",
  Unsupported: "text-slate-700 border-slate-400/60 bg-slate-50",
};

// The options of a select, with the stored choice kept in the list even when it is no longer offered.
const withCurrent = (options, current) => (options.includes(current) ? options : [...options, current]);

/** The gate: the claimed and observed figures beside the threshold, the budget decision and the date. A gate not yet saved starts
 *  with the server's prefill (docs/specs/verdict-and-memo.md section 3), each prefilled field marked until the analyst edits or saves
 *  it; the budget decision starts blank. Nothing is saved until the threshold, the decision and the date are all filled; a row with
 *  no metric of the app also needs the analyst's metric and its direction. `edits` holds only what the analyst changed. */
export function GateCell({ row, ccy, onSave, prefill, budgets = [], edits, onEdit }) {
  const { draft, prefilled } = gateDraft(row, prefill, edits);
  const context = gateContext(row, ccy);
  const named = needsMetricName(row);
  const set = (k) => (e) => onEdit(row, { [k]: e.target.value });
  const options = budgets.includes(row.gate_budget_decision) || !row.gate_budget_decision ? budgets : [...budgets, row.gate_budget_decision];
  const other = edits?.budgetOther;
  const pick = (value) => (value === OTHER_DECISION ? onEdit(row, { budgetOther: true, budget: "" }) : onEdit(row, { budgetOther: false, budget: value }));
  const mark = (field) => prefilled.includes(field) && <span className="text-[10px] font-mono text-sky-700" data-testid={`register-gate-prefilled-${field}`}>{PREFILLED}</span>;
  const save = () => {
    let edit;
    try { edit = gateEdit(row, draft); } catch (e) { toast.error(e.message); return; }
    if (draft.key && !row.key_gate && !row.gate_saved) edit.key_gate = true;
    if (Object.keys(edit).length) onSave(row, edit).catch(() => {});
  };
  return (
    <div className="max-w-xs space-y-1">
      {row.gate_needed && <div className="text-[10px] font-mono text-amber-800" data-testid="register-gate-needed">{GATE_NEEDED}</div>}
      <div className="text-slate-600" data-testid="register-gate-context">{context}</div>
      {row.gate_sentence && <div className="text-slate-800" data-testid="register-gate-sentence">{seeGlossary(row.gate_sentence)}</div>}
      {row.gate_saved && <div className="text-[10px] font-mono text-emerald-700" data-testid="register-gate-saved">Gate saved</div>}
      {named && (
        <div className="flex gap-1 flex-wrap">
          <Input value={draft.metricName} onChange={set("metricName")} maxLength={GATE_METRIC_MAX} placeholder={GATE_METRIC_PLACEHOLDER} className="h-7 text-xs" data-testid="register-gate-metric-name" />
          <select value={draft.direction} onChange={set("direction")} className={selectClass} data-testid="register-gate-direction">
            <option value="" />
            {GATE_DIRECTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          {mark("metricName")}
        </div>
      )}
      <Input value={draft.threshold} onChange={set("threshold")} placeholder="Threshold" inputMode="decimal" className="h-7 text-xs font-mono" data-testid="register-gate-threshold" />
      {mark("threshold")}
      {options.length ? (
        <select value={other ? OTHER_DECISION : draft.budget} onChange={(e) => pick(e.target.value)} className={`${selectClass} w-full`} data-testid="register-gate-budget-pick">
          <option value="">Budget decision…</option>
          {options.map((d) => <option key={d} value={d}>{d}</option>)}
          <option value={OTHER_DECISION}>{OTHER_DECISION}</option>
        </select>
      ) : null}
      {(other || !options.length) && (
        <Input value={draft.budget} onChange={set("budget")} maxLength={GATE_BUDGET_MAX} placeholder="Budget decision (max 200 characters)" className="h-7 text-xs" data-testid="register-gate-budget" />
      )}
      <DateField testId="register-gate-date" value={draft.date} onChange={(v) => onEdit(row, { date: v })}
        placeholder="Gate date" className="!mt-0 h-7 text-xs" />
      {mark("date")}
      <Button size="sm" onClick={save} className="h-7 bg-sky-600 hover:bg-sky-500" data-testid="register-gate-save">Save gate</Button>
      <label className="flex items-center gap-1.5 text-slate-700">
        <input type="checkbox" checked={draft.key} disabled={!row.gate_saved && !row.gate_needed} data-testid="register-key-gate"
          onChange={(e) => (row.gate_saved ? onSave(row, { key_gate: e.target.checked }).catch(() => {}) : onEdit(row, { key: e.target.checked }))} />
        {KEY_GATE_LABEL} {mark("key")}
      </label>
    </div>
  );
}

/** The reason code of a turnover answer, then `children` (the Revenue and Volume buttons) on the same line. The deck list's edit
 *  form uses the same control, so an answer there is recorded as the buttons record it. */
export function TurnoverReason({ row, reason, setReason, testId = "register-turnover-reason", children }) {
  const options = reasonsFor(row);
  const shown = options.some(([code]) => code === reason) ? reason : "";      // a stored code this row no longer offers shows blank
  return (
    <div className="flex flex-nowrap items-center gap-1">
      <select value={shown} onChange={(e) => setReason(e.target.value)} className={`${selectClass} shrink-0`} data-testid={testId}>
        <option value="">Reason…</option>
        {options.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
      </select>
      {children}
    </div>
  );
}

/** A turnover claim (claim-matching.md section 11): the label or the question, and one click, Revenue or Volume, with a reason
 *  code. It is shown on every turnover row, so an answer can be changed. The deck list passes `heading` ("Turnover – confirm:")
 *  for a claim the analyst has not confirmed: it stands in place of the label and the question. */
export function TurnoverCell({ row, onAnswer, heading }) {
  const [reason, setReason] = useState(row.turnover_reason || "");     // no default: the analyst picks the reason
  const take = takeRateText(row);
  const suggested = row.turnover_state === "ask" ? row.turnover_suggested : null;      // pre-selected, still to be confirmed
  return (
    <div className="mt-1 space-y-1" data-testid="register-turnover">
      {heading ? <div className="font-semibold text-slate-900" data-testid="turnover-confirm">{heading}</div> : (
        <div className="text-slate-800" data-testid="register-turnover-note">{row.turnover_note}
          {row.turnover_set_by === "analyst" && <span className="text-[10px] text-slate-500"> · set by you</span>}
        </div>
      )}
      {take && (
        <div className="font-mono text-[11px] text-slate-700" data-testid="register-take-rate">
          {take}
          <div className="text-[10px] text-slate-500" data-testid="register-take-rate-source">{row.implied_take_rate_source}</div>
        </div>
      )}
      {row.deck_revenue_note && <div className="font-mono text-[11px] text-slate-700" data-testid="register-deck-revenue">{row.deck_revenue_note}</div>}
      {row.file_note && <div className="text-[11px] text-slate-600" data-testid="turnover-file-note">{row.file_note}</div>}
      {!heading && <div className="text-[10px] text-slate-500">{TURNOVER_QUESTION}</div>}
      <TurnoverReason row={row} reason={reason} setReason={setReason}>
        {[["revenue", "Revenue"], ["volume", "Volume"]].map(([value, label]) => (
          <Button key={value} size="sm"
            className={`${CALCULATE_CLASS} ${ACTIVE_REASON[reason] === value ? "" : "opacity-50"}`}
            aria-pressed={suggested === value ? true : undefined}
            data-testid={`register-turnover-${value}`} disabled={!answerReady(value, reason, row)}
            onClick={() => onAnswer(row, { as: value, reason }).catch(() => {})}>{label}</Button>
        ))}
      </TurnoverReason>
    </div>
  );
}

/** The claim register of one audit, in the order the server ranks it (docs/specs/claim-matching.md section 8). */
export default function ClaimRegister({ auditId, results, onChanged }) {
  const [rows, setRows] = useState(null);
  const [prefill, setPrefill] = useState({});
  const [budgets, setBudgets] = useState([]);
  const [edits, setEdits] = useState({});          // per claim, only what the analyst changed in the gate fields
  const [error, setError] = useState(null);
  const ccy = results?.reporting_currency;

  const load = useCallback((d) => { setRows(registerRows(d)); setPrefill(d.gate_prefill || {}); setBudgets(d.budget_decisions || []); }, []);

  useEffect(() => {
    let cancelled = false;
    getClaimRegister(auditId)
      .then((d) => { if (!cancelled) load(d); })
      .catch((e) => { if (!cancelled) setError(describeRequestError(e).message); });
    return () => { cancelled = true; };
  }, [auditId, load]);

  // A save gives the register back; the prefill and the budget list are read again beside it, since a saved gate leaves them.
  const afterSave = useCallback((d) => {
    setRows(registerRows(d));
    getClaimRegister(auditId).then((x) => { setPrefill(x.gate_prefill || {}); setBudgets(x.budget_decisions || []); }).catch(() => {});
    if (onChanged) onChanged();
  }, [auditId, onChanged]);

  const { edits, onEdit, clear, saveAll } = useGateEdits({ auditId, rows: rows || [], prefill, afterSave });

  const save = useCallback((row, edit) => updateClaimInputs(auditId, row.claim_id, edit)
    .then((d) => { clear([row.claim_id]); afterSave(d); })
    .catch((e) => { toast.error(describeRequestError(e).message); throw e; }), [auditId, afterSave, clear]);

  const answer = useCallback((row, payload) => answerTurnover(auditId, row.claim_id, payload)
    .then((d) => { setRows(registerRows(d)); if (onChanged) onChanged(); })
    .catch((e) => { toast.error(describeRequestError(e).message); throw e; }), [auditId, onChanged]);

  return (
    <section className="mb-6" data-testid="claim-register">
      <div className="flex items-end justify-between flex-wrap gap-3 mb-3">
        <h2 className="font-heading text-lg font-semibold text-slate-900">{REGISTER_HEADING}</h2>
        <div className="flex gap-2">
        <Button size="sm" onClick={saveAll} className="h-8 bg-sky-600 hover:bg-sky-500" data-testid="register-gates-save-all">Save all gates</Button>
        <Button asChild variant="outline" size="sm" className="h-8">
          <a href={claimsCsvUrl(auditId)} data-testid="claim-register-csv"><Download className="h-3.5 w-3.5 mr-1.5" />{DOWNLOAD_LABEL}</a>
        </Button>
        </div>
      </div>
      {error && <div className="text-xs text-rose-700" data-testid="claim-register-error">{error}</div>}
      {!rows && !error && <Loader2 className="h-4 w-4 animate-spin text-slate-500" />}
      {rows && rows.length === 0 && (
        <p className="text-sm text-slate-600" data-testid="claim-register-empty">No approved claims yet. Approve claims in the deck list and they are tested here.</p>
      )}
      {rows && rows.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-[#E5E7EB] bg-white">
          <table className="w-full text-xs" data-testid="claim-register-table">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB]">
                {/* the headers are set in capitals; "VaS" keeps its own case, as the glossary writes it */}
                {REGISTER_COLUMNS.map((c) => <th key={c} className={`py-2 px-3 font-medium whitespace-nowrap ${c === "VaS" ? "normal-case" : ""}`}>{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const observed = observedText(row, ccy);
                return (
                  <tr key={row.claim_id} className="border-b border-[#F1F5F9] align-top" data-testid="claim-register-row">
                    <td className="py-2 px-3 font-mono text-slate-700">{row.rank}</td>
                    <td className="py-2 px-3 text-slate-900 min-w-[10rem]" data-testid="register-claim">
                      <span title={rateHover(row, ccy) || undefined}>
                        <FxText text={claimCellText(row, ccy)} href={`/audit/${auditId}/mapping#fx-settings`} testId="register-claim-fx-link" />
                      </span>
                    </td>
                    <td className="py-2 px-3 font-mono text-slate-700 whitespace-nowrap">
                      {row.period || NO_DATE}
                    </td>
                    <td className="py-2 px-3">
                      <select value={row.segment} onChange={(e) => save(row, { segment: e.target.value }).catch(() => {})} className={selectClass} data-testid="register-segment">
                        {withCurrent(segmentOptions(results), row.segment).map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                      <div className="text-[10px] text-slate-500 mt-0.5">{row.segment_set_by === "analyst" ? "set by you" : "proposed"}</div>
                    </td>
                    <td className="py-2 px-3 font-mono text-slate-600 whitespace-nowrap">{row.page_ref || "—"}</td>
                    <td className="py-2 px-3 text-slate-700 whitespace-nowrap" data-testid="register-reading">{readingText(row.deck_reading)}</td>
                    <td className="py-2 px-3 min-w-[9rem]">
                      <select value={row.metric ?? NO_METRIC} onChange={(e) => save(row, { metric: e.target.value }).catch(() => {})} className={selectClass} data-testid="register-metric">
                        {withCurrent(metricOptions(row), row.metric ?? NO_METRIC).map((m) => (
                          <option key={m} value={m}>{m === NO_METRIC ? "none" : m}</option>
                        ))}
                      </select>
                      <div className="font-mono text-slate-900 mt-1" data-testid="register-observed">
                        <Provenance source={row.observed_source}>{observed.value}</Provenance>
                        {observed.at && <span className="text-[10px] text-slate-500"> · {observed.at}</span>}
                      </div>
                    </td>
                    <td className="py-2 px-3 font-mono text-slate-800 whitespace-nowrap" data-testid="register-gap">{gapText(row, ccy)}</td>
                    <td className="py-2 px-3 text-slate-700 min-w-[9rem]" data-testid="register-gloss">{row.gloss || "—"}</td>
                    <td className="py-2 px-3 font-mono text-slate-700 whitespace-nowrap" data-testid="register-value-at-stake">{valueAtStakeText(row)}</td>
                    <td className="py-2 px-3 font-mono text-slate-700 whitespace-nowrap" data-testid="register-overlaps">{overlapsText(row, rows)}</td>
                    <td className="py-2 px-3 min-w-[10rem]">
                      <span className={`text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap ${LABEL_STYLE[row.evidence_label] || ""}`} data-testid="register-evidence">
                        {row.evidence_label}
                      </span>
                      <span className="ml-1 text-slate-600" data-testid="register-evidence-reason">· {row.reason}</span>
                      {String(row.reason || "").startsWith("FX rate needed") && (
                        <a href={`/audit/${auditId}/mapping#fx-settings`} className="ml-1 text-sky-700 underline" data-testid="register-fx-link">FX settings</a>
                      )}
                      {row.turnover_state && <TurnoverCell row={row} onAnswer={answer} />}
                      {evidenceLines(row).second && (
                        <div className="mt-1 font-mono text-[11px] text-slate-700" data-testid="register-evidence-source">
                          <Provenance source={row.observed_source}>{evidenceLines(row).second}</Provenance>
                        </div>
                      )}
                    </td>
                    <td className="py-2 px-3"><GateCell row={row} ccy={ccy} onSave={save} prefill={prefill[row.claim_id]} budgets={budgets} edits={edits[row.claim_id]} onEdit={onEdit} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
