import React, { act } from "react";
import { createRoot } from "react-dom/client";

import Diagnostics from "./Diagnostics";
import * as api from "@/lib/api";
import { S22_RECONCILIATION, S22_SAME_SOURCE } from "@/lib/chatUpload";

jest.mock("@/lib/api", () => ({ getAudit: jest.fn(), getResults: jest.fn(), reportUsage: jest.fn(), getDecks: jest.fn() }));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const src = (file, rows) => ({ file, sheet: "CSV", rows, row_numbers: [2] });
const month = (m, file, pnl) => ({ month: m, revenue_file: file, pnl, gap: file - pnl, gap_pct: pnl ? Math.round(((file - pnl) / pnl) * 10000) / 10000 : null,
  source: { revenue_file: src("rev.csv", "row 2"), pnl: src("pnl.csv", "row 2") } });
const REC = { available: true, first: "2024-01", last: "2024-02", file_total: 2000, pnl_total: 2000, gap: 0, gap_pct: 0, blocker: false,
  by_month: [month("2024-01", 1100, 1000), month("2024-02", 900, 1000)] };
const RESULTS = (rec) => ({ audit: {}, results: { reporting_currency: "EUR", missing_data: [], anomalies: null, revenue_reconciliation: rec } });
const DECKS = [{ deck_id: "d1", file: "plan.pdf", page_unit: "page", diagnostics: [
  { page: 4, kind: "corrected", field: "period", reason: "year under bar differs", original: "2023", corrected: "2022" },
  { page: 5, kind: "derived figure, not a claim", metric: "revenue", value: 200000, period: null },
  { page: 7, kind: "launch date without product name", metric: "product", value: null, period: "2025-Q3" },
] }];
const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
let root, host;

async function mount(rec) {
  api.getAudit.mockResolvedValue({ id: "a1" });
  api.getResults.mockResolvedValue(RESULTS(rec));
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [] });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Diagnostics />); });
}
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); jest.clearAllMocks(); });

test("the reconciliation section lists each month and ends with the window total", async () => {
  await mount(REC);
  const section = q("reconciliation");
  expect(section.querySelector("h3").textContent).toBe(S22_RECONCILIATION);
  expect([...section.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual(["Month", "Revenue file", "P&L", "Gap", "Gap %"]);
  const rows = [...section.querySelectorAll('[data-testid="reconciliation-row"]')];
  expect(rows.map((r) => r.children[0].textContent)).toEqual(["2024-01", "2024-02"]);
  expect(rows[0].children[4].textContent).toBe("10%");
  expect(rows[1].children[4].textContent).toBe("-10%");
  expect(rows[0].getAttribute("title")).toContain("rev.csv");
  const total = q("reconciliation-total");
  expect(total.children[0].textContent).toBe("Window total");
  expect(total.previousElementSibling).toBe(rows[1]);
  expect(total.nextElementSibling).toBeNull();
});

test("a month above 2% with a window total under 2% shows in the table and raises no alert here", async () => {
  await mount(REC);
  expect(q("reconciliation-row")).not.toBeNull();
  expect(document.body.querySelector('[role="alert"]')).toBeNull();
});

test("a gap % of a month whose P&L figure is 0 reads as a dash", async () => {
  await mount({ ...REC, by_month: [month("2024-01", 100, 0)] });
  expect(q("reconciliation-row").children[4].textContent).toBe("—");
});

test("a P&L that is the only revenue source shows Not applicable – same source in place of the table", async () => {
  await mount({ available: false, status: "not_applicable", reason: S22_SAME_SOURCE, by_month: [] });
  expect(S22_SAME_SOURCE).toBe("Not applicable – same source");
  const section = q("reconciliation");
  expect(section.querySelector("h3").textContent).toBe(S22_RECONCILIATION);
  expect(q("reconciliation-not-applicable").textContent).toBe("Not applicable – same source");
  expect(section.querySelector("table")).toBeNull();
  expect(q("reconciliation-row")).toBeNull();
  expect(document.body.querySelector('[role="alert"]')).toBeNull();
});

test("without a P&L the section is hidden", async () => {
  await mount(null);
  expect(q("reconciliation")).toBeNull();
  expect(document.body.textContent).toContain("Forensic Diagnostics");
});

test("the anomaly flags show the citation of the revenue file", async () => {
  api.getAudit.mockResolvedValue({ id: "a1" });
  api.getResults.mockResolvedValue({ audit: {}, results: { reporting_currency: "EUR", missing_data: [], revenue_reconciliation: null,
    anomalies: { negative_mrr_months: [], revenue_gap_then_resume: [], revenue_missing_customer_id: { count: 0, rows: [] },
      deals_close_before_created: { excluded_count: 0, rows: [] }, source: { ...src("rev.csv", "rows 2–9"), rule: "Flags" } } } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Diagnostics />); });
  expect(q("provenance-hover-diagnostics-anomalies")).not.toBeNull();
});

test("CRM rows sharing a deal ID show their collapsed rows and distinct IDs next to the deals closed before created", async () => {
  api.getAudit.mockResolvedValue({ id: "a1" });
  api.getResults.mockResolvedValue({ audit: {}, results: { reporting_currency: "EUR", missing_data: [], revenue_reconciliation: null,
    anomalies: { negative_mrr_months: [], revenue_gap_then_resume: [], revenue_missing_customer_id: { count: 0, rows: [] },
      deals_close_before_created: { excluded_count: 0, rows: [] }, deals_duplicate_id: { rows: 9, distinct_ids: 3, collapsed: 6, rows_list: [2] },
      source: { ...src("rev.csv", "rows 2–9"), rule: "Flags" } } } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Diagnostics />); });
  const row = q("diagnostics-deal-repeats");
  expect(row.textContent).toContain("CRM rows sharing a deal ID");
  expect(q("diagnostics-deal-repeats-count").textContent).toBe("6");
  expect(q("diagnostics-deal-repeats-detail").textContent).toBe("3 distinct deal IDs");
  expect(row.previousElementSibling.textContent).toContain("Deals close-before-created");
});

test("stale results read Stale – re-run audit, not Not computed yet; no results at all read Not computed yet", async () => {
  api.getAudit.mockResolvedValue({ id: "a1" });
  api.getResults.mockRejectedValue({ response: { status: 409, data: { detail: { code: "results_stale", message: "Stale – re-run audit" } } } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Diagnostics />); });
  expect(q("diagnostics-stale").textContent).toBe("Stale – re-run audit");
  expect(document.body.textContent).not.toContain("Not computed yet");
  await act(async () => { root.unmount(); }); host.remove();
  api.getResults.mockRejectedValue({ response: { status: 404 } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Diagnostics />); });
  expect(document.body.textContent).toContain("Not computed yet.");
});

test("the deck reading lines list what a check corrected, with both values, and the claims that never entered the register", async () => {
  await mount(REC);
  const lines = [...document.body.querySelectorAll('[data-testid="diagnostics-deck-line"]')].map((n) => n.textContent);
  expect(lines).toEqual([
    "plan.pdf · page 4: corrected period, 2023 → 2022 (year under bar differs)",
    "plan.pdf · page 5: derived figure, not a claim · revenue 200000",
    "plan.pdf · page 7: launch date without product name · product · 2025-Q3",
  ]);
});

test("no deck diagnostics, no deck reading section", async () => {
  await mount(REC);
  await act(async () => { root.unmount(); });
  host.remove();
  api.getDecks.mockResolvedValue({ decks: [{ deck_id: "d1", file: "plan.pdf" }], candidates: [] });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Diagnostics />); });
  expect(q("diagnostics-deck-reading")).toBeNull();
});
