/**
 * The date picker's rules (docs/specs/chat-upload.md section 4.1): a calendar with month and year arrows and a
 * typeable year, from MIN_YEAR to MAX_YEAR. Anything outside is rejected; a year such as 0001 is never shown.
 * Pure functions over ISO dates (YYYY-MM-DD) and a view of { year, month } (month 0-11).
 */
export const MIN_YEAR = 2000;
export const MAX_YEAR = 2100;
export const YEAR_ERROR = `Year must be between ${MIN_YEAR} and ${MAX_YEAR}`;

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];
const SHORT = MONTH_NAMES.map((m) => m.slice(0, 3));
export const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
export const monthName = (month) => MONTH_NAMES[month];

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

/** {year, month, day} of a real calendar date inside the range, else null. */
export function parseIso(iso) {
  const m = ISO.exec(iso ?? "");
  if (!m) return null;
  const [year, month, day] = [Number(m[1]), Number(m[2]) - 1, Number(m[3])];
  if (year < MIN_YEAR || year > MAX_YEAR) return null;
  const check = new Date(Date.UTC(year, month, day));
  return check.getUTCFullYear() === year && check.getUTCMonth() === month && check.getUTCDate() === day ? { year, month, day } : null;
}

export const toIso = (year, month, day) => `${String(year).padStart(4, "0")}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;

/** "30 Jun 2026"; "" for an empty, malformed or out-of-range value, so no year outside the range is ever shown. */
export function displayDate(iso) {
  const d = parseIso(iso);
  return d ? `${d.day} ${SHORT[d.month]} ${d.year}` : "";
}

/** The year a typed text names: an integer of 4 digits inside the range, else null. */
export function parseYear(text) {
  const t = String(text ?? "").trim();
  if (!/^\d{4}$/.test(t)) return null;
  const year = Number(t);
  return year >= MIN_YEAR && year <= MAX_YEAR ? year : null;
}

/** The month the calendar opens at: the value's, else today's, kept inside the range. */
export function openingView(iso, today = new Date()) {
  const d = parseIso(iso);
  if (d) return { year: d.year, month: d.month };
  const year = Math.min(MAX_YEAR, Math.max(MIN_YEAR, today.getFullYear()));
  return { year, month: year === today.getFullYear() ? today.getMonth() : 0 };
}

/** The view moved by whole months; null at the ends of the range (the arrow is disabled there). */
export function shiftMonth(view, delta) {
  const index = view.year * 12 + view.month + delta;
  const year = Math.floor(index / 12);
  return year < MIN_YEAR || year > MAX_YEAR ? null : { year, month: index - year * 12 };
}

/** The view moved by whole years, same month; null outside the range. */
export function shiftYear(view, delta) {
  const year = view.year + delta;
  return year < MIN_YEAR || year > MAX_YEAR ? null : { year, month: view.month };
}

/** Weeks of the month, Monday first: arrays of 7 cells, each a day number or null. */
export function weeks(view) {
  const lead = (new Date(Date.UTC(view.year, view.month, 1)).getUTCDay() + 6) % 7;
  const length = new Date(Date.UTC(view.year, view.month + 1, 0)).getUTCDate();
  const cells = [...Array(lead).fill(null), ...Array.from({ length }, (_, i) => i + 1)];
  while (cells.length % 7) cells.push(null);
  return Array.from({ length: cells.length / 7 }, (_, w) => cells.slice(w * 7, w * 7 + 7));
}

/** Why a date may not be saved, or null: for every date field (as-of, target, gate). Empty is allowed. */
export function dateRangeError(label, iso) {
  if (!iso) return null;
  const m = ISO.exec(iso);
  if (!m) return `${label} must be a full date (YYYY-MM-DD)`;
  const year = Number(m[1]);
  if (year < MIN_YEAR || year > MAX_YEAR) return `${label} year must be between ${MIN_YEAR} and ${MAX_YEAR}`;
  return parseIso(iso) ? null : `${label} must be a real date`;
}

export const TYPED_ERROR = "Type the date as 2026-06-30 or 30.06.2026";

/** The ISO date a typed text names, or null. Two forms are read, and no other, because 06/07/2026 is June in one locale
 *  and July in another: year-month-day with dashes ("2026-06-30") and day.month.year with dots ("30.06.2026"). A date
 *  that does not exist, or lies outside MIN_YEAR to MAX_YEAR, is null. */
export function parseTyped(text) {
  const t = String(text ?? "").trim();
  let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t);
  const [year, month, day] = m ? [m[1], m[2], m[3]] : (m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(t)) ? [m[3], m[2], m[1]] : [];
  if (year === undefined) return null;
  const iso = toIso(Number(year), Number(month) - 1, Number(day));
  return parseIso(iso) ? iso : null;
}

/** Room the calendar needs: its height in pixels, with a margin. */
export const CALENDAR_HEIGHT = 340;

/** "bottom" when the calendar fits below the field, else "top". Decided once, when the calendar opens, and kept until it
 *  closes: the calendar never jumps from one side to the other. `rect` is the field's bounding box. */
export const pickSide = (rect, viewportHeight, needed = CALENDAR_HEIGHT) => (viewportHeight - rect.bottom >= needed ? "bottom" : "top");
