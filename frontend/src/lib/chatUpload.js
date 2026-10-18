/**
 * Chat upload and column mapping: the approved wording (docs/specs/chat-upload.md section 11, S1-S22) and the small
 * pure helpers the screen uses. The wording lives here once so the components and their tests read the same text.
 */
import { seeGlossary } from "./glossary";

export const S2_EXPLAINER_CONSENT =
  "The model reads every column header and a masked sample to propose the mapping. When the rules cannot tell what a file holds, the AI also sees its sheet names and the title rows above each table.";
export const S3_EXPLAINER_NO_CONSENT =
  "Mapping is done by rules only: AI-assisted reading is off for this audit. You map the columns the rules cannot decide.";
export const S4_DROP_ZONE_LEAD =
  "Drop files here or use the paperclip. Required: Revenue by customer (monthly, 24–36 months). The audit will not run without a revenue file. Optional: CRM export and P&L. ";
export const S4_DROP_ZONE_BOLD = ".xlsx or .csv only";      // the only bold part of the text
export const S6_UNKNOWN_TYPE = "Could not tell what this file holds. Pick its type:";
export const S7_REFUSED = "This window takes .xlsx and .csv files. Decks go in the deck panel below.";
export const S7B_XLS_REFUSED = "Save as .xlsx or .csv and upload again.";
export const S_UPLOAD_RETRY = "The file could not be read. Press Map to try again.";   // no answer from the server (timeout or network error)
export const S12_MODEL_FAILED = "AI reading unavailable – these columns need your decision.";
export const S17_NARRATIVE_FAILED_TITLE = "Narrative could not be generated.";
// S18: the delete dialog. The name in the body is shown in bold by the dialog; the text around it is here.
export const S18_TITLE = (company) => `Delete ${company}?`;
export const S18_BODY = ["Deleting this audit with its files, mappings and results cannot be undone. Type ", " to confirm."];
export const S18_MISMATCH = "Name does not match";
export const S20_NOTE_PLACEHOLDER = "Why? Up to 60 characters; no file names, figures or names.";
export const S21_NOTE_REFUSED = "Leave out file names, figures and cell values: this note is kept with the usage counts.";
export const S22_RECONCILIATION = "Revenue reconciliation";
export const NOTE_MAX = 60;

export const ALLOWED_EXTENSIONS = ["xlsx", "csv"];

// S11: the fixed list of reasons for a correction; the codes are the ones the server accepts.
export const REASONS = [
  { code: "header_misleading", label: "Header is misleading" },
  { code: "other_column_right", label: "Another column is the right one" },
  { code: "values_do_not_fit", label: "Values do not fit this field" },
  { code: "wrong_kind_of_date", label: "Wrong kind of date" },
  { code: "not_needed", label: "Column not needed" },
  { code: "other", label: "Other" },
];

export const TYPE_LABELS = { revenue: "Revenue lines", crm: "CRM deals", pnl: "P&L (monthly)" };
const LOADED_LABELS = { revenue: "A revenue file", crm: "A CRM file", pnl: "A P&L file" };

// S5: the month range appears once the date column is confirmed; before that the line ends on the row count.
export const S5_head = (view) => {
  const head = `Detected: ${TYPE_LABELS[view.dtype]} · ${view.row_count.toLocaleString("en-US")} rows`;
  return view.months ? `${head} · ${view.months.count} months (${fmtMonth(view.months.first)} – ${fmtMonth(view.months.last)})` : head;
};
// S26a-c (2026-10-16): the detected type with its source and the Change button; the sheet read; what a miss says.
export const TYPE_SOURCES = { rules: "by rules", ai: "AI suggestion", you: "your choice" };
export const S26_type = (view) => `Type: ${TYPE_LABELS[view.dtype]}${TYPE_SOURCES[view.type_source] ? ` (${TYPE_SOURCES[view.type_source]})` : ""}`;
export const S26_CHANGE = "Change";
export const S26_sheet = (view) => `Sheet "${view.sheet}" · header on row ${view.header_row}`;
const LOOKS = {
  summary: "a forecast or summary table: periods (years or quarters) run across the columns and each line is a metric",
  monthly_wide: "a table with months across the columns and one line per row",
};
export const S27_SHOW_COLUMNS = "Show columns";
export const S27_miss = (view) => {
  const looks = view.miss.looks || {};
  const what = LOOKS[looks.shape] || `a table of ${(looks.rows ?? 0).toLocaleString("en-US")} rows and ${looks.columns ?? 0} columns`;
  return `Could not read this file as ${TYPE_LABELS[view.dtype]}. Missing: ${view.miss.missing.map(fieldName).join(", ")}. It looks like ${what}.`;
};
// S28a-d (2026-10-16, section 20): a forecast table read as claims, one plan line × one year; nothing is saved before Confirm.
const claimsWord = (n) => `${n.toLocaleString("en-US")} ${n === 1 ? "claim" : "claims"}`;
export const S28_read = (fc) => `Read as ${claimsWord(fc.count)} from ${fc.sheet}!${fc.range}. Default label: Unverified.`;
export const S28_SHOW_CLAIMS = "Show claims";
export const S28_cap = (fc) => `The table holds ${fc.total.toLocaleString("en-US")} claims; the first 60 by row order are read.`;
export const S28_CONFIRM = "Save claims";      // George, 2026-10-16
export const S28_saved = (n) => `Saved ${claimsWord(n)} as Unverified.`;
/** One year of a line in the Show claims list: its period as the file states it (or the fiscal year it was rolled up to) and its
 *  value with its unit: "2025F 1,980,000 EUR", "FY2026 65.2%", "2025F 26 people". */
export const forecastValueText = (line, v) => {
  const n = Number(v.value).toLocaleString("en-US", { maximumFractionDigits: 2 });
  const figure = line.unit === "%" ? `${n}%` : [n, line.currency || line.unit].filter(Boolean).join(" ");
  return `${v.period_text || `FY${v.target_date}`} ${figure}`;
};
/** The cells a line's claims cite, first to last: "C5:H5", "H5:BC5". */
export const forecastCells = (line) => {
  const first = line.values[0].cell.split(":")[0];
  const last = line.values[line.values.length - 1].cell.split(":").pop();
  return first === last ? first : `${first}:${last}`;
};
export const S8_replace = (dtype, file) => `${LOADED_LABELS[dtype]} is already loaded (${file}). Replace it?`;

// S23: the mapping table's headers (the last column holds the buttons).
export const MAPPING_HEADERS = ["In your file", "Means", "Confidence", "Mapped by", ""];
// S24: who mapped a column.
export const MAPPED_BY = {
  rules: "Rules", ai: "AI suggestion – confirm", you: "You", needs: "You – choose", saved: "Saved from earlier upload",
};
export const mappedBy = (row) => {
  if (row.decision === "confirm" || row.decision === "correct") return MAPPED_BY.you;
  if (row.state === "needs") return MAPPED_BY.needs;
  if (row.source === "saved") return MAPPED_BY.saved;
  if (row.source === "ai") return MAPPED_BY.ai;
  return MAPPED_BY.rules;
};
// S9: the confidence cell, never a dash. A rule row shows its number (with the fit note when the values lower it), an AI
// suggestion says "AI suggestion – confirm" and never its number (George, 2026-10-17), a column with no proposal says it
// needs confirmation, both until the analyst decides them; a saved mapping says "reused". A column the rules found no field
// for scores 0.
export const S9_confidence = (row) => {
  const decided = row.decision === "confirm" || row.decision === "correct";
  if (row.source === "saved") return "reused";
  if (row.source === "ai" && !decided) return MAPPED_BY.ai;
  if (row.source === "ai" || row.source === "needs" || row.source === "decision" || row.state === "needs") {
    return decided ? "confirmed" : "needs confirmation";
  }
  const n = row.confidence ?? 0;
  return row.fit_note ? `${n} · ${row.fit_note}` : String(n);
};
// Row order (section 4.4): rows that need a click first, then ascending confidence; the auto-accepted 100s come last.
// A row with no score shown (an AI suggestion, whose number stays off screen; a column with no proposal) counts as the
// lowest. Stable on file order.
export function sortColumns(columns) {
  const level = (c) => (c.source === "ai" ? -1 : c.confidence ?? -1);
  return columns.map((c, i) => [c, i]).sort(([a, i], [b, j]) =>
    (b.pending ? 1 : 0) - (a.pending ? 1 : 0) || level(a) - level(b) || i - j).map(([c]) => c);
}

// S25: the info box above the mapping table, open by default.
export const S25_TITLE = "Why this step matters";
export const S25_PARAGRAPHS = [
  "Every figure in this audit depends on how the columns are interpreted. If a column is mapped incorrectly—for example, bookings are treated as revenue, or an invoice date as a service date—the resulting calculations may look correct but be wrong.",
  "The app suggests a mapping for each column and indicates its confidence level. High-confidence mappings are accepted automatically, but you can change them. Low-confidence mappings appear at the top of the table and require your review.",
  "No calculations begin until all required columns are confirmed.",
  "Your choices are saved with the audit and automatically reused if you upload the same file again.",
];
// S29: the fields a CRM file feeds, in an info box above its mapping table, open by default (George, 2026-10-17, word for word).
export const S29_TITLE = "Fields used in this analysis";
export const S29_PARAGRAPHS = [
  "Match Created date, Close date, and Stage / status to calculate sales cycles and win rates.",
  "Segment is optional. If mapped (for example a plan tier or company size), the sales cycle is also shown per segment with its median, spread and deal count. If not mapped, only the overall sales cycle is shown.",
  "Founder involved is optional. If mapped, it must hold yes or no per deal (yes / y / true / 1, no / n / false / 0); the app then compares the win rate of deals with and without the founder. Values it cannot read are listed and left out. If not mapped, the founder comparison reads Missing.",
  "Deal ID is used to remove repeated rows: rows that share a deal ID with the same stage and dates (for example one row per product line) count as one deal, and the number of rows collapsed is reported under Worth flagging.",
  "Close date is also used for the quarter-end clustering check: the share of won deals closed in the last 10 days of a quarter, by the company's fiscal year-end (needs at least 20 won deals).",
  "Amount can be mapped but is not used in any calculation.",
];
export const S13_READY = "Ready – press Run audit";
export const S13_status = (view) => {
  if (view.read_as_claims) return S28_saved(view.read_as_claims.claims);     // read as claims: it waits for nothing (section 20)
  if (view.miss && view.miss.missing.length > 0) return `Required field not mapped: ${view.miss.missing.map(fieldName).join(", ")}`;
  if (view.pending > 0) return `${view.pending} columns wait for your decision`;
  if (view.missing_required.length > 0) return `Required field not mapped: ${view.missing_required.map(fieldName).join(", ")}`;
  return S13_READY;
};
export const S14_same = (version) => `Same file as before: saved mapping v${version} applied.`;
export const S16a_MISSING = "Revenue file missing: upload and map it to compute metrics.";
export const S16d_UNCONFIRMED = "Revenue file uploaded – confirm the mapping to compute metrics.";

export const fieldName = (f) => (f ? f.replace(/_/g, " ") : "—");

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function fmtMonth(ym) {
  const [y, m] = ym.split("-").map(Number);
  return `${MONTH_NAMES[m - 1]} ${y}`;
}

export function fmtBytes(n) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export const extensionOf = (name) => {
  const i = (name || "").lastIndexOf(".");
  return i < 0 ? "" : name.slice(i + 1).toLowerCase();
};

/** The field a column holds, as a disabled-option hint: {field: column that holds it}. */
export function heldFields(columns, except) {
  const out = {};
  columns.forEach((c) => {
    if (c.field && c.column !== except && ["auto", "unsure", "ai", "confirmed", "corrected"].includes(c.state)) out[c.field] = c.column;
  });
  return out;
}

// Map: files dropped in the chat are only attached; nothing is read until the analyst presses Map, which reads them and maps
// their columns (rules, then the AI for what is left, then the confirmation list). Run audit is the only way to calculate.
// The "revenue file missing" banner appears only after Map has been pressed.
export const MAP_LABEL = "Map";
export const MAP_TOOLTIP = "Reads the attached files and maps their columns. Run audit follows once every column is confirmed.";
export const MAP_NO_FILE_TOOLTIP = "Attach the revenue file first. It is the only required file.";
/** Map: off while nothing is attached and nothing is loaded, or while a press is being worked. */
export const mapState = ({ attached, loaded, busy }) => {
  const noFile = attached === 0 && loaded === 0;
  return { disabled: noFile || busy, tooltip: noFile ? MAP_NO_FILE_TOOLTIP : MAP_TOOLTIP };
};
/** The mapping is complete when a revenue file is loaded, no file waits unread, and every loaded file has no column left for
 *  the analyst's decision and no required field unmapped (section 4.3). */
export const mappingComplete = ({ attached, views }) => attached === 0 && views.some((v) => v.dtype === "revenue" && !v.read_as_claims)
  && views.every((v) => v.pending === 0 && v.missing_required.length === 0);
export const CALCULATE_CLASS = "bg-sky-600 hover:bg-sky-500 gap-2";      // the Map button and the register's claim-type buttons look the same
/** Shown beside the mapping list once the analyst has confirmed the last open column (section 24.5). */
export const ALL_CONFIRMED_LINE = "All columns confirmed. Press Run audit at the bottom of the page to calculate.";
export const REVENUE_REQUIRED_NOTE = seeGlossary("The revenue file is the only required file. Every metric in the audit – ARR, NRR, churn, CAC payback – is computed from it; without it nothing can be calculated or verified.");
const pressedKey = (auditId) => `calculate-pressed:${auditId}`;
export function calculatePressed(auditId) {
  try { return window.sessionStorage.getItem(pressedKey(auditId)) === "1"; } catch (e) { return false; }
}
export function setCalculatePressed(auditId, on = true) {
  try {
    if (on) window.sessionStorage.setItem(pressedKey(auditId), "1"); else window.sessionStorage.removeItem(pressedKey(auditId));
  } catch (e) { /* storage may be blocked: the banner then follows the next press */ }
}
