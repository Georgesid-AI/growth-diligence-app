/**
 * Create Growth Audit form: date checks and Target ARR display.
 *
 * Both date fields are the app's own date picker (components/DateField.jsx), whose value is ISO YYYY-MM-DD with a year
 * from 2000 to 2100. Any other string is refused, never guessed, because 06/07/2026 is June in one locale and July in
 * another.
 */
import { dateRangeError } from "./datePicker";

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

// Fiscal year-end: the month the company's fiscal year ends in (1-12), December unless set.
// FY25 is the fiscal year that ends in 2025 (docs/specs/deck-parser.md section 2).
export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];
export const DEFAULT_FISCAL_YEAR_END = 12;

// AI-assisted reading (docs/specs/llm-structure-reading.md section 4): one checkbox per audit, ticked by
// default, directly above the create button. Word for word from the spec.
export const CONSENT_EXPLAINER = "This app reads tables and charts in the uploaded decks with an AI model. Every number is checked by code against its source cell; anything that does not match is marked as unverified. Emails, phone numbers, personal names and the customers named in the uploaded data files are replaced before anything is sent.";
export const CONSENT_LABEL = "AI-assisted reading enabled per engagement terms. Uncheck if the client requires code-based extraction only; this may identify fewer findings.";

// The client (the investor commissioning the audit) is required.
export function requiredFieldError(form) {
  if (!form.company_name?.trim()) return "Company name is required";
  if (!form.client_name?.trim()) return "Client name is required";
  return null;
}

// The audit's set-up fields sit at the top of the upload and mapping page (docs/specs/chat-upload.md section 2), each with
// one line of help. The creation dialog asks for the audit name only (and the client and the consent, which are not set-up).
export const SETUP_HELP = {
  reporting_currency: "All figures are converted to this currency. Use the company's home currency; the verdict and memo use it.",
  target_arr: "The plan figure the audit tests. Every claim's value at stake is measured against it.",
  target_date: "When the plan says Target ARR is reached. Sets the forecast horizon.",
  as_of_month: "Last month of actual data. Metrics are computed up to this month. Defaults to the last P&L month.",
  fiscal_year_end: "Maps FY labels in the deck to months. A wrong setting shifts every FY claim.",
};
export const SETUP_LABELS = {
  reporting_currency: "Reporting currency", target_arr: "Target ARR", target_date: "Target date", as_of_month: "As-of month",
  fiscal_year_end: "Fiscal year-end",
};
export const REPORTING_CURRENCIES = ["EUR", "USD", "GBP", "JPY"];
