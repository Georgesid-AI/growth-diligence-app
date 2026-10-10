/**
 * Board deck upload: the scope message and the display strings for the candidate approval
 * list (docs/specs/deck-parser.md). Pure functions over the stored candidates.
 *
 * A candidate's value is a figure as the deck wrote it, not a computed metric, so it keeps
 * its decimals ("2.5", "13.72%") instead of going through format.js rounding.
 */
import { displayDate } from "./datePicker";

export const PLACEHOLDER = "—";
export const NO_DATE = "no date";        // the Period column of a claim that states no date

export const DECK_ACCEPT = ".pptx,.pdf,.docx";

// Hover on the Confidence column, word for word.
export const CONFIDENCE_HOVER = "Confidence shows how well this figure was read from the deck, not whether it is true. High: value, date and unit were all found and the figure appears in more than one place in the deck. Medium: value found with a date or a unit, but one detail is missing or the figure appears once. Low: value found, date and unit missing. 'Not corroborated' means the figure appears only once in the deck. 'No date' or 'no unit' names the detail that was not found; you can add it in the row. Whether the figure is true is shown by the evidence label after the data files are calculated.";

// Shown above the upload button, word for word.
export const DECK_UPLOAD_HELP = "Board deck or growth plan: the company's board decks, investor updates, growth model or business plan, as PDF or PowerPoint. Up to 8 documents per audit. The audit reads the claims from them and tests each against the data files.";

// Shown on the upload screen, word for word from the spec.
export const DECK_SCOPE_INTRO = "We read text from PowerPoint, Word and text-based PDF files.";
export const DECK_SCOPE_CANNOT = [
  "Scanned PDFs, images or charts saved as pictures. There is no text in them to read, only pixels.",
  "Keynote files or Google Slides links. Please export them as PowerPoint or PDF first.",
];
export const DECK_SCOPE_OUTRO = "If a number you need sits in a picture, use Add claim and cite the page, or upload the source spreadsheet.";

// Shown above the approval list, word for word.
export const CLAIMS_HEADING = "Claims found in the uploaded documents";
export const CLAIMS_INTRO = "These figures were extracted automatically and inform the growth plan. While errors are possible, you only need to check claims that look incorrect or implausible against their source slides before making your selection.";
export const CLAIMS_CHOICES = [
  ["✓ Approve:", "Confirm this is a claim the company makes. It will be added to the claim register and tested against the data."],
  ["✎ Edit:", "Correct the figure, type, unit or date, then approve the claim. It will be added to the claim register and tested against the data."],
  ["✕ Reject:", "Exclude items that are not company claims, such as another company's figures, funds raised or chart axis labels. Rejected items remain in the record but are not used."],
];

// Add claim: a figure the analyst reads off a slide or page the parser could not read. The server tags it origin "analyst".
export const ADD_CLAIM_LABEL = "Add claim";
export const ADD_CLAIM_NEEDS_SOURCE = "Enter the value, choose the metric and the source document, and enter the page number.";
export const ANALYST_ADDED_TAG = "Added by analyst";
export const ANALYST_CONFIDENCE = "Analyst-entered";

/** The POST body of Add claim from the form draft, or null while the source document or the page is missing, or the value is. */
export function newClaimPayload(draft) {
  const page = Number(draft.page);
  if (!draft.deck_id || !Number.isInteger(page) || page < 1 || draft.value === "" || !draft.claim_type || !draft.metric) return null;
  return {
    claim_type: draft.claim_type, metric: draft.metric, deck_id: draft.deck_id, page,
    value: Number(draft.value), value_high: draft.value_high === "" ? null : Number(draft.value_high),
    unit: draft.unit.trim() || null, currency: draft.currency.trim() ? draft.currency.trim().toUpperCase() : null,
    target_date: draft.target_date.trim() || null,
  };
}

// A figure no heading names a type for (docs/specs/deck-parser.md section 2): not guessed, the analyst chooses.
export const UNKNOWN_TYPE_LABEL = "Unknown – choose type";

// Labels for every type a stored claim may carry; "usage" only on claims parsed before it was dropped; "other" on an
// item the model labelled other (docs/specs/structure-labelling.md section 4).
export const TYPE_LABELS = {
  revenue: "Revenue", revenue_growth: "Revenue growth", growth: "Growth", retention: "Retention", sales: "Sales",
  customers: "Customers", users: "Users", user_growth: "User growth", gross_margin: "Gross margin",
  gross_profit: "Gross profit", costs: "Costs", ebitda: "EBITDA", net_profit: "Net profit", usage: "Usage",
  people: "People", product: "Product", market: "Market size", cash: "Cash", burn: "Burn", runway: "Runway", ltv: "LTV",
  cac: "CAC", customer_lifetime: "Customer lifetime", ltv_cac: "LTV/CAC", trials_per_day: "Trials per day",
  months_to_profitability: "Months to profitability", use_of_funds: "Use of funds", other: "Other",
  unknown: UNKNOWN_TYPE_LABEL,
};
// The types an analyst can choose: same order and names as backend app/decks/claims.py CLAIM_TYPES.
// "Use of funds" is a type the model may read from a structure, not one the parser gives.
export const CLAIM_TYPES = Object.keys(TYPE_LABELS).filter((t) => !["usage", "use_of_funds", "other", "unknown"].includes(t));
// Suggestions for the unit field; a count's unit is the noun it counts ("paying users").
export const CLAIM_UNITS = ["%", "x", "months", "years", "weeks", "days", "hours", "count", "customers", "users"];
// What the unit "count" stands for, shown beside it in the unit list; a currency stays in its own field.
export const COUNT_UNIT_HINT = "customers, headcount, deals";

// Types whose figure counts things: they carry the unit "count" (or the noun counted) and never a currency.
export const COUNT_TYPES = ["customers", "users", "people", "trials_per_day"];
export const COUNT_UNIT = "count";

// One header per column of the approval list, in column order.
export const COLUMNS = ["Type", "Value", "Period", "Confidence", "Claim in the deck", "Source", "Status", "Action"];

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
// A converted figure is in whole units of the reporting currency: the rate and the date it applies at are on hover.
const whole = (v) => Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
const present = (v) => v !== null && v !== undefined && Number.isFinite(Number(v));

function amount(c, value, high, rate) {
  if (!present(value)) return PLACEHOLDER;
  const scale = rate ? Number(rate) : 1;
  const fmt = rate ? whole : figure;
  const n = present(high) ? `${fmt(value * scale)}–${fmt(high * scale)}` : fmt(value * scale);
  if (c.unit === "%") return `${n}%`;
  if (c.unit === "x") return `${n}x`;
  if (c.unit) return `${n} ${c.unit}`;
  return c.currency ? `${n} ${rate ? c.fx.currency : c.currency}` : n;
}

// A direction the deck states with no figure ("Positive EBITDA"): shown as such, never as a dash.
export const directionText = (direction) => `${direction} (no figure)`;
export const FX_NEEDED = "FX rate needed";
export const FX_SETTINGS_LABEL = "FX settings";
export const FX_SETTINGS_ANCHOR = "fx-settings";

/** "USD→EUR": the pair a claim in another currency needs a rate for, or null when it has none or needs none. */
export const fxPair = (c) => (c?.fx && c.currency && !c.unit && c.fx.rate == null && c.fx.currency ? `${c.currency}→${c.fx.currency}` : null);

/** What the missing-rate note says, "BRL→EUR rate missing – enter it in FX settings at the top of the page": the words
 *  "FX settings" are shown as a link to the audit's FX settings (FX_SETTINGS_LABEL). */
export const rateMissingText = (pair) => `${pair} rate missing – enter it in ${FX_SETTINGS_LABEL} at the top of the page`;

/** The rate behind a converted figure, for hover: "1 GBP = 1.14 EUR on 30 Jun 2026". Null when the claim is not converted. */
export function conversionHover(c) {
  if (!c?.fx || !c.currency || c.unit || c.fx.rate == null) return null;
  const on = displayDate(c.fx.date);
  return `Rate used: 1 ${c.currency} = ${figure(c.fx.rate)} ${c.fx.currency}${on ? ` on ${on}` : ""}`;
}

/** The claim's figure in the audit's currency, when it is stated in another one: "150,000 GBP (171,000 EUR)", whole units. The
 *  rate and its date are on hover (conversionHover), never in the row. No saved rate: "150,000 BRL (BRL→EUR rate missing – enter
 *  it in FX settings at the top of the page)". `fx` comes from the server with the claim. */
function withConversion(c, text, value, high) {
  if (!c.fx || !c.currency || c.unit || !present(value)) return text;
  if (c.fx.rate == null) return `${text} (${rateMissingText(fxPair(c) || c.currency)})`;
  return `${text} (${amount(c, value, high, c.fx.rate)})`;
}

/** "3,600,000 USD", "15%", "4.9x", "24 months", "2.5", "12,000,000–13,000,000 USD" for a range;
 *  "—" for a date-only claim. A table row lists its values by period:
 *  "200 (Y/E 22) · 5,000 (Y/E 23) · …". */
export function claimValue(c) {
  if (c?.by_period?.length) {
    return c.by_period.map((i) => `${withConversion(c, amount(c, i.value, i.value_high), i.value, i.value_high)} (${periodLabel(i, c) || PLACEHOLDER})`).join(" · ");
  }
  if (!present(c?.value) && c?.claim_direction) return directionText(c.claim_direction);
  return withConversion(c || {}, amount(c || {}, c?.value, c?.value_high), c?.value, c?.value_high);
}

const MONTH_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** One period in the formats of the Period column: "FY2023", "Q2 2024", "H1 2024", "Jun 2024", "30 Jun 2024". `target` is the
 *  stored target date ("2023", "2024-Q2", "2024-H1", "2024-06"); a month under a fiscal year ("FY2025-04") reads from
 *  the period's start date. Anything else is shown as the deck states it. */
export function periodLabel(v, c) {
  const target = v?.target_date || c?.target_date;
  if (!target) return v?.period_text || v?.period || "";
  const t = String(target);
  let m;
  if ((m = /^(\d{4})$/.exec(t))) return `FY${m[1]}`;
  if ((m = /^(\d{4})-Q([1-4])$/.exec(t))) return `Q${m[2]} ${m[1]}`;
  if ((m = /^(\d{4})-H([12])$/.exec(t))) return `H${m[2]} ${m[1]}`;
  if ((m = /^(\d{4})-(\d{2})$/.exec(t)) && Number(m[2]) >= 1 && Number(m[2]) <= 12) return `${MONTH_SHORT[Number(m[2]) - 1]} ${m[1]}`;
  if (/^FY\d{4}-\d{2}$/.test(t) && /^\d{4}-\d{2}/.test(v?.period_start || "")) {
    return `${MONTH_SHORT[Number(v.period_start.slice(5, 7)) - 1]} ${v.period_start.slice(0, 4)}`;
  }
  // A full date; one outside the range is never shown (no year 0001): the deck's own wording, else nothing.
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) return displayDate(t) || v?.period_text || "";
  return v?.period_text || t;
}

/** The Period column: a table row's first to last period, else the claim's period, each in one format
 *  ("FY2023", "Q2 2024", "Jun 2024"); "no date" only when the deck gives no period. The deck's own wording stays in the claim. */
export function claimPeriod(c) {
  const periods = (c?.by_period || []).map((v) => periodLabel(v, c)).filter(Boolean);
  const date = periods.length ? (periods.length > 1 ? `${periods[0]}–${periods[periods.length - 1]}` : periods[0]) : periodLabel(c, c);
  // "per year" read from a label's brackets ("Turnover (£/year)"): shown beside the date, or alone when the deck gives no year.
  // A basis of "per year" next to a year adds nothing; it stays only when no year is found.
  const basis = c?.period_basis === "per year" && date ? null : c?.period_basis;
  return [date, basis].filter(Boolean).join(" · ") || NO_DATE;
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

// The word the deck uses for the figure ("Turnover", "Revenue"), shown before it so two figures are never mistaken for one metric.
const figureText = (f) => {
  const n = present(f.value_high) ? `${figure(f.value)}–${figure(f.value_high)}` : figure(f.value);
  if (f.unit === "%") return `${f.label ? `${f.label} ` : ""}${n}%`;
  if (f.unit === "x") return `${f.label ? `${f.label} ` : ""}${n}x`;
  return [f.label, n, f.currency || f.unit].filter(Boolean).join(" ");
};
const placeText = (f) => sourceRef(f.source);

/** The sentence under the "Deck inconsistency" tag, built from the two figures the server compared:
 *  "The deck gives different figures for this metric: 5 at deck.pptx · slide 1 and 6 at deck.pptx · slide 4."
 *  A revenue-type figure names its deck label: "Turnover 550,508 GBP at deck.pdf · page 17 and Revenue 150,000 GBP at deck.pdf · page 19."
 *  A use-of-funds figure names its source, "text" or "chart", and a pair may carry a note, appended after a semicolon:
 *  "... text 40% at deck.pdf · page 22 and chart 42% at deck.pdf · page 22; chart excludes Marketing, rescaled."
 *  The parser pairs only figures whose values differ. Null when the server sent no pair, and
 *  then no tag is shown: a tag never stands without its explanation. */
export function inconsistencyText(c) {
  const pairs = c?.inconsistencies || [];
  if (!pairs.length) return null;
  return pairs.map(({ this: a, other: b, note }) => `The deck gives different figures for this metric: ${figureText(a)} at ${placeText(a)} and ${figureText(b)} at ${placeText(b)}${note ? `; ${note}` : ""}.`).join(" ");
}

// Model reading (docs/specs/llm-structure-reading.md): every row the model read carries one of these,
// and so does every mapping field it proposed. Python checked a Verified value against its source cell.
export const VERIFIED_LABEL = "Verified";
export const AI_SUGGESTION_LABEL = "AI suggestion, not verified";
export const STORED_MAPPING_LABEL = "Your confirmed mapping for these headers";

// Structure labelling (docs/specs/structure-labelling.md): Python reads every figure; an ambiguous one ("2.500",
// "Telegram(30K)") carries both readings with Python's default first, which is the row's value.
/** [{value, label, selected}] for a row whose figure reads two ways, the default first and pre-selected;
 *  [] when there is nothing to choose. Choosing the other reading is an Edit. */
export function readingChoices(c) {
  const readings = c?.readings || [];
  if (readings.length < 2) return [];
  return readings.map((r, i) => ({
    value: r.value,
    label: `${amount(c, r.value)} (${[r.dot_reading, r.bracket_reading].filter(Boolean).join(", ")})`,
    selected: i === 0,
  }));
}

// An item the model labelled "other", or a figure no heading names a type for ("unknown"), is listed under that type;
// the server approves it only once its type is edited to a claim type.
export const OTHER_TYPE_NOTE = "Choose a claim type, then approve.";
export const needsType = (c) => c?.claim_type === "other" || c?.claim_type === "unknown";

/** The Confidence column: "High", "Medium – not corroborated", "Low – no date, no heading". The server derives it from
 *  the checks the parser runs (never a model's own score); a row from an older server shows the placeholder. */
export const confidenceText = (c) => c?.confidence?.text || PLACEHOLDER;

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
  if (deck.ai_cost_usd) lines.push(`Cost: $${Number(deck.ai_cost_usd).toFixed(2)}`);
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

/** The claims shown under a tab, in the order the server sent them: ascending by slide or page, across all decks under
 *  "All", and within a page in reading order. A reviewed claim keeps its place. */
export function claimsForDeck(candidates, deckId) {
  return deckId === ALL_DECKS ? candidates || [] : (candidates || []).filter((c) => c.deck_id === deckId);
}

// The order of the claims table (docs/specs/deck-parser.md section 6): the group of the claim's type, set by the server, then
// slide or page. Groups 6 and 7 start collapsed under a header with their count.
export const CLAIM_GROUPS = [
  [1, "Revenue, ARR, MRR and bookings"], [2, "P&L items"], [3, "Customers, users, usage, retention and sales"],
  [4, "Hiring and roadmap"], [5, "Market size"], [6, UNKNOWN_TYPE_LABEL], [7, "Other"],
];
export const COLLAPSED_BY_DEFAULT = [6, 7];

/** [{group, title, claims, collapsed}] for the groups that hold a claim, in group order; the claims keep the server's order. */
export function claimSections(claims) {
  return CLAIM_GROUPS.map(([group, title]) => ({
    group, title, claims: (claims || []).filter((c) => (c.group ?? 7) === group), collapsed: COLLAPSED_BY_DEFAULT.includes(group),
  })).filter((s) => s.claims.length > 0);
}

/** Counts per status, for the list header. */
export function statusCounts(candidates) {
  const out = { pending: 0, approved: 0, rejected: 0, edited: 0 };
  (candidates || []).forEach((c) => { out[c.status] = (out[c.status] || 0) + 1; });
  return out;
}
