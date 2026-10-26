/**
 * Board deck upload: the scope message and the display strings for the candidate approval
 * list (docs/specs/deck-parser.md). Pure functions over the stored candidates.
 *
 * A candidate's value is a figure as the deck wrote it, not a computed metric, so it keeps
 * its decimals ("2.5", "13.72%") instead of going through format.js rounding.
 */
import { displayDate } from "./datePicker";
import evidenceLabels from "./evidence_labels.json";
import informationalFlags from "./informational_flags.json";
import listTexts from "./claims_list_texts.json";

export const PLACEHOLDER = "—";
export const NO_DATE = "no date";        // the Period column of a claim that states no date

export const DECK_ACCEPT = ".pptx,.pdf,.docx";
export const DECK_TYPE_REFUSED = "Only .pptx, .docx and .pdf files can be uploaded here.";
/** True when the file name ends in one of the accepted deck extensions. */
export const isDeckFile = (name) => DECK_ACCEPT.split(",").some((ext) => String(name).toLowerCase().endsWith(ext));

// Hover on the Extraction confidence column, word for word (docs/specs/evidence-labels.md section 1): how well the figure was read,
// never whether it is true. The same explainer heads the register's column (evidence_labels.json).
export const CONFIDENCE_HOVER = evidenceLabels.explainers.extraction_confidence;

// Shown above the upload button, word for word.
export const DECK_UPLOAD_HELP = "Board deck or growth plan: the company's board decks, investor updates, growth model or business plan, as PDF or PowerPoint. Up to 8 documents per audit. The audit reads the claims from them and tests each against the data files.";

// Shown on the upload screen, word for word from the spec.
export const DECK_SCOPE_INTRO = "Upload PowerPoint, Word and text-based PDF files.";
export const DECK_SCOPE_CANNOT_LEAD = "The app cannot read:";
export const DECK_SCOPE_CANNOT = [
  "Scanned PDFs, images or charts saved as pictures. There is no text in them to read, only pixels.",
  "Keynote files or Google Slides links. Please export them as PowerPoint or PDF first.",
];
export const DECK_SCOPE_OUTRO = "If a number you need sits in a picture, use Add claim and cite the page, or upload the source spreadsheet.";

// Shown above the approval list, word for word.
export const CLAIMS_HEADING = "Claims found in the uploaded documents";
export const CLAIMS_INTRO = "These figures were read from the uploaded documents and tested against the data automatically. Errors are possible: check only the claims that look incorrect or implausible against their source slides, or that wait for your answer.";
export const CLAIMS_CHOICES = [
  ["✓ Keep:", "Shown on a claim a check asks about: confirm this is a claim the company makes. It is then tested against the data and enters the claim register."],
  ["✎ Edit:", "Correct the figure, type, unit or date. The claim is tested again against the data."],
  ["✕ Reject:", "Exclude items that are not company claims, such as another company's figures, funds raised or chart axis labels. Rejected items remain in the record but are not used."],
];

// Add claim: a figure the analyst reads off a slide or page the parser could not read. The server tags it origin "analyst".
export const ADD_CLAIM_LABEL = "Add claim";
export const ADD_CLAIM_NEEDS_SOURCE = "Enter the value, choose the metric and the source document, and enter the page number.";
export const ANALYST_ADDED_TAG = "Added by analyst";
export const ANALYST_CONFIDENCE = "Analyst-entered";

// Acquisition channels (docs/specs/chat-upload.md section 17): one platform per claim, tested against no metric, so Add claim
// asks for the platform and not for a metric.
export const ACQUISITION_CHANNELS = "acquisition_channels";
export const ADD_CLAIM_PLATFORM_LABEL = "Platform (required)";

/** The POST body of Add claim from the form draft, or null while the source document or the page is missing, or the value is
 *  (the metric tested, or for acquisition channels the platform). */
export function newClaimPayload(draft) {
  const page = Number(draft.page);
  const channel = draft.claim_type === ACQUISITION_CHANNELS;
  if (!draft.deck_id || !Number.isInteger(page) || page < 1 || draft.value === "" || !draft.claim_type
      || (channel ? !(draft.label || "").trim() : !draft.metric)) return null;
  return {
    claim_type: draft.claim_type, ...(channel ? { label: draft.label.trim(), unit: "count" } : { metric: draft.metric }), deck_id: draft.deck_id, page,
    value: Number(draft.value), value_high: draft.value_high === "" ? null : Number(draft.value_high),
    ...(channel ? {} : { unit: draft.unit.trim() || null }), currency: channel || !draft.currency.trim() ? null : draft.currency.trim().toUpperCase(),
    target_date: draft.target_date.trim() || null,
  };
}

// Labels for every type a stored claim may carry; "usage" only on claims parsed before it was dropped. An item the model labelled
// other and a figure no heading names a type for are both Other (docs/specs/claim-types-and-correction.md section 4).
export const TYPE_LABELS = {
  revenue: "Revenue", arr: "ARR", mrr: "MRR", revenue_growth: "Revenue growth", growth: "Growth", retention: "Retention", churn: "Churn", nrr: "NRR", sales: "Sales",
  customers: "Customers", users: "Users", user_growth: "User growth", gross_margin: "Gross margin",
  gross_profit: "Gross profit", costs: "Costs", ebitda: "EBITDA", net_profit: "Net profit", usage: "Usage",
  people: "People", product: "Product", market: "Market size", cash: "Cash", burn: "Burn", runway: "Runway", ltv: "LTV",
  cac: "CAC", cac_payback: "CAC payback", customer_lifetime: "Customer lifetime", ltv_cac: "LTV/CAC", trials_per_day: "Trials per day",
  months_to_profitability: "Months to profitability", arpa: "ARPA", arpu: "ARPU", pipeline: "Pipeline", acquisition_channels: "Acquisition channels", use_of_funds: "Use of funds", pricing: "Pricing",
  installed_units: "Installed units",       // read from a forecast table only (chat-upload.md section 20), in no type list
  other: "Other",
  unknown: "Other",
};
// The types an analyst can choose: the names of backend app/decks/claims.py ANALYST_TYPES (CLAIM_TYPES and the five recurring types: ARR, MRR, Churn, NRR, CAC payback; engine contract 8).
// "Use of funds" is a type the model may read from a structure, not one the parser gives.
export const CLAIM_TYPES = Object.keys(TYPE_LABELS).filter((t) => !["usage", "use_of_funds", "pricing", "installed_units", "other", "unknown"].includes(t));
// The editor also offers Other: a figure typed Other leaves the register and is never a task (claim-types-and-correction.md 4).
export const OTHER_TYPES = ["other", "unknown"];
export const EDIT_TYPES = [...CLAIM_TYPES, "other"];
export const isOther = (c) => OTHER_TYPES.includes(c?.claim_type);
// Suggestions for the unit field; a count's unit is the noun it counts ("paying users").
export const CLAIM_UNITS = ["%", "x", "months", "years", "weeks", "days", "hours", "count", "customers", "users"];
// What the unit "count" stands for, shown beside it in the unit list; a currency stays in its own field.
export const COUNT_UNIT_HINT = "customers, headcount, deals";

// Types whose figure counts things: they carry the unit "count" (or the noun counted) and never a currency.
export const COUNT_TYPES = ["customers", "users", "people", "trials_per_day", "acquisition_channels", "installed_units"];
export const COUNT_UNIT = "count";

// One header per column of the approval list, in column order.
export const COLUMNS = ["Type", "Value", "Period", "Claim in the deck", "Source", "Extraction confidence", "Status", "Action"];

/** The pop-up of a heading (hover, or a tap on a phone): what the column holds and what its values mean. All texts: claims_list_texts.json. */
export const columnText = (name) => listTexts.columns[name] || "";

export const typeLabel = (t) => TYPE_LABELS[t] || t;

export const STATUS_LABELS = { pending: "Needs your attention", approved: "In the register", rejected: "Rejected", edited: "Edited" };

// The structure a model reading cites, by its type (docs/specs/deck-parser.md section 7).
export const STRUCTURE_NAMES = {
  table: "table", chart: "chart", kpi_panel: "KPI panel", roadmap: "roadmap", hiring_table: "hiring table",
  unit_economics: "unit-economics table", use_of_funds: "use-of-funds table",
};

/** "board.pptx · slide 5 · notes", "plan.pdf · page 19 · table 1, row 4, col 2", and for a model reading
 *  its cell: "plan.pdf · page 19 · table 1, cell r4c3", "plan.pdf · page 19 · KPI panel, cell r2c1". */
export function sourceRef(ref) {
  if (!ref) return PLACEHOLDER;
  if (ref.kind === "sheet") return `${ref.file} · ${ref.sheet}!${ref.cell}`;      // a forecast table's cell (chat-upload.md section 20)
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

/** What a screen reads where the stored results are of an older engine contract (George, 2026-10-20). */
export const STALE_LABEL = "Stale – re-run audit";

/** The rate behind a converted figure, for hover: "1 GBP = 1.14 EUR on 30 Jun 2026". Null when the claim is not converted. */
export function conversionHover(c) {
  if (!c?.fx || !c.currency || c.unit || c.fx.rate == null) return null;
  const on = c.fx.date_stale ? STALE_LABEL : displayDate(c.fx.date);
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

// A slide with a funds cue phrase and a word of another split (revenue, region, a run of years): its percentages stay Unknown.
export const MIXED_SLIDE_LABEL = "mixed slide – check";

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
// Deck-list badge texts only (George, 2026-10-21): the stored label stays as above; the badge says what Python did.
export const BADGE_MATCHED = "Matched to page";
export const BADGE_NOT_MATCHED = "AI suggestion, not matched";
export const badgeText = (label) => (label === VERIFIED_LABEL ? BADGE_MATCHED : label === AI_SUGGESTION_LABEL ? BADGE_NOT_MATCHED : label);
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

// The fields every claim holds besides its figure (docs/specs/claim-types-and-correction.md sections 1 to 3), as the editor offers
// them. Every select offers Unknown. Values are the server's.
export const FIGURE_TYPE_OPTIONS = [["actual", "Actual"], ["target", "Target"], ["unknown", "Unknown"]];
export const POPULATION_OPTIONS = {
  customers: [["paying", "Paying customers"], ["registered", "Registered users"], ["active", "Active users"]],
  users: [["paying", "Paying customers"], ["registered", "Registered users"], ["active", "Active users"]],
  user_growth: [["paying", "Paying customers"], ["registered", "Registered users"], ["active", "Active users"]],
  sales: [["deals won", "Deals won"], ["all closed", "All closed deals"], ["open", "Open deals"]],
};
export const GROWTH_TYPES = ["revenue_growth", "growth", "user_growth"];
export const GROWTH_BASIS_OPTIONS = [["mom", "MoM"], ["yoy", "YoY"], ["annualised", "Annualised"], ["cumulative", "Cumulative"], ["unknown", "Unknown"]];
export const EDIT_REASONS = [["parser_misread", "Parser misread the deck"], ["deck_context", "Deck context says otherwise"], ["other", "Other"]];
export const DEFAULT_EDIT_REASON = "parser_misread";
const FIELD_NAMES = { claim_type: "Type", value: "Value", value_high: "To (range)", unit: "Unit", currency: "Currency", target_date: "Period",
  by_period: "Values by period", population: "Population", figure_type: "Figure type", growth_basis: "Growth basis" };
const OPTION_LABELS = Object.fromEntries([...FIGURE_TYPE_OPTIONS, ...Object.values(POPULATION_OPTIONS).flat(), ...GROWTH_BASIS_OPTIONS]);

/** The figure type, population and growth basis the editor opens on: the stored value, else the one the register reads
 *  (`claim_fields`, sent by the server), else Unknown ("" for a population). */
export function claimFields(c) {
  const read = c?.claim_fields || {};
  return {
    figure_type: c?.figure_type || read.figure_type || "unknown",
    population: c?.population || read.population || "",
    growth_basis: c?.growth_basis || read.growth_basis || "unknown",
  };
}

const logValue = (field, v) => {
  if (v === null || v === undefined || v === "") return "Unknown";
  if (field === "claim_type") return typeLabel(v);
  if (Array.isArray(v)) return v.map((i) => i.value ?? "Unknown").join(", ");
  return OPTION_LABELS[v] || String(v);
};

/** The Status cell's hover: one line per edit, "Figure type: Target → Actual · analyst · 15 Oct 2026 · Parser misread the deck". */
export function editLogText(c) {
  const reasons = Object.fromEntries(EDIT_REASONS);
  return (c?.edit_log || []).map((e) => [`${FIELD_NAMES[e.field] || e.field}: ${logValue(e.field, e.previous)} → ${logValue(e.field, e.value)}`,
    e.by, displayDate(String(e.at || "").slice(0, 10)), reasons[e.reason] || e.reason].filter(Boolean).join(" · ")).join("\n");
}

// A line the analyst picked on the stored deck page (claim-types-and-correction.md section 5).
export const ADDED_FROM_DECK_TAG = "Added from deck by analyst";
export const VIEW_PAGE_LABEL = "View page";
export const ADD_FROM_DECK_LABEL = "Add from deck";

/** The Confidence column: "High", "Medium – not corroborated", "Low – no date, no heading". The server derives it from
 *  the checks the parser runs (never a model's own score); a row from an older server shows the placeholder. */
export const confidenceText = (c) => c?.confidence?.text || PLACEHOLDER;

const reasonOf = (word) => {
  const year = /^year label below: (\d{4})$/.exec(word);
  return year ? listTexts.year_label_below.replace("{year}", year[1]) : listTexts.reasons[word] || word;
};
/** The one-line plain reason under the confidence value, from the checks the server named in confidence.failed:
 *  "Medium – the period comes from the page heading, not from the figure's own label." Empty for a row without a confidence. */
export function confidenceReason(c) {
  const conf = c?.confidence;
  if (!conf) return "";
  if (!conf.level) return listTexts.reasons[conf.text] || "";
  if (!(conf.failed || []).length) return listTexts.reasons.High;
  return `${conf.level} – ${conf.failed.map(reasonOf).join("; ")}`;
}

/** The claim cell of the list: the type, with the segment when one is set, and the "part of <metric> <period> total" line of a part of a group. */
export function typeCellLines(c) {
  const segment = c?.made_of?.segment;
  return { title: segment ? `${typeLabel(c.claim_type)} · ${segment}` : typeLabel(c.claim_type), partOf: c?.made_of?.part_of || null };
}

// The deck panel's run log (docs/specs/llm-structure-reading.md sections 3, 4 and 9).
export const DECK_AI_STATUS = {
  reading: "reading", waiting: "waiting for revenue file", read: "read", not_read: "not read", stopped: "not read",
  python_only: "not read (AI-assisted reading is off for this audit)",
};
// Consent unticked (George, 2026-10-22, chat-upload.md section 28): since the page read replaced the rules read, such a deck lists no
// claim at all, so the one line says so and where to go. It stands alone, without the "AI reading:" prefix.
// A deck whose deck_reading prompt is not in the store (George, 2026-10-23, review of PR 164, M6): the one line, standing alone; the next Run audit reads the deck.
export const PROMPT_MISSING_LINE = "AI reading not run – deck_reading prompt missing in prompt store";
export const CONSENT_OFF_LINE = "Deck not read. AI-assisted reading is off for this audit, so no claims were extracted. Tick consent on the Upload page to read it, or use Add claim.";

/** The AI read's status in the deck line (George, 2026-10-23, chat-upload.md section 28): "waiting for revenue file", "queued", "page n of N"
 *  while the pages go, "done, n read, r rejected" after. It counts pages the model was sent and answered (read) or refused (rejected),
 *  never the pages of the file; a deck with consent off says so. */
export function aiReadStatus(deck) {
  switch (deck?.ai_status) {
    case "waiting": return DECK_AI_STATUS.waiting;
    case "reading": {
      const p = deck.read_progress;
      return p && p.total ? `page ${Math.min(p.done + 1, p.total)} of ${p.total}` : deck.ai_message === "restarted" ? "restarted" : "queued";
    }
    case "python_only": return "not run (AI-assisted reading is off)";
    case "read": case "not_read": case "stopped": case "prompt_missing":
      return `done, ${deck.pages_read || 0} read, ${deck.pages_rejected || 0} rejected`;
    default: return deck?.ai_status || "";
  }
}

/** "N pages parsed · M with figures · AI read: <status>". The page count is the file's, parsed, never "read". */
export function deckReadLine(deck) {
  return `${deck.pages} ${deck.page_unit || "page"}s parsed · ${deck.figure_pages} with figures · AI read: ${aiReadStatus(deck)}`;
}

/** The upload row's text: the one it got at upload, until the stored deck of a page read is known; then the same line the panel shows
 *  (George, 2026-10-23: the row said "queued" while the panel said "done"). */
export function uploadLineText(line, decks) {
  const stored = line.deckId && (decks || []).find((d) => d.deck_id === line.deckId);
  return stored?.ai_status && stored.pages && stored.figure_pages != null ? `done · ${deckReadLine(stored)}` : line.text;
}

/** ["AI reading: read", "Sent to the model: slides 4, 7, 12"] for one deck (no cost: usage-and-allowance.md section 9); the stop
 *  message when the audit reached its token limit; how many of the model's periods Python replaced
 *  with the one its header cells give. */
export function deckRunLog(deck) {
  if (!deck?.ai_status) return [];
  // The server sends the S26 line with a deck the page read left unread; under DECK_PIPELINE=rules the rules read still lists claims, so the old line stands (L5).
  if (deck.ai_status === "python_only" && deck.ai_message) return [deck.ai_message];
  if (deck.ai_status === "prompt_missing") return [deck.ai_message || PROMPT_MISSING_LINE];
  const lines = [deck.figure_pages != null && deck.pages ? deckReadLine(deck) : `AI reading: ${deck.ai_status === "reading" && deck.ai_message === "restarted" ? "restarted" : DECK_AI_STATUS[deck.ai_status] || deck.ai_status}`];
  if (deck.skipped_pages?.length) lines.push(`Skipped the following pages (${deck.skipped_pages.join(", ")}) – no figures relevant for the audit`);
  if (deck.ai_status !== "reading") for (const n of deck.unread_pages || []) lines.push(`page ${n} not read`);
  if (deck.ai_status === "stopped" && deck.ai_message) lines.push(deck.ai_message);
  if (deck.sent_pages?.length) lines.push(`Sent to the model: ${deck.page_unit || "slide"}s ${deck.sent_pages.join(", ")}`);
  if (deck.periods_corrected) lines.push(`Periods corrected from the header cells: ${deck.periods_corrected}`);
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

/** [{id, label, count}]: "All" first, then each deck in the order it was uploaded, left to right (a new deck on the right), with its claim count. */
export function deckTabs(decks, candidates) {
  const count = (id) => (candidates || []).filter((c) => c.deck_id === id).length;
  const ordered = [...(decks || [])].sort((a, b) => String(a.uploaded_at || "").localeCompare(String(b.uploaded_at || "")));
  return [{ id: ALL_DECKS, label: "All", count: (candidates || []).length },
    ...ordered.map((d) => ({ id: d.deck_id, label: d.file, count: count(d.deck_id) }))];
}

/** The claims shown under a tab, in the order the server sent them: ascending by slide or page, across all decks under
 *  "All", and within a page in reading order. A reviewed claim keeps its place. */
export function claimsForDeck(candidates, deckId) {
  return deckId === ALL_DECKS ? candidates || [] : (candidates || []).filter((c) => c.deck_id === deckId);
}

// The two views of the claims table (George, 2026-10-22, docs/design/ai-reads-rules-check.md): a claim the checks flagged
// (`flags`: closed words from the server's checker, e.g. "currency assumed") is listed under Review, never in the main list; a
// flag never deletes or retypes a claim. The analyst keeps, edits or rejects it there as anywhere else.
export const CLAIMS_VIEW = "claims";
export const REVIEW_VIEW = "review";
export const VIEW_LABELS = { [CLAIMS_VIEW]: "Claims", [REVIEW_VIEW]: "Review" };
export const REVIEW_INTRO = "Flagged by the checks: the figure, its unit, its label or its page could not be confirmed on the slide. Each flag names what to check.";
// An informational flag (George, 2026-10-23: "cell corrected") is a note on the row; the claim stays in the main list. The list is the
// server's (checker.INFORMATIONAL_FLAGS); a backend test keeps the two equal.
// "year label below: 2022" (George, 2026-10-23) is informational too: the list carries its pattern, the flag has a year in it.
export const INFORMATIONAL_FLAGS = informationalFlags.flags;
const INFORMATIONAL_PATTERNS = informationalFlags.patterns.map((p) => new RegExp(p));
export const isInformational = (f) => INFORMATIONAL_FLAGS.includes(f) || INFORMATIONAL_PATTERNS.some((rx) => rx.test(f));
export const isFlagged = (c) => (c?.flags || []).some((f) => !isInformational(f));

/** The claims of one view: the flagged ones under Review, the rest under Claims; the server's order is kept. */
export function claimsForView(claims, view) {
  return (claims || []).filter((c) => isFlagged(c) === (view === REVIEW_VIEW));
}

/** Corrections a check made or offers (claim-matching.md section 33): `corrections` [{field, reason, original, corrected, state, options}] on a
 *  claim; an applied one reads "Corrected: period 2023 → 2022" with Undo, one that waits is a button per candidate on the card. */
const withIndex = (c, state) => (c?.corrections || []).map((e, index) => ({ ...e, index })).filter((e) => e.state === state);
export const appliedCorrections = (c) => withIndex(c, "applied");
export const waitingCorrections = (c) => withIndex(c, "choose");
export const correctionText = (e) => `Corrected: ${e.field} ${e.original ?? "none"} → ${e.corrected}`;
export const UNDO_LABEL = "Undo";
export const DIAGNOSTICS_DECK_HEADING = "Deck reading";
/** The Diagnostics lines of the decks' page reads (claim-matching.md section 33): what a check corrected, with the original and the corrected
 *  value, and the claims that never entered the register ("derived figure, not a claim", "launch date without product name"). */
export function diagnosticLines(decks) {
  return (decks || []).flatMap((d) => (d.diagnostics || []).map((x) => {
    const where = `${d.file} · ${d.page_unit === "slide" ? "slide" : "page"} ${x.page}`;
    if (x.kind === "corrected") return `${where}: corrected ${x.field}, ${x.original ?? "none"} → ${x.corrected} (${x.reason})`;
    return `${where}: ${x.kind}${x.metric ? ` · ${x.metric}` : ""}${x.value != null ? ` ${x.value}` : ""}${x.period ? ` · ${x.period}` : ""}`;
  }));
}
export const KEEP_ALL_LABEL = "Keep all";
/** The rows "Keep all" keeps: the section's claims a check asks about (pending, flagged), never an Other figure. */
export const keepAllRows = (claims) => (claims || []).filter((c) => c.status === "pending" && !isOther(c) && isFlagged(c));
export const POPULATION_QUESTION = "Are these paying customers or registered users?";
export const POPULATION_ANSWERS = [["paying", "Paying customers"], ["registered", "Registered users"]];
/** Whether a reason of the register is the question about the population alone ("required field unknown: population; set it ..."). */
export const asksPopulationOnly = (reason) => /^required field unknown: population;/.test(reason || "");

/** "currency assumed · scenario label not on page": the flags of a claim, as the checker wrote them. */
export const LABEL_MISMATCH_FLAG = "label mismatch";
export const LABEL_MISMATCH_QUESTION = listTexts.label_mismatch_question;
// The closed word of the server stays; the screen asks the question (George, 2026-10-26).
export const flagsText = (c) => (c?.flags || []).map((f) => (f === LABEL_MISMATCH_FLAG ? LABEL_MISMATCH_QUESTION : f)).join(" · ");

// The order of the claims table (docs/specs/deck-parser.md section 6): the group of the claim's type, set by the server, then
// slide or page. Other starts collapsed under its count (claim-types-and-correction.md section 4).
// Acquisition channels and Use of funds are sections of their own, directly above Other (chat-upload.md section 17).
export const OTHER_GROUP = 9;
// A best-case or worst-case figure is no plan target: it is listed in its own section above Other, whatever its type, and enters the register
// as Unverified (George, 2026-10-23, review of PR 164, H2). The server puts such a claim in this group.
export const SCENARIO_GROUP = 6;
// Pricing (group 10) and Use of funds start collapsed and are listed after Market size and before Other (George, 2026-10-23).
export const PRICING_GROUP = 10;
export const CLAIM_GROUPS = [
  [1, "Revenue, ARR, MRR and bookings"], [2, "P&L items"], [3, "Customers, users, usage, retention and sales"],
  [4, "Hiring and roadmap"], [5, "Market size"], [PRICING_GROUP, "Pricing"], [7, "Acquisition channels"], [8, "Use of funds"],
  [SCENARIO_GROUP, "Scenarios"], [OTHER_GROUP, "Other"],
];

/** Whether a claim is a best or worst case (the page reader's `scenario`). */
export const isCase = (c) => c?.scenario === "best" || c?.scenario === "worst";
const CASE_WORDS = { best: "Best case", realistic: "Realistic case", worst: "Worst case" };
/** "Best case", "Realistic case", "Worst case"; empty for a claim that names no case. */
export const scenarioText = (c) => CASE_WORDS[c?.scenario] || "";
export const COLLAPSED_BY_DEFAULT = [8, OTHER_GROUP, PRICING_GROUP];

/** "1 other figure", "3 other figures": the header of the Other section, which has no review count. */
export const otherFiguresTitle = (n) => `${n} other figure${n === 1 ? "" : "s"}`;

/** [{group, title, claims, collapsed}] for the groups that hold a claim, in group order; the claims keep the server's order. */
export function claimSections(claims) {
  return CLAIM_GROUPS.map(([group, title]) => ({
    group, title, claims: (claims || []).filter((c) => (c.group ?? OTHER_GROUP) === group), collapsed: COLLAPSED_BY_DEFAULT.includes(group),
  })).filter((s) => s.claims.length > 0).map((s) => (s.group === OTHER_GROUP ? { ...s, title: otherFiguresTitle(s.claims.length) } : s));
}

/** Counts per status, for the list header; `auto` is how many of the claims in the register Python entered on its own (simplified-flow.md
 *  section 2). Other figures are not claims and are not counted. */
export function statusCounts(candidates) {
  const out = { pending: 0, approved: 0, rejected: 0, edited: 0, auto: 0 };
  (candidates || []).filter((c) => !isOther(c)).forEach((c) => {
    out[c.status] = (out[c.status] || 0) + 1;
    if (c.status === "approved" && c.auto_accepted) out.auto += 1;
  });
  return out;
}

/** "1 needs your attention · 3 in the register (2 auto) · 1 edited · 0 rejected"; the bracket is left out when Python entered none. */
export const countLine = (counts) =>
  `${counts.pending} need${counts.pending === 1 ? "s" : ""} your attention · ${counts.approved} in the register${counts.auto > 0 ? ` (${counts.auto} auto)` : ""} · ${counts.edited} edited · ${counts.rejected} rejected`;

/** The status cell of a claim: "Entered by the app" for a claim Python entered on its own, else the status; a claim re-opened because a check
 *  now asks about it carries its note ("Re-opened – a check now asks about it"). */
export const statusText = (c) =>
  (c.status === "approved" && c.auto_approval && "Entered by the app") || (c.status === "pending" && c.auto_note) || STATUS_LABELS[c.status] || c.status;
