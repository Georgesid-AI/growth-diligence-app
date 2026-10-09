/**
 * The "Claim register" section of the Dashboard (docs/specs/claim-matching.md section 8): what each column shows,
 * what the analyst may edit, and the edits sent to PUT /api/audits/{id}/claims/{claim_id}. The rows come from the
 * server as they are tested and ranked there (backend/app/claim_matching.py); nothing is tested or ranked here.
 */
import metricUnits from "./claim_metrics.json";
import { PLACEHOLDER, fmtCount, fmtCurrency } from "./format";
import { typeLabel } from "./deckClaims";
import { dateRangeError, displayDate } from "./datePicker";

export const REGISTER_HEADING = "Claim register";
export const DOWNLOAD_LABEL = "Download baseline (CSV)";
// docs/specs/verdict-and-memo.md section 2.1: value at stake, overlaps and evidence join the columns of claim-matching.md section 8.
export const REGISTER_COLUMNS = ["#", "Claim", "Period", "Segment", "Page", "Read from deck", "Observed", "Gap", "Gloss", "Value at stake",
  "Overlaps with", "Evidence", "Gate"];
// Only these are editable (section 3 adds the gate's metric name and direction on a row with no app metric, and the key mark).
export const EDITABLE_FIELDS = ["segment", "metric", "gate_threshold", "gate_budget_decision", "gate_date", "gate_metric_name",
  "gate_direction", "key_gate"];
export const READ_ONLY_FIELDS = ["rank", "claim", "period", "page", "deck_reading", "observed", "gap", "gloss", "value_at_stake",
  "overlaps_with", "evidence"];

// Screen wording W4, W5, W22 (verdict-and-memo.md section 11).
export const GATE_NEEDED = "Gate needed";
export const KEY_GATE_LABEL = "Key gate";
export const GATE_METRIC_PLACEHOLDER = "Metric (max 100 characters)";
export const GATE_METRIC_MAX = 100;
export const GATE_DIRECTIONS = [["at least", "At least"], ["at most", "At most"]];
const NO_APP_METRIC = ["no metric", "metric does not fit the claim's unit"];

export const WHOLE_COMPANY = "Whole company";
export const NOT_IN_DATA = "Not in the data";
export const NO_METRIC = "none";
export const GATE_BUDGET_MAX = 200;

const METRIC_UNIT = metricUnits.metrics;
const DURATIONS = ["days", "weeks", "months", "years"];

// Section 11 of docs/specs/claim-matching.md: the one-click answer to "revenue or volume?" and its reason codes.
/** The two pairs the server refuses: a reason that says the opposite of the answer. */
export const contradicts = (answer, reason) => (answer === "volume" && reason === "deck_says_gross_revenue")
  || (answer === "revenue" && reason === "deck_says_processed_volume");

export const TURNOVER_REASONS = [
  ["deck_says_gross_revenue", "Deck says gross revenue"], ["deck_says_processed_volume", "Deck says processed volume"],
  ["file_confirms", "File confirms"], ["other", "Other"],
];
export const TURNOVER_QUESTION = "Revenue or transaction volume?";

/** "Implied take rate 10.0% (derived, not verified)": revenue ÷ volume, or null. */
export const takeRateText = (row) => (row.implied_take_rate == null ? null
  : `Implied take rate ${(row.implied_take_rate * 100).toFixed(2)}% (derived, not verified)`);

export const csvUrl = (apiBase, auditId) => `${apiBase}/audits/${auditId}/claims.csv`;
export const registerRows = (data) => data?.register ?? [];

/** currency, %, days, weeks, months or count: what the claimed figure is measured in (mirrors the backend). */
export function claimUnit(row) {
  if (row.currency) return "currency";
  const unit = (row.unit || "").trim().toLowerCase();
  if (unit === "%") return "%";
  const duration = unit.match(/^(day|week|month|year)s?$/);
  if (duration) return `${duration[1]}s`;
  if (/^hours?$/.test(unit)) return null;              // not a duration the engine measures
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

/** Whether the gate of a row also needs the analyst's metric name and direction: the row has no metric of the app. */
export const needsMetricName = (row) => NO_APP_METRIC.includes(row.reason);

/** W1: "not yet computed · shortfall 18.3%"; a row with no shortfall reads "not yet computed". */
export function valueAtStakeText(row) {
  const base = "not yet computed";
  return row.shortfall == null ? base : `${base} · shortfall ${(row.shortfall * 100).toFixed(1)}%`;
}

/** W2: the ranks of the rows it overlaps with, "#3, #7"; none: a dash. */
export function overlapsText(row, rows) {
  const rank = Object.fromEntries(rows.map((r) => [r.claim_id, r.rank]));
  const ranks = (row.overlaps_with || []).map((id) => rank[id]).filter((n) => n != null).sort((a, b) => a - b);
  return ranks.length ? ranks.map((n) => `#${n}`).join(", ") : PLACEHOLDER;
}

/** W3: the label and reason, then the analysis and source key the figure was read from, with the month or quarter. */
export function evidenceLines(row) {
  const first = `${row.evidence_label} · ${row.reason}`;
  if (!row.evidence_analysis) return { first, second: null };
  const at = row.observed_at ? ` (${row.observed_at})` : "";
  return { first, second: `${row.evidence_analysis} · ${row.evidence_source_key}${at}` };
}

const trimmed = (v, dp) => String(Number(Number(v).toFixed(dp)));

/** "positive (no figure)": a direction the deck states with no figure (docs/specs/claim-matching.md section 2). */
export const directionText = (direction) => `${direction} (no figure)`;

/** "(171,000 EUR at 1.14, 30 Jun 2026)": a claim in another currency, converted at the saved rate before it is matched. */
export function conversionText(row, ccy) {
  if (row.claimed_converted == null || row.fx_rate == null) return "";
  const range = row.claimed_converted_high == null ? fmtCurrency(row.claimed_converted, ccy)
    : `${fmtCurrency(row.claimed_converted)}–${fmtCurrency(row.claimed_converted_high, ccy)}`;
  const at = displayDate(row.fx_date);
  return ` (${range} at ${trimmed(row.fx_rate, 6)}${at ? `, ${at}` : ""})`;
}

/** "200,000 EUR", "41%", "4 customers": the claimed figure in the claim's own unit; in another currency than the audit's,
 *  both figures: "150,000 GBP (171,000 EUR at 1.14, 30 Jun 2026)"; a direction with no figure: "positive (no figure)". */
export function claimFigure(row, ccy) {
  const lo = row.claimed_value;
  const hi = row.claimed_high;
  if (lo == null && row.claim_direction) return directionText(row.claim_direction);
  if (row.currency && row.claimed_converted != null) {
    return (hi == null ? fmtCurrency(lo, row.currency) : `${fmtCurrency(lo)}–${fmtCurrency(hi, row.currency)}`) + conversionText(row, ccy);
  }
  if (row.currency) return hi == null ? fmtCurrency(lo, row.currency) : `${fmtCurrency(lo)}–${fmtCurrency(hi, row.currency)}`;
  if (row.unit === "%") return hi == null ? `${trimmed(lo, 4)}%` : `${trimmed(lo, 4)}–${trimmed(hi, 4)}%`;
  const num = (v) => (DURATIONS.includes(claimUnit(row)) ? trimmed(v, 4) : fmtCount(v));
  return `${hi == null ? num(lo) : `${num(lo)}–${num(hi)}`}${row.unit ? ` ${row.unit}` : ""}`;
}

/** "Revenue · 200,000 EUR": the claim's type and its figure. */
export const claimText = (row, ccy) => `${typeLabel(row.claim_type)} · ${claimFigure(row, ccy)}`;

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
  const dateError = dateRangeError("The gate date", date);
  if (dateError) throw new Error(dateError);
  if ((date || null) !== (row.gate_date ?? null)) out.gate_date = date || null;
  if (needsMetricName(row)) {
    const name = String(draft.metricName ?? "").trim();
    if (name.length > GATE_METRIC_MAX) throw new Error(`The metric is at most ${GATE_METRIC_MAX} characters`);
    if ((name || null) !== (row.gate_metric_name ?? null)) out.gate_metric_name = name || null;
    const direction = draft.direction || null;
    if (direction !== (row.gate_direction ?? null)) out.gate_direction = direction;
  }
  return out;
}

/** What the analyst sees beside the empty gate fields: the claimed and the observed figure. No threshold is proposed. */
export function gateContext(row, ccy) {
  const claimed = `Claimed ${claimFigure(row, ccy)} (${row.period || row.period_note || PLACEHOLDER})`;
  if (row.observed_value == null) return claimed;
  const observed = observedText(row, ccy);
  return `${claimed} · Observed ${observed.value} (${observed.at})`;
}
