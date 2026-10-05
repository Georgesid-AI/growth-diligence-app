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

// Shown above the approval list, word for word.
export const CLAIMS_HEADING = "Claims found in the deck";
export const CLAIMS_INTRO = "These figures may inform the growth plan. They were identified automatically and may contain errors. Check each claim against its source slide, then choose:";
export const CLAIMS_CHOICES = [
  ["✓ Approve:", "Confirm this is a claim the company makes. It will be added to the claim register and tested against the data."],
  ["✎ Edit:", "Correct the figure, type, unit or date, then approve the claim. It will be added to the claim register and tested against the data."],
  ["✕ Reject:", "Exclude items that are not company claims, such as another company's figures, funds raised or chart axis labels. Rejected items remain in the record but are not used."],
];

// Labels for every type a stored claim may carry; "usage" only on claims parsed before it was dropped.
export const TYPE_LABELS = {
  revenue: "Revenue", revenue_growth: "Revenue growth", growth: "Growth", retention: "Retention", sales: "Sales",
  customers: "Customers", users: "Users", user_growth: "User growth", gross_margin: "Gross margin",
  gross_profit: "Gross profit", costs: "Costs", ebitda: "EBITDA", usage: "Usage",
  people: "People", product: "Product", market: "Market",
};
// The types an analyst can choose: same order and names as backend app/decks/claims.py CLAIM_TYPES.
export const CLAIM_TYPES = Object.keys(TYPE_LABELS).filter((t) => t !== "usage");
// Suggestions for the unit field; a count's unit is the noun it counts ("paying users").
export const CLAIM_UNITS = ["%", "x", "months", "years", "weeks", "days", "hours", "customers", "users"];

// One header per column of the approval list, in column order.
export const COLUMNS = ["Type", "Value", "Date", "Claim in the deck", "Source", "Status", "Action"];

export const typeLabel = (t) => TYPE_LABELS[t] || t;

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

function amount(c, value, high) {
  if (!present(value)) return PLACEHOLDER;
  const n = present(high) ? `${figure(value)}–${figure(high)}` : figure(value);
  if (c.unit === "%") return `${n}%`;
  if (c.unit === "x") return `${n}x`;
  if (c.unit) return `${n} ${c.unit}`;
  return c.currency ? `${n} ${c.currency}` : n;
}

/** "3,600,000 USD", "15%", "4.9x", "24 months", "2.5", "12,000,000–13,000,000 USD" for a range;
 *  "—" for a date-only claim. A table row lists its values by period:
 *  "200 (Y/E 22) · 5,000 (Y/E 23) · …". */
export function claimValue(c) {
  if (c?.by_period?.length) {
    return c.by_period.map((i) => `${amount(c, i.value, i.value_high)} (${i.period || i.target_date || PLACEHOLDER})`).join(" · ");
  }
  return amount(c || {}, c?.value, c?.value_high);
}

/** The Date column: a table row's first to last period, else the claim's target date. */
export function claimDate(c) {
  const dates = (c?.by_period || []).map((i) => i.target_date).filter(Boolean);
  if (dates.length) return dates.length > 1 ? `${dates[0]}–${dates[dates.length - 1]}` : dates[0];
  return c?.target_date || PLACEHOLDER;
}

/** The edit sent for a table row: one value per period, in the row's order; dates stay. */
export function rowEdit(row, values) {
  return row.by_period.map((i, k) => ({
    value: values[k] === "" || values[k] === undefined ? null : Number(values[k]),
    value_high: i.value_high ?? null,
    target_date: i.target_date ?? null,
  }));
}

// Shown on both claims when one deck gives the same type and period different values.
export const INCONSISTENCY_LABEL = "Deck inconsistency";

// Deck selector above the claims table: "All" plus one tab per deck.
export const ALL_DECKS = "all";
export const REMOVE_DECK_CONFIRM = "This deletes the deck and all its claims, including reviewed ones.";

/** The most recently uploaded deck's id, or ALL_DECKS when there is no deck. */
export function defaultDeck(decks) {
  if (!decks?.length) return ALL_DECKS;
  return [...decks].sort((a, b) => String(b.uploaded_at || "").localeCompare(String(a.uploaded_at || "")))[0].deck_id;
}

/** [{id, label, count}]: "All" first, then each deck (most recent first) with its claim count. */
export function deckTabs(decks, candidates) {
  const count = (id) => (candidates || []).filter((c) => c.deck_id === id).length;
  const ordered = [...(decks || [])].sort((a, b) => String(b.uploaded_at || "").localeCompare(String(a.uploaded_at || "")));
  return [{ id: ALL_DECKS, label: "All", count: (candidates || []).length },
    ...ordered.map((d) => ({ id: d.deck_id, label: d.file, count: count(d.deck_id) }))];
}

/** The claims shown under a tab, in the order the server sent them (to review first, then slide or page). */
export function claimsForDeck(candidates, deckId) {
  return deckId === ALL_DECKS ? candidates || [] : (candidates || []).filter((c) => c.deck_id === deckId);
}

/** Counts per status, for the list header. */
export function statusCounts(candidates) {
  const out = { pending: 0, approved: 0, rejected: 0, edited: 0 };
  (candidates || []).forEach((c) => { out[c.status] = (out[c.status] || 0) + 1; });
  return out;
}
