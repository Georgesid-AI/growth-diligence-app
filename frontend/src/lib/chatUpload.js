/**
 * Chat upload and column mapping: the approved wording (docs/specs/chat-upload.md section 11, S1-S22) and the small
 * pure helpers the screen uses. The wording lives here once so the components and their tests read the same text.
 */
import { seeGlossary } from "./glossary";

export const S1_TEXT_REPLY = "This window accepts files and mapping confirmations.";
export const S2_EXPLAINER_CONSENT =
  "Mapping is done by rules first. Where rules cannot decide, the AI sees only those columns' headers, up to 3 example numbers or dates per column and a pattern for text columns – never your full file and never a name – and you confirm those columns.";
export const S3_EXPLAINER_NO_CONSENT =
  "Mapping is done by rules only: AI-assisted reading is off for this audit. You map the columns the rules cannot decide.";
export const S4_DROP_ZONE =
  "Drop files here or use the paperclip. Required: revenue by customer (monthly, 24–36 months). Also useful: CRM export, P&L. Board decks go to the Deck panel. .xlsx or .csv only.";
export const S6_UNKNOWN_TYPE = "Could not tell what this file holds. Pick its type:";
export const S7_REFUSED = "This window takes .xlsx and .csv files. Decks go in the deck panel below.";
export const S7B_XLS_REFUSED = "Save as .xlsx or .csv and upload again.";
export const S12_MODEL_FAILED = "AI reading unavailable – these columns need your decision.";
export const S17_NARRATIVE_FAILED_TITLE = "Narrative could not be generated.";
// S18: the delete dialog. The name in the body is shown in bold by the dialog; the text around it is here.
export const S18_TITLE = (company) => `Delete ${company}?`;
export const S18_BODY = ["Deleting this audit with its files, mappings and results cannot be undone. Type ", " to confirm."];
export const S18_MISMATCH = "Name does not match";
export const S19_USAGE_TOTALS = "Usage totals (all audits)";
export const S19_USAGE_EXPLAINER = "Totals across all audits on this server since counting began. Counts and costs only — no file names, figures or company names. Kept to improve the app.";
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
// suggestion or a column with no proposal says it needs confirmation until the analyst decides it, a saved mapping says
// "reused". A column the rules found no field for scores 0.
export const S9_confidence = (row) => {
  const decided = row.decision === "confirm" || row.decision === "correct";
  if (row.source === "saved") return "reused";
  if (row.source === "ai" || row.source === "needs" || row.source === "decision" || row.state === "needs") {
    return decided ? "confirmed" : "needs confirmation";
  }
  const n = row.confidence ?? 0;
  return row.fit_note ? `${n} · ${row.fit_note}` : String(n);
};
// Row order (section 4.4): rows that need a click first, then ascending confidence; the auto-accepted 100s come last.
// A row with no score (an AI suggestion, a column with no proposal) counts as the lowest. Stable on file order.
export function sortColumns(columns) {
  const level = (c) => c.confidence ?? -1;
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
export const S13_status = (view) => {
  if (view.pending > 0) return `${view.pending} columns wait for your decision`;
  if (view.missing_required.length > 0) return `Required field not mapped: ${view.missing_required.map(fieldName).join(", ")}`;
  return "Ready for calculation";
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

// Map and Calculate (task of 2026-10-09): files dropped in the chat are only attached; nothing is read until the analyst
// presses Map, which reads them and maps their columns (rules, then the AI for what is left, then the confirmation list).
// Calculate computes the metrics and waits until the mapping is complete. The "revenue file missing" banner appears
// only after Map has been pressed.
export const MAP_LABEL = "Map";
export const MAP_TOOLTIP = "Reads the attached files and maps their columns. Calculate follows once every column is confirmed.";
export const MAP_NO_FILE_TOOLTIP = "Attach the revenue file first. It is the only required file.";
export const CALCULATE_LABEL = "Calculate";
export const CALCULATE_TOOLTIP = "Computes the metrics from the mapped files.";
export const CALCULATE_NOT_MAPPED_TOOLTIP = "Map the revenue file and confirm every column that waits for you first.";
/** Map: off while nothing is attached and nothing is loaded, or while a press is being worked. */
export const mapState = ({ attached, loaded, busy }) => {
  const noFile = attached === 0 && loaded === 0;
  return { disabled: noFile || busy, tooltip: noFile ? MAP_NO_FILE_TOOLTIP : MAP_TOOLTIP };
};
/** The mapping is complete when a revenue file is loaded, no file waits unread, and every loaded file has no column left for
 *  the analyst's decision and no required field unmapped (section 4.3). */
export const mappingComplete = ({ attached, views }) => attached === 0 && views.some((v) => v.dtype === "revenue")
  && views.every((v) => v.pending === 0 && v.missing_required.length === 0);
/** Both Calculate buttons (header and chat) show this one state: on only when the mapping is complete and nothing is running. */
export const calculateState = ({ attached, views, busy }) => {
  const ready = mappingComplete({ attached, views });
  return { disabled: !ready || busy, tooltip: ready ? CALCULATE_TOOLTIP : CALCULATE_NOT_MAPPED_TOOLTIP };
};
export const CALCULATE_CLASS = "bg-sky-600 hover:bg-sky-500 gap-2";      // the header button and the chat buttons look the same
export const SEND_TOOLTIP = "Send a message (for answering the chat's questions)";
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
