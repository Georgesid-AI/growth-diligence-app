/**
 * The reading screen's words and shapes (docs/design/read-check-review.md section 11, docs/design/audit-page-mockup.html; PR 3 step d).
 * Pure functions over the register the server sends (GET /audits/{id}/reading). Every number goes through lib/format.js (section 11.5).
 */
import { PLACEHOLDER, fmtCount, fmtCurrency, fmtPct } from "./format";
import { monthName } from "./periods";


/** Hover text on every heading (section 11.3 and the mockup): a table cannot be drawn without it, and a test walks every table for it. */
export const HOVERS = {
  lines: {
    Line: "The row label as it stands in the file, in file order. A rate row is shown under the line it refers to.",
    "Interpreted as": "What the whole row was interpreted as: revenue, bookings, ARR, MRR, churn rate, customers, forecast, variance, other.",
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
    Row: "What the whole row or table was interpreted as: revenue, bookings, ARR, churn rate, customers, forecast, variance, other.",
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
/** The deck tab's full figures list (docs/design/audit-page-mockup.html): every figure read from the deck, with its page and outcome. */
export const FIGURE_HOVERS = {
  Metric: "What the figure measures.",
  Value: "The number as the reader took it from the page; the full value is kept.",
  Period: "The month, quarter or year it belongs to; a dash when the figure's own line or column names none.",
  Label: "The label printed with the figure on the page, as the reader took it.",
  Page: "The deck page the figure was read from.",
  Outcome: "Matches source, Doesn't match source or Needs attention, after code compared the value with the page text.",
};
export const FIGURE_WIDTHS = [22, 14, 14, 26, 8, 16];

export const NUMERIC = { lines: [], confirmed: ["Value"], rejected: ["Reading says", "Cell holds"], cannot_check: ["Value"] };
export const TITLES = { confirmed: "Matches source", rejected: "Doesn't match source", uncertain: "Uncertain", cannot_check: "Needs attention" };
/** The one line under each category's heading (brief of George, 2026-11-05, item 8). */
export const EXPLAIN = {
  confirmed: "The figure was found in the file or on the page.",
  rejected: "The file or page shows a different value.",
  uncertain: "The two readings disagree; pick one. Until you do, the item is left out of all metrics and ratings.",
  cannot_check: "The app cannot check this by itself (a date, no comparable cell). Nothing is excluded; you decide if it matters.",
};

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
      { bold: fmtCount(s.confirmed), text: ` ${s.confirmed === 1 ? "figure matches" : "figures match"} source` },
      { text: `${fmtCount(s.rejected)} ${s.rejected === 1 ? "doesn't" : "don't"} match source` },
      { text: `${fmtCount(s.cannot_check)} ${s.cannot_check === 1 ? "needs" : "need"} attention` },
      { text: "actual to ", bold: lastActualText(s.last_actual, s.granularity) },
    ],
    [...maskingLine(s), { text: plural(s.row_labels_coded ?? 0, "row label coded", "row labels coded") }],
  ];
}

/** The three summary lines of a deck block: the pages; the figures, "confirmed on the page they cite"; the masking. */
export function deckSummary(s, figures) {
  const pages = s.pages ?? 0;
  const skipped = s.skipped_pages || [];
  const read = Math.max(pages - skipped.length, 0);
  const first = [{ text: plural(pages, "page", "pages") }, { text: `${plural(read, "page", "pages")} processed` }];
  if (skipped.length) {
    first.push({ text: `${plural(skipped.length, "page", "pages")} skipped (no digits in ${skipped.length === 1 ? "its" : "their"} text: ${skipped.join(", ")})` });
  }
  const f = figures || { read: 0 };
  return [
    first,
    [
      { bold: fmtCount(f.read), text: ` ${f.read === 1 ? "figure" : "figures"} read` },
      { bold: fmtCount(s.confirmed), text: " match the page they cite" },
      { text: `${fmtCount(s.rejected)} ${s.rejected === 1 ? "doesn't" : "don't"} match source` },
      { text: `${fmtCount(s.cannot_check)} ${s.cannot_check === 1 ? "needs" : "need"} attention${s.cannot_check ? " (charts without text)" : ""}` },
    ],
    maskingLine(s),
  ];
}

export const OUTCOME_LABELS = TITLES;

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

const colNumber = (letters) => [...letters].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);
const colLetters = (n) => { let out = ""; for (let k = n; k > 0; k = Math.floor((k - 1) / 26)) out = String.fromCharCode(65 + ((k - 1) % 26)) + out; return out; };

/** The Actual / plan cell of a line: the reading's "mixed, boundary D" is shown as "actuals through column D, plan from E" (the column after). */
export function actualPlanText(value) {
  const m = /^mixed, boundary ([A-Z]+)$/.exec(value || "");
  const next = m ? colNumber(m[1]) + 1 : 0;
  return m ? `actuals through column ${m[1]}, plan from ${colLetters(next)}` : value;
}

/** "Reading uncertain – confirm" (docs/design/reading-consistency.md): the label of an item the two reads of a file or a page disagree on. */
export const UNCERTAIN_LABEL = "Reading uncertain – confirm";
/** The words of one candidate of an uncertain item, from its closed fields; "not in this reading" when the read gave nothing. */
export function candidateText(item, side) {
  const c = item[side];
  if (item.kind === "row") {
    if (!c) return "not in this reading";
    // A unit, currency or basis the reads disagree on is named with its value, so two readings of one role are told apart (2026-11-05).
    const named = (item.fields || []).filter((f) => ["unit", "currency", "basis"].includes(f)).map((f) => `${f} ${c[f] ?? "none"}`);
    return [c.role, c.metric, c.cells, c.scenario ? `scenario ${c.scenario}` : c.segment ? "a segment" : null, c.parent_row ? `part of row ${c.parent_row}` : null, ...named].filter(Boolean).join(" · ");
  }
  return c == null ? "not in this reading" : String(c);
}
/** The title of an uncertain item: a row, a sheet-level field or a whole sheet. */
export function uncertainTitle(item) {
  if (item.kind === "row") return `${item.sheet}, row ${item.row}${item.fields?.length ? ` (${item.fields.join(", ")} differ)` : ""}`;
  if (item.kind === "field") return `${item.sheet}: ${item.field}`;
  return `Sheet ${item.sheet}`;
}

// ---------------------------------------------------------------------------
// The Uncertain list (brief of George, 2026-11-05, items 9 and 10): one line per item, the differing fields only, in plain words.
// ---------------------------------------------------------------------------
export const UNCERTAIN_TITLE = "Uncertain";
const FIELD_WORDS = { role: "role", metric: "metric", series: "series", plan_series: "plan series", parent_row: "parent row", unit: "unit", currency: "currency",
  basis: "basis", row: "row", period: "period", value: "value" };
export const fieldWord = (f) => FIELD_WORDS[f] || String(f).replace(/_/g, " ");

/** "row 4", "rows 6–9" (three or more in a run), "rows 6, 8": the row numbers an item covers. */
export function rowsText(item) {
  const rows = [...new Set(item.rows?.length ? item.rows : [item.row])].sort((a, b) => a - b);
  if (rows.length === 1) return `row ${rows[0]}`;
  const parts = [];
  for (let i = 0; i < rows.length;) {
    let j = i;
    while (j + 1 < rows.length && rows[j + 1] === rows[j] + 1) j += 1;
    if (j - i >= 2) parts.push(`${rows[i]}–${rows[j]}`); else for (let k = i; k <= j; k += 1) parts.push(String(rows[k]));
    i = j + 1;
  }
  return `rows ${parts.join(", ")}`;
}

const SERIES = ["series", "plan_series"];
const figure = (v) => (v == null ? "none" : fmtCount(v));

/** "2021-03: 12,000 / 12,500 · 3 of 30 periods differ": the first period where the two reads differ with both values, and how many differ. */
export function seriesDiffText(d) {
  return `${d.period}: ${figure(d.first)} / ${figure(d.second)} · ${d.differing} of ${d.total} period${d.total === 1 ? "" : "s"} differ`;
}

const rowValue = (item, c, f, side) => {
  const d = SERIES.includes(f) ? item.series_diff?.[f] : null;
  if (d) return `${d.period}: ${figure(d[side])}`;
  if (SERIES.includes(f)) return "different values";         // never the bare period count (combined fixes, 2026-11-05)
  return c[f] ?? "none";
};

/** The words of one reading of an item: only the fields that differ, each named ("role arr · parent row 5"); "not in this reading" when the read gave nothing. */
export function readingsText(item, side) {
  const c = item[side];
  if (item.kind === "figure") return (item.fields || []).map((f) => `${fieldWord(f)} ${c?.[f] ?? "none"}`).join(" · ") || "not in this reading";
  if (item.kind !== "row") return c == null ? "not in this reading" : String(c);
  if (!c) return "not in this reading";
  if ((item.fields || []).includes("row")) return [c.role, c.metric, c.cells].filter(Boolean).join(" · ");
  return (item.fields || []).map((f) => `${fieldWord(f)} ${rowValue(item, c, f, side)}`).join(" · ");
}

/** What differs, in plain words: "role, parent row". */
export function differsText(item) {
  if (item.kind === "row" || item.kind === "figure") {
    return (item.fields || []).map((f) => (item.series_diff?.[f] ? `${fieldWord(f)} (${seriesDiffText(item.series_diff[f])})` : fieldWord(f))).join(", ");
  }
  return item.kind === "field" ? item.field : "sheet";
}

/** The label text of a row item from the lines the screen holds for its file: "Net revenue", or "Line 6; Line 7; Line 8; …" for a run of rows (three at most); "" when none. */
export function rowLabels(item, file) {
  const lines = (file?.lines || []).find((l) => l.sheet === item.sheet)?.lines || [];
  const rows = [...new Set(item.rows?.length ? item.rows : [item.row])].sort((a, b) => a - b);
  const labels = rows.map((n) => lines.find((l) => l.row === n)?.label).filter(Boolean);
  return labels.length ? `${labels.slice(0, 3).join("; ")}${labels.length > 3 ? "; …" : ""}` : "";
}

/** The "Row or figure" of a spreadsheet item: "Sales, rows 6–9 · Line 6; …" (the labels when `file` holds them); of a layout item, the field. */
export function whereText(item, file) {
  if (item.kind === "row") {
    const labels = rowLabels(item, file);
    return `${item.sheet}, ${rowsText(item)}${labels ? ` · ${labels}` : ""}`;
  }
  if (item.kind === "field") return `${item.sheet}: ${item.field}`;
  return `Sheet ${item.sheet}`;
}

/** A deck figure as the list names it: "170,044 EUR, 2019 · page 11, cell r4c2" - its value and period beside the page and cell, whatever field differs. */
export function figureWhere(fig) {
  const named = fig.currency || (["money", "count", "rate"].includes(fig.unit) ? "" : fig.unit || "");        // a currency, else a unit the deck prints (%, x, days...)
  const value = fig.value == null ? "" : `${fmtCount(fig.value)}${named === "%" ? "%" : named ? ` ${named}` : ""}`;
  const head = [value, fig.period].filter(Boolean).join(", ") || fig.metric;
  return `${head} · page ${fig.page ?? "?"}${fig.cell ? `, cell ${fig.cell}` : ""}`;
}

/** The Uncertain list of the whole audit: one entry per spreadsheet item and per deck figure that waits, in file order. */
export function uncertainEntries(files) {
  const out = [];
  for (const f of files || []) {
    if (f.kind === "sheet") {
      for (const item of f.consistency?.uncertain || []) out.push({ id: `${f.file_hash}:${item.key}`, file: f.file, fileLabel: f.file, where: whereText(item, f), item, fileHash: f.file_hash, kind: "sheet" });
    } else if (f.kind === "deck") {
      for (const fig of f.figures || []) {
        if (!fig.uncertain || !fig.reading) continue;
        const [one, two] = fig.reading.details || [];
        const fields = ["metric", "value", "period"].filter((k) => (one?.[k] ?? null) !== (two?.[k] ?? null));
        const item = { kind: "figure", fields, first: one || null, second: two || null };
        out.push({ id: `${f.deck_id}:${fig.id}`, file: f.file, fileLabel: `${f.file} · page ${fig.page ?? "?"}`, where: figureWhere(fig), item, figure: fig, kind: "deck" });
      }
    }
  }
  return out;
}
