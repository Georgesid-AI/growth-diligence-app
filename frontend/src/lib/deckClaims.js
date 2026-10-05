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
  gross_profit: "Gross profit", costs: "Costs", ebitda: "EBITDA", net_profit: "Net profit", usage: "Usage",
  people: "People", product: "Product", market: "Market", use_of_funds: "Use of funds",
};
// The types an analyst can choose: same order and names as backend app/decks/claims.py CLAIM_TYPES.
// "Use of funds" is a type the model may read from a structure, not one the parser gives.
export const CLAIM_TYPES = Object.keys(TYPE_LABELS).filter((t) => t !== "usage" && t !== "use_of_funds");
// Suggestions for the unit field; a count's unit is the noun it counts ("paying users").
export const CLAIM_UNITS = ["%", "x", "months", "years", "weeks", "days", "hours", "customers", "users"];

// One header per column of the approval list, in column order.
export const COLUMNS = ["Type", "Value", "Date", "Claim in the deck", "Source", "Status", "Action"];

export const typeLabel = (t) => TYPE_LABELS[t] || t;

export const STATUS_LABELS = { pending: "To review", approved: "Approved", rejected: "Rejected", edited: "Edited" };

// The structure a model reading cites, by its type (docs/specs/deck-parser.md section 7).
export const STRUCTURE_NAMES = {
  table: "table", chart: "chart", kpi_panel: "KPI panel", roadmap: "roadmap", hiring_table: "hiring table",
  unit_economics: "unit-economics table", use_of_funds: "use-of-funds table",
};

/** "board.pptx · slide 5 · notes", "plan.pdf · page 19 · table 1, row 4, col 2", and for a model reading
 *  its cell: "plan.pdf · page 19 · table 1, cell r4c3", "plan.pdf · page 19 · KPI panel, cell r2c1". */
export function sourceRef(ref) {
  if (!ref) return PLACEHOLDER;
  const where = ref.slide != null ? `slide ${ref.slide}` : `page ${ref.page}`;
  const parts = [ref.file, where];
  if (ref.kind === "notes") parts.push("notes");
  if (ref.kind === "table") parts.push(`table ${ref.table}, row ${ref.row}, col ${ref.col}`);
  if (ref.kind === "structure") {
    const name = STRUCTURE_NAMES[ref.structure] || ref.structure;
    parts.push(`${name}${ref.table != null ? ` ${ref.table}` : ""}, cell ${ref.cell}`);
  }
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

/** The Date column: a table row's first to last period, else the claim's date, each as the deck
 *  states it ("FY25", "Y/E 22") when it does; the date range behind it stays server-side. */
export function claimDate(c) {
  const shown = (v) => v?.period_text || v?.target_date;
  const dates = (c?.by_period || []).map(shown).filter(Boolean);
  if (dates.length) return dates.length > 1 ? `${dates[0]}–${dates[dates.length - 1]}` : dates[0];
  return shown(c) || PLACEHOLDER;
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

// Model reading (docs/specs/llm-structure-reading.md): every row the model read carries one of these,
// and so does every mapping field it proposed. Python checked a Verified value against its source cell.
export const VERIFIED_LABEL = "Verified";
export const AI_SUGGESTION_LABEL = "AI suggestion, not verified";
export const STORED_MAPPING_LABEL = "Your confirmed mapping for these headers";

// The deck panel's run log (docs/specs/llm-structure-reading.md sections 3, 4 and 9).
export const DECK_AI_STATUS = {
  reading: "reading", waiting: "waiting for revenue file", read: "read", not_read: "not read", stopped: "not read",
  python_only: "not read (AI-assisted reading is off for this audit)",
};

// A deck uploaded while AI reading was off is not read when reading is switched on: it is uploaded again.
export const UPLOADED_BEFORE_CONSENT = "Uploaded before AI reading was enabled; re-upload to read.";

/** ["AI reading: read", "Sent to the model: slides 4, 7, 12", "Cost: $0.0123"] for one deck; the stop
 *  message when the audit reached its token limit; how many of the model's periods Python replaced
 *  with the one its header cells give; the re-upload line for a deck uploaded while AI reading was
 *  off, once it is on. */
export function deckRunLog(deck) {
  if (deck?.uploaded_before_consent) return [`AI reading: ${DECK_AI_STATUS.not_read}`, UPLOADED_BEFORE_CONSENT];
  if (!deck?.ai_status) return [];
  const lines = [`AI reading: ${DECK_AI_STATUS[deck.ai_status] || deck.ai_status}`];
  if (deck.ai_status === "stopped" && deck.ai_message) lines.push(deck.ai_message);
  if (deck.sent_pages?.length) lines.push(`Sent to the model: ${deck.page_unit || "slide"}s ${deck.sent_pages.join(", ")}`);
  if (deck.periods_corrected) lines.push(`Periods corrected from the header cells: ${deck.periods_corrected}`);
  if (deck.ai_cost_usd) lines.push(`Cost: $${Number(deck.ai_cost_usd).toFixed(4)}`);
  return lines;
}

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
