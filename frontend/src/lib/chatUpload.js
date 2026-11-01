/**
 * Upload: the approved wording (docs/specs/chat-upload.md section 11, S1-S22) and the small
 * pure helpers the screen uses. The wording lives here once so the components and their tests read the same text.
 */
import { seeGlossary } from "./glossary";
import { fmtBytes as formatBytes, fmtCount } from "./format";

// The deck sentence of S2 (Upload page restructure, George, 2026-10-28): the zero-data-retention wording only when the server says PROVIDER_ZDR is on.
export const ZDR_SENTENCE_ON = "Deck pages are processed by Anthropic under a zero-data-retention arrangement. Nothing is retained after the reply and nothing is used for training.";
export const ZDR_SENTENCE_OFF = "Deck pages are sent to Anthropic's API for reading and are not used for training.";
// S2 (PR 4, read-check-review.md section 12): the files are read, not mapped; no sentence about mapping or confirming rows.
export const READ_AUTOMATICALLY_LINE = "Files are read automatically. Nothing waits for your confirmation.";
export const s2Explainer = (zdr) =>
  "The AI reads every cell of each uploaded spreadsheet – sheet names, headers, row labels and figures – after the masking described above, and figures are checked by code against their cells. "
  + `${READ_AUTOMATICALLY_LINE} `
  + "The AI reads every page of uploaded decks to find plan figures: the text of each page that carries a figure, masked as above, and one image of the whole page, which is not masked. "
  + `${zdr ? ZDR_SENTENCE_ON : ZDR_SENTENCE_OFF} `
  + "Uploaded files are stored for this audit and deleted with it.";
export const S3_EXPLAINER_NO_CONSENT =
  "AI-assisted reading is off for this audit: uploaded spreadsheets and decks are stored but not read. Tick the box above to read them.";
export const S4_DROP_ZONE_LEAD =
  "Drop files here or use the paperclip. Required: a revenue file – revenue by customer, invoices or a monthly revenue report (24–36 months). The audit will not run without a revenue file. Optional: CRM export and P&L. ";
export const S4_DROP_ZONE_BOLD = ".xlsx or .csv only";      // the only bold part of the text
export const S7_REFUSED = "This window takes .xlsx and .csv files. Decks go in the deck panel below.";
export const S7B_XLS_REFUSED = "Save as .xlsx or .csv and upload again.";
export const S_UPLOAD_RETRY = "The file could not be read. Press Map to try again.";   // no answer from the server (timeout or network error)
export const S17_NARRATIVE_FAILED_TITLE = "Narrative could not be generated.";
// S18: the delete dialog. The name in the body is shown in bold by the dialog; the text around it is here.
export const S18_TITLE = (company) => `Delete ${company}?`;
export const S18_BODY = ["Deleting this audit with its files, mappings and results cannot be undone. Type ", " to confirm."];
export const S18_MISMATCH = "Name does not match";
export const S20_NOTE_PLACEHOLDER = "Why? Up to 60 characters; no file names, figures or names.";
export const S21_NOTE_REFUSED = "Leave out file names, figures and cell values: this note is kept with the usage counts.";
export const S22_RECONCILIATION = "Revenue reconciliation";
export const S22_SAME_SOURCE = "Not applicable – same source";
export const NOTE_MAX = 60;

export const ALLOWED_EXTENSIONS = ["xlsx", "csv"];

// A byte size by the one display rule (lib/format.js), kept under its old name here.
export const fmtBytes = (n) => (n == null ? "" : n < 1024 ? `${fmtCount(n)} B` : formatBytes(n));

export const extensionOf = (name) => {
  const i = (name || "").lastIndexOf(".");
  return i < 0 ? "" : name.slice(i + 1).toLowerCase();
};

// Map: files dropped in the list are only attached; nothing is sent until the analyst presses Map, which stores them and starts the reading.
// Run audit is the only way to calculate; nothing waits for a confirmation. The "no file read" banner appears only after Map has been pressed.
export const MAP_LABEL = "Map";
export const MAP_TOOLTIP = "Sends the attached files to be read. Run audit follows once they are read.";
export const MAP_NO_FILE_TOOLTIP = "Attach a file first.";
/** Map: off while nothing is attached and nothing is loaded, or while a press is being worked. */
export const mapState = ({ attached, loaded, busy }) => {
  const noFile = attached === 0 && loaded === 0;
  return { disabled: noFile || busy, tooltip: noFile ? MAP_NO_FILE_TOOLTIP : MAP_TOOLTIP };
};
export const CALCULATE_CLASS = "bg-sky-600 hover:bg-sky-500 gap-2";      // the Map button and the register's claim-type buttons look the same
export const S16a_MISSING = "No file has been read yet: upload a file and run the audit.";
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
