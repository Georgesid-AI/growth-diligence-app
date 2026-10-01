/**
 * Display rows for the dashboard's "Missing data" and "Questions for management"
 * lists. Pure functions over the stored results - every figure goes through
 * format.js, so the lists follow the same number rules as the rest of the page.
 */
import { PLACEHOLDER, fmtDays, fmtMonths, fmtPct } from "./format";

export const COMPUTED_STATUS = "Computed – explanation requested";
export const NONE = "None";

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

export function missingRows(results) {
  return (results?.missing_data || []).map((m) => ({
    metric: m.metric,
    reason: m.reason,
    absent: absentFieldsText(m.absent_fields),
  }));
}
