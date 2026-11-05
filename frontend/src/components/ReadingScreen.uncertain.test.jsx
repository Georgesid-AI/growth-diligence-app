import React, { act } from "react";
import { createRoot } from "react-dom/client";

import ReadingScreen from "./ReadingScreen";
import * as api from "@/lib/api";
import { UNCERTAIN_LABEL, candidateText, uncertainTitle } from "@/lib/readingView";

/**
 * "Reading uncertain – confirm" (docs/design/reading-consistency.md): what the two reads of a file or a page disagree on, with both candidates and a button for
 * each, on the file's tab, on the Detected layout block and on a deck's figures. Nothing is picked for the analyst. Run with --no-cache (rule 25).
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

const rowItem = { key: "uncertain:row:Sales:23", kind: "row", sheet: "Sales", row: 23, fields: ["metric"],
  first: { role: "customers", metric: "customers", cells: "B23:AP23", segment: false, parent_row: null },
  second: { role: "customers", metric: "logos", cells: "B23:AP23", segment: false, parent_row: null } };
const fieldItem = { key: "uncertain:field:Sales:granularity", kind: "field", sheet: "Sales", field: "granularity", name: "granularity", first: "monthly", second: "quarterly" };

const register = (uncertain, extra = {}) => ({
  files: [
    { kind: "sheet", file: "revenue.xlsx", file_hash: "h1", size: 1, summary: { period_columns: 4, rows_mapped: 1, last_actual: "2022-05", granularity: "monthly", confirmed: 0, rejected: 0, cannot_check: 0 },
      anchors: { as_of: null, revenue_row: null, actual_plan: null }, lines: [{ sheet: "Sales", lines: [] }],
      consistency: { status: "compared", reason: null, label: UNCERTAIN_LABEL, uncertain }, ...extra },
    { kind: "deck", file: "Board.pdf", deck_id: "d1", pages: 3, summary: { pages: 3, confirmed: 0, rejected: 0, cannot_check: 0 }, anchors: { figures: { read: 2, found_on_page: 1, from_image: 0 } },
      figures: [
        { key: "f1", id: "c1", metric: "revenue", value: 150000, unit: "money", currency: "USD", period: "2025", label: null, page: 1, outcome: "confirmed", uncertain: true,
          reading: { index: 0, options: ["revenue · 150,000 · 2025", "revenue · 160,000 · 2025"] } },
        { key: "f2", id: "c2", metric: "customers", value: 800, unit: "count", currency: null, period: null, label: null, page: 1, outcome: "confirmed", uncertain: false, reading: null },
      ] },
  ],
  tables: { confirmed: [], rejected: [], cannot_check: [] }, counts: { confirmed: 0, rejected: 0, cannot_check: 0 }, cards: [], review: {},
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

describe("the words of an uncertain item", () => {
  test("a row names its sheet, row and the fields that differ; a candidate is its closed fields; a missing candidate says so", () => {
    expect(uncertainTitle(rowItem)).toBe("Sales, row 23 (metric differ)");
    expect(candidateText(rowItem, "first")).toBe("customers · customers · B23:AP23");
    expect(candidateText({ ...rowItem, first: null }, "first")).toBe("not in this reading");
    // A difference in unit, currency or basis (George, 2026-11-05) is named on each button, so two readings of one role are told apart.
    const money = { ...rowItem, fields: ["currency"], first: { ...rowItem.first, unit: "money", currency: "EUR" }, second: { ...rowItem.first, unit: "money", currency: "USD" } };
    expect(candidateText(money, "first")).toBe("customers · customers · B23:AP23 · currency EUR");
    expect(candidateText(money, "second")).toBe("customers · customers · B23:AP23 · currency USD");
    const basis = { ...rowItem, fields: ["basis", "unit"], first: { ...rowItem.first, basis: "monthly", unit: "count" }, second: { ...rowItem.first, basis: "yearly", unit: null } };
    expect(candidateText(basis, "second")).toBe("customers · customers · B23:AP23 · basis yearly · unit none");
    expect(uncertainTitle(fieldItem)).toBe("Sales: granularity");
    expect(candidateText(fieldItem, "second")).toBe("quarterly");
  });
});

describe("a spreadsheet's uncertain items", () => {
  test("a row is listed on the file's tab with both candidates and a button for each; a pick is sent, nothing is chosen for the analyst", async () => {
    await show(register([rowItem]));
    expect(all("uncertain-item")).toHaveLength(0);            // the All tab lists them in its Uncertain table, not as cards
    await tab(0);
    const item = q("uncertain-item");
    expect(q("uncertain-label").textContent).toBe("Uncertain");
    expect(item.textContent).toContain("Sales, row 23");
    expect(q("uncertain-first-text").textContent).toBe("First reading: metric customers");
    expect(q("uncertain-second-text").textContent).toBe("Second reading: metric logos");
    expect(q("uncertain-first").textContent).toBe("Use first");
    expect(q("uncertain-second").textContent).toBe("Use second");
    expect(api.decideUncertain).not.toHaveBeenCalled();
    api.decideUncertain.mockResolvedValue({});
    await act(async () => { q("uncertain-second").click(); });
    expect(api.decideUncertain).toHaveBeenCalledWith("a1", "h1", { key: "uncertain:row:Sales:23", pick: "second" });
  });

  test("a differing sheet-level field is flagged on the Detected layout block, not on the tab", async () => {
    await show(register([fieldItem]));
    expect(q("detected-layout").querySelector("[data-testid=uncertain-item]").textContent).toContain("Sales: granularity");
    expect(q("uncertain-first").textContent).toBe("First reading: monthly");
    expect(q("uncertain-second").textContent).toBe("Second reading: quarterly");
    await tab(0);
    expect(document.body.querySelectorAll("[data-testid=uncertain-item]")).toHaveLength(1);
  });

  test("two agreeing reads show nothing; a second read that did not complete says so on the tab", async () => {
    await show(register([]));
    await tab(0);
    expect(q("uncertain-item")).toBeNull();
    await act(async () => { root.unmount(); });
    host.remove();
    await show(register([], { consistency: { status: "not_compared", reason: "second read not completed: timed out", label: UNCERTAIN_LABEL, uncertain: [] } }));
    await tab(0);
    expect(q("consistency-note").textContent).toBe("second read not completed: timed out");
  });
});

describe("a deck's uncertain figures", () => {
  test("the figure says Uncertain with a button for each reading; choosing sends the correction and reloads", async () => {
    await show(register([]));
    await tab(1);
    const rows = all("deck-figure");
    expect(rows[0].textContent).toContain("Uncertain");
    expect(rows[1].textContent).not.toContain("Uncertain");
    const buttons = all("deck-figure-choose");
    expect(buttons.map((b) => b.textContent)).toEqual(["Use first", "Use second"]);
    expect(buttons.map((b) => b.title)).toEqual(["revenue · 150,000 · 2025", "revenue · 160,000 · 2025"]);
    api.answerCorrection.mockResolvedValue({});
    await act(async () => { buttons[1].click(); });
    expect(api.answerCorrection).toHaveBeenCalledWith("a1", "c1", { index: 0, action: "choose", option: 1 });
  });
});
