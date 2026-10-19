/**
 * Revenue file recognition: the approved wording of S31a-S31k (docs/specs/revenue-file-recognition.md section 7) and the small pure
 * helpers the line uses. The wording lives here once so the component and its tests read the same text. No text mentions a
 * confidence number or a cost; a reason code has one closed text.
 */
import { fmtMonth } from "./chatUpload";

// The six types, in the order of the specification (section 3); the keys are the codes the server accepts.
export const TYPE_LABELS = {
  invoice_transactions: "Invoice transactions",
  customer_revenue: "Customer revenue",
  monthly_revenue_report: "Monthly revenue report",
  revenue_summary: "Revenue summary",
  financial_statements: "Financial statements",
  arr_mrr_snapshot: "ARR/MRR snapshot",
};
// S31a: where the type came from. An AI suggestion says it is not verified (CLAUDE.md rule 18).
export const TYPE_SOURCE_TEXT = { rules: "by rules", ai: "AI suggestion, not verified", you: "your choice" };
export const TYPE_REASON_TEXT = { rules_and_model_disagree: "Two readings differ. Choose the type.", type_unsure: "Choose the type." };
export const TYPE_CHOOSE = "Type: choose the type";

export const TURNOVER_QUESTION = "Is this money the company earned (revenue) or the value of transactions processed (volume)?";
// S31e: one closed text per reason code of the server (`REASONS` in app/recognition.py).
export const REASON_TEXT = {
  no_candidate: "No row looks like revenue. Choose the revenue row.",
  tie: "Two rows fit equally. Choose the revenue row.",
  confidence_80: "Please confirm the revenue row.",
  row_missing: "The proposed row could not be matched to the sheet. Choose the revenue row.",
  label_mismatch: "The proposed row could not be matched to the sheet. Choose the revenue row.",
  marked_not_revenue: "The proposed row is a forecast, budget, bookings, pipeline, contract value or run-rate row. Choose the revenue row.",
  not_numeric_enough: "The proposed row has too few numbers. Choose the revenue row.",
  no_revenue_word: "The proposed row has no revenue word in its label. Choose the revenue row.",
  rules_and_model_disagree: "Two readings differ. Choose the revenue row.",
  no_as_of_month: "The audit has no as-of month, so this month needs your confirmation.",
  after_as_of: "The proposed month is after the as-of month. Choose a month up to it.",
  not_a_period: "The proposed column is not a month. Choose the last actual month.",
  turnover_question: TURNOVER_QUESTION,
  type_unsure: "Choose the type.",
};
// The same reasons for the month: "Choose the revenue row." becomes "Choose the last actual month."
export const MONTH_REASON_TEXT = { ...REASON_TEXT, rules_and_model_disagree: "Two readings differ. Choose the last actual month." };
// The reasons that wait for a confirmation only (they share one Correct button, decision 4).
export const CONFIRM_ONLY = ["confidence_80", "no_as_of_month"];

const ANALYSIS = {
  customer_level: "customer-level analysis (NRR, gross churn, concentration, cohorts)",
  trend: "trend analysis (MRR/ARR, growth, run-rate)",
  claim_matching: "claim matching only",
  monthly_series: "monthly series missing",
};

/** S31b: "Supports: a and b. Blocked: x, needs y; z, needs w." The Blocked part is left out when nothing is blocked. */
export const supportsText = (rec) => {
  const supports = (rec.supports || []).map((a) => ANALYSIS[a]).join(" and ");
  const blocked = (rec.blocked || []).map((b) => `${ANALYSIS[b.analysis]}, needs ${b.needs}`).join("; ");
  return `Supports: ${supports}.${blocked ? ` Blocked: ${blocked}.` : ""}`;
};

/** S31c: the revenue row line. A recurring row is called a recurring row, never a revenue row. */
export const rowText = (row) => {
  if (row.row == null && row.column == null) return "Revenue row: choose the row.";
  const where = row.row != null ? `row ${row.row}` : `column ${row.column}`;
  return `${row.kind === "recurring" ? "Recurring row" : "Revenue row"}: ${row.label} (${where})`;
};
export const rowChoice = (c) => `${c.label} (${c.row != null ? `row ${c.row}` : `column ${c.column}`})`;

/** S31d: "Jun 2025". */
export const monthText = (month) => (month ? fmtMonth(month) : "");

/** S31i: "{n} rows ({kinds}) are not used as revenue and are kept as claims for matching." The kinds, in sheet order, without repeats. */
export const claimsText = (rows) => {
  if (!rows || rows.length === 0) return null;
  const kinds = [...new Set(rows.map((r) => r.kind))].join(", ");
  return rows.length === 1
    ? `1 row (${kinds}) is not used as revenue and is kept as a claim for matching.`
    : `${rows.length} rows (${kinds}) are not used as revenue and are kept as claims for matching.`;
};

/** S31k: the currencies a drop-down offers, the audit's reporting currency first. */
export const CURRENCIES = ["EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "BGN", "CZK", "HUF", "RON", "CAD", "AUD", "NZD", "JPY",
  "CNY", "HKD", "SGD", "INR", "AED", "ZAR", "BRL", "MXN", "TRY", "ILS"];
export const currencyChoices = (reporting) => (reporting && CURRENCIES.includes(reporting)
  ? [reporting, ...CURRENCIES.filter((c) => c !== reporting)] : CURRENCIES);
export const CURRENCY_NOT_FOUND = "Currency not found in the file. Confirm the currency:";

/** S31j: the status line of a file read by recognition only. */
export const S31j_status = (n) => (n === 1 ? "1 choice waits for you" : `${n} choices wait for you`);

/** S31l (section 6.7): a sheet with a metrics block and a dated list. Which table supplies the revenue series, and how the other one
 *  compares with it month by month. The list is a cross-check when it matches, never a second source. */
export const TABLES_TEXT = "Two tables on this sheet: a metrics block and a dated list.";
const SOURCE_NAME = { metrics_block: "the revenue row of the metrics block", dated_list: "the dated list" };
export const sourceText = (source) => {
  const c = source.cross_check;
  if (source.state === "click") {
    return c.status === "match"
      ? `The dated list matches the row month by month (${c.months} months). Choose which table supplies the revenue series:`
      : `The dated list and the revenue row differ in ${c.months_off} of ${c.months} months. Choose which table supplies the revenue series:`;
  }
  const read = `Revenue series: ${SOURCE_NAME[source.supplier]}.`;
  return c.status === "match" ? `${read} The dated list matches it month by month (${c.months} months).`
    : `${read} The dated list and the revenue row differ in ${c.months_off} of ${c.months} months.`;
};
export const SOURCE_CHOICES = { metrics_block: "Use the revenue row", dated_list: "Use the dated list" };
