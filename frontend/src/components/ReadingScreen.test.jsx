import React, { act } from "react";
import { createRoot } from "react-dom/client";

import ReadingScreen, { ReadingTop } from "./ReadingScreen";
import * as api from "@/lib/api";
import { HOVERS, WIDTHS } from "@/lib/readingView";
import fs from "fs";
import path from "path";

/**
 * The reading screen (docs/design/read-check-review.md section 11, docs/design/audit-page-mockup.html; PR 3 step d), on a synthetic register. Run with
 * --no-cache (rule 25).
 */
jest.mock("@/lib/api", () => ({
  getReading: jest.fn(), decideCard: jest.fn(), changeReading: jest.fn(), getCell: jest.fn(), getDeckPage: jest.fn(), downloadReading: jest.fn(),
  getAudit: jest.fn(), updateAudit: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const all = (id) => [...document.body.querySelectorAll(`[data-testid="${id}"]`)];
let host, root;

const AUDIT = { id: "a1", reporting_currency: "EUR", fiscal_year_end: 12, as_of_month: "2022-05-31", as_of_by: "detected", as_of_file: "revenue.xlsx",
  as_of_evidence: "customers row 23 stops at AP (confirmed on sheet Sales, column AP)", datasets: { revenue: { months: { first: "2019-01", last: "2022-05" } } } };

const src = (cell, extra = {}) => ({ file: "revenue.xlsx", file_hash: "h1", sheet: "Sales", cell, ...extra });
const line = (row, label, over = {}) => ({ row, label, read_as: "revenue", basis: "monthly", actual_plan: "mixed, boundary AP", cells: `B${row}:AW${row}`, indent: 0, moved: false,
  role: "revenue", parent_row: null, ...over });
const REGISTER = {
  files: [
    { kind: "sheet", file: "revenue.xlsx", file_hash: "h1", size: 61440,
      summary: { period_columns: 48, rows_mapped: 41, last_actual: "2022-05", granularity: "monthly", confirmed: 37, rejected: 1, cannot_check: 1, personal_removed: 0, company_coded: 0 },
      anchors: { as_of: { month: "2022-05", evidence: "customers row 23 stops at AP (confirmed on sheet Sales, column AP)" },
                 revenue_row: { sheet: "Sales", row: 11, label: "Recognised revenue", basis: "monthly" }, actual_plan: { sheet: "Sales", last_actual: "AP", plan_from: "AQ" } },
      lines: [{ sheet: "Sales", lines: [
        line(11, "Recognised revenue"),
        line(3, "revenue growth rate", { read_as: "growth rate", basis: "rate", indent: 1, moved: true, role: "growth_rate" }),
        line(14, "MRR from annual subscriptions", { read_as: "MRR, part of row 11", indent: 1, parent_row: 11, role: "mrr" }),
        line(15, "Annual, enterprise", { read_as: "MRR, part of row 14", indent: 2, parent_row: 14, role: "mrr" }),
        line(23, "Total clients", { read_as: "customers", role: "customers" }),
      ] }] },
    { kind: "deck", file: "Board report.pdf", deck_id: "d1", pages: 20,
      summary: { pages: 20, pages_with_figures: 15, confirmed: 15, rejected: 0, cannot_check: 3, personal_removed: 1, company_coded: 17, skipped_pages: [1, 2, 7] },
      anchors: { figures: { read: 112, found_on_page: 109, from_image: 3 } },
      figures: [
        { key: "f1", metric: "arr", value: 0.045, unit: "rate", currency: null, period: "2021", label: "Closing ARR", page: 3, outcome: "confirmed" },
        { key: "f2", metric: "mrr", value: 2500, unit: "money", currency: "EUR", period: null, label: null, page: 8, outcome: "cannot_check" },
      ] },
  ],
  tables: {
    confirmed: [
      { key: "k1", kind: "figure", metric: "revenue", value: 78829.4, unit: "money", currency: "EUR", period: "2022-05", basis: "monthly", actual_plan: "actual",
        row_role: "revenue", source: src("AP11"), note: "set by analyst", set_at: "2026-10-31", hover: "value set by analyst; the check did not confirm it" },
      { key: "k2", kind: "deck_figure", metric: "arr", value: 0.045, unit: "rate", currency: null, period: "2021", basis: null, actual_plan: "actual", row_role: null,
        source: { file: "Board report.pdf", deck_id: "d1", page: 3 }, note: null },
    ],
    rejected: [
      { key: "k3", kind: "figure", metric: "arr", value: 447223.43, unit: "money", currency: "EUR", period: "2022-04", cell_value: 398736, cell_period: "2022-04",
        reason: "Reading says 447223; cell AO13 holds 398736.", reread: "repeats the first reading", action: "card", card_id: "c1", source: src("AO13") },
    ],
    cannot_check: [
      { key: "k4", kind: "figure", metric: "mrr", value: 2500, unit: "money", currency: "EUR", period: "2021-01", reason: "Page 8 has no text layer; figure read from the image.",
        used_in: "MRR series", source: { file: "Board report.pdf", deck_id: "d1", page: 8 } },
    ],
  },
  counts: { confirmed: 2, rejected: 1, cannot_check: 1 },
  cards: [{ id: "c1", kind: "citation_failed_twice", status: "open", title: "The reader and the file disagree", subject: { metric: "ARR", period: "2022-04" },
    actions: ["use_cell", "use_reader", "type_value"], source: src("AO13"),
    reader: { label: "Reader, twice", value: 447223.43, unit: "money", currency: "EUR", period: "2022-04", evidence: "April update ARR as stated on page 20" },
    other: { label: "Cell AO13", value: 398736, unit: "money", currency: "EUR", period: "2022-04", evidence: null } }],
  review: {},
};

async function show(register = REGISTER, audit = AUDIT) {
  api.getReading.mockResolvedValue(register);
  api.getAudit.mockResolvedValue(audit);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<ReadingScreen audit={audit} setAudit={() => {}} />); });
  await act(async () => { await Promise.resolve(); });
}
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); jest.clearAllMocks(); });

describe("the strip and the file blocks", () => {
  test("the strip has the currency, the period, the as-of month with Change and the FY end; the evidence line has Confirmed on in green", async () => {
    await show();
    expect(q("assumption-currency").textContent).toBe("CurrencyEUR");
    expect(q("assumption-period").textContent).toBe("Reporting periodJan 2019 – May 2022");
    expect(q("assumption-as-of").textContent).toBe("As-of monthMay 2022 Change");
    expect(q("assumption-fy-end").textContent).toBe("FY endDecember");
    expect(q("assumption-as-of-evidence").textContent).toContain("Confirmed on column AP.");
    expect(q("assumption-as-of-evidence").querySelector("b").textContent).toBe("Confirmed on column AP.");
  });

  test("the reporting period reads the first and last actual month across the files, and is never a dash while an as-of month exists", async () => {
    await show({ ...REGISTER, period: { first: "2019-01", last: "2022-05" } }, { ...AUDIT, datasets: {} });
    expect(q("assumption-period").textContent).toBe("Reporting periodJan 2019 – May 2022");
    await act(async () => { root.unmount(); }); host.remove();
    await show(REGISTER, { ...AUDIT, datasets: {} });
    expect(q("assumption-period").textContent).toBe("Reporting periodMay 2022");
  });

  test("a row-level check outcome is a note on its row in the lines table; a file-level one is a note under the summary", async () => {
    const files = REGISTER.files.map((f, i) => (i ? f : { ...f, notes: [{ name: "Period columns", outcome: "cannot_check", reason: "header unclear" }],
      lines: [{ sheet: "Sales", lines: [line(11, "Recognised revenue", { note: "segment row without its total row" })] }] }));
    await show({ ...REGISTER, files });
    expect(q("line-11").querySelector('[data-testid="line-note"]').textContent).toContain("segment row without its total row");
    expect(q("file-note").textContent).toBe("Period columns: header unclear");
  });

  test("a spreadsheet block reads in the mockup's words: the number first, the masking counts on a line of their own, Last actual and not As-of month", async () => {
    await show();
    const [sheet, deck] = all("file-block");
    expect(sheet.querySelector("h2").textContent).toBe("revenue.xlsx 60 KB");
    expect([...sheet.querySelectorAll('[data-testid="file-summary"]')].map((p) => p.textContent)).toEqual([
      "48 month columns · 41 rows mapped · 37 figures confirmed · 1 rejected · 1 cannot check · actual to May 2022",
      "0 personal items removed · 0 company names coded"]);
    expect(sheet.querySelector('[data-testid="file-summary"] b').textContent).toBe("37");
    expect(sheet.querySelector(".anchors .k").textContent).toBe("Last actual");
    expect(sheet.querySelector(".anchors").textContent).not.toContain("As-of month");
    expect(sheet.querySelector('[data-testid="anchor-as-of"]').textContent).toMatch(/^May 2022 — /);
    expect(sheet.querySelector('[data-testid="anchor-revenue"]').textContent).toBe("Row 11, Recognised revenue, monthly");
    expect(sheet.querySelector('[data-testid="anchor-boundary"]').textContent).toBe("Actual to column AP, plan from AQ");
    expect([...sheet.querySelectorAll(".anchors a")].map((a) => a.textContent)).toEqual(["Change", "Change", "Change"]);
    expect(sheet.querySelector("summary").textContent).toBe("Show all lines");
    expect([...deck.querySelectorAll('[data-testid="file-summary"]')].map((p) => p.textContent)).toEqual([
      "20 pages · 17 pages read · 3 pages skipped (no digits in their text: 1, 2, 7)",
      "112 figures read · 15 confirmed on the page they cite · 0 rejected · 3 cannot check (charts without text)",
      "1 personal item removed · 17 company names coded"]);
    expect([...deck.querySelectorAll('[data-testid="file-summary"]')[1].querySelectorAll("b")].map((b) => b.textContent)).toEqual(["112", "15"]);
    expect(deck.querySelector('[data-testid="anchor-figures"]')).toBeNull();
    expect(q("deck-show-all")).toBeNull();
  });

  test("page and pages, its and their: one skipped page reads in the singular", async () => {
    const files = REGISTER.files.map((f) => (f.kind === "deck" ? { ...f, pages: 1, summary: { ...f.summary, pages: 1, skipped_pages: [1], confirmed: 0, cannot_check: 0, personal_removed: 0, company_coded: 1 },
      anchors: { figures: { read: 1, found_on_page: 0, from_image: 0 } } } : f));
    await show({ ...REGISTER, files });
    expect([...all("file-block")[1].querySelectorAll('[data-testid="file-summary"]')].map((p) => p.textContent)).toEqual([
      "1 page · 0 pages read · 1 page skipped (no digits in its text: 1)",
      "1 figure read · 0 confirmed on the page they cite · 0 rejected · 0 cannot check",
      "0 personal items removed · 1 company name coded"]);
  });

  test("the lines table sits in the details box, in file order; a rate row is directly under its line with the note; part rows are indented", async () => {
    await show();
    const details = q("lines-details");
    expect(details.open).toBe(false);
    const rows = [...details.querySelectorAll("tbody tr")];
    expect(rows.map((r) => r.querySelector("td").textContent.replace(" · shown under its line", ""))).toEqual(
      ["Recognised revenue", "revenue growth rate", "MRR from annual subscriptions", "Annual, enterprise", "Total clients"]);
    expect(rows[1].className).toContain("moved");
    expect(rows[1].className).toContain("sub");
    expect(rows[1].querySelector('[data-testid="moved-note"]').textContent).toBe(" · shown under its line");
    expect(rows[2].className).toBe("sub");
    expect(rows[3].className).toBe("sub");
    expect(rows[3].querySelector("td").dataset.indent).toBe("2");
    expect(rows[3].querySelector("td").style.paddingLeft).toBe("42px");
    expect(rows[2].querySelector("td").style.paddingLeft).toBe("");
    expect(rows[0].className).toBe("");
    expect([...details.querySelectorAll("th")].map((th) => th.textContent)).toEqual(["Line", "Read as", "Basis", "Actual / plan", "Cells"]);
    await act(async () => { details.querySelector("summary").click(); });
    expect(q("lines-details").querySelector("summary").textContent).toBe("Hide all lines");
  });

  test("Change on the revenue row sends the row to the server", async () => {
    api.changeReading.mockResolvedValue({ overrides: 2 });
    await show();
    await act(async () => { q("anchor-revenue-change").click(); });
    const input = q("anchor-revenue-change-input");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "14");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { q("anchor-revenue-change-save").click(); });
    expect(api.changeReading).toHaveBeenCalledWith("a1", "h1", { what: "revenue_row", sheet: "Sales", row: 14 });
  });
});

describe("the Check results section", () => {
  test("a heading with a lead sentence, a tab row with All and one tab per file with its figure count, and the note under it", async () => {
    await show();
    expect(q("results-heading").textContent).toBe("Check results");
    expect(q("results-lead").textContent).toBe("Every figure the model read, after code opened its cell or page and compared the value. Three tables: Confirmed, Rejected, Cannot check.");
    expect([q("tab-all"), ...all("tab-file")].map((a) => a.textContent)).toEqual(["All 52", "revenue.xlsx 37", "Board report.pdf 15"]);
    expect(q("tab-all").className).toBe("on");
    expect(q("tab-note").textContent).toBe("Each tab shows the Confirmed, Rejected and Cannot check results for one file. For decks, it also lists every figure read from the deck, with its page number and outcome.");
    const css = fs.readFileSync(path.resolve(__dirname, "../App.css"), "utf8");
    expect(css).toMatch(/h1\.section \{[^}]*border-top: 2px solid var\(--ink\)/);
  });

  test("All shows the strip, every file's block and the three tables across files", async () => {
    await show();
    expect(q("assumptions-strip")).not.toBeNull();
    expect(all("file-block")).toHaveLength(2);
    expect(q("heading-confirmed").textContent).toBe("Confirmed · 2");
    expect(q("deck-figures")).toBeNull();
  });

  test("a spreadsheet's tab shows its block and the three tables for that file only", async () => {
    await show();
    await act(async () => { all("tab-file")[0].click(); });
    expect(all("file-block")).toHaveLength(1);
    expect(q("file-block").querySelector("h2").textContent).toContain("revenue.xlsx");
    expect(q("assumptions-strip")).toBeNull();
    expect(q("heading-confirmed").textContent).toBe("Confirmed · 1");
    expect(q("heading-rejected").textContent).toBe("Rejected · 1");
    expect(q("heading-cannot_check").textContent).toBe("Cannot check · 0");
    expect(all("card-citation_failed_twice")).toHaveLength(1);
    expect(q("deck-figures")).toBeNull();
    expect(q("tab-all").className).toBe("");
    expect(all("tab-file").map((a) => a.className)).toEqual(["on", ""]);
  });

  test("a deck's tab shows its summary lines, every figure with metric, value, period, label, page and outcome, and its three tables", async () => {
    await show();
    await act(async () => { all("tab-file")[1].click(); });
    expect(all("file-block")).toHaveLength(1);
    expect(all("file-summary")).toHaveLength(3);
    const box = q("deck-figures");
    expect([...box.querySelectorAll("th")].map((th) => th.textContent)).toEqual(["Metric", "Value", "Period", "Label", "Page", "Outcome"]);
    for (const th of box.querySelectorAll("th")) expect(th.getAttribute("title")).toBeTruthy();
    expect(all("deck-figure").map((r) => [...r.querySelectorAll("td")].map((td) => td.textContent))).toEqual([
      ["arr", "4.5%", "FY 2021", "Closing ARR", "3", "Confirmed"], ["mrr", "2,500 EUR", "—", "—", "8", "Cannot check"]]);
    expect(box.className).toBe("box");
    expect(q("heading-confirmed").textContent).toBe("Confirmed · 1");
    expect(q("heading-cannot_check").textContent).toBe("Cannot check · 1");
    expect(q("heading-rejected").textContent).toBe("Rejected · 0");
    expect(all("card-citation_failed_twice")).toHaveLength(0);
    await act(async () => { q("tab-all").click(); });
    expect(all("file-block")).toHaveLength(2);
  });
});

describe("the three result tables", () => {
  test("Confirmed starts collapsed behind its count; Rejected and Cannot check show every row", async () => {
    await show();
    expect(q("confirmed-details").open).toBe(false);
    expect(q("heading-confirmed").textContent).toBe("Confirmed · 2");
    expect(q("heading-rejected").textContent).toBe("Rejected · 1");
    expect(q("heading-cannot_check").textContent).toBe("Cannot check · 1");
    expect(all("row-rejected")).toHaveLength(1);
    expect(all("row-cannot_check")).toHaveLength(1);
    expect(q("confirmed-details").querySelector("summary").textContent).toBe("Show");
    await act(async () => { q("confirmed-details").querySelector("summary").click(); });
    expect(q("confirmed-details").open).toBe(true);
  });

  test("a figure the analyst set on a card is Confirmed, marked set by analyst with its date and the hover text", async () => {
    await show();
    const marks = all("set-by-analyst");
    expect(marks).toHaveLength(1);
    expect(marks[0].textContent).toBe("set by analyst, 2026-10-31");
    expect(marks[0].getAttribute("title")).toBe("value set by analyst; the check did not confirm it");
    expect(q("table-confirmed").contains(marks[0])).toBe(true);
  });

  test("every heading of every table has hover text", async () => {
    await show();
    const heads = [...document.body.querySelectorAll("th")];
    expect(heads.length).toBe(Object.values(HOVERS).reduce((n, h) => n + Object.keys(h).length, 0));          // the lines table and the three result tables
    for (const th of heads) expect(th.getAttribute("title")).toBeTruthy();
    for (const kind of Object.keys(HOVERS)) for (const [name, text] of Object.entries(HOVERS[kind])) expect(`${kind}.${name}`.length && text.length).toBeGreaterThan(10);
  });

  test("column order, widths, right-aligned numbers, and Source last with the cell first", async () => {
    await show();
    expect([...q("table-confirmed").querySelectorAll("th")].map((t) => t.textContent)).toEqual(["Metric", "Value", "Period", "Label", "Basis", "Actual / plan", "Row", "Source"]);
    expect([...q("table-rejected").querySelectorAll("th")].map((t) => t.textContent)).toEqual(["Metric", "Reading says", "Cell holds", "Reason", "Re-read", "Action", "Source"]);
    expect([...q("table-cannot_check").querySelectorAll("th")].map((t) => t.textContent)).toEqual(["Metric", "Value", "Period", "Label", "Why", "Used in", "Source"]);
    for (const kind of ["confirmed", "rejected", "cannot_check"]) {
      const widths = [...q(`table-${kind}`).querySelectorAll("col")].map((c) => c.style.width);
      expect(widths).toEqual(WIDTHS[kind].map((w) => `${w}%`));
      expect(WIDTHS[kind].reduce((a, b) => a + b, 0)).toBe(100);
      const last = [...q(`table-${kind}`).querySelectorAll("th")].pop();
      expect(last.textContent).toBe("Source");
    }
    expect([...q("table-confirmed").querySelectorAll("th.num")].map((t) => t.textContent)).toEqual(["Value"]);
    expect([...q("table-rejected").querySelectorAll("th.num")].map((t) => t.textContent)).toEqual(["Reading says", "Cell holds"]);
    const src1 = q("table-confirmed").querySelector("tbody tr td.src");
    expect(src1.textContent).toBe("AP11 · Sales · revenue.xlsx");
    expect(src1.querySelector("b").textContent).toBe("AP11");
    expect(all("row-confirmed")[1].querySelector("td.src").textContent).toBe("p3 · Board report.pdf");
  });

  test("every number goes through the one formatter: whole numbers, one decimal below ten", async () => {
    await show();
    await act(async () => { q("confirmed-details").querySelector("summary").click(); });
    const [sheetRow, deckRow] = all("row-confirmed");
    expect(sheetRow.querySelector('td[data-h="Value"]').textContent).toBe("78,829 EUR");
    expect(deckRow.querySelector('td[data-h="Value"]').textContent).toBe("4.5%");
    const rejected = q("row-rejected");
    expect(rejected.querySelector('td[data-h="Reading says"]').textContent).toBe("447,223 EURApr 2022".replace("Apr", "April"));
    expect(rejected.querySelector('td[data-h="Cell holds"]').textContent).toContain("398,736 EUR");
  });

  test("rows carry data-h labels and there is no narrow-screen layout: desktop only", () => {
    const css = fs.readFileSync(path.resolve(__dirname, "../App.css"), "utf8");
    expect(css).not.toMatch(/@media \(max-width/);
    expect(css).not.toContain("content: attr(data-h)");
  });

  test("Period is a dash when the figure has none and Label, right after it, shows the printed label", async () => {
    const row = { key: "k9", kind: "deck_figure", metric: "arr", value: 100, unit: "money", currency: "EUR", period: null, label: "Closing ARR", basis: null, actual_plan: null,
      row_role: null, source: { file: "Board report.pdf", deck_id: "d1", page: 4 }, note: null };
    await show({ ...REGISTER, tables: { ...REGISTER.tables, confirmed: [row] }, counts: { ...REGISTER.counts, confirmed: 1 } });
    await act(async () => { q("confirmed-details").querySelector("summary").click(); });
    const tr = q("row-confirmed");
    expect(tr.querySelector('td[data-h="Period"]').textContent).toBe("—");
    expect(tr.querySelector('td[data-h="Label"]').textContent).toBe("Closing ARR");
    expect(WIDTHS.confirmed[3]).toBe(14);
    expect([WIDTHS.confirmed[4], WIDTHS.confirmed[6]]).toEqual([8, 8]);
  });

  test("the Source link shows the cell with its neighbours", async () => {
    api.getCell.mockResolvedValue({ sheet: "Sales", cell: "AO13", rows: [{ row: 13, cells: [{ ref: "AN13", text: "1", cited: false }, { ref: "AO13", text: "398736", cited: true }] }] });
    await show();
    await act(async () => { q("table-rejected").querySelector('[data-testid="source-link"]').click(); });
    await act(async () => { await Promise.resolve(); });
    expect(api.getCell).toHaveBeenCalledWith("a1", "h1", "Sales", "AO13");
    expect(q("source-view").querySelector("td.cited").textContent).toBe("398736");
  });
});

describe("the cards", () => {
  test("a card shows both readings with their evidence, the cell link, and the three actions", async () => {
    await show();
    const card = q("card-citation_failed_twice");
    expect(card.querySelector("h3").textContent).toBe("ARR, April 2022: the reader and the file disagree");
    const two = card.querySelector(".two").textContent;
    expect(two).toContain("Reader, twice");
    expect(two).toContain('447,223 EUR, April 2022 — "April update ARR as stated on page 20"');
    expect(two).toContain("Cell AO13398,736 EUR, April 2022");
    expect([...card.querySelectorAll(".actions button")].map((b) => b.textContent)).toEqual(["Use the cell", "Use the reader", "Type a value"]);
    expect(card.querySelector('[data-testid="source-link"]').textContent).toContain("AO13");
  });

  test("Use the cell, Use the reader and a typed value are sent to the server", async () => {
    api.decideCard.mockResolvedValue({});
    await show();
    await act(async () => { q("card-use_cell").click(); });
    expect(api.decideCard).toHaveBeenCalledWith("a1", "c1", { action: "use_cell" });
    await act(async () => { q("card-use_reader").click(); });
    expect(api.decideCard).toHaveBeenLastCalledWith("a1", "c1", { action: "use_reader" });
    await act(async () => { q("card-type_value").click(); });
    const input = q("card-typed");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "400000");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { q("card-typed-save").click(); });
    expect(api.decideCard).toHaveBeenLastCalledWith("a1", "c1", { action: "type_value", value: 400000 });
  });

  test("nothing flagged: no card, no Rejected rows", async () => {
    await show({ ...REGISTER, tables: { ...REGISTER.tables, rejected: [] }, counts: { ...REGISTER.counts, rejected: 0 }, cards: [] });
    expect(all("card-citation_failed_twice")).toHaveLength(0);
    expect(document.body.querySelector(".card")).toBeNull();
    expect(q("heading-rejected").textContent).toBe("Rejected · 0");
  });
});

describe("the top of the page", () => {
  test("one sentence, the AI-reading tick, and no Why this step matters", async () => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => { root.render(<ReadingTop audit={{ ...AUDIT, structure_reading_consent: true }} setAudit={() => {}} host={<button data-testid="run">Run audit</button>} />); });
    expect(q("reading-explainer").textContent).toMatch(/^The model reads each file in full\./);
    expect(q("setup-consent-checkbox").checked).toBe(true);
    expect(q("setup-consent-tick-label").textContent).toBe("AI reading");
    expect(q("run").textContent).toBe("Run audit");
    expect(document.body.textContent).not.toContain("Why this step matters");
  });
});

describe("a reviewer's card (PR 4b)", () => {
  const LONG = "Rows 4 and 10 both carry the recognised revenue of the month, so the report counts it twice; the second row is the bookings line of the sales team, which is booked before it is recognised and sits under the same heading as the revenue line.";
  const FINDING_CARD = { id: "r1", kind: "reviewer_disagreement", status: "open", title: LONG, subject: {}, actions: ["use_reader"],
    source: { file: "revenue.xlsx", file_hash: "h1", sheet: "Report", cell: "B4:M4" },
    reader: { label: "Reader, twice", value: null }, other: { label: "Reviewer", evidence: "Row 10 is bookings." },
    finding: { what: LONG, reading: "Row 10 is bookings.", confidence: "high" },
    cites: [
      { key: "row:Report:4", kind: "row", label: "Row 4", reader: { role: "revenue", metric: "revenue", basis: "monthly", second_role: "revenue" }, source: { file: "revenue.xlsx", file_hash: "h1", sheet: "Report", cell: "B4:M4" } },
      { key: "figure:0", kind: "figure", label: "Figure revenue", reader: { metric: "revenue", value: 10625, unit: "money", currency: "EUR", period: "2025-06" }, source: { file: "revenue.xlsx", file_hash: "h1", sheet: "Report", cell: "G4" } },
      { key: "p2a", kind: "page_figure", label: "Page 2: arr", reader: { metric: "arr", value: 447223, unit: "money", currency: "EUR", period: "2024-12" }, source: { file: "deck.pdf", deck_id: "d1", page: 2 } },
    ] };

  test("one finding is one card with its full text and each cited row or figure with the reader's own value", async () => {
    await show({ ...REGISTER, cards: [FINDING_CARD] });
    const cards = all("card-reviewer_disagreement");
    expect(cards).toHaveLength(1);
    expect(q("card-title").textContent).toBe(LONG);
    expect(q("card-reviewer-reading").textContent).toContain("Row 10 is bookings.");
    const cites = all("card-cite");
    expect(cites.map((c) => c.querySelector("b").textContent)).toEqual(["Row 4", "Figure revenue", "Page 2: arr"]);
    expect(cites.map((c) => c.querySelector('[data-testid="card-cite-reader"]').textContent)).toEqual([
      "read as revenue, monthly", "10,625 EUR, June 2025", "447,223 EUR, December 2024"]);
    expect(cites[1].querySelector('[data-testid="source-link"]').textContent).toContain("G4");
  });
});
