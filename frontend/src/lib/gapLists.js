/**
 * Display rows for the dashboard's "Missing data" and "Questions for management"
 * lists. Pure functions over the stored results - every figure goes through
 * format.js, so the lists follow the same number rules as the rest of the page.
 */
import { PLACEHOLDER, fmtCount, fmtDays, fmtMonths, fmtPct } from "./format";

export const COMPUTED_STATUS = "Computed – explanation requested";
export const NONE = "None";
export const RECOMPUTE_TO_CHECK = "Recompute to check";

// Same names the Upload & Mapping screen uses for each upload type.
export const UPLOAD_LABELS = { revenue: "Revenue Lines", crm: "CRM Deals", pnl: "P&L (monthly)" };

const fieldName = (f) => String(f).replace(/_/g, " ");

function cacHeadline(cp) {
  const q = cp.headline_quarter;
  const months = q ? cp.quarters?.[q]?.[`L${cp.default_l}`]?.months : null;
  return months != null ? `${fmtMonths(months)} (${q})` : PLACEHOLDER;
}

const VALUE_BY_KEY = {
  sales_cycle: (r) => fmtDays(r.median_days),
  win_rate: (r) => fmtPct(r.win_rate_pct),
  founder_win_rate: (r) =>
    `with founder ${fmtPct(r.by_founder?.with_founder?.win_rate_pct)} · without founder ${fmtPct(r.by_founder?.without_founder?.win_rate_pct)}`,
  nrr: (r) => fmtPct(r.overall_pct),
  gross_churn: (r) => fmtPct(r.overall_pct),
  cac_payback: cacHeadline,
};

/** The computed value of a question's result, as a display string. */
export function computedValue(resultKey, results) {
  const result = results?.[resultKey];
  const show = VALUE_BY_KEY[resultKey];
  return result && show ? show(result) : PLACEHOLDER;
}

/** "file · sheet · rows" for a stored source citation. */
export function sourceText(source) {
  if (!source) return PLACEHOLDER;
  return [source.file, source.sheet, source.rows].filter(Boolean).join(" · ") || PLACEHOLDER;
}

/** absent_fields as plain text, one clause per upload type. */
export function absentFieldsText(absent) {
  if (!absent || !Object.keys(absent).length) return "";
  return Object.entries(absent)
    .map(([dtype, fields]) => `${UPLOAD_LABELS[dtype] || dtype}: ${
      fields?.length ? fields.map(fieldName).join(", ") : "columns present, no usable rows"}`)
    .join("; ");
}

export function questionRows(results) {
  return (results?.questions_for_management || []).map((q) => ({
    metric: q.metric,
    value: computedValue(q.result_key, results),
    source: results?.[q.result_key]?.source || null,
    sourceText: sourceText(results?.[q.result_key]?.source),
    status: q.status || COMPUTED_STATUS,
    question: q.question,
  }));
}

/** What the questions card says when it has no rows. Results computed before V6 have
 *  no questions_for_management field at all: nothing was checked, so not "None". */
export function questionsEmptyText(results) {
  return Array.isArray(results?.questions_for_management) ? NONE : RECOMPUTE_TO_CHECK;
}

export function missingRows(results) {
  return (results?.missing_data || []).map((m) => ({
    metric: m.metric,
    reason: m.reason,
    absent: absentFieldsText(m.absent_fields),
  }));
}

export const ANOMALIES_NOT_COMPUTED = "Not computed: calculation error. See Missing Data.";

/** The dashboard's anomaly flags as { label, count, detail } rows, or null when the engine
 *  could not compute them (results.anomalies is null): a failure never reads as 0 anomalies. */
export function anomalyFlags(results) {
  const a = results?.anomalies;
  if (!a) return null;
  const dates = a.date_order_from_data ?? [];
  return [
    { label: "Months with negative MRR", count: a.negative_mrr_months.length, detail: a.negative_mrr_months.join(", ") },
    { label: "Customers with gaps > 2 months then resume", count: a.revenue_gap_then_resume.length,
      detail: a.revenue_gap_then_resume.slice(0, 8).join(", ") },
    { label: "Revenue lines missing customer ID", count: a.revenue_missing_customer_id.count },
    { label: "Deals with close before created (excluded)", count: a.deals_close_before_created.excluded_count },
    { label: "Date columns with day/month order set from the data", count: dates.length,
      detail: dates.map((n) => `${n.field} (${n.dataset}): ${n.order}, ${fmtCount(n.rows)} rows`).join("; ") },
  ];
}
