import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Provenance } from "@/components/Provenance";
import DateField from "@/components/DateField";
import { answerTurnover, claimsCsvUrl, getClaimRegister, updateClaimInputs } from "@/lib/api";
import {
  DOWNLOAD_LABEL, GATE_BUDGET_MAX, GATE_DIRECTIONS, GATE_METRIC_MAX, GATE_METRIC_PLACEHOLDER, GATE_NEEDED, KEY_GATE_LABEL, NO_METRIC,
  REGISTER_COLUMNS, REGISTER_HEADING, TURNOVER_QUESTION, TURNOVER_REASONS, contradicts, claimCellText, rateHover, takeRateText, evidenceLines, gapText, gateContext, gateEdit, metricOptions, needsMetricName,
  observedText, overlapsText, readingText, registerRows, segmentOptions, valueAtStakeText,
} from "@/lib/claimRegister";
import { describeRequestError } from "@/lib/requestError";
import FxText from "@/components/FxText";
import { NO_DATE } from "@/lib/deckClaims";

const selectClass = "h-8 rounded-md border border-[#E5E7EB] bg-white px-2 text-xs max-w-[11rem]";
const LABEL_STYLE = {
  Verified: "text-emerald-800 border-emerald-500/50 bg-emerald-50",
  Contradicted: "text-rose-800 border-rose-500/50 bg-rose-50",
  Unverified: "text-amber-800 border-amber-500/50 bg-amber-50",
  Unsupported: "text-slate-700 border-slate-400/60 bg-slate-50",
};

// The options of a select, with the stored choice kept in the list even when it is no longer offered.
const withCurrent = (options, current) => (options.includes(current) ? options : [...options, current]);

/** The gate: the claimed and observed figures beside an empty threshold, a budget decision and a date. Nothing is proposed and
 *  nothing is saved until the threshold, the decision and the date are all filled; a row with no metric of the app also
 *  needs the analyst's metric and its direction (docs/specs/verdict-and-memo.md section 3). */
function GateCell({ row, ccy, onSave }) {
  const initial = {
    threshold: row.gate_threshold ?? "", budget: row.gate_budget_decision ?? "", date: row.gate_date ?? "",
    metricName: row.gate_metric_name ?? "", direction: row.gate_direction ?? "",
  };
  const [draft, setDraft] = useState(initial);
  const key = JSON.stringify(initial);
  useEffect(() => setDraft(JSON.parse(key)), [key]);
  const context = gateContext(row, ccy);
  const named = needsMetricName(row);
  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  const save = () => {
    let edit;
    try { edit = gateEdit(row, draft); } catch (e) { toast.error(e.message); return; }
    if (Object.keys(edit).length) onSave(row, edit).catch(() => {});
  };
  return (
    <div className="max-w-xs space-y-1">
      {row.gate_needed && <div className="text-[10px] font-mono text-amber-800" data-testid="register-gate-needed">{GATE_NEEDED}</div>}
      <div className="text-slate-600" data-testid="register-gate-context">{context}</div>
      {row.gate_sentence && <div className="text-slate-800" data-testid="register-gate-sentence">{row.gate_sentence}</div>}
      {row.gate_saved && <div className="text-[10px] font-mono text-emerald-700" data-testid="register-gate-saved">Gate saved</div>}
      {named && (
        <div className="flex gap-1">
          <Input value={draft.metricName} onChange={set("metricName")} maxLength={GATE_METRIC_MAX} placeholder={GATE_METRIC_PLACEHOLDER} className="h-7 text-xs" data-testid="register-gate-metric-name" />
          <select value={draft.direction} onChange={set("direction")} className={selectClass} data-testid="register-gate-direction">
            <option value="" />
            {GATE_DIRECTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      )}
      <Input value={draft.threshold} onChange={set("threshold")} placeholder="Threshold" inputMode="decimal" className="h-7 text-xs font-mono" data-testid="register-gate-threshold" />
      <Input value={draft.budget} onChange={set("budget")} maxLength={GATE_BUDGET_MAX} placeholder="Budget decision (max 200 characters)" className="h-7 text-xs" data-testid="register-gate-budget" />
      <DateField testId="register-gate-date" value={draft.date} onChange={(v) => setDraft((d) => ({ ...d, date: v }))}
        placeholder="Gate date" className="!mt-0 h-7 text-xs" />
      <Button size="sm" onClick={save} className="h-7 bg-sky-600 hover:bg-sky-500" data-testid="register-gate-save">Save gate</Button>
      <label className="flex items-center gap-1.5 text-slate-700">
        <input type="checkbox" checked={!!row.key_gate} disabled={!row.gate_saved} data-testid="register-key-gate"
          onChange={(e) => onSave(row, { key_gate: e.target.checked }).catch(() => {})} />
        {KEY_GATE_LABEL}
      </label>
    </div>
  );
}

/** A turnover claim (claim-matching.md section 11): the label or the question, and one click, Revenue or Volume, with a reason
 *  code. It is shown on every turnover row, so an answer can be changed. */
function TurnoverCell({ row, onAnswer }) {
  const [reason, setReason] = useState(row.turnover_reason || "");     // no default: the analyst picks the reason
  const take = takeRateText(row);
  const suggested = row.turnover_state === "ask" ? row.turnover_suggested : null;      // pre-selected, still to be confirmed
  return (
    <div className="mt-1 space-y-1" data-testid="register-turnover">
      <div className="text-slate-800" data-testid="register-turnover-note">{row.turnover_note}
        {row.turnover_set_by === "analyst" && <span className="text-[10px] text-slate-500"> · set by you</span>}
      </div>
      {take && (
        <div className="font-mono text-[11px] text-slate-700" data-testid="register-take-rate">
          {take}
          <div className="text-[10px] text-slate-500" data-testid="register-take-rate-source">{row.implied_take_rate_source}</div>
        </div>
      )}
      {row.deck_revenue_note && <div className="font-mono text-[11px] text-slate-700" data-testid="register-deck-revenue">{row.deck_revenue_note}</div>}
      <div className="text-[10px] text-slate-500">{TURNOVER_QUESTION}</div>
      <div className="flex flex-wrap items-center gap-1">
        <select value={reason} onChange={(e) => setReason(e.target.value)} className={selectClass} data-testid="register-turnover-reason">
          <option value="">Reason…</option>
          {TURNOVER_REASONS.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
        </select>
        {[["revenue", "Revenue"], ["volume", "Volume"]].map(([value, label]) => (
          <Button key={value} size="sm" variant={row.turnover_state === value ? "default" : suggested === value ? "secondary" : "outline"}
            className={`h-7 ${suggested === value ? "ring-2 ring-sky-400" : ""}`} aria-pressed={suggested === value ? true : undefined}
            data-testid={`register-turnover-${value}`} disabled={!reason || contradicts(value, reason)} onClick={() => onAnswer(row, { as: value, reason }).catch(() => {})}>{label}</Button>
        ))}
      </div>
    </div>
  );
}

/** The claim register of one audit, in the order the server ranks it (docs/specs/claim-matching.md section 8). */
export default function ClaimRegister({ auditId, results, onChanged }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const ccy = results?.reporting_currency;

  useEffect(() => {
    let cancelled = false;
    getClaimRegister(auditId)
      .then((d) => { if (!cancelled) setRows(registerRows(d)); })
      .catch((e) => { if (!cancelled) setError(describeRequestError(e).message); });
    return () => { cancelled = true; };
  }, [auditId]);

  const save = useCallback((row, edit) => updateClaimInputs(auditId, row.claim_id, edit)
    .then((d) => { setRows(registerRows(d)); if (onChanged) onChanged(); })
    .catch((e) => { toast.error(describeRequestError(e).message); throw e; }), [auditId, onChanged]);

  const answer = useCallback((row, payload) => answerTurnover(auditId, row.claim_id, payload)
    .then((d) => { setRows(registerRows(d)); if (onChanged) onChanged(); })
    .catch((e) => { toast.error(describeRequestError(e).message); throw e; }), [auditId, onChanged]);

  return (
    <section className="mb-6" data-testid="claim-register">
      <div className="flex items-end justify-between flex-wrap gap-3 mb-3">
        <h2 className="font-heading text-lg font-semibold text-slate-900">{REGISTER_HEADING}</h2>
        <Button asChild variant="outline" size="sm" className="h-8">
          <a href={claimsCsvUrl(auditId)} data-testid="claim-register-csv"><Download className="h-3.5 w-3.5 mr-1.5" />{DOWNLOAD_LABEL}</a>
        </Button>
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
                {REGISTER_COLUMNS.map((c) => <th key={c} className="py-2 px-3 font-medium whitespace-nowrap">{c}</th>)}
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
                    <td className="py-2 px-3"><GateCell row={row} ccy={ccy} onSave={save} /></td>
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
