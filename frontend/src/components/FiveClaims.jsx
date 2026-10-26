import { useEffect, useState } from "react";
import { Provenance } from "@/components/Provenance";
import { EvidenceLabel, EvidenceDefinitions } from "@/components/EvidenceLabel";
import { getClaimRegister } from "@/lib/api";
import { claimCellText, detailItems, observedText, registerRows } from "@/lib/claimRegister";
import { NO_DATE } from "@/lib/deckClaims";
import { partsLabel } from "@/lib/claimGroups";

export const FIVE_HEADING = "The five selected claims";
export const FIVE_COLUMNS = ["Plan assumes", "Evidence shows", "Result"];

/** The five of the conclusion: the confirmed five, else the proposed five, each as the verdict lists it. */
export function selectedFive(verdict) {
  const v = verdict?.verdict;
  if (v?.five?.length) return v.five;
  const byId = Object.fromEntries((verdict?.candidates || []).map((c) => [c.claim_id, c]));
  return (v?.top5?.in_force || []).map((id) => byId[id]).filter(Boolean);
}

function Row({ f, row, rows, ccy }) {
  const [source, setSource] = useState(false);
  const [details, setDetails] = useState(false);
  const observed = row ? observedText(row, ccy) : null;
  const link = "text-sky-700 underline underline-offset-2";
  return (
    <li className="py-2 border-b border-[#F1F5F9] text-xs" data-testid="verdict-five-row">
      <div className="grid gap-x-4 gap-y-1 md:grid-cols-[1fr_1fr_1.3fr]">
        <div data-testid="five-plan">
          <span className="font-mono text-slate-700">#{f.rank}</span> <span className="text-slate-900">{row ? claimCellText(row, ccy) : f.claim}</span>
          {row && <div className="font-mono text-[11px] text-slate-500">{row.period || NO_DATE}</div>}
          {f.group && (
            <div className="text-[11px] text-slate-500" data-testid="five-group">
              Annual total with {partsLabel(f.group.parts)}{f.group.contradicted.length > 0 ? ` · ${f.group.contradicted.length} contradicted` : ""}
            </div>
          )}
        </div>
        <div data-testid="five-evidence" className="font-mono text-slate-900">
          {observed && observed.value !== "—" ? (
            <><Provenance source={row.observed_source}>{observed.value}</Provenance>{observed.at && <span className="text-[10px] text-slate-500"> · {observed.at}</span>}</>
          ) : <span className="text-slate-500">—</span>}
        </div>
        <div data-testid="five-result">
          <EvidenceLabel row={f} />
          <span className="text-slate-600"> · {f.reason}</span>
        </div>
      </div>
      <div className="mt-1 flex gap-3">
        <button type="button" className={link} aria-expanded={source} data-testid="five-source-link" onClick={() => setSource((s) => !s)}>Source</button>
        <button type="button" className={link} aria-expanded={details} data-testid="five-details-toggle" onClick={() => setDetails((d) => !d)}>Details</button>
      </div>
      {source && (
        <div className="mt-1 font-mono text-[11px] text-slate-500 break-words" data-testid="five-source">
          {[row?.observed_citation, row?.page_ref].filter(Boolean).join(" · ") || "—"}
        </div>
      )}
      {details && row && row.relationship && <div className="mt-1 text-[11px] text-slate-500" data-testid="five-relationship">{row.relationship}</div>}
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

/** The five selected claims, one row each: Plan assumes · Evidence shows · Result, a source link and a Details toggle; the five label
 *  definitions are printed once under them. The register rows are read again whenever `tick` changes. */
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
      <div className="hidden md:grid gap-x-4 md:grid-cols-[1fr_1fr_1.3fr] text-[10px] uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB] pb-1">
        {FIVE_COLUMNS.map((c) => <span key={c}>{c}</span>)}
      </div>
      <ul>{five.map((f) => <Row key={f.claim_id} f={f} row={byId[f.claim_id]} rows={rows} ccy={ccy} />)}</ul>
      <EvidenceDefinitions />
    </section>
  );
}
