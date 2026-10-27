/**
 * Create Growth Audit form: date checks and Target ARR display.
 *
 * Both date fields are the app's own date picker (components/DateField.jsx), whose value is ISO YYYY-MM-DD with a year
 * from 2000 to 2100. Any other string is refused, never guessed, because 06/07/2026 is June in one locale and July in
 * another.
 */
import { dateRangeError } from "./datePicker";
import { seeGlossary } from "./glossary";
import { monthName } from "./periods";

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
  const range = dateRangeError("Target date", targetDate) || dateRangeError("As-of month", asOf);
  if (range) return range;
  if (targetDate && !isIsoDate(targetDate)) return "Target date must be a full date (YYYY-MM-DD)";
  if (asOf && !isIsoDate(asOf)) return "As-of month must be a full date (YYYY-MM-DD)";
  if (!targetDate) return null;
  if (asOf && targetDate.slice(0, 7) <= asOf.slice(0, 7)) return "Target date must be after the as-of month";
  return null;
}

// Keep Target ARR as plain digits (one optional decimal point) in state...
export function plainNumber(text) {
  const [raw, ...dec] = String(text ?? "").replace(/[^\d.]/g, "").split(".");
  const int = raw.replace(/^0+(?=\d)/, "");          // no leading zeros: typing 5 over "0" gives 5, not 05
  return dec.length ? `${int}.${dec.join("")}` : int;
}

// A stored 0 or an empty value is "not set": the box shows empty, never "0".
export function storedNumberInput(v) {
  return Number(v) ? plainNumber(String(v)) : "";
}

// ...and show it with comma thousands: "6000000" -> "6,000,000".
export function groupThousands(plain) {
  if (!plain) return "";
  const [int, dec] = plain.split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return dec === undefined ? grouped : `${grouped}.${dec}`;
}

// Fiscal year-end: the month the company's fiscal year ends in (1-12), December unless set.
// FY25 is the fiscal year that ends in 2025 (docs/specs/deck-parser.md section 2).
export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];
export const DEFAULT_FISCAL_YEAR_END = 12;

// AI-assisted reading (docs/specs/chat-upload.md section 23): one checkbox per audit, ticked by default at creation, in the
// set-up section at the top of the Upload page. Word for word from the spec.
export const CONSENT_LABEL = "Use AI to read deck tables, charts and the text of pages that carry a figure, and to suggest column matches. Names, contact details and customer names are masked in spreadsheet data before it is sent; deck pages are sent as printed, with no redaction. Untick if the client requires code-based extraction only; this may find fewer figures. Narratives use AI on computed results either way.";
export const VERIFIED_LINE = "Every extracted number is checked by code against its source cell. Numbers that don't match are marked unverified for review.";

// The text above the name field of the creation dialog (chat-upload.md section 23), word for word.
export const NEW_AUDIT_TITLE = "Create a new audit";
export const NEW_AUDIT_PARAGRAPHS = [
  "Start by entering your project or company name.",
  "Once you upload your files, the app identifies file types, matches data columns to the fields used in the audit, and uses AI to read tables and charts in your decks. You'll review any column matches that need confirmation before calculations begin.",
  "Before content is sent to the AI model, the app replaces email addresses, phone numbers, personal names and customer names found in your uploaded data files.",
  "On the next screen, you can add your files and review the upload requirements.",
];

// The project or company name is the only field of the creation dialog.
export function requiredFieldError(form) {
  if (!form.company_name?.trim()) return "Company name is required";
  return null;
}

// The audit's set-up fields sit at the top of the upload and mapping page (docs/specs/chat-upload.md section 2), each with
// one line of help. The creation dialog asks for the audit name only.
export const SETUP_HELP = {
  reporting_currency: "All figures are converted to this currency. Use the company's home currency; the verdict and memo use it.",
  target_arr: seeGlossary("The plan figure the audit tests. Every claim's VaS is measured against it."),
  target_date: seeGlossary("When the plan says Target ARR is reached. Sets the forecast horizon."),
  as_of_month: "Last month of actual data. Metrics are computed up to this month. "
    + "Defaults to the last month of the revenue file once it is mapped; a month you set is kept.",
  fiscal_year_end: "Maps FY labels in the deck to months. A wrong setting shifts every FY claim.",
  first_quarterly_review: "Gate dates are never later than this. Defaults to the audit's creation date plus 90 days.",
  // docs/specs/dates-and-periods.md section 2
  analysis_date: "The date of this analysis. It dates the memo and your own text; it never changes the period of a figure.",
  last_month_complete: "Tick when the revenue file's last month holds all its invoices. Unticked, that month is shown but not used for NRR and growth.",
};
export const AS_OF_PLACEHOLDER = "last month of the revenue file";

/** The revenue file's last month (YYYY-MM) as the screen knows it: the computed source period, else the mapped file's months; null before. */
export const revenueLastMonth = (audit) => audit?.results?.source_period?.month || audit?.datasets?.revenue?.months?.last || null;

/** The line under the as-of field when its month is later than the revenue file's last month (chat-upload.md section 30), else null. */
export function asOfWarning(asOf, revenueLast) {
  if (!asOf || !revenueLast || asOf.slice(0, 7) <= revenueLast) return null;
  return `The as-of month, ${monthName(asOf)}, is later than the last month of the revenue file, ${monthName(revenueLast)}. `
    + `The figures stop at ${monthName(revenueLast)}; the months after it hold no revenue.`;
}

export const SETUP_LABELS = {
  reporting_currency: "Reporting currency", target_arr: "Target ARR", target_date: "Target date", as_of_month: "As-of month",
  fiscal_year_end: "Fiscal year-end", first_quarterly_review: "First quarterly review",
  analysis_date: "Requested analysis date", last_month_complete: "Last month is complete",
  structure_reading_consent: "AI reading",
};
export const REPORTING_CURRENCIES = ["EUR", "USD", "GBP", "JPY"];

export const NOT_SET = "n.a.";
const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-18T12:32:00+00:00" -> "18 Oct 2026, 14:32" in the viewer's local time (docs/specs/chat-upload.md section 24); "n.a." when unreadable. */
export function formatCreated(value) {
  const d = value ? new Date(value) : null;
  if (!d || Number.isNaN(d.getTime())) return NOT_SET;
  const two = (n) => String(n).padStart(2, "0");
  return `${d.getDate()} ${SHORT_MONTHS[d.getMonth()]} ${d.getFullYear()}, ${two(d.getHours())}:${two(d.getMinutes())}`;
}
