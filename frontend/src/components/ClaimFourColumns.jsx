import { EvidenceLabel } from "@/components/EvidenceLabel";
import { Provenance } from "@/components/Provenance";
import FxText from "@/components/FxText";
import { NO_DATE } from "@/lib/deckClaims";
import { missingText } from "@/lib/periods";
import { FORECAST_NOTE, REGISTER_COLUMNS, claimCellText, evidenceLines, gapText, observedText, rateHover } from "@/lib/claimRegister";

/**
 * The four columns of a claim, shared by the register and the five selected claims (docs/specs/forecast-and-payback.md section 5, design note
 * section 6): Claim and period · Evidence / calculation · Result · Source. The server evaluated the row once; this reads its fields and tests,
 * ranks or sums nothing. `prefix` keeps the test ids of the register ("register-") and of the five ("five-") apart.
 */
export const FOUR_COLUMNS = REGISTER_COLUMNS;

/** The one sentence shown whenever a forecast appears: above the register, under the five, on no row. */
export function ForecastNote({ testId }) {
  return <p className="text-xs text-slate-600 mb-2" data-testid={testId}>{FORECAST_NOTE}</p>;
}

/** The four cells of a row: { claim, evidence, result, source }. `labelRow` (the label and the open Definition check) and `reason` stand in for
 *  the row's own where a group's item takes the label of its worst member (the five). */
export function fourCells({ row, ccy, auditId, labelRow, reason, prefix = "register-" }) {
  const observed = observedText(row, ccy);
  const path = evidenceLines(row).second;
  const months = missingText({ missing: row.months_missing });
  const claim = (
    <>
      <span title={rateHover(row, ccy) || undefined} data-testid={`${prefix}claim`}>
        <FxText text={claimCellText(row, ccy)} href={`/audit/${auditId}/mapping#fx-settings`} testId={`${prefix}claim-fx-link`} />
      </span>
      <div className="font-mono text-[11px] text-slate-500" data-testid={`${prefix}period`}>{row.period || NO_DATE}</div>
      {row.period && row.period_note ? <div className="text-[11px] text-slate-500" data-testid={`${prefix}period-note`}>{row.period_note}</div> : null}
    </>
  );
  const lines = row.calc_lines || [];
  const evidence = lines.length > 0 ? (
    <ul className="space-y-0.5 text-slate-900" data-testid={`${prefix}calc`}>
      {lines.map((line, i) => <li key={i} data-testid={`${prefix}calc-line`}>{line}</li>)}
    </ul>
  ) : (
    <>
      <div className="font-mono text-slate-900" data-testid={`${prefix}observed`}>
        <Provenance source={row.observed_source}>{observed.value}</Provenance>
        {observed.at && <span className="text-[10px] text-slate-500"> · {observed.at}</span>}
      </div>
      <div className="font-mono text-slate-800" data-testid={`${prefix}gap`}>{gapText(row, ccy)}</div>
      {months && <div className="text-[10px] font-mono text-amber-800" data-testid={`${prefix}months-missing`}>{months}</div>}
    </>
  );
  const result = (
    <>
      <EvidenceLabel row={labelRow ?? row} testId={`${prefix}evidence`} />
      {row.auto_approval && <span className="ml-1 text-[10px] font-mono text-slate-500" data-testid={`${prefix}auto`}>auto</span>}
      <div className="mt-0.5 text-slate-700" data-testid={`${prefix}evidence-reason`}>{reason ?? row.reason}</div>
      {String(reason ?? row.reason ?? "").startsWith("FX rate needed") && (
        <a href={`/audit/${auditId}/mapping#fx-settings`} className="text-sky-700 underline text-[11px]" data-testid={`${prefix}fx-link`}>FX settings</a>
      )}
    </>
  );
  const source = row.source || row.observed_citation || path || row.page_ref ? (
    <>
      {row.source && <div className="text-slate-800" data-testid={`${prefix}source-ref`}>{row.source}</div>}
      {row.observed_citation && (
        <div className="font-mono text-[10px] text-slate-500 break-words" data-testid={`${prefix}observed-citation`}>{row.observed_citation}</div>
      )}
      {path && <div data-testid={`${prefix}evidence-source`}><Provenance source={row.observed_source}>{path}</Provenance></div>}
      {row.page_ref && <div className="text-slate-700" data-testid={`${prefix}page`}>{row.page_ref}</div>}
    </>
  ) : <span className="text-slate-500">—</span>;
  return { claim, evidence, result, source };
}
