/**
 * The single place numbers become display strings on the frontend.
 *
 * Mirrors backend/app/formatting.py rule for rule; both are pinned to
 * format_vectors.json. Every figure on the dashboard goes through here, from the
 * raw computed value - the calc engine and MongoDB keep full precision.
 *
 *   currency  whole number, comma thousands, code   3129104.4 -> "3,129,104 EUR"
 *   count     observed count, nearest               100.0 -> "100"
 *   countUp   required / implied count, rounds up   128.3 -> "129"
 *   days      rounds up, "days" suffix              42.1  -> "43 days"
 *   months    the display rule, "months" suffix      12.24 -> "12 months"
 *   pct       a fraction as a percent, display rule  1.0641 -> "106%", 0.045 -> "4.5%"
 *   ratio     the display rule, "x"                  3.28  -> "3.3x"
 *
 * The display rule (docs/design/read-check-review.md section 11.5): whole numbers; one decimal only for a single-digit multiple (3.3x), a
 * single-digit number (1.2) or a single-digit percent (4.5 %); a trailing ".0" is dropped. Stored values are never rounded. This file is the
 * only place a component turns a number into text: src/lib/format.noRawNumbers.test.js fails on any other toFixed / toLocaleString.
 */
export const PLACEHOLDER = "—";

const EPSILON = 1e-9; // absorbs binary noise so 43.00000000000001 is not "44"

const missing = (v) => v === null || v === undefined || typeof v === "boolean" || !Number.isFinite(Number(v));

// Round half away from zero at `dp` decimals, via the exponent-string trick so
// 1.005 -> 1.01 (a plain Math.round(x * 100) gives 1.00).
function roundHalfUp(value, dp = 0) {
  const abs = Math.abs(Number(value));
  const text = String(abs);
  const r = text.includes("e")
    ? Math.round(abs * 10 ** dp) / 10 ** dp
    : Number(`${Math.round(Number(`${text}e${dp}`))}e-${dp}`);
  return Number(value) < 0 ? -r : r;
}

const ceilUp = (value) => Math.ceil(Number(value) - EPSILON);

const group = (n) => {
  const t = Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0, useGrouping: true });
  return n < 0 && n !== 0 ? `-${t}` : t;
};

/** The one display rule: a number that is single-digit after rounding to one decimal keeps that decimal (".0" dropped); any other is whole. */
export function displayNumber(value) {
  const one = roundHalfUp(value, 1);
  if (Math.abs(one) >= 10) return group(roundHalfUp(value));
  if (one === 0) return "0";
  const t = String(Math.abs(one));
  return `${one < 0 ? "-" : ""}${t.endsWith(".0") ? t.slice(0, -2) : t}`;
}

export function fmtCurrency(value, ccy) {
  if (missing(value)) return PLACEHOLDER;
  const t = displayNumber(value);
  return ccy ? `${t} ${ccy}` : t;
}
export const fmtCount = (v) => (missing(v) ? PLACEHOLDER : displayNumber(v));
/** Any number no other kind names: a size, a token count, a score. */
export const fmtNumber = fmtCount;
/** A value shown exactly as stored, never rounded: an exchange rate, which is an input and not a result. */
export const fmtExact = (v) => (missing(v) ? PLACEHOLDER : String(Number(v)));
export const fmtCountUp = (v) => (missing(v) ? PLACEHOLDER : group(ceilUp(v)));
// Days round up; the unit is a suffix and does not change the number. Use
// fmtDaysNumber to compose a range ("17–59 days").
export const fmtDaysNumber = (v) => (missing(v) ? PLACEHOLDER : group(ceilUp(v)));
export const fmtDays = (v) => {
  if (missing(v)) return PLACEHOLDER;
  const n = ceilUp(v);
  return `${group(n)} ${n === 1 ? "day" : "days"}`;
};
// CAC payback is a duration in months: one decimal, nearest - not rounded up.
export const fmtMonths = (v) => (missing(v) ? PLACEHOLDER : `${displayNumber(v)} months`);
// A percent is held as its fraction (1.0641 is 106.41%); reading it for display means times 100. toPrecision drops the
// binary noise of the product (0.085 * 100 is 8.500000000000002), so a .5 rounds up as in the backend.
export const fmtPct = (v) => (missing(v) ? PLACEHOLDER : `${displayNumber(Number((Number(v) * 100).toPrecision(12)))}%`);
export const fmtRatio = (v) => (missing(v) ? PLACEHOLDER : `${displayNumber(v)}x`);
/** A rate already written as a percent (4.5, not 0.045). */
export const fmtPercentPoints = (v) => (missing(v) ? PLACEHOLDER : `${displayNumber(v)}%`);
/** Percentage points: "+1.2 pts". */
export const fmtPoints = (v) => (missing(v) ? PLACEHOLDER : `${Number(v) > 0 ? "+" : ""}${displayNumber(Number((Number(v) * 100).toPrecision(12)))} pts`);
/** A byte size: "61 KB", "1.2 MB". */
export const fmtBytes = (n) => (missing(n) ? PLACEHOLDER : Number(n) < 1024 * 1024 ? `${displayNumber(Number(n) / 1024)} KB` : `${displayNumber(Number(n) / 1024 / 1024)} MB`);
/** The owner pages' costs: USD, to the cent below 10 (a cost of 0.03 is not "0"); every other number there goes through the rule. */
export const fmtUsd = (v) => (missing(v) ? PLACEHOLDER : `USD ${Math.abs(Number(v)) >= 10 ? displayNumber(v) : roundHalfUp(v, 2).toFixed(2)}`);

const BY_KIND = {
  currency: fmtCurrency, count: fmtCount, count_up: fmtCountUp, days: fmtDays,
  months: fmtMonths, pct: fmtPct, ratio: fmtRatio, plain: fmtCount,
};

/** Format by kind name - the same kinds the backend registry uses. */
export function fmt(kind, value, ccy) {
  const f = BY_KIND[kind];
  if (!f) throw new Error(`unknown display kind ${kind}`);
  return f(value, ccy);
}

/** "3,129,104 EUR" -> the band's range from raw thresholds, e.g. "100–1,000 EUR". */
export function bandRangeLabel(low, high, ccy) {
  if (high === null || high === undefined) return `${fmtCurrency(low, ccy)}+`;
  if (!low) return `<${fmtCurrency(high, ccy)}`;
  return `${fmtCurrency(low)}–${fmtCurrency(high, ccy)}`;
}
