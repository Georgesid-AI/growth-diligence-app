import React, { act } from "react";
import { createRoot } from "react-dom/client";

import ReadingScreen from "./ReadingScreen";
import * as api from "@/lib/api";

/** Board-pack layout fixes on the mapping page (items 2, 6, 7): a hidden sheet is named, a text-style deck figure shows its line, a reviewer's card
 *  offers its correction beside Keep as read, or is a note with no button. Run with --no-cache (rule 25). */
jest.mock("@/lib/api", () => ({
  getReading: jest.fn(), decideCard: jest.fn(), changeReading: jest.fn(), getCell: jest.fn(), getDeckPage: jest.fn(), downloadReading: jest.fn(),
  getAudit: jest.fn(), updateAudit: jest.fn(), saveFx: jest.fn(), decideUncertain: jest.fn(), answerCorrection: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const all = (id) => [...document.body.querySelectorAll(`[data-testid="${id}"]`)];
let host, root;
const AUDIT = { id: "a1", reporting_currency: "EUR", fiscal_year_end: 12, as_of_month: "2024-11-30", as_of_by: "detected", as_of_file: "pack.xlsx", as_of_evidence: "x",
  datasets: {} };
const line = (row, label) => ({ row, label, read_as: "R&D", basis: "monthly", actual_plan: "actual", cells: `B${row}:D${row}`, indent: 0, moved: false, role: "rnd", parent_row: null });
const SOURCE = { file: "pack.xlsx", file_hash: "h1", sheet: "PNL", cell: "B4" };
const cite = { key: "row:PNL:4", kind: "row", label: "Row 4", reader: { role: "revenue", metric: "revenue", basis: "monthly" }, source: SOURCE };
const reviewer = (id, extra) => ({ id, kind: "reviewer_disagreement", status: "open", title: "Doubt", subject: {}, source: SOURCE, reader: { label: "Reader" },
  other: { label: "Reviewer" }, finding: { what: `Doubt ${id}`, reading: "The sheet title says GBP.", confidence: "high" }, cites: [cite], ...extra });
const REGISTER = {
  files: [
    { kind: "sheet", file: "pack.xlsx", file_hash: "h1", size: 1000, hidden_sheets: ["data_for_graphs"],
      summary: { period_columns: 3, rows_mapped: 2, last_actual: "2024-11", granularity: "monthly", confirmed: 1, rejected: 0, cannot_check: 0, personal_removed: 0, company_coded: 0 },
      anchors: { as_of: { month: "2024-11", evidence: "x" }, revenue_row: { sheet: "PNL", row: 4, label: "Revenue", basis: "monthly" }, actual_plan: { sheet: "PNL", last_actual: "D", plan_from: "E" } },
      lines: [{ sheet: "PNL", lines: [line(5, "R&D")] }, { sheet: "data_for_graphs", lines: [line(4, "R&D")] }] },
    { kind: "deck", file: "deck.pdf", deck_id: "d1", pages: 3, summary: { pages: 3, pages_with_figures: 1, confirmed: 1, rejected: 0, cannot_check: 0, personal_removed: 0, company_coded: 0, skipped_pages: [] },
      anchors: { figures: { read: 1, found_on_page: 1, from_image: 0 } },
      figures: [{ key: "f1", metric: "arr", value: 1774628, unit: "money", currency: "EUR", period: null, label: null, page: 1, outcome: "confirmed", cell: "r2c1",
        line: "ARR: 1 774 628 EUR - 93% of the plan!" }] },
  ],
  tables: {
    confirmed: [
      { key: "k1", kind: "figure", metric: "rnd", value: 30, unit: "money", currency: "EUR", period: "2024-11", basis: "monthly", actual_plan: "actual", row_role: "rnd",
        source: { file: "pack.xlsx", file_hash: "h1", sheet: "data_for_graphs", cell: "B4", hidden: true }, note: null },
      { key: "k2", kind: "deck_figure", metric: "arr", value: 1774628, unit: "money", currency: "EUR", period: null, basis: null, actual_plan: "actual", row_role: null,
        source: { file: "deck.pdf", deck_id: "d1", page: 1, line: "ARR: 1 774 628 EUR - 93% of the plan!" }, note: null },
    ],
    rejected: [], cannot_check: [],
  },
  counts: { confirmed: 2, rejected: 0, cannot_check: 0 },
  cards: [
    reviewer("fix", { actions: ["apply_fix", "use_reader"], fix: { field: "currency", value: "GBP", old: "EUR", label: "Set currency GBP" } }),
    reviewer("note", { actions: [] }),
  ],
  review: {},
};

async function show() {
  api.getReading.mockResolvedValue(REGISTER);
  api.getAudit.mockResolvedValue(AUDIT);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<ReadingScreen audit={AUDIT} setAudit={() => {}} />); });
  await act(async () => { await Promise.resolve(); });
}
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); jest.clearAllMocks(); });

test("a row read on a hidden sheet is named so in its source, and the sheet's lines table says so", async () => {
  await show();
  const sources = all("source-link").map((a) => a.textContent);
  expect(sources).toContain("B4 · data_for_graphs (hidden) · pack.xlsx");
  expect(sources.some((t) => t.includes("PNL (hidden)"))).toBe(false);
  await act(async () => { all("tab-file")[0].click(); });
  expect(all("hidden-sheet").map((c) => c.textContent)).toEqual(["data_for_graphs (hidden)"]);
});

test("a deck figure of a text-style page is referred to by page and line, not by its anchor", async () => {
  await show();
  const sources = all("source-link").map((a) => a.textContent);
  expect(sources).toContain("p1: ARR: 1 774 628 EUR - 93% of the plan! · deck.pdf");
  expect(document.body.textContent).not.toContain("r2c1");
});

test("a reviewer's doubt with a correction offers it beside Keep as read, and a doubt with none is a note with no button", async () => {
  await show();
  const [fix, note] = all("card-reviewer_disagreement");
  expect([...fix.querySelectorAll(".actions button")].map((b) => b.textContent)).toEqual(["Set currency GBP", "Keep as read"]);
  expect(fix.querySelector('[data-testid="card-note"]')).toBeNull();
  expect(note.querySelectorAll(".actions button")).toHaveLength(0);
  expect(note.querySelector('[data-testid="card-note"]').textContent).toMatch(/^Note/);
  await act(async () => { fix.querySelector('[data-testid="card-apply_fix"]').click(); });
  expect(api.decideCard).toHaveBeenLastCalledWith("a1", "fix", { action: "apply_fix" });
});
