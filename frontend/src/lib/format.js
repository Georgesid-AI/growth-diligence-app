const CCY_SYMBOL = { EUR: "€", USD: "$", GBP: "£", JPY: "¥" };

export function money(value, ccy = "EUR", compact = true) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sym = CCY_SYMBOL[ccy] || "";
  const abs = Math.abs(value);
  if (compact) {
    if (abs >= 1_000_000_000) return `${sym}${(value / 1_000_000_000).toFixed(1)}B`;
    if (abs >= 1_000_000) return `${sym}${(value / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000) return `${sym}${(value / 1_000).toFixed(1)}K`;
  }
  return `${sym}${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function pct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

export function num(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
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
