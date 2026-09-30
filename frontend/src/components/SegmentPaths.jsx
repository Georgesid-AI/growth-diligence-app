import { AlertTriangle } from "lucide-react";
import {
  fmtCurrency, fmtCount, fmtCountUp, fmtPct, fmtRatio, fmtMonths,
} from "@/lib/format";
import { metricLabel, metricQualifier, bracketed } from "@/lib/metricNames";

/**
 * Segment mix paths to target ARR.
 *
 * Runs on customer SEGMENTS only - ACV bands are the separate monetary cut and are not
 * used here. Stage one projects each segment's existing ARR at that segment's own
 * trailing-12-month NRR held flat; stage two is the gap new customers must fill, and
 * the reverse-solve asks what mix of NEW customers (landed ACV, gross landings) would
 * fill it at the observed rate. Every name comes from the shared label map and every
 * figure from the shared formatters.
 *
 * It is an arithmetic projection at constant NRR, not a forecast, and says so at the
 * top, in the heading, and beside every projected figure.
 */
const L = (path) => metricLabel(path);
const Q = (path) => bracketed(metricQualifier(path));

export function SegmentPaths({ sp, ccy }) {
  return (
    <div data-testid="segment-paths-panel" className="bg-white border border-[#E5E7EB] rounded-lg p-5 mb-6">
      <div className="flex items-baseline justify-between mb-3 flex-wrap gap-2">
        <h3 className="font-heading font-semibold text-slate-900 text-sm">
          Constant-NRR projection (not a forecast)
        </h3>
        <span className="text-[10px] font-mono text-slate-500">segments only · ACV bands are a separate cut</span>
      </div>
      <div
        data-testid="segment-paths-assumption"
        className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-800"
      >
        <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
        <span>
          {sp.assumption} Nothing here says NRR will hold; it shows what the existing base is worth if it does,
          so the size of the gap left for new customers can be read against that.
        </span>
      </div>

      {!sp.stage_one ? <Unavailable sp={sp} /> : (
        <>
          <StageOne sp={sp} ccy={ccy} />
          {!sp.available && <Unavailable sp={sp} />}
          {sp.available && <Gap sp={sp} ccy={ccy} />}
          {sp.available && Object.keys(sp.reverse_solve || {}).sort((a, b) => a - b).map((w) => (
            <ReverseSolve key={w} sp={sp} w={w} ccy={ccy} primary={w === "12"} />
          ))}
        </>
      )}
    </div>
  );
}

function Unavailable({ sp }) {
  return (
    <div data-testid="segment-paths-missing" className="text-sm text-slate-700 space-y-1">
      <div className="text-slate-900 font-medium">Not available: a required input is missing.</div>
      {(sp.missing_inputs || []).map((m, i) => (
        <div key={i} className="text-xs text-slate-600">
          <span className="font-mono">{m.input}</span> — {m.resolve}
        </div>
      ))}
    </div>
  );
}

function Th({ children, right }) {
  return <th className={`py-1.5 pr-3 ${right ? "text-right" : ""}`}>{children}</th>;
}

function StageOne({ sp, ccy }) {
  const so = sp.stage_one;
  const proj = Q("projected_arr");
  return (
    <div className="mb-5" data-testid="segment-stage-one">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-mono mb-1">
        Stage one · existing base · {fmtMonths(sp.horizon_months)} to target date
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] font-mono uppercase tracking-wider text-slate-500 text-left">
              <Th>Segment</Th>
              <Th right>{L("start_arr")}</Th>
              <Th right>{L("nrr.overall_pct")} {Q("nrr.overall_pct")}</Th>
              <Th right>{L("projected_arr")} {proj}</Th>
              <Th right>{L("change_arr")} {Q("change_arr")}</Th>
              <Th right>{L("arr_change_per_nrr_point")} {Q("arr_change_per_nrr_point")}</Th>
            </tr>
          </thead>
          <tbody className="font-mono text-slate-800">
            {Object.entries(so.segments).map(([seg, v]) => (
              <tr key={seg} className="border-t border-[#E5E7EB]" data-testid={`segment-row-${seg}`}>
                <td className="py-1.5 pr-3">
                  {seg}
                  <div className="text-[10px] text-slate-500">
                    {fmtCount(v.customers)} customers
                    {v.nrr_base_customers != null && ` · NRR base ${fmtCount(v.nrr_base_customers)}`}
                  </div>
                  {v.small_base && (
                    <div data-testid={`small-base-${seg}`} className="text-[10px] text-amber-700">
                      small base (fewer than 10 customers) — this NRR moves a lot on one customer
                    </div>
                  )}
                </td>
                <td className="py-1.5 pr-3 text-right">{fmtCurrency(v.start_arr, ccy)}</td>
                <td className="py-1.5 pr-3 text-right">{v.nrr_pct == null ? "n/c" : fmtPct(v.nrr_pct)}</td>
                <td className="py-1.5 pr-3 text-right">
                  {v.projected_arr == null
                    ? <span title={v.reason}>n/c</span> : fmtCurrency(v.projected_arr, ccy)}
                </td>
                <td className={`py-1.5 pr-3 text-right ${v.change_arr < 0 ? "text-rose-700" : ""}`}
                    data-testid={`segment-change-${seg}`}>
                  {v.change_arr == null ? "n/c" : fmtCurrency(v.change_arr, ccy)}
                </td>
                <td className="py-1.5 pr-3 text-right">
                  {v.arr_change_per_nrr_point == null ? "n/c" : fmtCurrency(v.arr_change_per_nrr_point, ccy)}
                </td>
              </tr>
            ))}
            <tr className="border-t border-[#D1D5DB] font-semibold">
              <td className="py-1.5 pr-3">All segments</td>
              <td className="py-1.5 pr-3 text-right">{fmtCurrency(so.start_arr_total, ccy)}</td>
              <td />
              <td className="py-1.5 pr-3 text-right" data-testid="projected-base-arr">
                {so.projected_base_arr == null ? "n/c" : fmtCurrency(so.projected_base_arr, ccy)}
              </td>
              <td className="py-1.5 pr-3 text-right">
                {so.projected_base_arr == null ? "n/c" : fmtCurrency(so.projected_base_arr - so.start_arr_total, ccy)}
              </td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      {sp.unsegmented_customers > 0 && (
        <div className="mt-1 text-[11px] text-amber-700">
          {fmtCount(sp.unsegmented_customers)} active customers with {fmtCurrency(sp.unsegmented_arr, ccy)} ARR have no segment
          and are left out of this analysis — map a segment for them to include them.
        </div>
      )}
    </div>
  );
}

function Gap({ sp, ccy }) {
  return (
    <div className="mb-5" data-testid="segment-stage-two">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-mono mb-1">
        Stage two · the gap for new customers
      </div>
      {sp.target_met_by_base ? (
        <div className="text-sm text-slate-800">
          The projected base alone reaches the target ARR of {fmtCurrency(sp.target_arr, ccy)}, so no new customers are required.
        </div>
      ) : (
        <div className="text-sm text-slate-800">
          <span className="font-mono text-lg text-slate-900" data-testid="gap-arr">{fmtCurrency(sp.gap_arr, ccy)}</span>{" "}
          <span className="text-xs text-slate-500">{L("gap_arr")} {Q("gap_arr")}: {fmtCurrency(sp.target_arr, ccy)} target − projected base</span>
        </div>
      )}
    </div>
  );
}

function ReverseSolve({ sp, w, ccy, primary }) {
  const r = sp.reverse_solve[w];
  const landed = sp.landed[w] || {};
  const title = `Last ${w} months${primary ? "" : " (secondary)"}`;
  return (
    <div className={`mb-4 ${primary ? "" : "opacity-90"}`} data-testid={`reverse-solve-${w}`}>
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-mono mb-1">
        Reverse-solve · {title} · gross landings, landed ACV
      </div>
      {!r.computable || r.target_met_by_base ? (
        <div data-testid={`reverse-solve-${w}-unavailable`} className="text-xs text-slate-600">
          {r.target_met_by_base ? r.reason : `Not computable: ${r.reason}.`}
        </div>
      ) : (
        <>
          <div className="text-sm text-slate-800 mb-2" data-testid={`reverse-solve-${w}-summary`}>
            At the observed <span className="font-medium">gross</span> rate of {fmtCount(r.gross_new_per_year)} new customers
            a year ({fmtCountUp(r.new_customers_by_target)} by the target date), the gap needs a blended landed ACV of{" "}
            <span className="font-mono font-semibold">{fmtCurrency(r.required_blended_landed_acv, ccy)}</span>.
            {r.reachable === false && r.best_segment_landed_acv != null && (
              <> No mix of segments gets there: the best segment ({r.best_segment}) lands at{" "}
                {fmtCurrency(r.best_segment_landed_acv, ccy)}. At today's mix (landed ACV{" "}
                {fmtCurrency(r.current_mix_landed_acv, ccy)}), the target needs{" "}
                <span className="font-mono font-semibold">{fmtCountUp(r.required_new_per_year_at_current_mix)}</span> gross new
                customers a year — {fmtRatio(r.required_vs_observed_gross)} the observed rate.</>
            )}
            {r.reachable === true && (
              <> {r.moved_mix_pct > 0
                ? <>A mix reaches it; the smallest shift from today's mix moves {fmtPct(r.moved_mix_pct)} of new customers toward {r.best_segment}.</>
                : <>Today's mix already reaches it.</>}
                {" "}At today's mix the target needs {fmtCountUp(r.required_new_per_year_at_current_mix)} gross new customers a year.</>
            )}
            {r.reachable == null && <> Whether any mix reaches it cannot be determined: {r.reason}.</>}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] font-mono uppercase tracking-wider text-slate-500 text-left">
                  <Th>Segment</Th>
                  <Th right>{L("new_customers")}</Th>
                  <Th right>{L("landed_acv")} {Q("landed_acv")}</Th>
                  <Th right>{L("current_mix_pct")}</Th>
                  <Th right>{L("required_mix_pct")}</Th>
                  <Th right>{L("shift_pct_points")}</Th>
                </tr>
              </thead>
              <tbody className="font-mono text-slate-800">
                {Object.entries(landed.segments || {}).map(([seg, v]) => {
                  const m = (r.by_segment || {})[seg] || {};
                  return (
                    <tr key={seg} className="border-t border-[#E5E7EB]">
                      <td className="py-1.5 pr-3">
                        {seg}
                        {v.small_sample && (
                          <div className="text-[10px] text-amber-700">small sample (fewer than 10 landings)</div>
                        )}
                      </td>
                      <td className="py-1.5 pr-3 text-right" data-testid={`landed-n-${w}-${seg}`}>n={fmtCount(v.new_customers)}</td>
                      <td className="py-1.5 pr-3 text-right">
                        {v.landed_acv == null ? <span title="no customers landed in this window">n/c</span> : fmtCurrency(v.landed_acv, ccy)}
                      </td>
                      <td className="py-1.5 pr-3 text-right">{m.current_mix_pct == null ? "—" : fmtPct(m.current_mix_pct)}</td>
                      <td className="py-1.5 pr-3 text-right">{m.required_mix_pct == null ? "—" : fmtPct(m.required_mix_pct)}</td>
                      <td className="py-1.5 pr-3 text-right">{m.shift_pct_points == null ? "—" : fmtPct(m.shift_pct_points)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {primary && (
        <div className="mt-2 text-[11px] text-slate-500">
          Gross new customers count everyone who landed, including any who have since left. The Path to Plan panel above
          counts <span className="font-medium">net</span> new customers (after those who left), so the two rates differ.
          New customers are valued at landed ACV — first-month ARR, no expansion applied.
        </div>
      )}
    </div>
  );
}
