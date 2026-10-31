import { useEffect, useState } from "react";
import { EvidenceDefinitions, EvidenceLabel } from "@/components/EvidenceLabel";
import { FOUR_COLUMNS, ForecastNote, fourCells } from "@/components/ClaimFourColumns";
import { getClaimRegister } from "@/lib/api";
import { detailItems, hasForecast, registerRows } from "@/lib/claimRegister";
import { partsLabel } from "@/lib/claimGroups";
import { fmtCount } from "@/lib/format";

export const FIVE_HEADING = "The five selected claims";
export const FIVE_COLUMNS = FOUR_COLUMNS;
const GRID = "md:grid-cols-[1.1fr_1.4fr_1.1fr_0.9fr]";

/** The five of the conclusion: the confirmed five, else the proposed five, each as the verdict lists it. */
export function selectedFive(verdict) {
  const v = verdict?.verdict;
  if (v?.five?.length) return v.five;
  const byId = Object.fromEntries((verdict?.candidates || []).map((c) => [c.claim_id, c]));
  return (v?.top5?.in_force || []).map((id) => byId[id]).filter(Boolean);
}

function Row({ f, row, rows, ccy, auditId }) {
  const [details, setDetails] = useState(false);
  const link = "text-sky-700 underline underline-offset-2";
  // The row of the register is the one evaluation; the item of the verdict only lends the label of a group's worst member and its reason.
  const cells = row ? fourCells({ row, ccy, auditId, labelRow: f, reason: f.reason, prefix: "five-" }) : null;
  return (
    <li className="py-2 border-b border-[#F1F5F9] text-xs" data-testid="verdict-five-row">
      <div className={`grid gap-x-4 gap-y-1 ${GRID}`}>
        <div data-testid="five-plan">
          {cells ? cells.claim : <span className="text-slate-900" data-testid="five-claim">{f.claim}</span>}
          {f.group && (
            <div className="text-[11px] text-slate-500" data-testid="five-group">
              Annual total with {partsLabel(f.group.parts)}{f.group.contradicted.length > 0 ? ` · ${fmtCount(f.group.contradicted.length)} contradicted` : ""}
            </div>
          )}
        </div>
        <div data-testid="five-evidence-cell">{cells ? cells.evidence : <span className="text-slate-500">—</span>}</div>
        <div data-testid="five-result">{cells ? cells.result : <><EvidenceLabel row={f} testId="five-evidence" /><div className="mt-0.5 text-slate-700" data-testid="five-evidence-reason">{f.reason}</div></>}</div>
        <div data-testid="five-source">{cells ? cells.source : <span className="text-slate-500">—</span>}</div>
      </div>
      <div className="mt-1 flex gap-3">
        <button type="button" className={link} aria-expanded={details} data-testid="five-details-toggle" onClick={() => setDetails((d) => !d)}>Details</button>
      </div>
      {details && row && row.relationship && <div className="mt-1 text-[11px] text-slate-500" data-testid="five-relationship">{row.relationship}</div>}
      {details && row && (row.calc_details || []).length > 0 && (
        <ul className="mt-1 font-mono text-[11px] text-slate-600" data-testid="five-calc-details">
          {row.calc_details.map((line, i) => <li key={i}>{line}</li>)}
        </ul>
      )}
      {details && row && (
        <div className="mt-1 text-[11px] text-slate-500" data-testid="five-details">
          {detailItems(row, rows, ccy, "five-").map(([text, testId], i) => (
            <span key={testId}>{i > 0 && " · "}<span data-testid={testId}>{text}</span></span>
          ))}
        </div>
      )}
    </li>
  );
}

/** The five selected claims, one row each in the four columns (Claim and period · Evidence / calculation · Result · Source) and a Details toggle; the
 *  forecast note once when a forecast is among them; the five label definitions printed once under them. The register rows are read again
 *  whenever `tick` changes. */
export default function FiveClaims({ auditId, verdict, ccy, tick }) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    let cancelled = false;
    Promise.resolve(getClaimRegister(auditId)).then((d) => { if (!cancelled) setRows(registerRows(d)); }).catch(() => {});
    return () => { cancelled = true; };
  }, [auditId, tick]);
  const five = selectedFive(verdict);
  if (!five.length) return null;
  const byId = Object.fromEntries(rows.map((r) => [r.claim_id, r]));
  return (
    <section className="mb-6 rounded-md border border-[#E5E7EB] bg-white p-4" data-testid="verdict-five">
      <h2 className="font-heading text-lg font-semibold text-slate-900 mb-2">{FIVE_HEADING}</h2>
      <div className={`hidden md:grid gap-x-4 ${GRID} text-[10px] uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB] pb-1`}>
        {FIVE_COLUMNS.map((c) => <span key={c}>{c}</span>)}
      </div>
      <ul>{five.map((f) => <Row key={f.claim_id} f={f} row={byId[f.claim_id]} rows={rows} ccy={ccy} auditId={auditId} />)}</ul>
      {five.some((f) => byId[f.claim_id]) && hasForecast(five.map((f) => byId[f.claim_id]).filter(Boolean)) && <ForecastNote testId="five-forecast-note" />}
      <EvidenceDefinitions />
    </section>
  );
}
