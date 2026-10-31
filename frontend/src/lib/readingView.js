/**
 * The reading screen's words and shapes (docs/design/read-check-review.md section 11, docs/design/audit-page-mockup.html; PR 3 step d).
 * Pure functions over the register the server sends (GET /audits/{id}/reading). Every number goes through lib/format.js (section 11.5).
 */
import { PLACEHOLDER, fmtCount, fmtCurrency, fmtPct } from "./format";
import { monthName } from "./periods";

export const EXPLAINER = "The model reads each file in full. Names, contact details and ID numbers are removed first; client names are replaced by codes that exist only in this audit. Code checks every figure against its cell.";

/** Hover text on every heading (section 11.3 and the mockup): a table cannot be drawn without it, and a test walks every table for it. */
export const HOVERS = {
  lines: {
    Line: "The row label as it stands in the file, in file order. A rate row is shown under the line it refers to.",
    "Read as": "What the whole row was read as: revenue, bookings, ARR, MRR, churn rate, customers, forecast, variance, other.",
    Basis: "How the value accumulates: monthly, quarterly, yearly, cumulative to date, last 12 months, or a rate.",
    "Actual / plan": "Whether the row holds actual figures, plan figures, or both with a boundary column.",
    Cells: "The cells the values occupy. Click to open the sheet there.",
  },
  confirmed: {
    Metric: "What the figure measures, e.g. recognised revenue, ARR, customers.",
    Value: "The number as it stands in the file, shown rounded; the full value is kept.",
    Period: "The month, quarter or year this value belongs to.",
    Label: "The label printed with the figure in the file or on the deck page, as the reader took it.",
    Basis: "How the value accumulates: monthly, quarterly, yearly, cumulative to date, or last 12 months.",
    "Actual / plan": "Whether the cell sits before or after the file's last actual month.",
    Row: "What the whole row or table was read as: revenue, bookings, ARR, churn rate, customers, forecast, variance, other.",
    Source: "The file, sheet and cell, or the deck page, the figure was read from. Click to see the cell.",
  },
  rejected: {
    Metric: "What the reading said the figure measures.",
    "Reading says": "The value and period the reader recorded.",
    "Cell holds": "What the code found when it opened the cited cell.",
    Reason: "Why the check failed: value differs, period differs, cell does not exist, or a structural check failed.",
    "Re-read": "Result of the automatic second reading: agrees with the cell, repeats the first reading, or gives a third value.",
    Action: "What happens next: corrected automatically, or a card for you to decide.",
    Source: "The cited file, sheet and cell, or deck page. Click to see the cell.",
  },
  cannot_check: {
    Metric: "What the figure measures.",
    Value: "The value the reader recorded.",
    Period: "The month, quarter or year it belongs to.",
    Label: "The label printed with the figure in the file or on the deck page, as the reader took it.",
    Why: "Why no check was possible: layout description not a value; deck page is an image; unit or scale differs from the cell; no cell cited; depends on a masked name.",
    "Used in": "Which computed figures rely on it, so you know what is affected.",
    Source: "Where it was read from. For a deck page without text, the page number only.",
  },
};

/** Column widths in percent, in the order of the design note's tables (section 11.3); the lines table follows the mockup. */
export const WIDTHS = {
  lines: [34, 16, 14, 16, 20],
  confirmed: [18, 10, 10, 14, 8, 8, 8, 24],
  rejected: [14, 12, 12, 22, 12, 10, 18],
  cannot_check: [14, 10, 10, 14, 22, 12, 18],
};
export const NUMERIC = { lines: [], confirmed: ["Value"], rejected: ["Reading says", "Cell holds"], cannot_check: ["Value"] };
export const TITLES = { confirmed: "Confirmed", rejected: "Rejected", cannot_check: "Cannot check" };
export const NARROW_PX = 900;

/** "2022-05" -> "May 2022"; "2024-Q1" -> "Q1 2024"; "2024" -> "FY 2024"; anything else as it is; none -> "—". */
export function periodLabel(period) {
  if (!period) return PLACEHOLDER;
  if (/^\d{4}-\d{2}/.test(period)) return monthName(period);
  const q = /^(\d{4})-Q([1-4])$/.exec(period);
  if (q) return `Q${q[2]} ${q[1]}`;
  return /^\d{4}$/.test(period) ? `FY ${period}` : period;
}

/** A figure with its unit by the one formatter: money with its currency, a count, a rate as a percent. A rate is a fraction (0.045 is 4.5%): the
 *  reader's unit decides, no scale is guessed from the size of the number. */
export function valueText(value, unit, currency) {
  if (value === null || value === undefined) return PLACEHOLDER;
  if (unit === "rate") return fmtPct(value);
  if (unit === "money") return fmtCurrency(value, currency);
  return fmtCount(value);
}

export const basisLabel = (basis) => (basis ? String(basis).replace(/_/g, " ") : PLACEHOLDER);
export const actualPlanLabel = (v) => v || PLACEHOLDER;

/** "AP11 · 2019-2022 Sales · revenue.xlsx" or "p12 · deck.pdf": the cell or page first. */
export function sourceParts(source) {
  if (source.page) return { first: `p${source.page}`, rest: source.file || "" };
  return { first: source.cell || "sheet", rest: [source.sheet, source.file].filter(Boolean).join(" · ") };
}

const plural = (n, one, many) => `${fmtCount(n)} ${n === 1 ? one : many}`;
const GRAIN = { monthly: "month", quarterly: "quarter", yearly: "year" };

/** The last actual period of a file: "May 2022", or "FY 2021" for a yearly file. */
export function lastActualText(month, granularity) {
  if (!month) return "not determined";
  return granularity === "yearly" ? `FY ${month.slice(0, 4)}` : monthName(month);
}

/** The masking line, below the summary (docs/design/audit-page-mockup.html): "0 personal items removed · 17 company names coded". */
const maskingLine = (s) => [
  { text: plural(s.personal_removed ?? 0, "personal item removed", "personal items removed") },
  { text: plural(s.company_coded ?? 0, "company name coded", "company names coded") },
];

/** The summary lines of a spreadsheet block, in the mockup's words: a number first, then its text. Each line is a list of parts; a part with
 *  `bold` draws that number (or period) in the heavier weight. */
export function sheetSummary(s) {
  const grain = GRAIN[s.granularity] || "period";
  return [
    [
      { text: plural(s.period_columns ?? 0, `${grain} column`, `${grain} columns`) },
      { text: plural(s.rows_mapped ?? 0, "row mapped", "rows mapped") },
      { bold: fmtCount(s.confirmed), text: ` ${s.confirmed === 1 ? "figure" : "figures"} confirmed` },
      { text: `${fmtCount(s.rejected)} rejected` },
      { text: `${fmtCount(s.cannot_check)} cannot check` },
      { text: "actual to ", bold: lastActualText(s.last_actual, s.granularity) },
    ],
    maskingLine(s),
  ];
}

/** The three summary lines of a deck block: the pages; the figures, "confirmed on the page they cite"; the masking. */
export function deckSummary(s, figures) {
  const pages = s.pages ?? 0;
  const skipped = s.skipped_pages || [];
  const read = Math.max(pages - skipped.length, 0);
  const first = [{ text: plural(pages, "page", "pages") }, { text: `${plural(read, "page", "pages")} read` }];
  if (skipped.length) {
    first.push({ text: `${plural(skipped.length, "page", "pages")} skipped (no digits in ${skipped.length === 1 ? "its" : "their"} text: ${skipped.join(", ")})` });
  }
  const f = figures || { read: 0 };
  return [
    first,
    [
      { bold: fmtCount(f.read), text: ` ${f.read === 1 ? "figure" : "figures"} read` },
      { bold: fmtCount(s.confirmed), text: " confirmed on the page they cite" },
      { text: `${fmtCount(s.rejected)} rejected` },
      { text: `${fmtCount(s.cannot_check)} cannot check${s.cannot_check ? " (charts without text)" : ""}` },
    ],
    maskingLine(s),
  ];
}

export function deckFiguresText(f) {
  return `${fmtCount(f.read)} read, ${fmtCount(f.found_on_page)} found on their page, ${fmtCount(f.from_image)} from charts without text`;
}

/** The "Confirmed on column AP" part of the evidence line, and the text before it: the evidence as the reader wrote it, less its checked column. */
export function splitEvidence(line) {
  const m = /^(.*?)\s*\(confirmed on sheet (.+?), column ([A-Z]+)\)\s*$/.exec(line || "");
  return m ? { text: m[1], confirmed: `Confirmed on column ${m[3]}.` } : { text: line || "", confirmed: null };
}

/** The heading of a card: "ARR, April 2022: the reader and the file disagree". */
export function cardTitle(card) {
  const subject = [card.subject?.metric, card.subject?.period ? periodLabel(card.subject.period) : null].filter(Boolean).join(", ");
  return subject ? `${subject}: ${card.title.charAt(0).toLowerCase()}${card.title.slice(1)}` : card.title;
}

export const ACTION_LABELS = { use_cell: "Use the cell", use_reader: "Use the reader", type_value: "Type a value" };
