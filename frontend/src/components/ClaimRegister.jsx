import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EvidenceLabel } from "@/components/EvidenceLabel";
import { ForecastNote, fourCells } from "@/components/ClaimFourColumns";
import { answerDefinitionCheck, answerTurnover, claimsCsvUrl, downloadFile, getClaimRegister, updateClaimInputs } from "@/lib/api";
import {
  DEFINITION_ANSWERS, DOWNLOAD_LABEL, GATE_TAGS, NO_METRIC,
  REGISTER_COLUMNS, REGISTER_COLUMN_WIDTHS, REGISTER_HEADING, STALE_LABEL, TURNOVER_QUESTION, answerReady, reasonsFor, claimCellText, takeRateText, metricOptions,
  detailItems, hasForecast, registerRows, segmentOptions, COLUMN_EXPLAINERS, EVIDENCE_SUBTITLE, EXTRACTION_EXPLAINER,
  GROWTH_BASES, SET_GROWTH_BASIS,
} from "@/lib/claimRegister";
import { GROUP_DETAILS, countsOf, countsText, detailsLabel, partsOf, visibleRows } from "@/lib/claimGroups";
import { CALCULATE_CLASS } from "@/lib/chatUpload";
import { describeRequestError } from "@/lib/requestError";
import { seeGlossary } from "@/lib/glossary";
import { NO_DATE } from "@/lib/deckClaims";

// The button the dropdown points at is drawn like Map and Compute; the other is the same style, paler. Any other reason: both pale.
const ACTIVE_REASON = { deck_says_gross_revenue: "revenue", deck_says_processed_volume: "volume" };
const selectClass ="h-8 rounded-md border border-[#E5E7EB] bg-white px-2 text-xs max-w-[11rem]";

// The options of a select, with the stored choice kept in the list even when it is no longer offered.
const withCurrent = (options, current) => (options.includes(current) ? options : [...options, current]);

/** What a row says about its gate: the sentence, written from the claim, with "(proposed)" until the analyst edits it in Verdict detail, then
 *  "(set by the analyst)". A Verified row has none. The gates are edited in that section only (docs/design/simplified-flow.md). */
function GateStatus({ row }) {
  if (!row.gate_sentence) return null;
  return (
    <div className="text-slate-800" data-testid="register-gate-sentence">
      {seeGlossary(row.gate_sentence)} <span className="text-[10px] font-mono text-slate-500" data-testid="register-gate-status">{GATE_TAGS[row.gate_status]}</span>
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

/** A gap beyond 50% of the claim (claim-matching.md section 4.1): "Observed 26, claimed 1. Same metric and period?" and Yes / No, on one
 *  line. The answer given stays marked and can be changed. A card on the Audit page passes `heading`: the period of a table row's value. */
export function DefinitionCell({ row, onAnswer, heading }) {
  const answered = row.definition_check !== "ask";
  return (
    <div className="mt-1 flex flex-nowrap items-center gap-1.5" data-testid="definition-check">
      {heading && <span className="font-mono text-slate-500 shrink-0">{heading} ·</span>}
      <span className="text-slate-800" data-testid="definition-question">{row.definition_question}</span>
      {DEFINITION_ANSWERS.map(([value, label]) => (
        <Button key={value} size="sm" variant="outline" className={`h-7 shrink-0 ${row.definition_check === value ? "border-sky-600 text-sky-800" : ""}`}
          aria-pressed={answered ? row.definition_check === value : undefined} data-testid={`definition-${value}`}
          onClick={() => onAnswer(row, value).catch(() => {})}>{label}</Button>
      ))}
      {answered && <span className="text-[10px] text-slate-500 shrink-0">· set by you</span>}
    </div>
  );
}

/** The one-click "Set growth basis" of a growth claim whose basis is unknown (docs/specs/dates-and-periods.md section 5). */
export function GrowthBasisCell({ row, onSet }) {
  return (
    <div className="mt-1 flex flex-nowrap items-center gap-1.5" data-testid="register-growth-basis">
      <span className="text-slate-800">{SET_GROWTH_BASIS}</span>
      {GROWTH_BASES.map(([value, label]) => (
        <Button key={value} size="sm" variant="outline" className="h-7 shrink-0" data-testid={`growth-basis-${value}`}
          onClick={() => onSet(row, { growth_basis: value }).catch(() => {})}>{label}</Button>
      ))}
    </div>
  );
}

/** The Details of a row, one control (docs/specs/forecast-and-payback.md section 5.1, claim-groups.md section 4): the collapsed line carries the
 *  contradiction of a part ("Details · 4 parts · 1 contradicted"); opened it shows the parts of a reconciled annual total, the parts of another set
 *  and the figures stated again, each with its own claim, period, label and reason; the formula inputs of a calculation; and the corrections: the
 *  segment and metric, the extraction confidence, how the deck was read, the gloss, value at stake, overlaps and the gate. The questions a row asks
 *  (turnover, definition check, growth basis) stay outside it. */
function RowDetails({ row, rows, ccy, results, save }) {
  const [open, setOpen] = useState(false);
  const parts = partsOf(row, rows);
  const detail = detailItems(row, rows, ccy);
  return (
    <div data-testid="register-details">
      <button type="button" className="text-sky-700 underline underline-offset-2" aria-expanded={open}
        data-testid={parts.length ? "register-group-toggle" : "register-details-toggle"}
        onClick={() => setOpen((o) => !o)}>{parts.length ? detailsLabel(parts) : GROUP_DETAILS}</button>
      {open && (
        <div className="mt-1 space-y-1 border-l-2 border-[#E5E7EB] pl-3" data-testid="register-details-body">
          {parts.length > 0 && (
            <ul className="space-y-1" data-testid="register-group-parts">
              {parts.map((p) => (
                <li key={p.claim_id} data-testid="register-group-part">
                  {p.group_role === "repeat" && <span className="text-slate-600">Also stated: </span>}
                  {p.group_role === "segment_part" && <span className="text-slate-900">{p.segment} · </span>}
                  <span className="text-slate-900">{claimCellText(p, ccy)}</span>
                  {p.group_role === "repeat" && <span className="font-mono text-slate-500"> · {p.page_ref}</span>}
                  <span className="font-mono text-slate-500"> · {p.period || NO_DATE}</span> · <EvidenceLabel row={p} testId="register-group-part-evidence" />
                  <span className="text-slate-600"> · {p.reason}</span>
                  {p.relationship && <span className="text-slate-500"> · {p.relationship}</span>}
                </li>
              ))}
            </ul>
          )}
          {(row.calc_details || []).length > 0 && (
            <ul className="font-mono text-slate-600" data-testid="register-calc-details">
              {row.calc_details.map((line, i) => <li key={i}>{line}</li>)}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1">Segment
              <select value={row.segment} onChange={(e) => save(row, { segment: e.target.value }).catch(() => {})} className={selectClass} data-testid="register-segment">
                {withCurrent(segmentOptions(results), row.segment).map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <span className="text-[10px] text-slate-500">{row.segment_set_by === "analyst" ? "set by you" : "proposed"}</span>
            <label className="flex items-center gap-1">Metric
              <select value={row.metric ?? NO_METRIC} onChange={(e) => save(row, { metric: e.target.value }).catch(() => {})} className={selectClass} data-testid="register-metric">
                {withCurrent(metricOptions(row), row.metric ?? NO_METRIC).map((m) => (
                  <option key={m} value={m}>{m === NO_METRIC ? "none" : m}</option>
                ))}
              </select>
            </label>
            <span className="font-mono text-slate-700" title={EXTRACTION_EXPLAINER}>
              Extraction confidence <span data-testid="register-confidence">{row.extraction_confidence || "—"}</span>
            </span>
          </div>
          <div>
            {detail.map(([text, testId], i) => (
              <span key={testId}>{i > 0 && " · "}<span data-testid={testId}>{text}</span></span>
            ))}
          </div>
          <GateStatus row={row} />
        </div>
      )}
    </div>
  );
}

/** The claim register of one audit, in the order the server ranks it (docs/specs/claim-matching.md section 8). */
export default function ClaimRegister({ auditId, results, onChanged }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [stale, setStale] = useState(false);
  const ccy = results?.reporting_currency;

  const load = useCallback((d) => {
    setRows(registerRows(d)); setStale(Boolean(d.results_stale));
  }, []);

  useEffect(() => {
    let cancelled = false;
    getClaimRegister(auditId)
      .then((d) => { if (!cancelled) load(d); })
      .catch((e) => { if (!cancelled) setError(describeRequestError(e).message); });
    return () => { cancelled = true; };
  }, [auditId, load]);

  // A save gives the register back.
  const save = useCallback((row, edit) => updateClaimInputs(auditId, row.claim_id, edit)
    .then((d) => { setRows(registerRows(d)); if (onChanged) onChanged(); })
    .catch((e) => { toast.error(describeRequestError(e).message); throw e; }), [auditId, onChanged]);

  const answer = useCallback((row, payload) => answerTurnover(auditId, row.claim_id, payload)
    .then((d) => { setRows(registerRows(d)); if (onChanged) onChanged(); })
    .catch((e) => { toast.error(describeRequestError(e).message); throw e; }), [auditId, onChanged]);

  const answerDefinition = useCallback((row, value) => answerDefinitionCheck(auditId, row.claim_id, value)
    .then((d) => { setRows(registerRows(d)); if (onChanged) onChanged(); })
    .catch((e) => { toast.error(describeRequestError(e).message); throw e; }), [auditId, onChanged]);

  return (
    <section id="claim-register" className="mb-6" data-testid="claim-register">
      <div className="flex items-end justify-between flex-wrap gap-3 mb-3">
        <h2 className="font-heading text-lg font-semibold text-slate-900">{REGISTER_HEADING}</h2>
        <div className="flex gap-2">
        <Button asChild variant="outline" size="sm" className="h-8">
          <a href={claimsCsvUrl(auditId)} data-testid="claim-register-csv"
            onClick={(e) => { e.preventDefault(); downloadFile(`/audits/${auditId}/claims.csv`, "claims.csv").catch(() => toast.error("The CSV could not be downloaded.")); }}><Download className="h-3.5 w-3.5 mr-1.5" />{DOWNLOAD_LABEL}</a>
        </Button>
        </div>
      </div>
      {error && <div className="text-xs text-rose-700" data-testid="claim-register-error">{error}</div>}
      {!rows && !error && <Loader2 className="h-4 w-4 animate-spin text-slate-500" />}
      {rows && stale && (
        <p className="text-sm text-amber-800" data-testid="claim-register-stale">{STALE_LABEL}</p>
      )}
      {rows && rows.length === 0 && !stale && (
        <p className="text-sm text-slate-600" data-testid="claim-register-empty">No claims in the register yet. Run audit tests the claims found in the uploaded documents; the ones that need your word are under Needs your attention.</p>
      )}
      {rows && countsText(countsOf(rows)) && <p className="text-xs text-slate-600 mb-2" data-testid="claim-register-counts">{countsText(countsOf(rows))}</p>}
      {rows && hasForecast(rows) && <ForecastNote testId="forecast-note" />}
      {rows && rows.length > 0 && (
        <div className="rounded-md border border-[#E5E7EB] bg-white" data-testid="claim-register-scroll">
          <table className="w-full table-fixed text-xs" data-testid="claim-register-table">
            <colgroup>{REGISTER_COLUMN_WIDTHS.map((w, i) => <col key={REGISTER_COLUMNS[i]} style={{ width: `${w}%` }} />)}</colgroup>
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB]">
                {REGISTER_COLUMNS.map((c) => (
                  <th key={c} className="py-2 px-3 font-medium" title={COLUMN_EXPLAINERS[c]}>
                    {c}
                    {c === "Result" && <div className="normal-case tracking-normal text-[10px] text-slate-400">{EVIDENCE_SUBTITLE}</div>}
                  </th>
                ))}
              </tr>
            </thead>
            {/* one tbody per claim: the four columns, then a smaller line spanning the row with the questions it asks and its Details */}
            {visibleRows(rows).map((row) => {
              const cells = fourCells({ row, ccy, auditId });
              return (
                <tbody key={row.claim_id} className="border-b border-[#F1F5F9] align-top break-words" data-testid="claim-register-row">
                  <tr>
                    <td className="pt-2 px-3 text-slate-900">{cells.claim}</td>
                    <td className="pt-2 px-3">{cells.evidence}</td>
                    <td className="pt-2 px-3">{cells.result}</td>
                    <td className="pt-2 px-3">{cells.source}</td>
                  </tr>
                  <tr>
                    <td colSpan={REGISTER_COLUMNS.length} className="pb-2 px-3 text-[11px] text-slate-500 space-y-1" data-testid="register-detail">
                      {row.relationship && <div className="text-slate-600" data-testid="register-relationship">{row.relationship}</div>}
                      <div className="text-xs text-slate-700 space-y-1">
                        {row.turnover_state && <TurnoverCell row={row} onAnswer={answer} />}
                        {row.definition_check && <DefinitionCell row={row} onAnswer={answerDefinition} />}
                        {row.growth_basis === "unknown" && <GrowthBasisCell row={row} onSet={save} />}
                      </div>
                      <RowDetails row={row} rows={rows} ccy={ccy} results={results} save={save} />
                    </td>
                  </tr>
                </tbody>
              );
            })}
          </table>
        </div>
      )}
    </section>
  );
}
