/**
 * Create Growth Audit form: date checks and Target ARR display.
 *
 * Both date fields are <input type="date">, whose value is ISO YYYY-MM-DD in every
 * browser whatever it displays (30/06/2026, 06/30/2026, ...). Any other string means
 * the browser fell back to a text box; it is refused, never guessed, because
 * 06/07/2026 is June in one locale and July in another.
 */
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function isIsoDate(v) {
  const m = ISO_DATE.exec(v ?? "");
  if (!m) return false;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.toISOString().slice(0, 10) === v;
}

// A stored as-of value may be the older YYYY-MM; a date input needs YYYY-MM-DD.
export function asOfInputValue(v) {
  if (!v) return "";
  if (/^\d{4}-\d{2}$/.test(v)) {
    const [y, m] = v.split("-").map(Number);
    return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
  }
  return v;
}

// Same rule as the engine: the target must fall in a later month than the as-of month.
export function targetDateError(targetDate, asOf) {
  if (targetDate && !isIsoDate(targetDate)) return "Target date must be a full date (YYYY-MM-DD)";
  if (asOf && !isIsoDate(asOf)) return "As-of month must be a full date (YYYY-MM-DD)";
  if (!targetDate) return null;
  const year = Number(targetDate.slice(0, 4));
  if (year < 2000 || year > 2100) return "Target date year must be between 2000 and 2100";
  if (asOf && targetDate.slice(0, 7) <= asOf.slice(0, 7)) return "Target date must be after the as-of month";
  return null;
}

// Keep Target ARR as plain digits (one optional decimal point) in state...
export function plainNumber(text) {
  const [int, ...dec] = String(text ?? "").replace(/[^\d.]/g, "").split(".");
  return dec.length ? `${int}.${dec.join("")}` : int;
}

// ...and show it with comma thousands: "6000000" -> "6,000,000".
export function groupThousands(plain) {
  if (!plain) return "";
  const [int, dec] = plain.split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return dec === undefined ? grouped : `${grouped}.${dec}`;
}
