// docs/specs/integrity-coverage.md (plan section 2 and 7.1): the conclusion, the two blocks and the data requests.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// GET /audits/{id}/integrity for plan test 2 (1): two checks completed and Green, four blocked.
const SPARSE = {
  conclusion: "Insufficient assessment coverage (2 of 6)", code: "insufficient", completed: 2, applicable: 6,
  completed_text: "Completed 2 of 6 applicable checks",
  memo_sentence: "Insufficient assessment coverage is not a finding about the company: 4 of the 6 applicable checks could not be completed.",
  results: [
    { check: "Gaps in customer data", result: "Green", finding: "0 customers with gaps; 0 revenue lines without a customer ID", source: "revenue.csv · CSV · rows 2–71" },
    { check: "Deck-vs-deck figures", result: "Green", finding: "No figure differs between the decks", source: "board.pptx" },
  ],
  coverage: [
    { check: "Revenue reconciliation", status: "Blocked — company data missing", reason: "P&L with a revenue line, overlapping the revenue file's months" },
    { check: "Gaps in customer data", status: "Completed", reason: null },
    { check: "Quarter-end clustering", status: "Blocked — company data missing", reason: "CRM export with close dates" },
    { check: "Smoothness", status: "Blocked — company data missing", reason: "Revenue file with 12 months or more" },
    { check: "Benford on transactions", status: "Blocked — company data missing", reason: "Transaction-level file" },
    { check: "Deck-vs-deck figures", status: "Completed", reason: null },
  ],
  blocked: ["Revenue reconciliation", "Quarter-end clustering", "Smoothness", "Benford on transactions"],
  data_requests: ["Revenue reconciliation: P&L with a revenue line, overlapping the revenue file's months"],
};

async function mount(integrity) {
  const IntegrityCoverage = require("./IntegrityCoverage").default;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<IntegrityCoverage integrity={integrity} />); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}

test("plan 2 (1): two completed and Green, four blocked reads Insufficient assessment coverage (2 of 6), never Reliable", async () => {
  const { host, done } = await mount(SPARSE);
  try {
    expect(host.querySelector('[data-testid="integrity-conclusion"]').textContent).toBe("Insufficient assessment coverage (2 of 6)");
    expect(host.textContent).not.toContain("Reliable");
    expect(host.querySelector('[data-testid="integrity-completed"]').textContent).toBe("Completed 2 of 6 applicable checks");
    expect(host.querySelector('[data-testid="integrity-blocked"]').textContent)
      .toBe("Blocked: Revenue reconciliation, Quarter-end clustering, Smoothness, Benford on transactions");
  } finally { await done(); }
});

test("the two blocks are separate tables: results of completed checks, and assessment coverage of all six", async () => {
  const { host, done } = await mount(SPARSE);
  try {
    const a = host.querySelector('[data-testid="integrity-results"]');
    const b = host.querySelector('[data-testid="integrity-coverage"]');
    expect(a).not.toBe(b);
    expect([...a.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual(["Check", "Result", "Finding", "Source"]);
    expect([...b.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual(["Check", "Status", "Reason"]);
    expect(a.querySelectorAll("tbody tr").length).toBe(2);
    expect(b.querySelectorAll("tbody tr").length).toBe(6);
  } finally { await done(); }
});

test("plan 2 (3): a check blocked by missing company data is in the data request list", async () => {
  const { host, done } = await mount(SPARSE);
  try {
    expect(host.querySelector('[data-testid="integrity-requests"]').textContent)
      .toContain("Revenue reconciliation: P&L with a revenue line, overlapping the revenue file's months");
  } finally { await done(); }
});

// docs/design/pnl-lines.md section 3: the findings of a statement's lines are listed with their cell, outside the six checks.
test("the P&L line findings are listed under the results with the cell they cite and do not change the coverage", async () => {
  const withFindings = { ...SPARSE, statement_findings: [
    { kind: "sign", line: "OPEX total", period: "FY 2021", text: "OPEX total differs from the sum of its lines by 3,000,000 in FY 2021",
      source: "pnl.csv · CSV · row 12" }] };
  const { host, done } = await mount(withFindings);
  try {
    const box = host.querySelector('[data-testid="integrity-statement"]');
    expect(box.textContent).toContain("OPEX total differs from the sum of its lines by 3,000,000 in FY 2021");
    expect(box.textContent).toContain("pnl.csv · CSV · row 12");
    expect(host.querySelector('[data-testid="integrity-coverage"]').querySelectorAll("tbody tr").length).toBe(6);
  } finally { await done(); }
  const none = await mount(SPARSE);
  try {
    expect(none.host.querySelector('[data-testid="integrity-statement"]')).toBeNull();
  } finally { await none.done(); }
});
