const CCY_SYMBOL = { EUR: "€", USD: "$", GBP: "£", JPY: "¥" };

export function money(value, ccy = "EUR", compact = true) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sym = CCY_SYMBOL[ccy] || "";
  const abs = Math.abs(value);
  if (compact) {
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
