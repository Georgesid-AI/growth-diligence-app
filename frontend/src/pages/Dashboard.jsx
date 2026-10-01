import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ResponsiveContainer, ReferenceLine, Legend,
} from "recharts";
import { Loader2, AlertTriangle, Download } from "lucide-react";
import { Layout } from "@/components/Layout";
import { MetricCard } from "@/components/MetricCard";
import { Provenance } from "@/components/Provenance";
import { Gloss } from "@/components/Gloss";
import { Narrative } from "@/components/Narrative";
import { NarrativeControl } from "@/components/NarrativeControl";
import { getAudit, getResults, exportUrl, readNarrative, generateNarrative, getDisclosure, NARRATIVE_TIMEOUT_MS } from "@/lib/api";
import { GLOSSARY } from "@/lib/glossary";
import { SegmentPaths } from "@/components/SegmentPaths";
import { describeRequestError, logRequestFailure } from "@/lib/requestError";
import { metricLabel, metricQualifier, bracketed } from "@/lib/metricNames";
import { NONE, missingRows, questionRows, questionsEmptyText } from "@/lib/gapLists";
import { fmtCurrency, fmtCount, fmtCountUp, fmtDays, fmtDaysNumber, fmtMonths, fmtPct, fmtRatio, bandRangeLabel, monthEndDate } from "@/lib/format";

const SEG_COLORS = ["#0284C7", "#059669", "#D97706", "#DB2777", "#475569"];

const chartAxis = { stroke: "#475569", fontSize: 11, fontFamily: "JetBrains Mono" };
const tooltipStyle = { backgroundColor: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, fontSize: 12, color: "#0F172A" };

function cohortTier(v) {
  if (v === null || v === undefined) return "bg-slate-50 text-slate-600";
  if (v >= 100) return "bg-emerald-700 text-white";
  if (v >= 90) return "bg-emerald-200 text-emerald-900";
  if (v >= 80) return "bg-emerald-100 text-emerald-900";
  if (v >= 70) return "bg-amber-100 text-amber-900";
  return "bg-rose-100 text-rose-900";
}

export default function Dashboard() {
  const { id } = useParams();
  const nav = useNavigate();
  const [audit, setAudit] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [narrative, setNarrative] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [disclosure, setDisclosure] = useState(null);

  useEffect(() => {
    getAudit(id).then(setAudit).catch(() => {});
    getResults(id)
      .then(setData)
      .catch((e) => setError(e.response?.status === 409 ? "not_computed" : "error"));
  }, [id]);

  // Read-only on load: this returns a narrative someone already generated, or
  // nothing. It cannot call the model provider, so opening an audit never
  // spends. Generating is the button below, and only the button.
  useEffect(() => {
    if (!data) return;
    let cancelled = false;
    readNarrative(id, "growth_engine")
      .then((res) => { if (!cancelled) setNarrative(res); })
      .catch((e) => {
        if (cancelled) return;
        // Say what failed instead of quietly offering "Generate" as if nothing were wrong.
        const failure = describeRequestError(e);
        logRequestFailure("read narrative", failure);
        setNarrative({ narrative_status: "unavailable", reason: `Could not load the saved narrative: ${failure.message}` });
      });
    return () => { cancelled = true; };
  }, [id, data]);

  // Provenance block for the foot of the page. Re-read whenever the narrative
  // changes, so a regeneration updates the model and time shown.
  useEffect(() => {
    if (!data) return;
    let cancelled = false;
    getDisclosure(id)
      .then((d) => { if (!cancelled) setDisclosure(d); })
      .catch(() => { if (!cancelled) setDisclosure(null); });
    return () => { cancelled = true; };
  }, [id, data, narrative]);

  // The only path that spends an AI request.
  const onGenerate = () => {
    setGenerating(true);
    generateNarrative(id, "growth_engine")
      .then(setNarrative)
      .catch((e) => {
        const failure = describeRequestError(e, { timeoutMs: NARRATIVE_TIMEOUT_MS });
        logRequestFailure("generate narrative", failure);
        setNarrative({ narrative_status: "unavailable", reason: failure.message });
      })
      .finally(() => setGenerating(false));
  };

  if (error === "not_computed") {
    return (
      <Layout audit={audit}>
        <div className="border border-dashed border-[#E5E7EB] rounded-xl py-24 text-center">
          <AlertTriangle className="h-10 w-10 text-amber-500 mx-auto mb-4" />
          <p className="text-slate-700 mb-4">This audit hasn't been computed yet.</p>
          <button onClick={() => nav(`/audit/${id}/mapping`)} className="text-sky-700 hover:text-sky-800 underline">
            Go to Upload & Mapping →
          </button>
        </div>
      </Layout>
    );
  }
  if (error === "error") {
    return (
      <Layout audit={audit}>
        <div className="border border-dashed border-[#E5E7EB] rounded-xl py-24 text-center">
          <AlertTriangle className="h-10 w-10 text-rose-500 mx-auto mb-4" />
          <p className="text-slate-700 mb-4">Couldn't load this audit's results.</p>
          <button onClick={() => nav("/")} className="text-sky-700 hover:text-sky-800 underline">Back to Audit Hub →</button>
        </div>
      </Layout>
    );
  }
  if (!data) {
    return (
      <Layout audit={audit}>
        <div className="flex items-center justify-center py-32 text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /></div>
      </Layout>
    );
  }

  const r = data.results;
  const ccy = r.reporting_currency;

  // Plan of record — the same audit record the top-nav badge reads. `audit` carries
  // the datasets (and so the FX rates); `data.audit` is the subset the results
  // endpoint echoes back, and stands in until getAudit resolves.
  const por = audit ?? data.audit;
  // FX rates are entered per revenue dataset as {CCY: rate}. The reporting currency
  // maps to itself at 1.0, so it is not a consolidated foreign entity. Only the
  // getAudit payload carries datasets — until it lands, show nothing rather than
  // assert single-currency for a company that may well consolidate a foreign entity.
  const fxRates = Object.entries(audit?.datasets?.revenue?.fx ?? {}).filter(
    ([c]) => c.toUpperCase() !== ccy.toUpperCase()
  );
  const fxDisplay = !audit?.datasets
    ? "—"
    : fxRates.length === 0
    ? "N/A (single-currency reporting)"
    : fxRates.map(([c, rate]) => `1 ${c} = ${rate} ${ccy}`).join(" · ");
  const asOfFullDate = monthEndDate(r.as_of_month);
  const missing = missingRows(r);
  const questions = questionRows(r);

  // Headline CAC payback: the latest COMPLETE quarter only. A partial quarter pairs a
  // full quarter of lagged S&M with part of a quarter's new MRR and overstates payback,
  // so it never headlines (it stays in the quarterly table, labelled). The quarter is
  // named beside the figure so an older quarter is never mistaken for the current one.
  const cacQualifier = metricQualifier("cac_payback.months");
  let cac = { value: "n/c", sub: "", status: "neutral", note: "", qualifier: bracketed(cacQualifier), source: r.cac_payback?.source };
  if (r.cac_payback) {
    const cp = r.cac_payback;
    const L = `L${cp.default_l}`;
    const qs = Object.keys(cp.quarters).sort();
    const computable = (q) => cp.quarters[q][L].months != null;
    // Results computed before partial quarters were flagged carry no 'partial'; they read as complete.
    const complete = (q) => cp.quarters[q].partial !== true && computable(q);
    const picked = cp.headline_quarter !== undefined ? cp.headline_quarter : ([...qs].reverse().find(complete) ?? null);
    const excluded = [...qs].reverse().find((q) => cp.quarters[q].partial === true && computable(q) && (!picked || q > picked));
    const partialNote = excluded
      ? `${excluded} not shown: partial (${cp.quarters[excluded].months_in_quarter} of 3 months)`
      : "";
    if (picked) {
      const m = cp.quarters[picked][L].months;
      cac = { value: fmtMonths(m), sub: "", note: partialNote, source: cp.source,
        qualifier: bracketed(`${picked}, ${cacQualifier}`),
        status: m > 18 ? "warning" : m <= 12 ? "growth_positive" : "neutral" };
    } else {
      const last = qs[qs.length - 1];
      cac.note = excluded
        ? `No complete quarter yet. ${partialNote}.`
        : (last ? cp.quarters[last][L].reason : "") || "No complete quarter with a computable payback";
    }
  }

  const nrrStatus = r.nrr ? (r.nrr.overall_pct >= 100 ? "growth_positive" : "warning") : "neutral";
  const churnStatus = r.gross_churn ? (r.gross_churn.overall_pct <= 8 ? "growth_positive" : r.gross_churn.overall_pct <= 15 ? "warning" : "critical") : "neutral";

  return (
    <Layout audit={audit}>
      {data.audit?.metrics_stale && (
        <div data-testid="stale-metrics-banner"
          className="mb-6 flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-800">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          Metrics are out of date — a setup input changed since this audit was last computed.
          <button onClick={() => nav(`/audit/${id}/mapping`)} className="ml-auto underline hover:text-amber-900 whitespace-nowrap">
            Recompute →
          </button>
        </div>
      )}
      <div className="flex items-end justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">{audit?.company_name}</h1>
          <p data-testid="header-context-strip" className="text-slate-600 text-xs font-mono mt-1">
            Target: <span className="text-slate-800">{fmtCurrency(por?.target_arr, por?.reporting_currency ?? ccy)} ARR</span>{" "}
            by <span className="text-slate-800">{por?.target_date ?? "—"}</span> · FX: {fxDisplay}
          </p>
          <p className="text-slate-500 text-xs font-mono mt-1">
            {asOfFullDate ? <>Figures reflect company data through <span className="text-sky-700">{asOfFullDate}</span>. </> : null}
            Computed {data.audit.computed_at?.slice(0, 10)} — verify nothing material has changed since.
            {" "}Reporting currency {ccy}. Hover any figure for source lineage.
          </p>
        </div>
        <a href={exportUrl(id)} data-testid="export-results-button"
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md bg-sky-50 border border-[#D1D5DB] text-sm text-slate-800 hover:bg-slate-100 transition-colors">
          <Download className="h-4 w-4" /> Export results
        </a>
      </div>

      {/* Generating is explicit and costed — see NarrativeControl. */}
      <NarrativeControl
        status={narrative?.narrative_status}
        generatedAt={narrative?.generated_at}
        superseded={narrative?.superseded}
        supersededReason={narrative?.superseded_reason}
        busy={generating}
        onGenerate={onGenerate}
      />

      {/* Metric strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3 sm:gap-4 mb-6">
        <MetricCard id="arr" label={metricLabel("arr.value")} qualifier={bracketed(metricQualifier("arr.value"))} status="growth_positive" source={r.arr?.source}
          value={r.arr ? fmtCurrency(r.arr.value, ccy) : "—"} sub={r.arr ? `MRR ${fmtCurrency(r.arr.mrr, ccy)}` : ""}
          caption="Shows distance to target" />
        <MetricCard id="nrr" label={metricLabel("nrr.overall_pct")} qualifier={bracketed(metricQualifier("nrr.overall_pct"))} status={nrrStatus} source={r.nrr?.source}
          value={r.nrr ? fmtPct(r.nrr.overall_pct) : "n/c"} sub={r.nrr ? `${fmtCount(r.nrr.nrr_base_customers ?? r.nrr.n)} base customers` : "needs 12m history"}
          caption="Growth from existing customers alone" />
        <MetricCard id="gross_churn" label={metricLabel("gross_churn.overall_pct")} qualifier={bracketed(metricQualifier("gross_churn.overall_pct"))} status={churnStatus} source={r.gross_churn?.source}
          value={r.gross_churn ? fmtPct(r.gross_churn.overall_pct) : "n/c"} sub={r.gross_churn ? "" : "needs 12m history"}
          caption="Shows revenue lost to churn" />
        <MetricCard id="cac_payback" label={metricLabel("cac_payback.months")} qualifier={cac.qualifier} status={cac.status} source={cac.source}
          value={cac.value} sub={cac.sub} note={cac.note}
          caption="Time to recoup acquisition cost" />
        <MetricCard id="sales_cycle" label={metricLabel("sales_cycle.median_days")} qualifier={bracketed(metricQualifier("sales_cycle.median_days"))} status="neutral" source={r.sales_cycle?.source}
          value={r.sales_cycle?.median_days != null ? fmtDays(r.sales_cycle.median_days) : "n/c"}
          sub={r.sales_cycle ? (
            <>
              <Gloss id="sales-cycle-iqr" text="Middle 50% range">
                IQR {fmtDaysNumber(r.sales_cycle.iqr?.[0])}–{fmtDaysNumber(r.sales_cycle.iqr?.[1])} days
              </Gloss>{" · "}
              <Gloss id="sales-cycle-n" text="Number of deals">n={fmtCount(r.sales_cycle.n)}</Gloss>
            </>
          ) : ""}
          caption="Speed of closing new deals" />
        <MetricCard id="win_rate" label={metricLabel("win_rate.win_rate_pct")} qualifier={bracketed(metricQualifier("win_rate.win_rate_pct"))} status="neutral" source={r.win_rate?.source}
          value={r.win_rate ? fmtPct(r.win_rate.win_rate_pct) : "n/c"}
          sub={r.win_rate ? (
            <Gloss id="win-rate-wl" text="Won versus lost">{fmtCount(r.win_rate.won)}W / {fmtCount(r.win_rate.lost)}L</Gloss>
          ) : ""}
          note={(r.win_rate?.excluded_invalid || r.win_rate?.excluded_after_as_of) ? (
            <Gloss id="win-rate-excluded" text="Excluded: invalid entries, and deals created or closed after the as-of month">
              {[
                r.win_rate.excluded_invalid ? `${fmtCount(r.win_rate.excluded_invalid)} invalid` : null,
                r.win_rate.excluded_after_as_of ? `${fmtCount(r.win_rate.excluded_after_as_of)} after as-of month` : null,
              ].filter(Boolean).join(" · ")} excluded
            </Gloss>
          ) : ""}
          caption="Shows how repeatable sales are" />
      </div>

      {/* Narrative — status tells the reader which figures were verified */}
      <Narrative state={generating ? { loading: true } : narrative} />

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6">
        <Card className="lg:col-span-8" testid="mrr-by-segment-chart" title="Monthly MRR by Segment" hint={`${r.mrr_series.months.length} months · recurring only`}>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={r.mrr_series.data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="month" {...chartAxis} minTickGap={24} />
              <YAxis {...chartAxis} tickFormatter={(v) => fmtCurrency(v)} width={90} />
              <RTooltip contentStyle={tooltipStyle} formatter={(v, n) => [fmtCurrency(v, ccy), n]} />
              <Legend wrapperStyle={{ fontSize: 11, fontFamily: "JetBrains Mono" }} />
              {r.mrr_series.segments.map((s, i) => (
                <Area key={s} type="monotone" dataKey={s} stackId="1" isAnimationActive={false}
                  stroke={SEG_COLORS[i % SEG_COLORS.length]} fill={SEG_COLORS[i % SEG_COLORS.length]} fillOpacity={0.25} />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card className="lg:col-span-4" testid="nrr-chart" title="NRR Over Time" hint="100% baseline">
          {r.nrr?.series ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={r.nrr.series} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                <XAxis dataKey="month" {...chartAxis} minTickGap={30} />
                <YAxis {...chartAxis} domain={["auto", "auto"]} tickFormatter={fmtPct} width={52} />
                <RTooltip contentStyle={tooltipStyle} formatter={(v) => [fmtPct(v), "NRR"]} />
                <ReferenceLine y={100} stroke="#64748B" strokeDasharray="4 4" />
                <Line type="monotone" dataKey="nrr_pct" stroke="#34D399" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <NotComputable label="Needs 12+ months of history" />
          )}
        </Card>
      </div>

      {/* Cohort + Path to plan */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6">
        <Card className="lg:col-span-8" title="Cohort MRR Retention" hint="% of starting MRR retained · rows = start cohort">
          <div className="overflow-x-auto -mx-2 px-2">
            <table className="w-full border-separate border-spacing-1 min-w-[640px]">
              <thead>
                <tr>
                  <th className="text-left text-[10px] font-mono uppercase tracking-wider text-slate-500 pb-1 pr-3">Cohort</th>
                  {Array.from({ length: r.cohort_retention.max_offset + 1 }).map((_, o) => (
                    <th key={o} className="text-[10px] font-mono text-slate-500 pb-1 w-12">M{o}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {r.cohort_retention.data.map((row) => (
                  <tr key={row.cohort}>
                    <td className="text-xs font-mono text-slate-700 pr-3 whitespace-nowrap">
                      {row.cohort} <span className="text-slate-600">n={fmtCount(row.n)}</span>
                    </td>
                    {Array.from({ length: r.cohort_retention.max_offset + 1 }).map((_, o) => {
                      const v = row.values[String(o)];
                      return (
                        <td key={o} data-testid={`cohort-cell-${row.cohort}-${o}`}
                          className={`text-center text-[11px] font-mono rounded py-1.5 ${cohortTier(v)}`}>
                          {v != null ? fmtPct(v) : ""}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="lg:col-span-4" testid="path-to-plan-panel" title="Path to Plan" hint="simple view · flat base · today's ACV · net-new customers / year">
          {r.acv_path ? (
            <>
              {r.acv_path.target_date_error && (
                <div data-testid="target-date-error" className="mb-3 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-800">
                  <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                  {r.acv_path.target_date_error} — required net-new not computed.
                </div>
              )}
              <div className="grid grid-cols-2 gap-3 mb-4">
                <Stat path="current_customers" value={fmtCount(r.acv_path.current_customers)} />
                <Stat path="current_arr" value={fmtCurrency(r.acv_path.current_arr, ccy)} />
                <Stat path="acv" value={fmtCurrency(r.acv_path.acv, ccy)} />
                {/* A TOTAL at the target ARR, existing customers included - not the gap. Results
                    computed before the rename carry it as customers_needed. */}
                <Stat path="total_customers_at_target"
                  value={fmtCountUp(r.acv_path.total_customers_at_target ?? r.acv_path.customers_needed)} />
                {/* The gap: shown only when the engine computed it, never derived here. */}
                {r.acv_path.additional_customers_needed != null && (
                  <Stat path="additional_customers_needed" value={fmtCountUp(r.acv_path.additional_customers_needed)} />
                )}
              </div>
              <ResponsiveContainer width="100%" height={160}>
                {(() => {
                  const bars = [
                    { k: "Required/yr", v: r.acv_path.required_net_new_per_year, fill: "#FBBF24" },
                    { k: "Observed net 12m", v: r.acv_path.observed_net_new_per_year_12m, fill: "#38BDF8" },
                    { k: "Observed net 24m", v: r.acv_path.observed_net_new_per_year_24m, fill: "#34D399" },
                  ];
                  return (
                    <BarChart data={bars}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                      <XAxis dataKey="k" {...chartAxis} />
                      <YAxis {...chartAxis} width={40} tickFormatter={fmtCount} />
                      <RTooltip contentStyle={tooltipStyle}
                        formatter={(v, _n, p) => [p.payload.k === "Required/yr" ? fmtCountUp(v) : fmtCount(v), p.payload.k]} />
                      <Bar dataKey="v" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                        {bars.map((b, i) => <Cell key={i} fill={b.fill} />)}
                      </Bar>
                    </BarChart>
                  );
                })()}
              </ResponsiveContainer>
              <div className="mt-3 text-xs font-mono text-slate-600">
                Required ÷ observed (12m):{" "}
                <span className={r.acv_path.required_vs_observed_12m > 1.2 ? "text-amber-700" : "text-emerald-700"}>
                  {fmtRatio(r.acv_path.required_vs_observed_12m)}
                </span>
              </div>
              {r.segment_paths?.stage_one && (
                <div data-testid="path-to-plan-view-note" className="mt-1 text-[11px] text-slate-500">
                  The simple view: the base held flat, new customers at today's blended ACV, net-new customers. The segment
                  view below asks the same question with different assumptions — see how the two relate there.
                </div>
              )}
            </>
          ) : <NotComputable label="No revenue data" />}
        </Card>
      </div>

      {/* Segment tables + ACV bands */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6">
        <Card className="lg:col-span-4" title="NRR by Segment">
          <SegTable rows={r.nrr?.by_segment} render={(v) => fmtPct(v.nrr_pct)} empty="Segment column not mapped" />
        </Card>
        <Card className="lg:col-span-4" title="Sales Cycle by Segment">
          <SegTable rows={r.sales_cycle?.by_segment} render={(v) => `${fmtDays(v.median_days)} · n=${fmtCount(v.n)}`} empty="Segment column not mapped" />
        </Card>
        <Card className="lg:col-span-4" title={`ACV Bands — active customers (as of ${r.as_of_month ?? "—"})`}>
          {r.acv_path ? (
            <div className="space-y-1.5">
              {r.acv_path.overall_band && (
                <div data-testid="acv-overall-band" className="text-sm text-slate-800 pb-1.5 mb-1.5 border-b border-[#E5E7EB]">
                  Overall: <span className="font-medium">{r.acv_path.overall_band.label}</span>{" "}
                  <span className="font-mono text-slate-600">({fmtCurrency(r.acv_path.acv, ccy)})</span>
                </div>
              )}
              {r.acv_path.bands.filter((b) => b.count > 0).map((b) => (
                <div key={b.key} className="flex items-center justify-between text-sm">
                  <span className="text-slate-700">
                    {b.label} <span className="text-slate-500">({bandRangeLabel(b.low, b.high, ccy)})</span>
                  </span>
                  <span className="font-mono text-slate-900">{fmtCount(b.count)}</span>
                </div>
              ))}
            </div>
          ) : <NotComputable label="No revenue data" />}
        </Card>
      </div>

      {/* Win rate by founder + CAC quarters */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6">
        <Card className="lg:col-span-4" title="Win Rate by Founder Involvement">
          {r.win_rate?.by_founder ? (
            <div className="space-y-3">
              {Object.entries(r.win_rate.by_founder).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <div>
                    <div className="text-sm text-slate-800 capitalize">{k.replace("_", " ")}</div>
                    <div className="text-[10px] font-mono text-slate-500">
                      n={fmtCount(v.n)} {v.small_sample && <span className="text-amber-700">· small sample</span>}
                    </div>
                  </div>
                  <div className="font-mono text-lg text-slate-900">{fmtPct(v.win_rate_pct)}</div>
                </div>
              ))}
            </div>
          ) : <NotComputable label="'Founder involved' column not mapped" />}
        </Card>

        <Card className="lg:col-span-8" title="CAC Payback by Quarter" hint="months · L = quarters of S&M lag">
          {r.cac_payback ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] font-mono uppercase tracking-wider text-slate-500 text-left">
                    <th className="py-1.5 pr-3">Quarter</th>
                    <th className="py-1.5 pr-3">New MRR</th>
                    <th className="py-1.5 pr-3">GM%</th>
                    <th className="py-1.5 pr-3">L0</th>
                    <th className="py-1.5 pr-3">L1</th>
                    <th className="py-1.5 pr-3">L2</th>
                  </tr>
                </thead>
                <tbody className="font-mono text-slate-800">
                  {Object.entries(r.cac_payback.quarters).map(([q, v]) => (
                    <tr key={q} className="border-t border-[#E5E7EB]">
                      <td className="py-1.5 pr-3 whitespace-nowrap">
                        {q}
                        {v.partial && (
                          <div data-testid={`cac-partial-${q}`} className="text-[10px] text-amber-700">
                            partial ({v.months_in_quarter} of 3 months)
                          </div>
                        )}
                      </td>
                      <td className="py-1.5 pr-3">{fmtCurrency(v.new_mrr, ccy)}</td>
                      <td className="py-1.5 pr-3">{fmtPct(v.gross_margin_pct)}</td>
                      {["L0", "L1", "L2"].map((L) => (
                        <td key={L} className="py-1.5 pr-3">
                          {v[L].months != null
                            ? <span title={v[L].sm_expense != null ? `S&M used: ${fmtCurrency(v[L].sm_expense, ccy)} · New MRR: ${fmtCurrency(v.new_mrr, ccy)} · GM: ${fmtPct(v.gross_margin_pct)}` : ""}>{fmtMonths(v[L].months)}</span>
                            : <span className="text-slate-600" title={v[L].reason}>n/c</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <NotComputable label="P&L not provided" />}
        </Card>
      </div>

      {/* Segment mix paths to target ARR - hidden for results computed before it existed */}
      {r.segment_paths && <SegmentPaths sp={r.segment_paths} ccy={ccy} />}

      {/* Missing data + anomalies summary */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <Card className="lg:col-span-4" title="Anomaly Flags" hint="detected, not interpreted">
          <div className="space-y-2 text-sm">
            <Flag label="Months with negative MRR" value={fmtCount(r.anomalies.negative_mrr_months.length)}
              detail={r.anomalies.negative_mrr_months.join(", ")} />
            <Flag label="Customers with gaps > 2 months then resume" value={fmtCount(r.anomalies.revenue_gap_then_resume.length)}
              detail={r.anomalies.revenue_gap_then_resume.slice(0, 8).join(", ")} />
            <Flag label="Revenue lines missing customer ID" value={fmtCount(r.anomalies.revenue_missing_customer_id.count)} />
            <Flag label="Deals with close before created (excluded)" value={fmtCount(r.anomalies.deals_close_before_created.excluded_count)} />
          </div>
        </Card>
        <Card className="lg:col-span-4" testid="missing-data" title="Missing Data" hint={`${fmtCount(missing.length)} items`}>
          {missing.length === 0 ? (
            <p data-testid="missing-data-none" className="text-sm text-slate-600">{NONE}</p>
          ) : (
            <div className="space-y-2">
              {missing.slice(0, 5).map((m, i) => (
                <div key={i} data-testid={`missing-data-item-${i}`} className="text-sm">
                  <div className="text-slate-800">{m.metric}</div>
                  <div className="text-[11px] text-slate-500">{m.reason}</div>
                  {m.absent && <div className="text-[11px] text-slate-600 mt-0.5">Absent fields — {m.absent}</div>}
                </div>
              ))}
              <button onClick={() => nav(`/audit/${id}/diagnostics`)} className="text-sky-700 hover:text-sky-800 text-xs underline mt-2">
                View full diagnostics →
              </button>
            </div>
          )}
        </Card>
        <Card className="lg:col-span-4" testid="management-questions" title="Questions for management"
          hint={`${fmtCount(questions.length)} items`}>
          {questions.length === 0 ? (
            <p data-testid="management-questions-none" className="text-sm text-slate-600">{questionsEmptyText(r)}</p>
          ) : (
            <div className="space-y-3">
              {questions.map((q, i) => (
                <div key={i} data-testid={`management-question-${i}`} className="text-sm">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-slate-800">{q.metric}</span>
                    <Provenance source={q.source} id={`management-question-${i}`}>
                      <span className="font-mono text-slate-900">{q.value}</span>
                    </Provenance>
                  </div>
                  <div className="text-[10px] font-mono text-slate-500 mt-0.5">{q.sourceText}</div>
                  <div className="text-[11px] text-amber-700 mt-0.5">{q.status}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card className="mb-6" testid="glossary" title="Glossary" hint="terms used above">
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-sm">
          {Object.entries(GLOSSARY).map(([term, def]) => (
            <div key={term} className="flex gap-2">
              <dt className="font-mono text-slate-900">{term}</dt>
              <dd className="text-slate-600">{def}</dd>
            </div>
          ))}
        </dl>
      </Card>

      {/* One disclosure for the whole analysis: which model wrote the narrative and
          when. Prompt version is deliberately not shown - it stays in the audit trail. */}
      {disclosure?.text && (
        <p data-testid="ai-disclosure" className="mb-6 border-t border-[#E5E7EB] pt-3 text-xs text-slate-500">
          {disclosure.text}
        </p>
      )}
    </Layout>
  );
}

function Card({ title, hint, className = "", testid, children }) {
  return (
    <div data-testid={testid} className={`bg-white border border-[#E5E7EB] rounded-lg p-5 ${className}`}>
      <div className="flex items-baseline justify-between mb-4">
        <h3 className="font-heading font-semibold text-slate-900 text-sm">{title}</h3>
        {hint && <span className="text-[10px] font-mono text-slate-500">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function Stat({ path, label, value }) {
  const name = label ?? metricLabel(path);
  const qualifier = bracketed(metricQualifier(path));
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-mono">{name}</div>
      <div className="font-mono text-slate-900 text-lg">{value}</div>
      {/* A stat is read on its own, so its qualifier sits beneath the value. */}
      {qualifier && <div className="text-[10px] text-slate-500 font-mono">{qualifier}</div>}
    </div>
  );
}

function SegTable({ rows, render, empty }) {
  if (!rows || Object.keys(rows).length === 0) return <NotComputable label={empty} />;
  return (
    <div className="space-y-2">
      {Object.entries(rows).map(([seg, v]) => (
        <div key={seg} className="flex items-center justify-between text-sm">
          <span className="text-slate-700">{seg}</span>
          <span className="font-mono text-slate-900">{render(v)}</span>
        </div>
      ))}
    </div>
  );
}

function Flag({ label, value, detail }) {
  const active = value > 0;
  return (
    <div className="flex items-start justify-between gap-3">
      <div>
        <div className="text-slate-700">{label}</div>
        {active && detail && <div className="text-[11px] font-mono text-slate-500 mt-0.5">{detail}</div>}
      </div>
      <span className={`font-mono px-2 py-0.5 rounded text-xs ${active ? "bg-amber-500/15 text-amber-700" : "bg-slate-100 text-slate-500"}`}>
        {value}
      </span>
    </div>
  );
}

function NotComputable({ label }) {
  return (
    <div className="flex items-center gap-2 text-slate-500 text-xs py-6 justify-center border border-dashed border-[#E5E7EB] rounded-md">
      <AlertTriangle className="h-3.5 w-3.5" /> {label}
    </div>
  );
}
