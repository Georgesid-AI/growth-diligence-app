/**
 * Board deck upload: the scope message and the display strings for the candidate approval
 * list (docs/specs/deck-parser.md). Pure functions over the stored candidates.
 *
 * A candidate's value is a figure as the deck wrote it, not a computed metric, so it keeps
 * its decimals ("2.5", "13.72%") instead of going through format.js rounding.
 */
export const PLACEHOLDER = "—";

export const DECK_ACCEPT = ".pptx,.pdf,.docx";

// Shown on the upload screen, word for word from the spec.
export const DECK_SCOPE_INTRO = "We read text from PowerPoint, Word and text-based PDF files.";
export const DECK_SCOPE_CANNOT = [
  "Scanned PDFs, images or charts saved as pictures. There is no text in them to read, only pixels.",
  "Keynote files or Google Slides links. Please export them as PowerPoint or PDF first.",
];
export const DECK_SCOPE_OUTRO = "If a number you need sits in a picture, add it as text or send the source spreadsheet.";

export const CLAIM_TYPES = ["revenue", "retention", "sales", "people", "product", "market"];
export const CLAIM_UNITS = ["%", "x", "months", "years", "weeks", "days", "hours"];

export const STATUS_LABELS = { pending: "To review", approved: "Approved", rejected: "Rejected", edited: "Edited" };

/** "board.pptx · slide 5 · notes", "plan.pdf · page 19 · table 1, row 4, col 2". */
export function sourceRef(ref) {
  if (!ref) return PLACEHOLDER;
  const where = ref.slide != null ? `slide ${ref.slide}` : `page ${ref.page}`;
  const parts = [ref.file, where];
  if (ref.kind === "notes") parts.push("notes");
  if (ref.kind === "table") parts.push(`table ${ref.table}, row ${ref.row}, col ${ref.col}`);
  return parts.join(" · ");
}

const figure = (v) => Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
const present = (v) => v !== null && v !== undefined && Number.isFinite(Number(v));

/** "3,600,000 USD", "15%", "4.9x", "24 months", "2.5", "12,000,000–13,000,000 USD" for a range;
 *  "—" for a date-only claim. */
export function claimValue(c) {
  if (!present(c?.value)) return PLACEHOLDER;
  const n = present(c.value_high) ? `${figure(c.value)}–${figure(c.value_high)}` : figure(c.value);
  if (c.unit === "%") return `${n}%`;
  if (c.unit === "x") return `${n}x`;
  if (c.unit) return `${n} ${c.unit}`;
  return c.currency ? `${n} ${c.currency}` : n;
}

/** Counts per status, for the list header. */
export function statusCounts(candidates) {
  const out = { pending: 0, approved: 0, rejected: 0, edited: 0 };
  (candidates || []).forEach((c) => { out[c.status] = (out[c.status] || 0) + 1; });
  return out;
}
