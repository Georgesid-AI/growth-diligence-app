/**
 * The "Claim register" section of the Dashboard (docs/specs/claim-matching.md section 8): what each column shows,
 * what the analyst may edit, and the edits sent to PUT /api/audits/{id}/claims/{claim_id}. The rows come from the
 * server as they are tested and ranked there (backend/app/claim_matching.py); nothing is tested or ranked here.
 */
import metricUnits from "./claim_metrics.json";
import { PLACEHOLDER, fmtCount, fmtCurrency } from "./format";
import { NO_DATE, rateMissingText, typeLabel } from "./deckClaims";
import { dateRangeError, displayDate } from "./datePicker";

export const REGISTER_HEADING = "Claim register";
export const DOWNLOAD_LABEL = "Download baseline (CSV)";
// docs/specs/verdict-and-memo.md section 2.1: value at stake ("VaS", in the glossary), overlaps and evidence join the columns of
// claim-matching.md section 8.
export const REGISTER_COLUMNS = ["#", "Claim", "Period", "Segment", "Page", "Read from deck", "Observed", "Gap", "Gloss", "VaS",
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
  ["file_confirms", "Revenue file confirms"], ["other", "Other"],
];
/** The row's own note when no revenue file covers the claim's period (backend NO_FILE_PERIOD). */
export const NO_FILE_PERIOD = "No revenue-file period to compare";
/** The reason codes a row offers: "Revenue file confirms" has nothing to confirm with when no revenue file covers the period. */
export const reasonsFor = (view) => TURNOVER_REASONS.filter(([code]) => !(code === "file_confirms" && view?.file_note === NO_FILE_PERIOD));
/** The note beside the reason "Other" (chat-upload.md S20): at most 60 characters, no digits. Cell text, file names and the
 *  company name cannot be told apart here. */
export const TURNOVER_NOTE_MAX = 60;
export const TURNOVER_NOTE_PLACEHOLDER = "Why? Up to 60 characters; no file names, figures or names.";
export const TURNOVER_NOTE_REFUSED = "Leave out file names, figures and cell values.";
export const noteRefused = (note) => /\d/.test(note) || note.length > TURNOVER_NOTE_MAX;
/** Whether an answer may be sent: a reason that fits, offered on this row, and for "Other" a filled note. */
export const answerReady = (answer, reason, note, view) =>
  Boolean(reason) && reasonsFor(view).some(([code]) => code === reason) && !contradicts(answer, reason)
  && (reason !== "other" || (note.trim() !== "" && !noteRefused(note)));
export const TURNOVER_QUESTION = "Revenue or transaction volume?";
// The deck list (section 11 point 8): a turnover claim never reads "Revenue" before the analyst confirms it.
export const TURNOVER_CONFIRM = "Turnover – confirm:";
export const UNVERIFIED = "Unverified";

/** The turnover views of a deck-list claim (one per value of a table row) and whether one still waits for the analyst. */
export function turnoverOf(candidate) {
  const views = candidate?.turnover || [];
  return { views, open: views.some((v) => v.turnover_set_by !== "analyst") };
}

/** "Turnover – confirm:" for a claim the analyst has not confirmed, with its period for a value of a table row
 *  ("FY2022 · Turnover – confirm:"); undefined once confirmed (the control then shows the answer). */
export const turnoverHeading = (view, multi) => (view.turnover_set_by === "analyst" ? undefined
  : `${multi && view.period ? `${view.period} · ` : ""}${TURNOVER_CONFIRM}`);

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

/** " (171,000 EUR)": a claim in another currency, converted at the saved rate before it is matched, in whole units. The rate and
 *  the date it applies at are on hover (rateHover) and in the stored row; they never stand in the claim's text. */
export function conversionText(row, ccy) {
  if (row.claimed_converted == null || row.fx_rate == null) return "";
  const range = row.claimed_converted_high == null ? fmtCurrency(row.claimed_converted, ccy)
    : `${fmtCurrency(row.claimed_converted)}–${fmtCurrency(row.claimed_converted_high, ccy)}`;
  return ` (${range})`;
}

/** "Rate used: 1 GBP = 1.14 EUR on 30 Jun 2026", or null for a claim that is not converted. */
export function rateHover(row, ccy) {
  if (row.claimed_converted == null || row.fx_rate == null || !row.currency) return null;
  const at = displayDate(row.fx_date);
  return `Rate used: 1 ${row.currency} = ${trimmed(row.fx_rate, 6)} ${ccy}${at ? ` on ${at}` : ""}`;
}

/** "GBP→EUR": the pair a claim in another currency has no saved rate for; null when it has a rate or needs none. */
export const missingRatePair = (row, ccy) =>
  (row.currency && ccy && row.currency !== ccy && row.claimed_value != null && row.claimed_converted == null && row.fx_rate == null
    ? `${row.currency}→${ccy}` : null);

/** "200,000 EUR", "41%", "4 customers": the claimed figure in the claim's own unit; in another currency than the audit's,
 *  both figures: "150,000 GBP (171,000 EUR)"; a direction with no figure: "positive (no figure)". */
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

/** "Revenue · 200,000 EUR": the claim's type and its figure. A turnover claim reads "Turnover · 550,508 GBP" until the analyst
 *  confirms it (claim-matching.md section 11 point 8): it never reads Revenue before. */
export const claimText = (row, ccy) => `${row.turnover_state && row.turnover_set_by !== "analyst" ? "Turnover"
  : typeLabel(row.claim_type)} · ${claimFigure(row, ccy)}`;

/** The claim cell: the type and the figure, and with no saved rate "(GBP→EUR rate missing – enter it in FX settings at the top of
 *  the page)", whose "FX settings" the screen shows as a link. */
export function claimCellText(row, ccy) {
  const pair = missingRatePair(row, ccy);
  return claimText(row, ccy) + (pair ? ` (${rateMissingText(pair)})` : "");
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

const READINGS = { parser: "Read by the parser", edited: "Edited by the analyst", "analyst-entered": "Analyst-entered" };
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
