/**
 * The "Claim register" section of the Dashboard (docs/specs/claim-matching.md section 8): what each column shows,
 * what the analyst may edit, and the edits sent to PUT /api/audits/{id}/claims/{claim_id}. The rows come from the
 * server as they are tested and ranked there (backend/app/claim_matching.py); nothing is tested or ranked here.
 */
import metricUnits from "./claim_metrics.json";
import evidenceLabels from "./evidence_labels.json";
import claimColumns from "./claim_columns.json";
import { PLACEHOLDER, fmtCount, fmtCurrency } from "./format";
import { NO_DATE, STALE_LABEL, rateMissingText, typeLabel } from "./deckClaims";
import { dateRangeError, displayDate } from "./datePicker";

export const REGISTER_HEADING = "Claim register";
/** George, 2026-10-20: figures stored under an older engine contract are never shown as current; Run audit calculates them again. */
export { STALE_LABEL };
export const DOWNLOAD_LABEL = "Download baseline (CSV)";
// The register is four columns, the same four on the five selected claims and in the memo's Appendix A (docs/specs/forecast-and-payback.md section 5;
// claim_columns.json, pinned by the backend): Claim and period · Evidence / calculation · Result · Source. The segment and metric, the extraction
// confidence, how the deck was read, the gloss, VaS (value at stake, in the glossary), overlaps, the formula inputs and the gate sit under Details.
export const REGISTER_COLUMNS = claimColumns.columns;
// The width of each column as a share of the table, in the order of REGISTER_COLUMNS; the table is fixed-layout, so they sum to 100.
export const REGISTER_COLUMN_WIDTHS = [26, 32, 24, 18];
/** The one sentence shown whenever a forecast appears (design note section 6): once above the register, once under the five, never on a row. */
export const FORECAST_NOTE = claimColumns.forecast_note;
// The hover explainers of the label, word for word from the shared list (evidence_labels.json, pinned by the backend).
export const EXTRACTION_EXPLAINER = evidenceLabels.explainers.extraction_confidence;
export const EVIDENCE_EXPLAINER = evidenceLabels.explainers.evidence_status;
export const EVIDENCE_STATUSES = evidenceLabels.statuses;
export const COLUMN_EXPLAINERS = { Result: EVIDENCE_EXPLAINER };
export const EVIDENCE_SUBTITLE = "(within the supplied evidence)";
// One style per evidence status, shared by the register and the conclusion section.
export const LABEL_STYLE = {
  Verified: "text-emerald-800 border-emerald-500/50 bg-emerald-50",
  Contradicted: "text-rose-800 border-rose-500/50 bg-rose-50",
  Inconclusive: "text-violet-800 border-violet-500/50 bg-violet-50",
  Unverified: "text-amber-800 border-amber-500/50 bg-amber-50",
  Unsupported: "text-slate-700 border-slate-400/60 bg-slate-50",
};
// The definition of each of the five labels, from the one shared list (docs/design/simplified-flow.md, Evidence labels): on hover
// wherever a label appears, and printed in full once under the five findings. LABEL_ORDER is the order they are printed in.
export const LABEL_DEFINITIONS = evidenceLabels.definitions;
export const LABEL_ORDER = Object.keys(evidenceLabels.definitions);
/** "Verified: the raw data confirms the claim." for a label; undefined for anything that is not one of the five (Definition check). */
export const labelDefinition = (label) => (LABEL_DEFINITIONS[label] ? `${label}: ${LABEL_DEFINITIONS[label]}` : undefined);
export const VAS_LABEL = "VaS";
// Only these are editable (section 3 adds the gate's metric name and direction on a row with no app metric).
export const EDITABLE_FIELDS = ["segment", "metric", "gate_threshold", "gate_budget_decision", "gate_date", "gate_metric_name",
  "gate_direction"];
export const READ_ONLY_FIELDS = ["rank", "claim", "period", "page", "deck_reading", "extraction_confidence", "observed", "gap", "gloss", "value_at_stake",
  "overlaps_with", "evidence"];

// Screen wording (verdict-and-memo.md section 11). A gate is written from the claim and reads "(proposed)" until the analyst edits it.
export const GATE_TAGS = { proposed: "(proposed)", "set by the analyst": "(set by the analyst)" };
export const OTHER_DECISION = "Other";
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
  ["file_confirms", "Revenue file confirms"],
];
/** The row's own note when no revenue file covers the claim's period (backend NO_FILE_PERIOD). */
export const NO_FILE_PERIOD = "Revenue file does not cover this period";
/** The reason codes a row offers: "Revenue file confirms" has nothing to confirm with when no revenue file covers the period. */
export const reasonsFor = (view) => TURNOVER_REASONS.filter(([code]) => !(code === "file_confirms" && view?.file_note === NO_FILE_PERIOD));
/** Whether an answer may be sent: a reason that is offered on this row and does not contradict the answer. */
export const answerReady = (answer, reason, view) =>
  Boolean(reason) && reasonsFor(view).some(([code]) => code === reason) && !contradicts(answer, reason);
export const TURNOVER_QUESTION = "Revenue or transaction volume?";
// The deck list (section 11 point 8): a turnover claim never reads "Revenue" before the analyst confirms it.
export const TURNOVER_CONFIRM = "Turnover – confirm:";
export const UNVERIFIED = "Unverified";

// docs/specs/dates-and-periods.md section 5: a growth claim with no basis waits for the analyst's one click.
export const SET_GROWTH_BASIS = "Set growth basis";
export const GROWTH_BASES = [["mom", "MoM"], ["yoy", "YoY"], ["annualised", "Annualised"], ["cumulative", "Cumulative"]];
export const growthBasisLabel = (basis) => (GROWTH_BASES.find(([value]) => value === basis) || [])[1] || null;

// Section 4.1 of docs/specs/claim-matching.md: a gap beyond 50% of the claim asks "Same metric and period?" before the row gets a label.
export const DEFINITION_CHECK = "Definition check";
export const DEFINITION_ANSWERS = [["yes", "Yes"], ["no", "No"]];

/** What the Evidence cell shows: the label, or "Definition check" while that question is open (a status, not an evidence label). */
export const labelText = (row) => (row.definition_check === "ask" ? DEFINITION_CHECK : row.evidence_label);

/** The Definition check views of a deck-list claim (one per value of a table row that has one) and whether one is still open. */
export function definitionOf(candidate) {
  const views = candidate?.definition || [];
  return { views, open: views.some((v) => v.definition_check === "ask") };
}

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

/** Whether the gate of a row also needs the analyst's metric name and direction: the row has no metric of the app (none set, or
 *  one that does not fit the claim's unit), or the app's metric counts another population than the claim. The server saves the gate
 *  by the same rule (claim_matching.needs_metric_name). */
export const needsMetricName = (row) => row.metric == null || NO_APP_METRIC.includes(row.reason)
  || String(row.reason || "").startsWith("population differs: ");

/** W1: the value at stake as an amount, else the server's reason ("not yet computed: Target ARR empty", "no ARR link: ..."), else
 *  "not yet computed"; a row that missed adds " · shortfall 18.3%". */
export function valueAtStakeText(row, ccy) {
  const base = row.value_at_stake_arr != null
    ? `${fmtCurrency(row.value_at_stake_arr, ccy)}${row.vas_reason ? ` (${row.vas_reason})` : ""}`   // "run-rate: Q3 2024 × 4"
    : row.vas_reason || "not yet computed";
  return row.shortfall == null ? base : `${base} · shortfall ${(row.shortfall * 100).toFixed(1)}%`;
}

/** How a claim is called in a sentence (the backend's claim_name): its metric or type, the segment when not the whole company, the period. */
export function claimName(row) {
  const base = row.metric || typeLabel(row.claim_type);
  const named = row.segment && row.segment !== WHOLE_COMPANY ? `${base} · ${row.segment}` : base;
  return row.period ? `${named}, ${row.period}` : named;
}

/** W2: the other rows it overlaps with, by name (no rank prefix, design note section 6); none: a dash. */
export function overlapsText(row, rows) {
  const byId = Object.fromEntries(rows.map((r) => [r.claim_id, r]));
  const names = (row.overlaps_with || []).map((id) => byId[id]).filter(Boolean).sort((a, b) => a.rank - b.rank).map(claimName);
  return names.length ? names.join(" · ") : PLACEHOLDER;
}

/** Whether a row is a forecast: classified a target by its source, for a period after the as-of month (the backend's is_forecast_row). */
export const isForecastRow = (row) => row.figure_type === "target" && Boolean(row.period_end) && Boolean(row.as_of_month)
  && String(row.period_end).slice(0, 7) > String(row.as_of_month).slice(0, 7);
export const hasForecast = (rows) => (rows || []).some(isForecastRow);

/** W3: the label and reason, then the analysis and source key the figure was read from, with the month or quarter. */
export function evidenceLines(row) {
  const first = `${row.evidence_label} · ${row.reason}`;
  if (!row.evidence_analysis) return { first, second: null };
  const at = row.observed_at ? ` (${row.observed_at})` : "";
  return { first, second: `${row.evidence_analysis} · ${row.evidence_source_key}${at}` };
}

/** The Details of a claim: how the deck was read, gloss, value at stake, overlaps, how it was approved, the growth basis (the page and the
 *  reason sit in the Source and Result columns). [text, testId] pairs; `prefix` keeps the test ids of a second copy (the five selected claims) apart from the register's. */
export function detailItems(row, rows, ccy, prefix = "register-") {
  return [
    [readingText(row.deck_reading), "reading"],
    [row.gloss || "—", "gloss"],
    [`${VAS_LABEL} ${valueAtStakeText(row, ccy)}`, "value-at-stake"],
    [`Overlaps with ${overlapsText(row, rows)}`, "overlaps"],
    ...(row.auto_approval ? [[row.auto_approval, "auto-approval"]] : []),
    ...(growthBasisLabel(row.growth_basis) ? [[`Growth basis ${growthBasisLabel(row.growth_basis)}`, "growth-basis-set"]] : []),
  ].map(([text, id]) => [text, `${prefix}${id}`]);
}

const multiple = (v) => (Math.round(Number(v) * 10 + 1e-9) / 10).toFixed(1);     // half up, absorbing binary noise: 2.25 -> "2.3"
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
  if (row.unit === "x") return hi == null ? `${multiple(lo)}x` : `${multiple(lo)}–${multiple(hi)}x`;       // a multiple: one decimal (George, 2026-10-24)
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

const READINGS = { parser: "Read by the parser", edited: "Edited by the analyst", "analyst-entered": "Analyst-entered",
  "added-from-deck": "Added from deck by analyst",       // claim-types-and-correction.md section 5
  "forecast-file": "Read from forecast table",          // chat-upload.md section 20
  "plan-file": "Plan in the P&L file" };                // docs/design/pnl-lines.md section 4
export const readingText = (reading) => READINGS[reading] || reading;

export const segmentEdit = (segment) => ({ segment });
export const metricEdit = (metric) => ({ metric });

/** The gate the analyst edits, as the PUT sends it: blank is null (clears the field), the threshold a number. A gate that is only the app's
 *  proposal (`gate_saved` false) is stored whole as soon as one field differs (threshold and date, and for a row with no metric of the app
 *  the metric name and direction too), since the server counts an edit only once those are filled; a saved gate sends the fields that changed. */
export function gateEdit(row, draft) {
  const threshold = String(draft.threshold ?? "").trim();
  const next = threshold === "" ? null : Number(threshold);
  if (next !== null && !Number.isFinite(next)) throw new Error("The threshold must be a number");
  const budget = String(draft.budget ?? "").trim();
  if (budget.length > GATE_BUDGET_MAX) throw new Error(`The budget decision is at most ${GATE_BUDGET_MAX} characters`);
  const date = String(draft.date ?? "").trim();
  const dateError = dateRangeError("The gate date", date);
  if (dateError) throw new Error(dateError);
  const all = { gate_threshold: next, gate_budget_decision: budget || null, gate_date: date || null };
  if (needsMetricName(row)) {
    const name = String(draft.metricName ?? "").trim();
    if (name.length > GATE_METRIC_MAX) throw new Error(`The metric is at most ${GATE_METRIC_MAX} characters`);
    all.gate_metric_name = name || null;
    all.gate_direction = draft.direction || null;
  }
  const changed = Object.fromEntries(Object.entries(all).filter(([k, v]) => v !== (row[k] ?? null)));
  if (row.gate_saved || !Object.keys(changed).length) return changed;
  return Object.fromEntries(Object.entries(all).filter(([k, v]) => v !== null || k in changed));
}

/** What the analyst sees beside the empty gate fields: the claimed and the observed figure. No threshold is proposed. */
export function gateContext(row, ccy) {
  const claimed = `Claimed ${claimFigure(row, ccy)} (${row.period || row.period_note || PLACEHOLDER})`;
  if (row.observed_value == null) return claimed;
  const observed = observedText(row, ccy);
  return `${claimed} · Observed ${observed.value} (${observed.at})`;
}

/** The gate fields as the analyst sees them: the row's own (the app's proposal until the analyst edits it), then what has been changed on screen. */
export function gateDraft(row, edits) {
  const e = edits || {};
  const pick = (own, shown) => (own !== undefined ? own : shown ?? "");
  return {
    threshold: pick(e.threshold, row.gate_threshold), date: pick(e.date, row.gate_date), metricName: pick(e.metricName, row.gate_metric_name),
    direction: pick(e.direction, row.gate_direction), budget: e.budget !== undefined ? e.budget : (row.gate_budget_decision ?? ""),
  };
}
