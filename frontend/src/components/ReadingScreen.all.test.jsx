import React, { act } from "react";
import { createRoot } from "react-dom/client";

import ReadingScreen from "./ReadingScreen";
import * as api from "@/lib/api";
import { EXPLAIN, TITLES, readingsText, rowsText } from "@/lib/readingView";

/**
 * The All section of the mapping page (brief of George, 2026-11-05, items 8 to 10 and 14): four categories each with its one-line explanation, the Uncertain
 * list (one row per item, grouped rows on one line, a pick removes the row), the per-file cards in the same words, and the review that stopped. Run with
 * --no-cache (rule 25).
 */
jest.mock("@/lib/api", () => ({
  getReading: jest.fn(), decideCard: jest.fn(), changeReading: jest.fn(), getCell: jest.fn(), getDeckPage: jest.fn(), downloadReading: jest.fn(),
  getAudit: jest.fn(), updateAudit: jest.fn(), saveFx: jest.fn(), decideUncertain: jest.fn(), answerCorrection: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const all = (id) => [...document.body.querySelectorAll(`[data-testid="${id}"]`)];
let host, root;
const AUDIT = { id: "a1", reporting_currency: "EUR", fiscal_year_end: 12, as_of_month: "2022-05-31", as_of_by: "detected", as_of_file: "revenue.xlsx", datasets: {} };

const view = (c, fields) => ({ role: "revenue", metric: "revenue", basis: "monthly", cells: "B6:M6", unit: "money", currency: "EUR", segment: false, parent_row: null, periods: 12, ...c, ...fields });
const group = { key: "uncertain:row:Sales:6", kind: "row", sheet: "Sales", row: 6, rows: [6, 7, 8, 9], fields: ["role", "parent_row"],
  first: view({ role: "revenue", parent_row: null }), second: view({ role: "arr", parent_row: 5 }) };
const single = { key: "uncertain:row:Sales:23", kind: "row", sheet: "Sales", row: 23, rows: [23], fields: ["metric"],
  first: view({ metric: "customers", role: "customers" }), second: view({ metric: "logos", role: "customers" }) };
const lone = { key: "uncertain:row:Sales:30", kind: "row", sheet: "Sales", row: 30, rows: [30], fields: ["row"], first: view({ role: "cash", metric: "cash" }), second: null };
const layout = { key: "uncertain:field:Sales:granularity", kind: "field", sheet: "Sales", field: "granularity", name: "granularity", first: "monthly", second: "quarterly" };

const figure = (over = {}) => ({ key: "deck:d1:c1", id: "c1", metric: "revenue", value: 150000, unit: "money", currency: "USD", period: "2025", label: null, page: 3, cell: "p3r2c1",
  outcome: "confirmed", uncertain: true, reading: { index: 0, options: ["revenue · 150,000 · 2025", "revenue · 160,000 · 2025"],
    details: [{ metric: "revenue", value: "150,000", period: "2025" }, { metric: "revenue", value: "160,000", period: "2025" }] }, ...over });

const register = (uncertain, figures = [figure()], over = {}) => ({
  files: [
    { kind: "sheet", file: "revenue.xlsx", file_hash: "h1", size: 1, summary: { period_columns: 12, rows_mapped: 4, last_actual: "2022-05", granularity: "monthly", confirmed: 2, rejected: 0, cannot_check: 0 },
      anchors: { as_of: null, revenue_row: null, actual_plan: null }, lines: [{ sheet: "Sales", lines: [] }],
      consistency: { status: "compared", reason: null, label: "Reading uncertain – confirm", uncertain } },
    { kind: "deck", file: "Board.pdf", deck_id: "d1", pages: 5, summary: { pages: 5, confirmed: 0, rejected: 0, cannot_check: 0 }, anchors: { figures: { read: figures.length, found_on_page: 0, from_image: 0 } }, figures },
  ],
  tables: {
    confirmed: [
      { key: "k1", kind: "figure", metric: "revenue", value: 100, unit: "money", currency: "EUR", period: "2022-05", basis: "monthly", actual_plan: "actual", row_role: "revenue", source: { file: "revenue.xlsx", file_hash: "h1", sheet: "Sales", cell: "G4" }, note: null },
      { key: "k2", kind: "figure", metric: "arr", value: 200, unit: "money", currency: "EUR", period: "2022-05", basis: "monthly", actual_plan: "actual", row_role: "arr", source: { file: "revenue.xlsx", file_hash: "h1", sheet: "Sales", cell: "G5" }, note: null },
    ],
    rejected: [{ key: "k3", kind: "figure", metric: "arr", value: 1, unit: "money", currency: "EUR", period: "2022-04", cell_value: 2, cell_period: "2022-04", reason: "differs", reread: "x", action: "a", source: { file: "revenue.xlsx", file_hash: "h1", sheet: "Sales", cell: "G6" } }],
    cannot_check: [{ key: "k4", kind: "figure", metric: "launch", value: null, unit: null, currency: null, period: "2021-01", reason: "a date", used_in: null, source: { file: "Board.pdf", deck_id: "d1", page: 8 } }],
  },
  counts: { confirmed: 2, rejected: 1, cannot_check: 1 }, cards: [], review: { stopped: null }, ...over,
});

async function show(reg) {
  api.getReading.mockResolvedValue(reg);
  api.getAudit.mockResolvedValue(AUDIT);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<ReadingScreen audit={AUDIT} setAudit={() => {}} />); });
  await act(async () => { await Promise.resolve(); });
}
afterEach(async () => { if (root) { await act(async () => { root.unmount(); }); host.remove(); root = null; } jest.clearAllMocks(); });
const tab = async (n) => { await act(async () => { all("tab-file")[n].click(); }); };

describe("the four categories (item 8)", () => {
  test("each heading carries its count and each has the one-line explanation under it", async () => {
    await show(register([group, single]));
    expect(["confirmed", "rejected", "uncertain", "cannot_check"].map((k) => q(`heading-${k}`).textContent)).toEqual(
      ["Matches source · 2", "Doesn't match source · 1", "Uncertain · 3", "Needs attention · 1"]);
    expect(TITLES).toEqual({ confirmed: "Matches source", rejected: "Doesn't match source", uncertain: "Uncertain", cannot_check: "Needs attention" });
    expect(EXPLAIN).toEqual({
      confirmed: "The figure was found in the file or on the page.",
      rejected: "The file or page shows a different value.",
      uncertain: "The two readings disagree; pick one. Until you do, the item is left out of all metrics and ratings.",
      cannot_check: "The app cannot check this by itself (a date, no comparable cell). Nothing is excluded; you decide if it matters.",
    });
    for (const k of Object.keys(EXPLAIN)) {
      const h = q(`heading-${k}`);
      expect(q(`explain-${k}`).textContent).toBe(EXPLAIN[k]);
      expect(h.nextElementSibling).toBe(q(`explain-${k}`));                // directly under the heading
    }
  });

  test("Needs review is gone from the screen", async () => {
    await show(register([]));
    expect(document.body.textContent).not.toMatch(/needs? review/i);
    expect(q("tab-note").textContent).toContain("Needs attention");
    expect(q("results-lead").textContent).toContain("Needs attention");
  });
});

describe("the Uncertain list (item 9)", () => {
  test("one row per item with the five columns and the two buttons; only the differing fields are named and shown; grouped rows are one line", async () => {
    await show(register([group, single, lone]));
    const table = q("table-uncertain");
    expect([...table.querySelectorAll("thead th")].slice(0, 5).map((h) => h.textContent)).toEqual(["File / page", "Row or figure", "What differs", "First reading", "Second reading"]);
    const rows = all("row-uncertain");
    expect(rows).toHaveLength(4);                                          // the group is one line; the deck figure is the fourth
    const cells = (r) => [...r.querySelectorAll("td")].map((c) => c.textContent);
    expect(cells(rows[0]).slice(0, 5)).toEqual(["revenue.xlsx", "Sales, rows 6–9", "role, parent row", "role revenue · parent row none", "role arr · parent row 5"]);
    expect(cells(rows[1]).slice(0, 5)).toEqual(["revenue.xlsx", "Sales, row 23", "metric", "metric customers", "metric logos"]);
    expect(cells(rows[2]).slice(0, 5)).toEqual(["revenue.xlsx", "Sales, row 30", "row", "cash · cash · B6:M6", "not in this reading"]);
    expect(rows[0].textContent).not.toContain("monthly");                  // fields the reads agree on are not repeated
    expect([...rows[0].querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Use first", "Use second"]);
  });

  test("a deck figure shows its page and cell, and what differs between the two readings", async () => {
    await show(register([], [figure({ reading: { index: 0, options: ["a", "b"], details: [{ metric: "revenue", value: "150,000", period: "2025" }, { metric: "revenue", value: "150,000", period: null }] } })]));
    const [row] = all("row-uncertain");
    const cells = [...row.querySelectorAll("td")].map((c) => c.textContent);
    expect(cells.slice(0, 5)).toEqual(["Board.pdf · page 3", "revenue · cell p3r2c1", "period", "period 2025", "period none"]);
  });

  test("picking sends the pick, reloads, updates the count and removes the row", async () => {
    api.decideUncertain.mockResolvedValue({});
    api.answerCorrection.mockResolvedValue({});
    await show(register([group, single]));
    expect(q("heading-uncertain").textContent).toBe("Uncertain · 3");
    api.getReading.mockResolvedValue(register([single]));
    await act(async () => { all("row-uncertain")[0].querySelectorAll("button")[1].click(); });
    expect(api.decideUncertain).toHaveBeenCalledWith("a1", "h1", { key: "uncertain:row:Sales:6", pick: "second" });
    await act(async () => { await Promise.resolve(); });
    expect(q("heading-uncertain").textContent).toBe("Uncertain · 2");
    expect(all("row-uncertain")).toHaveLength(2);
    api.getReading.mockResolvedValue(register([single], []));
    await act(async () => { all("row-uncertain")[1].querySelectorAll("button")[0].click(); });
    expect(api.answerCorrection).toHaveBeenCalledWith("a1", "c1", { index: 0, action: "choose", option: 0 });
    await act(async () => { await Promise.resolve(); });
    expect(q("heading-uncertain").textContent).toBe("Uncertain · 1");
  });

  test("with nothing uncertain the section says so and has no table", async () => {
    await show(register([], []));
    expect(q("heading-uncertain").textContent).toBe("Uncertain · 0");
    expect(q("table-uncertain")).toBeNull();
  });

  test("the row numbers and the readings are told in words", () => {
    expect(rowsText({ rows: [6, 7, 8, 9] })).toBe("rows 6–9");
    expect(rowsText({ rows: [6, 8] })).toBe("rows 6, 8");
    expect(rowsText({ rows: [23] })).toBe("row 23");
    expect(rowsText({ row: 4 })).toBe("row 4");
    expect(readingsText(group, "first")).toBe("role revenue · parent row none");
  });
});

describe("the per-file tab (item 10)", () => {
  test("keeps its cards, in the same words as the list: what differs, both readings, Use first and Use second", async () => {
    api.decideUncertain.mockResolvedValue({});
    await show(register([group, layout]));
    await tab(0);
    const item = all("uncertain-item").find((n) => n.textContent.includes("rows 6–9"));
    expect(item.textContent).toContain("Uncertain");
    expect(item.textContent).toContain("Sales, rows 6–9");
    expect(item.textContent).toContain("role, parent row");
    expect(item.textContent).toContain("role revenue · parent row none");
    expect(item.textContent).toContain("role arr · parent row 5");
    expect(item.textContent).not.toContain("Reading uncertain");
    expect([...item.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Use first", "Use second"]);
    await act(async () => { item.querySelectorAll("button")[0].click(); });
    expect(api.decideUncertain).toHaveBeenCalledWith("a1", "h1", { key: "uncertain:row:Sales:6", pick: "first" });
  });

  test("the deck tab says Uncertain on the figure with Use first and Use second", async () => {
    api.answerCorrection.mockResolvedValue({});
    await show(register([]));
    await tab(1);
    const [row] = all("deck-figure");
    expect(row.textContent).toContain("Uncertain");
    expect(all("deck-figure-choose").map((b) => b.textContent)).toEqual(["Use first", "Use second"]);
    await act(async () => { all("deck-figure-choose")[1].click(); });
    expect(api.answerCorrection).toHaveBeenCalledWith("a1", "c1", { index: 0, action: "choose", option: 1 });
  });

  test("the Detected layout block is unchanged: its item keeps the old label and the First reading buttons", async () => {
    await show(register([layout], []));
    const item = q("detected-layout").querySelector("[data-testid=uncertain-item]");
    expect(item.querySelector("[data-testid=uncertain-label]").textContent).toBe("Reading uncertain – confirm");
    expect(item.querySelector("[data-testid=uncertain-first]").textContent).toBe("First reading: monthly");
  });
});

describe("a review that stopped on the token allowance (item 14)", () => {
  const stopped = () => register([], [], { review: { stopped: { reviewed: 0, total: 2 } },
    tables: { ...register([]).tables, confirmed: register([]).tables.confirmed.map((r) => ({ ...r, unreviewed: true })) } });

  test("one red line at the top of the All section; unreviewed figures are marked in the Matches source list and are not counted as matches", async () => {
    await show(stopped());
    const line = q("review-stopped");
    expect(line.textContent).toBe("Review not run: token allowance reached. All 2 figures are unreviewed.");
    expect(line.className).toMatch(/bad|red/);
    expect(all("review-stopped")).toHaveLength(1);
    expect(q("heading-confirmed").textContent).toBe("Matches source · 0");
    await act(async () => { q("confirmed-details").querySelector("summary").click(); });
    expect(all("unreviewed-mark").map((n) => n.textContent)).toEqual(["unreviewed", "unreviewed"]);
  });

  test("no line and no mark when the review completed; none on a file's own tab", async () => {
    await show(register([], []));
    expect(q("review-stopped")).toBeNull();
    await act(async () => { q("confirmed-details").querySelector("summary").click(); });
    expect(q("unreviewed-mark")).toBeNull();
    await act(async () => { root.unmount(); });
    host.remove();
    root = null;
    await show(stopped());
    await tab(0);
    expect(q("review-stopped")).toBeNull();
  });
});
