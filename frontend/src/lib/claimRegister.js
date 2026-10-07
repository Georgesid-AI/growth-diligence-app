/**
 * The "Claim register" section of the Dashboard (docs/specs/claim-matching.md section 8): what each column shows,
 * what the analyst may edit, and the edits sent to PUT /api/audits/{id}/claims/{claim_id}. The rows come from the
 * server as they are tested and ranked there (backend/app/claim_matching.py); nothing is tested or ranked here.
 */
import metricUnits from "./claim_metrics.json";
import { PLACEHOLDER, fmtCount, fmtCurrency } from "./format";
import { typeLabel } from "./deckClaims";

export const REGISTER_HEADING = "Claim register";
export const DOWNLOAD_LABEL = "Download baseline (CSV)";
export const REGISTER_COLUMNS = ["#", "Claim", "Period", "Segment", "Page", "Read from deck", "Observed", "Gap", "Gloss", "Evidence", "Gate"];
// Section 8: only these are editable; value at stake is not shown until issue #6 fills it.
export const EDITABLE_FIELDS = ["segment", "metric", "gate_threshold", "gate_budget_decision", "gate_date"];
export const READ_ONLY_FIELDS = ["rank", "claim", "period", "page", "deck_reading", "observed", "gap", "gloss", "evidence"];

export const WHOLE_COMPANY = "Whole company";
export const NOT_IN_DATA = "Not in the data";
export const NO_METRIC = "none";
export const GATE_BUDGET_MAX = 200;

const METRIC_UNIT = metricUnits.metrics;
const DURATIONS = ["days", "weeks", "months"];

export const csvUrl = (apiBase, auditId) => `${apiBase}/audits/${auditId}/claims.csv`;
export const registerRows = (data) => data?.register ?? [];

/** currency, %, days, weeks, months or count: what the claimed figure is measured in (mirrors the backend). */
export function claimUnit(row) {
  if (row.currency) return "currency";
  const unit = (row.unit || "").trim().toLowerCase();
  if (unit === "%") return "%";
  const duration = unit.match(/^(day|week|month)s?$/);
  if (duration) return `${duration[1]}s`;
  if (/^(year|hour)s?$/.test(unit)) return null;       // not a duration the engine measures
  return "count";
}

const fits = (metricUnit, unit) => (["days", "months"].includes(metricUnit) ? DURATIONS.includes(unit) : unit === metricUnit);

/** The metrics the analyst may pick for a claim: those in its unit, or none. */
export function metricOptions(row) {
  const unit = claimUnit(row);
  return [...Object.keys(METRIC_UNIT).filter((m) => fits(METRIC_UNIT[m], unit)), NO_METRIC];
}

/** Every segment an engine figure is split by, without the "Unsegmented" bucket. */
export function dataSegments(results) {
  const found = new Set((results?.mrr_series?.segments || []).filter((s) => s !== "Unsegmented"));
  ["sales_cycle", "acv_path", "nrr"].forEach((key) => Object.keys(results?.[key]?.by_segment || {}).forEach((s) => found.add(s)));
  return [...found].sort();
}

export const segmentOptions = (results) => [WHOLE_COMPANY, ...dataSegments(results), NOT_IN_DATA];

const trimmed = (v, dp) => String(Number(Number(v).toFixed(dp)));

/** "Revenue · 200,000 EUR", "Sales · 41%", "Customers · 4 customers": the claim's type and its figure in its own unit. */
export function claimText(row) {
  const lo = row.claimed_value;
  const hi = row.claimed_high;
  let figure;
  if (row.currency) {
    const ccy = fmtCurrency(lo, row.currency);
    figure = hi == null ? ccy : `${fmtCurrency(lo)}–${fmtCurrency(hi, row.currency)}`;
  } else if (row.unit === "%") {
    figure = hi == null ? `${trimmed(lo, 4)}%` : `${trimmed(lo, 4)}–${trimmed(hi, 4)}%`;
  } else {
    const num = (v) => (DURATIONS.includes(claimUnit(row)) ? trimmed(v, 4) : fmtCount(v));
    figure = `${hi == null ? num(lo) : `${num(lo)}–${num(hi)}`}${row.unit ? ` ${row.unit}` : ""}`;
  }
  return `${typeLabel(row.claim_type)} · ${figure}`;
}

/** The figure in the metric's unit, as the backend's gloss rounds it. */
function inUnit(metric, value, ccy) {
  switch (METRIC_UNIT[metric]) {
    case "currency": return fmtCurrency(value, ccy);
    case "%": return `${trimmed(value, 2)}%`;
    case "days": return `${Number(value).toFixed(1)} days`;
    case "months": return `${Number(value).toFixed(1)} months`;
    default: return fmtCount(value);
  }
}

/** The observed value and the month or quarter it was read at; the source sits on the cell as a hover card. */
export function observedText(row, ccy) {
  if (row.observed_value == null) return { value: PLACEHOLDER, at: null };
  return { value: inUnit(row.metric, row.observed_value, ccy), at: row.observed_at || null };
}

/** The gap in the metric's native unit and as a share of the claim: "beat 2,125 EUR · 1.1%", "1.0 pp · 2.4%". */
export function gapText(row, ccy) {
  if (row.gap == null) return PLACEHOLDER;
  const size = Math.abs(row.gap);
  const unit = METRIC_UNIT[row.metric];
  const native = unit === "%" ? `${size.toFixed(1)} pp` : inUnit(row.metric, size, ccy);
  const share = row.gap_normalised == null ? "" : ` · ${(Math.abs(row.gap_normalised) * 100).toFixed(1)}%`;
  const prefix = row.gap_kind === "beat" ? "beat " : row.gap_kind === "to go" ? "to go " : "";
  return `${prefix}${native}${share}`;
}

const READINGS = { parser: "Read by the parser", edited: "Edited by the analyst" };
export const readingText = (reading) => READINGS[reading] || reading;

export const segmentEdit = (segment) => ({ segment });
export const metricEdit = (metric) => ({ metric });

/** The gate fields that changed, as the PUT sends them: blank is null (clears the field), the threshold a number. */
export function gateEdit(row, draft) {
  const out = {};
  const threshold = String(draft.threshold ?? "").trim();
  const next = threshold === "" ? null : Number(threshold);
  if (next !== null && !Number.isFinite(next)) throw new Error("The threshold must be a number");
  if (next !== (row.gate_threshold ?? null)) out.gate_threshold = next;
  const budget = String(draft.budget ?? "").trim();
  if (budget.length > GATE_BUDGET_MAX) throw new Error(`The budget decision is at most ${GATE_BUDGET_MAX} characters`);
  if ((budget || null) !== (row.gate_budget_decision ?? null)) out.gate_budget_decision = budget || null;
  const date = String(draft.date ?? "").trim();
  if ((date || null) !== (row.gate_date ?? null)) out.gate_date = date || null;
  return out;
}
