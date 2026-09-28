import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ResponsiveContainer, ReferenceLine, Legend,
} from "recharts";
import { Loader2, AlertTriangle, TrendingUp, Download } from "lucide-react";
import { Layout } from "@/components/Layout";
import { MetricCard } from "@/components/MetricCard";
import { Provenance } from "@/components/Provenance";
import { Gloss } from "@/components/Gloss";
import { getAudit, getResults, exportUrl } from "@/lib/api";
import { money, pct, num, monthEndDate } from "@/lib/format";

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

  useEffect(() => {
    getAudit(id).then(setAudit).catch(() => {});
    getResults(id)
      .then(setData)
      .catch((e) => setError(e.response?.status === 409 ? "not_computed" : "error"));
  }, [id]);

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

  // representative CAC (latest computable quarter at default L)
  let cac = { value: "n/c", sub: "", status: "neutral", note: "", source: r.cac_payback?.source };
  if (r.cac_payback) {
    const L = `L${r.cac_payback.default_l}`;
    const qs = Object.keys(r.cac_payback.quarters).sort();
    let picked = null;
    for (const q of qs) if (r.cac_payback.quarters[q][L].months != null) picked = q;
    if (picked) {
      const m = r.cac_payback.quarters[picked][L].months;
      cac = { value: `${m} mo`, sub: <Gloss id="cac-quarter" text="Quarter of calculation">{picked}</Gloss>,
        note: "", source: r.cac_payback.source,
        status: m > 18 ? "warning" : m <= 12 ? "growth_positive" : "neutral" };
    } else {
      const last = qs[qs.length - 1];
      cac.note = last ? r.cac_payback.quarters[last][L].reason : "";
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
            Target: <span className="text-slate-800">{money(por?.target_arr, por?.reporting_currency ?? ccy)} ARR</span>{" "}
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

      {/* Metric strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3 sm:gap-4 mb-6">
        <MetricCard id="arr" label="Ending ARR" status="growth_positive" source={r.arr?.source}
          value={r.arr ? money(r.arr.value, ccy) : "—"} sub={r.arr ? `MRR ${money(r.arr.mrr, ccy)}` : ""}
          caption="Shows distance to target" />
        <MetricCard id="nrr" label="Net Revenue Retention" status={nrrStatus} source={r.nrr?.source}
          value={r.nrr ? pct(r.nrr.overall_pct) : "n/c"} sub={r.nrr ? `${r.nrr.n} base customers` : "needs 12m history"}
          caption="Growth from existing customers alone" />
        <MetricCard id="gross_churn" label="Gross Revenue Churn" status={churnStatus} source={r.gross_churn?.source}
          value={r.gross_churn ? pct(r.gross_churn.overall_pct) : "n/c"} sub={r.gross_churn ? "12-month" : "needs 12m history"}
          caption="Shows revenue lost to churn" />
        <MetricCard id="cac_payback" label="CAC Payback" status={cac.status} source={cac.source}
          value={cac.value} sub={cac.sub} note={cac.note}
          caption="Time to recoup acquisition cost" />
        <MetricCard id="sales_cycle" label="Median Sales Cycle" status="neutral" source={r.sales_cycle?.source}
          value={r.sales_cycle?.median_days != null ? `${r.sales_cycle.median_days} d` : "n/c"}
          sub={r.sales_cycle ? (
            <>
              <Gloss id="sales-cycle-iqr" text="Middle 50% range">
                IQR {r.sales_cycle.iqr?.[0]}–{r.sales_cycle.iqr?.[1]}
              </Gloss>{" · "}
              <Gloss id="sales-cycle-n" text="Number of deals">n={r.sales_cycle.n}</Gloss>
            </>
          ) : ""}
          caption="Speed of closing new deals" />
        <MetricCard id="win_rate" label="Win Rate" status="neutral" source={r.win_rate?.source}
          value={r.win_rate ? pct(r.win_rate.win_rate_pct) : "n/c"}
          sub={r.win_rate ? (
            <Gloss id="win-rate-wl" text="Won versus lost">{r.win_rate.won}W / {r.win_rate.lost}L</Gloss>
          ) : ""}
          note={r.win_rate?.excluded_invalid ? (
            <Gloss id="win-rate-excluded" text="Excluded invalid entries">
              {r.win_rate.excluded_invalid} invalid excluded
            </Gloss>
          ) : ""}
          caption="Shows how repeatable sales are" />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6">
        <Card className="lg:col-span-8" testid="mrr-by-segment-chart" title="Monthly MRR by Segment" hint={`${r.mrr_series.months.length} months · recurring only`}>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={r.mrr_series.data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="month" {...chartAxis} minTickGap={24} />
              <YAxis {...chartAxis} tickFormatter={(v) => money(v, ccy)} width={60} />
              <RTooltip contentStyle={tooltipStyle} formatter={(v, n) => [money(v, ccy), n]} />
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
                <YAxis {...chartAxis} domain={["auto", "auto"]} tickFormatter={(v) => `${v}%`} width={44} />
                <RTooltip contentStyle={tooltipStyle} formatter={(v) => [`${v}%`, "NRR"]} />
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
                      {row.cohort} <span className="text-slate-600">n={row.n}</span>
                    </td>
                    {Array.from({ length: r.cohort_retention.max_offset + 1 }).map((_, o) => {
                      const v = row.values[String(o)];
                      return (
                        <td key={o} data-testid={`cohort-cell-${row.cohort}-${o}`}
                          className={`text-center text-[11px] font-mono rounded py-1.5 ${cohortTier(v)}`}>
                          {v != null ? Math.round(v) : ""}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="lg:col-span-4" testid="path-to-plan-panel" title="Path to Plan" hint="required vs observed net-new customers / year">
          {r.acv_path ? (
            <>
              {r.acv_path.target_date_error && (
                <div data-testid="target-date-error" className="mb-3 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-800">
                  <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                  {r.acv_path.target_date_error} — required net-new not computed.
                </div>
              )}
              <div className="grid grid-cols-2 gap-3 mb-4">
                <Stat label="Current customers" value={num(r.acv_path.current_customers)} />
                <Stat label="Current ARR" value={money(r.acv_path.current_arr, ccy)} />
                <Stat label="ACV" value={money(r.acv_path.acv, ccy)} />
                <Stat label="Customers needed" value={num(r.acv_path.customers_needed, 0)} />
              </div>
              <ResponsiveContainer width="100%" height={160}>
                {(() => {
                  const bars = [
                    { k: "Required/yr", v: r.acv_path.required_net_new_per_year, fill: "#FBBF24" },
                    { k: "Observed 12m", v: r.acv_path.observed_net_new_per_year_12m, fill: "#38BDF8" },
                    { k: "Observed 24m", v: r.acv_path.observed_net_new_per_year_24m, fill: "#34D399" },
                  ];
                  return (
                    <BarChart data={bars}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                      <XAxis dataKey="k" {...chartAxis} />
                      <YAxis {...chartAxis} width={40} />
                      <RTooltip contentStyle={tooltipStyle} />
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
                  {r.acv_path.required_vs_observed_12m ?? "—"}×
                </span>
              </div>
            </>
          ) : <NotComputable label="No revenue data" />}
        </Card>
      </div>

      {/* Segment tables + ACV bands */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6">
        <Card className="lg:col-span-4" title="NRR by Segment">
          <SegTable rows={r.nrr?.by_segment} render={(v) => pct(v.nrr_pct)} empty="Segment column not mapped" />
        </Card>
        <Card className="lg:col-span-4" title="Sales Cycle by Segment">
          <SegTable rows={r.sales_cycle?.by_segment} render={(v) => `${v.median_days}d · n=${v.n}`} empty="Segment column not mapped" />
        </Card>
        <Card className="lg:col-span-4" title={`ACV Bands — active customers (as of ${r.as_of_month ?? "—"})`}>
          {r.acv_path ? (
            <div className="space-y-1.5">
              {r.acv_path.overall_band && (
                <div data-testid="acv-overall-band" className="text-sm text-slate-800 pb-1.5 mb-1.5 border-b border-[#E5E7EB]">
                  Overall: <span className="font-medium">{r.acv_path.overall_band.label}</span>{" "}
                  <span className="font-mono text-slate-600">({r.acv_path.overall_band.value_label})</span>
                </div>
              )}
              {r.acv_path.bands.filter((b) => b.count > 0).map((b) => (
                <div key={b.key} className="flex items-center justify-between text-sm">
                  <span className="text-slate-700">
                    {b.label} <span className="text-slate-500">({b.range_label})</span>
                  </span>
                  <span className="font-mono text-slate-900">{b.count}</span>
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
                      n={v.n} {v.small_sample && <span className="text-amber-700">· small sample</span>}
                    </div>
                  </div>
                  <div className="font-mono text-lg text-slate-900">{pct(v.win_rate_pct)}</div>
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
                      <td className="py-1.5 pr-3">{q}</td>
                      <td className="py-1.5 pr-3">{money(v.new_mrr, ccy)}</td>
                      <td className="py-1.5 pr-3">{v.gross_margin_pct != null ? `${v.gross_margin_pct}%` : "—"}</td>
                      {["L0", "L1", "L2"].map((L) => (
                        <td key={L} className="py-1.5 pr-3">
                          {v[L].months != null
                            ? <span title={v[L].sm_expense != null ? `S&M used: ${money(v[L].sm_expense, ccy)} · New MRR: ${money(v.new_mrr, ccy)} · GM: ${v.gross_margin_pct}%` : ""}>{v[L].months}</span>
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

      {/* Missing data + anomalies summary */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <Card className="lg:col-span-6" title="Anomaly Flags" hint="detected, not interpreted">
          <div className="space-y-2 text-sm">
            <Flag label="Months with negative MRR" value={r.anomalies.negative_mrr_months.length}
              detail={r.anomalies.negative_mrr_months.join(", ")} />
            <Flag label="Customers with gaps > 2 months then resume" value={r.anomalies.revenue_gap_then_resume.length}
              detail={r.anomalies.revenue_gap_then_resume.slice(0, 8).join(", ")} />
            <Flag label="Revenue lines missing customer ID" value={r.anomalies.revenue_missing_customer_id.count} />
            <Flag label="Deals with close before created (excluded)" value={r.anomalies.deals_close_before_created.excluded_count} />
          </div>
        </Card>
        <Card className="lg:col-span-6" title="Missing Data" hint={`${r.missing_data.length} items`}>
          {r.missing_data.length === 0 ? (
            <div className="flex items-center gap-2 text-emerald-700 text-sm py-4">
              <TrendingUp className="h-4 w-4" /> All metrics computed — no missing inputs.
            </div>
          ) : (
            <div className="space-y-2">
              {r.missing_data.slice(0, 5).map((m, i) => (
                <div key={i} className="text-sm">
                  <div className="text-slate-800">{m.metric}</div>
                  <div className="text-[11px] text-slate-500">{m.reason}</div>
                </div>
              ))}
              <button onClick={() => nav(`/audit/${id}/diagnostics`)} className="text-sky-700 hover:text-sky-800 text-xs underline mt-2">
                View full diagnostics →
              </button>
            </div>
          )}
        </Card>
      </div>
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

function Stat({ label, value }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-mono">{label}</div>
      <div className="font-mono text-slate-900 text-lg">{value}</div>
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
