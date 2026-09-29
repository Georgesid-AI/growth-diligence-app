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
 *   days      rounds up (months too)                42.1  -> "43"
 *   pct       whole number, nearest                 106.41 -> "106%"
 *   ratio     always two decimals, "x"              1.28  -> "1.28x"
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

export function fmtCurrency(value, ccy) {
  if (missing(value)) return PLACEHOLDER;
  const t = group(roundHalfUp(value));
  return ccy ? `${t} ${ccy}` : t;
}
export const fmtCount = (v) => (missing(v) ? PLACEHOLDER : group(roundHalfUp(v)));
export const fmtCountUp = (v) => (missing(v) ? PLACEHOLDER : group(ceilUp(v)));
export const fmtDays = (v) => (missing(v) ? PLACEHOLDER : group(ceilUp(v)));
export const fmtMonths = fmtDays;
export const fmtPct = (v) => (missing(v) ? PLACEHOLDER : `${group(roundHalfUp(v))}%`);
export const fmtRatio = (v) => (missing(v) ? PLACEHOLDER : `${roundHalfUp(v, 2).toFixed(2)}x`);

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

/** Full calendar date for an as-of month: "2026-06" -> "2026-06-30". The engine
 *  keeps every month <= the as-of month, so data runs through that month's last
 *  day. A value that is already a full date passes through unchanged. */
export function monthEndDate(value) {
  if (!value) return null;
  const s = String(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  const m = /^(\d{4})-(\d{2})$/.exec(s);
  if (!m) return s;
  const day = new Date(Date.UTC(Number(m[1]), Number(m[2]), 0)).getUTCDate();
  return `${m[1]}-${m[2]}-${String(day).padStart(2, "0")}`;
}
